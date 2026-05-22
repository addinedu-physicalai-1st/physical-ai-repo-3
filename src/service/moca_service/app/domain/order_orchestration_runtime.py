import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol


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
    retry_count: int = 0
    next_retry_at: float = 0.0
    last_error: str | None = None
    manufacture_command_id: str = field(init=False)
    serving_command_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.manufacture_command_id = f"manufacture:{self.order_id}"
        self.serving_command_id = f"serving:{self.order_id}"


@dataclass
class WorkQueue:
    name: str
    pending: deque[int] = field(default_factory=deque)
    current_order_id: int | None = None

    def enqueue(self, order_id: int) -> None:
        if order_id == self.current_order_id or order_id in self.pending:
            return
        self.pending.append(order_id)

    def pop_next(self) -> int | None:
        if self.current_order_id is not None or not self.pending:
            return None
        self.current_order_id = self.pending.popleft()
        return self.current_order_id

    def complete_current(self, order_id: int) -> bool:
        if self.current_order_id != order_id:
            return False
        self.current_order_id = None
        return True

    def retry_current(self, order_id: int) -> bool:
        if self.current_order_id != order_id:
            return False
        self.current_order_id = None
        self.pending.appendleft(order_id)
        return True

    def remove(self, order_id: int) -> None:
        if self.current_order_id == order_id:
            self.current_order_id = None
        try:
            self.pending.remove(order_id)
        except ValueError:
            pass

    def clear(self) -> None:
        self.pending.clear()
        self.current_order_id = None


class OrderClaimRepository(Protocol):
    def claim_accepted_orders(self, limit: int = 10) -> list[Any]:
        ...

    def mark_completed(self, order_id: int) -> bool:
        ...

    def mark_failed(self, order_id: int) -> bool:
        ...


class OrderItemLookup(Protocol):
    def list_by_order_id(self, order_id: int) -> list[Any]:
        ...


class DDoobyManufacturePort(Protocol):
    def start_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        ...


