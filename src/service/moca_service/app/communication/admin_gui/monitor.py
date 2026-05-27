import json
import threading
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from app.communication.admin_gui.protocol import (
    EVENT_EMERGENCY_STOP,
    EVENT_SET_MODE,
    EVENT_SNAPSHOT,
    EVENT_START,
    EVENT_STOP,
    TOPIC_DOBY_CONTROLLER,
    TOPIC_MONITOR,
    TOPIC_ORDERS,
    TOPIC_PRODUCTS,
    TOPIC_TABLES,
)
from app.communication.admin_gui.doby_runtime import AdminGuiDobyRosRuntime
from app.communication.admin_gui.runtime import AdminGuiCommunicationRuntime
from app.service.menu_service import MenuService
from app.service.order_service import OrderService


class AdminGuiMonitorPublisher:
    def __init__(
        self,
        runtime: AdminGuiCommunicationRuntime,
        menu_service: MenuService,
        order_service: OrderService,
        logger,
        doby_runtime: AdminGuiDobyRosRuntime | None = None,
        *,
        interval_sec: float = 1.0,
    ) -> None:
        self.runtime = runtime
        self.menu_service = menu_service
        self.order_service = order_service
        self.doby_runtime = doby_runtime
        self.logger = logger
        self.interval_sec = interval_sec
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_products = b""
        self._last_orders = b""
        self._last_doby = b""

    def register(self) -> None:
        self.runtime.register_request_handler(TOPIC_MONITOR, EVENT_START, self._handle_start)
        self.runtime.register_request_handler(TOPIC_MONITOR, EVENT_STOP, self._handle_stop)
        self.runtime.register_request_handler(TOPIC_DOBY_CONTROLLER, EVENT_SET_MODE, self._handle_set_mode)
        self.runtime.register_request_handler(
            TOPIC_DOBY_CONTROLLER,
            EVENT_EMERGENCY_STOP,
            self._handle_emergency_stop,
        )

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)

    def _handle_start(self, _frame, _peer) -> bytes:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._last_products = b""
                self._last_orders = b""
                self._last_doby = b""
                self._thread = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name="admin-gui-monitor-publisher",
                )
                self._thread.start()
        return b'{"ok":true}'

    def _handle_stop(self, _frame, _peer) -> bytes:
        self.stop()
        return b'{"ok":true}'

    def _handle_set_mode(self, frame, _peer) -> bytes:
        if self.doby_runtime is None:
            return _json_payload(
                {
                    "ok": False,
                    "code": "DOBY_RUNTIME_NOT_CONFIGURED",
                    "message": "doby runtime not configured",
                }
            )
        payload = _json_object(frame.payload)
        mode = str(payload.get("mode", "")).strip()
        params = payload.get("params")
        if not isinstance(params, dict):
            params = {}
        if not mode:
            return _json_payload(
                {
                    "ok": False,
                    "code": "INVALID_MODE",
                    "message": "mode is required",
                }
            )
        return _json_payload(self.doby_runtime.request_mode_change(mode, params))

    def _handle_emergency_stop(self, _frame, _peer) -> bytes:
        if self.doby_runtime is None:
            return _json_payload(
                {
                    "ok": False,
                    "code": "DOBY_RUNTIME_NOT_CONFIGURED",
                    "message": "doby runtime not configured",
                }
            )
        return _json_payload(self.doby_runtime.request_emergency_stop())

    def _run(self) -> None:
        self.logger.info("admin_gui monitor publisher started")
        try:
            while not self._stop_event.is_set():
                self._publish_changed_products()
                self._publish_changed_orders()
                self._publish_tables()
                self._publish_changed_doby()
                self._stop_event.wait(self.interval_sec)
        finally:
            self.logger.info("admin_gui monitor publisher stopped")

    def _publish_changed_products(self) -> None:
        payload = _json_payload(_product_snapshot(self.menu_service.get_catalog()))
        if payload == self._last_products:
            return
        if self.runtime.publish_payload(TOPIC_PRODUCTS, EVENT_SNAPSHOT, payload):
            self._last_products = payload

    def _publish_changed_orders(self) -> None:
        payload = _json_payload(_order_snapshot(self.order_service.list_recent_orders()))
        if payload == self._last_orders:
            return
        if self.runtime.publish_payload(TOPIC_ORDERS, EVENT_SNAPSHOT, payload):
            self._last_orders = payload

    def _publish_tables(self) -> None:
        payload = _json_payload(_table_snapshot(self.order_service.get_table_assignment()))
        self.runtime.publish_payload(TOPIC_TABLES, EVENT_SNAPSHOT, payload)

    def _publish_changed_doby(self) -> None:
        if self.doby_runtime is None:
            return
        payload = _json_payload(self.doby_runtime.get_snapshot())
        if payload == self._last_doby:
            return
        if self.runtime.publish_payload(TOPIC_DOBY_CONTROLLER, EVENT_SNAPSHOT, payload):
            self._last_doby = payload


def _json_payload(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default).encode("utf-8")


def _json_object(payload: bytes) -> dict[str, Any]:
    if not payload:
        return {}
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("payload must be a JSON object")
    return decoded


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _product_snapshot(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    allergies_by_product: dict[str, list[str]] = {}
    for category in catalog.get("allergy", []):
        if not isinstance(category, dict):
            continue
        name = str(category.get("name", ""))
        for item in category.get("items", []):
            allergies_by_product.setdefault(str(item), []).append(name)

    products = []
    for product in catalog.get("menu", []):
        if not isinstance(product, dict):
            continue
        name = str(product.get("name", ""))
        products.append(
            {
                "id": product.get("id"),
                "name": name,
                "price": product.get("price", 0),
                "image": product.get("image", ""),
                "options": product.get("options", []),
                "allergies": allergies_by_product.get(name, []),
            }
        )
    return products


def _order_snapshot(orders) -> list[dict[str, Any]]:
    return [asdict(order) for order in orders]


def _table_snapshot(tables) -> list[dict[str, Any]]:
    return [
        {
            "table_id": table.table_id,
            "table_number": table.table_number,
            "pos_x": table.pos_x,
            "pos_y": table.pos_y,
            "status": table.status,
        }
        for table in tables
    ]
