import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class WorkState(str, Enum):
    ACCEPTED = "ACCEPTED"
    MANUFACTURING = "MANUFACTURING"
    MANUFACTURED = "MANUFACTURED"
    SERVING = "SERVING"
    SERVED = "SERVED"


@dataclass(frozen=True)
class ManufactureOrderItem:
    product_id: int
    product_name: str
    selected_options: list[Any]
    quantity: int
    unit_price: int


@dataclass
class WorkItem:
    order_id: int
    receive_type: str
    table_number: int | None
    order_items: list[ManufactureOrderItem]
    state: WorkState = WorkState.ACCEPTED
    retry_count: int = 0
    next_retry_at: float = 0.0
    last_error: str | None = None
    manufacture_command_id: str = field(init=False)
    serving_command_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.manufacture_command_id = f"manufacture:{self.order_id}"
        self.serving_command_id = f"serving:{self.order_id}"


class OrderClaimRepository(Protocol):
    def claim_accepted_orders(self, limit: int = 10) -> list[Any]:
        ...

    def mark_completed(self, order_id: int) -> bool:
        ...


class OrderItemLookup(Protocol):
    def list_by_order_id(self, order_id: int) -> list[Any]:
        ...


class DDoobyManufacturePort(Protocol):
    def enqueue_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        ...


class DobyServingPort(Protocol):
    def enqueue_serving(self, command_id: str, order_id: int, table_number: int | None) -> bool:
        ...