class DobyServingPort(Protocol):
    def start_serving(self, command_id: str, order_id: int, table_number: int | None) -> bool:
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
        self._items: dict[int, WorkItem] = {}
        self._manufacture_queue = WorkQueue("manufacture")
        self._serving_queue = WorkQueue("serving")
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._claim_thread: threading.Thread | None = None
        self._manufacture_thread: threading.Thread | None = None
        self._serving_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._claim_thread is not None and self._claim_thread.is_alive():
            return
        self._stop_event.clear()
        self._claim_thread = threading.Thread(
            target=self._run_claim_loop,
            daemon=True,
            name="order-orchestration-claim",
        )
        self._manufacture_thread = threading.Thread(
            target=self._run_manufacture_worker,
            daemon=True,
            name="order-orchestration-manufacture",
        )
        self._serving_thread = threading.Thread(
            target=self._run_serving_worker,
            daemon=True,
            name="order-orchestration-serving",
        )
        self._claim_thread.start()
        self._manufacture_thread.start()
        self._serving_thread.start()
        self.logger.info("order orchestration runtime started")

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        for thread in (self._claim_thread, self._manufacture_thread, self._serving_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self._claim_thread = None
        self._manufacture_thread = None
        self._serving_thread = None
        self._fail_in_progress_items()
        self.logger.info("order orchestration runtime stopped")

    def tick(self) -> None:
        self._claim_new_orders()

    def on_manufacture_completed(self, order_id: int, command_id: str | None = None) -> bool:
        expected = f"manufacture:{order_id}"
        if command_id is not None and command_id != expected:
            return False
        with self._lock:
            item = self._find_locked(order_id)
            if item is None:
                return False
            if not self._manufacture_queue.complete_current(order_id):
                return False
            self.logger.info(
                "manufacture completed subscribed order_id=%s command_id=%s",
                order_id,
                command_id,
            )
            item.retry_count = 0
            item.next_retry_at = 0.0
            item.last_error = None
            if item.receive_type == "TAKE_OUT":
                complete_now = True
            else:
                self._serving_queue.enqueue(order_id)
                complete_now = False
            self._condition.notify_all()
        if complete_now:
            self._complete(item)
        return True

    def on_serving_completed(self, order_id: int, command_id: str | None = None) -> bool:
        expected = f"serving:{order_id}"
        if command_id is not None and command_id != expected:
            return False
        with self._lock:
            item = self._find_locked(order_id)
            if item is None:
                return False
            if not self._serving_queue.complete_current(order_id):
                return False
            self.logger.info(
                "serving completed subscribed order_id=%s command_id=%s",
                order_id,
                command_id,
            )
            item.retry_count = 0
            item.next_retry_at = 0.0
            item.last_error = None
            self._condition.notify_all()
        self._complete(item)
        return True

    def list_work_items(self) -> list[WorkItem]:
        with self._lock:
            copies: list[WorkItem] = []
            for item in self._items.values():
                copied = WorkItem(
                    order_id=item.order_id,
                    receive_type=item.receive_type,
                    table_number=item.table_number,
                    order_items=list(item.order_items),
                )
                copied.retry_count = item.retry_count
                copied.next_retry_at = item.next_retry_at
                copied.last_error = item.last_error
                copies.append(copied)
            return copies

    def _run_claim_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._claim_new_orders()
            except Exception:
                self.logger.exception("order orchestration claim failed")
            self._stop_event.wait(self.tick_interval_sec)

    def _run_manufacture_worker(self) -> None:
        while not self._stop_event.is_set():
            item = self._wait_for_queue_item(self._manufacture_queue)
            if item is None:
                continue
            if not self._start_manufacture(item):
                continue

    def _run_serving_worker(self) -> None:
        while not self._stop_event.is_set():
            item = self._wait_for_queue_item(self._serving_queue)
            if item is None:
                continue
            if not self._start_serving(item):
                continue

    def _claim_new_orders(self) -> None:
        claimed = self.order_repository.claim_accepted_orders(self.claim_limit)
        if not claimed:
            return
        with self._condition:
            for order in claimed:
                order_id = int(order.order_id)
                if order_id in self._items:
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
                work_item = WorkItem(
                    order_id=order_id,
                    receive_type=str(getattr(order, "receive_type", "")),
                    table_number=getattr(order, "table_number", None),
                    order_items=order_items,
                )
                self._items[order_id] = work_item
                self._manufacture_queue.enqueue(order_id)
                self.logger.info(
                    "accepted order claimed order_id=%s receive_type=%s table_number=%s item_count=%s",
                    order_id,
                    str(getattr(order, "receive_type", "")),
                    getattr(order, "table_number", None),
                    len(order_items),
                )
            self._condition.notify_all()

    def _start_manufacture(self, item: WorkItem) -> bool:
        try:
            self.logger.info(
                "manufacture command start order_id=%s command_id=%s item_count=%s",
                item.order_id,
                item.manufacture_command_id,
                len(item.order_items),
            )
            ok = self.manufacture_port.start_manufacture(
                item.manufacture_command_id,
                item.order_id,
                item.order_items,
            )
            if not ok:
                raise RuntimeError("manufacture start rejected")
        except Exception as exc:
            with self._condition:
                self._manufacture_queue.retry_current(item.order_id)
            self._schedule_retry(item, exc)
            return False
        with self._condition:
            item.retry_count = 0
            item.next_retry_at = 0.0
            item.last_error = None
        return True

    def _start_serving(self, item: WorkItem) -> bool:
        try:
            self.logger.info(
                "serving command start order_id=%s command_id=%s table_number=%s",
                item.order_id,
                item.serving_command_id,
                item.table_number,
            )
            ok = self.serving_port.start_serving(
                item.serving_command_id,
                item.order_id,
                item.table_number,
            )
            if not ok:
                raise RuntimeError("serving start rejected")
        except Exception as exc:
            with self._condition:
                self._serving_queue.retry_current(item.order_id)
            self._schedule_retry(item, exc)
            return False
        with self._condition:
            item.retry_count = 0
            item.next_retry_at = 0.0
            item.last_error = None
        return True

    def _complete(self, item: WorkItem) -> None:
        if self.order_repository.mark_completed(item.order_id):
            with self._condition:
                self._items.pop(item.order_id, None)
                self._manufacture_queue.remove(item.order_id)
                self._serving_queue.remove(item.order_id)
                self._condition.notify_all()
            self.logger.info("order completed order_id=%s", item.order_id)

    def _fail_in_progress_items(self) -> None:
        with self._lock:
            items = list(self._items.values())
        for item in items:
            if self.order_repository.mark_failed(item.order_id):
                self.logger.info(
                    "order failed on runtime shutdown order_id=%s",
                    item.order_id,
                )
            else:
                self.logger.warning(
                    "order fail skipped on runtime shutdown order_id=%s",
                    item.order_id,
                )
        if items:
            with self._condition:
                failed_ids = {item.order_id for item in items}
                for order_id in failed_ids:
                    self._items.pop(order_id, None)
                    self._manufacture_queue.remove(order_id)
                    self._serving_queue.remove(order_id)
                self._condition.notify_all()

    def _schedule_retry(self, item: WorkItem, exc: Exception) -> None:
        with self._lock:
            if item.retry_count >= self.max_retry_count:
                item.last_error = str(exc)
                item.next_retry_at = float("inf")
                self.logger.error(
                    "order orchestration action exhausted retries order_id=%s error=%s",
                    item.order_id,
                    item.last_error,
                )
                self.order_repository.mark_failed(item.order_id)
                self._items.pop(item.order_id, None)
                self._manufacture_queue.remove(item.order_id)
                self._serving_queue.remove(item.order_id)
                self._condition.notify_all()
                return
            backoff_index = min(item.retry_count, len(self.backoff_sec) - 1)
            item.retry_count += 1
            item.next_retry_at = self.time_fn() + self.backoff_sec[backoff_index]
            item.last_error = str(exc)
            self._condition.notify_all()
        self.logger.warning(
            "order orchestration action failed order_id=%s retry_count=%s error=%s",
            item.order_id,
            item.retry_count,
            item.last_error,
        )

    def _find_locked(self, order_id: int) -> WorkItem | None:
        return self._items.get(order_id)

    def _wait_for_queue_item(
        self,
        queue: WorkQueue,
    ) -> WorkItem | None:
        with self._condition:
            while not self._stop_event.is_set():
                if queue.current_order_id is not None:
                    self._condition.wait(timeout=self.tick_interval_sec)
                    continue
                while queue.pending:
                    order_id = queue.pending[0]
                    item = self._items.get(order_id)
                    if item is None:
                        queue.pending.popleft()
                        continue
                    delay = item.next_retry_at - self.time_fn()
                    if delay > 0:
                        self._condition.wait(timeout=min(delay, self.tick_interval_sec))
                        break
                    queue.pop_next()
                    return item
                if not queue.pending:
                    self._condition.wait(timeout=self.tick_interval_sec)
            return None
