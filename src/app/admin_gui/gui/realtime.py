import json
import logging

from PyQt6.QtCore import QObject, pyqtSignal

from tcp import create_admin_gui_communication_runtime
from tcp.protocol import (
    ChunkAssembler,
    EVENT_EMERGENCY_STOP,
    EVENT_APPLY_MAP,
    EVENT_SET_MODE,
    EVENT_SNAPSHOT,
    EVENT_START,
    EVENT_STOP,
    TOPIC_DOBY_CONTROLLER,
    TOPIC_MAPS,
    TOPIC_MONITOR,
    TOPIC_ORDERS,
    TOPIC_PRODUCTS,
    TOPIC_TABLES,
)
from config import AdminGuiConfig, load_config


class AdminGuiRealtimeBridge(QObject):
    products_updated = pyqtSignal(list)
    orders_updated = pyqtSignal(list)
    tables_updated = pyqtSignal(list)
    maps_updated = pyqtSignal(dict)
    doby_updated = pyqtSignal(dict)
    doby_control_result = pyqtSignal(dict)
    map_apply_result = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config: AdminGuiConfig | None = None, logger: logging.Logger | None = None):
        super().__init__()
        self.config = config or load_config()
        self.logger = logger or logging.getLogger("admin_gui.realtime")
        self._assembler = ChunkAssembler()
        self._runtime = create_admin_gui_communication_runtime(
            listen_host=self.config.host,
            listen_port=self.config.port,
            peer_host=self.config.moca_service_host,
            peer_port=self.config.moca_admin_gui_port,
            logger=self.logger,
            peer_name="MocaService",
            timeout=self.config.tcp_timeout_sec,
        )
        self._runtime.subscribe(TOPIC_PRODUCTS, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_ORDERS, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_TABLES, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_MAPS, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_DOBY_CONTROLLER, EVENT_SNAPSHOT, self._handle_snapshot)

    def start(self) -> None:
        self._runtime.start()
        try:
            self._runtime.request(
                TOPIC_MONITOR,
                EVENT_START,
                b'{"client":"admin_gui"}',
                timeout=self.config.tcp_timeout_sec,
            )
        except Exception as exc:
            message = f"관제 시작 요청 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)

    def stop(self) -> None:
        try:
            self._runtime.request(
                TOPIC_MONITOR,
                EVENT_STOP,
                b'{"client":"admin_gui"}',
                timeout=self.config.tcp_timeout_sec,
            )
        except Exception as exc:
            self.logger.warning("관제 종료 요청 실패: %s", exc)
        finally:
            self._runtime.stop()

    def request_doby_mode(self, mode: str, params: dict | None = None) -> None:
        payload = json.dumps(
            {
                "mode": mode,
                "params": params or {},
                "override_priority": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._request_doby_control(EVENT_SET_MODE, payload)

    def request_doby_emergency_stop(self) -> None:
        self._request_doby_control(EVENT_EMERGENCY_STOP, b'{"reason":"operator"}')

    def request_map_apply(self, map_id: int) -> None:
        payload = json.dumps(
            {"map_id": int(map_id)},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self._runtime.request(
                TOPIC_MAPS,
                EVENT_APPLY_MAP,
                payload,
                timeout=max(self.config.tcp_timeout_sec, 10.0),
            )
            decoded = json.loads(response.decode("utf-8")) if response else {}
            if not isinstance(decoded, dict):
                decoded = {"ok": False, "message": "invalid map apply response"}
            self.map_apply_result.emit(decoded)
            if not decoded.get("ok"):
                self.error.emit(decoded.get("message") or decoded.get("reason") or "지도 적용 실패")
        except Exception as exc:
            message = f"지도 적용 요청 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)

    def _request_doby_control(self, event: int, payload: bytes) -> None:
        try:
            response = self._runtime.request(
                TOPIC_DOBY_CONTROLLER,
                event,
                payload,
                timeout=self.config.tcp_timeout_sec,
            )
            decoded = json.loads(response.decode("utf-8")) if response else {}
            if not isinstance(decoded, dict):
                decoded = {"ok": False, "message": "invalid doby control response"}
            self.doby_control_result.emit(decoded)
            if not decoded.get("ok"):
                self.error.emit(decoded.get("message") or decoded.get("reason") or "도비 제어 요청 실패")
        except Exception as exc:
            message = f"도비 제어 요청 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)

    def _handle_snapshot(self, frame, _peer) -> None:
        payload = self._assembler.add(frame)
        if payload is None:
            return
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            message = f"관제 데이터 디코딩 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)
            return

        if frame.topic == TOPIC_DOBY_CONTROLLER:
            if not isinstance(decoded, dict):
                message = "doby snapshot payload must be a JSON object"
                self.logger.warning(message)
                self.error.emit(message)
                return
            self.doby_updated.emit(decoded)
            return

        if frame.topic == TOPIC_MAPS:
            if not isinstance(decoded, dict):
                message = "map snapshot payload must be a JSON object"
                self.logger.warning(message)
                self.error.emit(message)
                return
            self.maps_updated.emit(decoded)
            return

        if not isinstance(decoded, list):
            message = "관제 snapshot payload must be a JSON array"
            self.logger.warning(message)
            self.error.emit(message)
            return

        if frame.topic == TOPIC_PRODUCTS:
            self.products_updated.emit(decoded)
        elif frame.topic == TOPIC_ORDERS:
            self.orders_updated.emit(decoded)
        elif frame.topic == TOPIC_TABLES:
            self.tables_updated.emit(decoded)