class OrderOrchestrationRuntime:
    def __init__(
        self,
        *,
        order_repository: OrderClaimRepository,
        order_item_repository: OrderItemLookup,
        manufacture_port: DDoobyManufacturePort,
        serving_port: DobyServingPort,
        logger: logging.Logger,
        tick_interval_sec: float = 1.0,
        claim_limit: int = 10,
        backoff_sec: tuple[float, ...] = (2.0, 5.0, 10.0),
        max_retry_count: int = 3,
        time_fn=time.time,
    ) -> None:
        self.order_repository = order_repository
        self.order_item_repository = order_item_repository
        self.manufacture_port = manufacture_port
        self.serving_port = serving_port
        self.logger = logger
        self.tick_interval_sec = tick_interval_sec
        self.claim_limit = claim_limit
        self.backoff_sec = backoff_sec
        self.max_retry_count = max_retry_count
        self.time_fn = time_fn
        self._items: list[WorkItem] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="order-orchestration-runtime",
        )
        self._thread.start()
        self.logger.info("order orchestration runtime started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.logger.info("order orchestration runtime stopped")

    def tick(self) -> None:
        self._claim_new_orders()
        with self._lock:
            items = list(self._items)
        for item in items:
            self._advance(item)

    def on_manufacture_completed(self, order_id: int, command_id: str | None = None) -> bool:
        expected = f"manufacture:{order_id}"
        if command_id is not None and command_id != expected:
            return False
        with self._lock:
            item = self._find_locked(order_id)
            if item is None:
                return False
            if item.state == WorkState.MANUFACTURING:
                item.state = WorkState.MANUFACTURED
                item.retry_count = 0
                item.next_retry_at = 0.0
                item.last_error = None
                return True
            return item.state in {WorkState.MANUFACTURED, WorkState.SERVING, WorkState.SERVED}

    def on_serving_completed(self, order_id: int, command_id: str | None = None) -> bool:
        expected = f"serving:{order_id}"
        if command_id is not None and command_id != expected:
            return False
        with self._lock:
            item = self._find_locked(order_id)
            if item is None:
                return False
            if item.state == WorkState.SERVING:
                item.state = WorkState.SERVED
                item.retry_count = 0
                item.next_retry_at = 0.0
                item.last_error = None
                return True
            return item.state == WorkState.SERVED

    def list_work_items(self) -> list[WorkItem]:
        with self._lock:
            copies: list[WorkItem] = []
            for item in self._items:
                copied = WorkItem(
                    order_id=item.order_id,
                    receive_type=item.receive_type,
                    table_number=item.table_number,
                    order_items=list(item.order_items),
                )
                copied.state = item.state
                copied.retry_count = item.retry_count
                copied.next_retry_at = item.next_retry_at
                copied.last_error = item.last_error
                copies.append(copied)
            return copies

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                self.logger.exception("order orchestration tick failed")
            self._stop_event.wait(self.tick_interval_sec)

    def _claim_new_orders(self) -> None:
        claimed = self.order_repository.claim_accepted_orders(self.claim_limit)
        if not claimed:
            return
        with self._lock:
            known = {item.order_id for item in self._items}
            for order in claimed:
                order_id = int(order.order_id)
                if order_id in known:
                    continue
                order_items = [
                    ManufactureOrderItem(
                        product_id=int(item.product_id),
                        product_name=str(item.product_name),
                        selected_options=list(item.selected_options),
                        quantity=int(item.quantity),
                        unit_price=int(item.unit_price),
                    )
                    for item in self.order_item_repository.list_by_order_id(order_id)
                ]
                self._items.append(
                    WorkItem(
                        order_id=order_id,
                        receive_type=str(getattr(order, "receive_type", "")),
                        table_number=getattr(order, "table_number", None),
                        order_items=order_items,
                    )
                )

    def _advance(self, item: WorkItem) -> None:
        if item.next_retry_at > self.time_fn():
            return
        if item.state == WorkState.ACCEPTED:
            self._enqueue_manufacture(item)
        elif item.state == WorkState.MANUFACTURED:
            if item.receive_type == "TAKE_OUT":
                item.state = WorkState.SERVED
            else:
                self._enqueue_serving(item)
        elif item.state == WorkState.SERVED:
            self._complete(item)

    def _enqueue_manufacture(self, item: WorkItem) -> None:
        try:
            ok = self.manufacture_port.enqueue_manufacture(
                item.manufacture_command_id,
                item.order_id,
                item.order_items,
            )
            if not ok:
                raise RuntimeError("manufacture enqueue rejected")
        except Exception as exc:
            self._schedule_retry(item, exc)
            return
        with self._lock:
            if item.state == WorkState.ACCEPTED:
                item.state = WorkState.MANUFACTURING
                item.retry_count = 0
                item.next_retry_at = 0.0
                item.last_error = None

    def _enqueue_serving(self, item: WorkItem) -> None:
        try:
            ok = self.serving_port.enqueue_serving(
                item.serving_command_id,
                item.order_id,
                item.table_number,
            )
            if not ok:
                raise RuntimeError("serving enqueue rejected")
        except Exception as exc:
            self._schedule_retry(item, exc)
            return
        with self._lock:
            if item.state == WorkState.MANUFACTURED:
                item.state = WorkState.SERVING
                item.retry_count = 0
                item.next_retry_at = 0.0
                item.last_error = None

    def _complete(self, item: WorkItem) -> None:
        if self.order_repository.mark_completed(item.order_id):
            with self._lock:
                self._items = [current for current in self._items if current.order_id != item.order_id]

    def _schedule_retry(self, item: WorkItem, exc: Exception) -> None:
        with self._lock:
            if item.retry_count >= self.max_retry_count:
                item.last_error = str(exc)
                item.next_retry_at = float("inf")
                self.logger.error(
                    "order orchestration action exhausted retries order_id=%s state=%s error=%s",
                    item.order_id,
                    item.state.value,
                    item.last_error,
                )
                return
            backoff_index = min(item.retry_count, len(self.backoff_sec) - 1)
            item.retry_count += 1
            item.next_retry_at = self.time_fn() + self.backoff_sec[backoff_index]
            item.last_error = str(exc)
        self.logger.warning(
            "order orchestration action failed order_id=%s state=%s retry_count=%s error=%s",
            item.order_id,
            item.state.value,
            item.retry_count,
            item.last_error,
        )

    def _find_locked(self, order_id: int) -> WorkItem | None:
        for item in self._items:
            if item.order_id == order_id:
                return item
        return None
