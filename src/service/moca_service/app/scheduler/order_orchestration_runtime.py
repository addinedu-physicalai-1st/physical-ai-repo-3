import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from pymysql.connections import Connection

    from app.repository.db import Database
else:
    Connection = Any


TAKE_OUT_RECEIVE_TYPE = "TAKE_OUT"


@dataclass(frozen=True)
class ManufactureOrderItem:
    """Controller-facing item payload used by the manufacture command."""

    product_id: int
    product_name: str
    selected_options: list[Any]
    quantity: int
    unit_price: int


@dataclass
class WorkItem:
    """In-memory orchestration state for one claimed order."""

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

    def snapshot(self) -> "WorkItem":
        copied = WorkItem(
            order_id=self.order_id,
            receive_type=self.receive_type,
            table_number=self.table_number,
            order_items=list(self.order_items),
        )
        copied.retry_count = self.retry_count
        copied.next_retry_at = self.next_retry_at
        copied.last_error = self.last_error
        return copied

    def reset_retry_state(self) -> None:
        self.retry_count = 0
        self.next_retry_at = 0.0
        self.last_error = None

    def schedule_retry(self, retry_count: int, next_retry_at: float, exc: Exception) -> None:
        self.retry_count = retry_count
        self.next_retry_at = next_retry_at
        self.last_error = str(exc)

    def exhaust_retries(self, exc: Exception) -> None:
        self.next_retry_at = float("inf")
        self.last_error = str(exc)


@dataclass
class WorkQueue:
    """Single-lane FIFO queue that keeps one current order in progress."""

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


@dataclass
class WorkQueues:
    """Queues for each sequential orchestration step."""

    manufacture: WorkQueue = field(default_factory=lambda: WorkQueue("manufacture"))
    serving: WorkQueue = field(default_factory=lambda: WorkQueue("serving"))

    def remove(self, order_id: int) -> None:
        self.manufacture.remove(order_id)
        self.serving.remove(order_id)

    def clear(self) -> None:
        self.manufacture.clear()
        self.serving.clear()


class OrderClaimRepository(Protocol):
    """Order repository operations required by the runtime."""

    def claim_accepted_orders(self, conn: Connection, limit: int = 10) -> list[Any]:
        ...

    def mark_completed(self, conn: Connection, order_id: int) -> bool:
        ...

    def mark_failed(self, conn: Connection, order_id: int) -> bool:
        ...


class OrderItemLookup(Protocol):
    """Order item lookup required after an order is claimed."""

    def list_by_order_id(self, conn: Connection, order_id: int) -> list[Any]:
        ...


class DDoobyManufacturePort(Protocol):
    """Outbound port for starting manufacture in the DDooby controller."""

    def start_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        ...


class DobyServingPort(Protocol):
    """Outbound port for starting serving in the Doby controller."""

    def start_serving(self, command_id: str, order_id: int, table_number: int | None) -> bool:
        ...


class OrderOrchestrationContext:
    """Shared dependencies and synchronized mutable state for orchestration threads."""

    def __init__(
        self,
        *,
        database: "Database",
        order_repository: OrderClaimRepository,
        order_item_repository: OrderItemLookup,
        manufacture_port: DDoobyManufacturePort,
        serving_port: DobyServingPort,
        logger: logging.Logger,
        tick_interval_sec: float,
        claim_limit: int,
        backoff_sec: tuple[float, ...],
        max_retry_count: int,
        time_fn: Callable[[], float],
    ) -> None:
        self.database = database
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
        self.items: dict[int, WorkItem] = {}
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()

    def list_work_items(self) -> list[WorkItem]:
        with self.lock:
            return [item.snapshot() for item in self.items.values()]

    def find_locked(self, order_id: int) -> WorkItem | None:
        return self.items.get(order_id)


class OrderLifecycle:
    """Applies terminal order state changes and retry policy."""

    def __init__(self, context: OrderOrchestrationContext, queues: WorkQueues) -> None:
        self.context = context
        self.queues = queues

    def complete_order(self, item: WorkItem) -> None:
        with self.context.database.connect() as conn:
            completed = self.context.order_repository.mark_completed(conn, item.order_id)
        if completed:
            with self.context.condition:
                self._remove_locked(item.order_id)
                self.context.condition.notify_all()
            self.context.logger.info("order completed order_id=%s", item.order_id)

    def fail_order(self, item: WorkItem, exc: Exception) -> None:
        with self.context.lock:
            if item.retry_count >= self.context.max_retry_count:
                item.exhaust_retries(exc)
                self.context.logger.error(
                    "order orchestration action exhausted retries order_id=%s error=%s",
                    item.order_id,
                    item.last_error,
                )
                with self.context.database.connect() as conn:
                    self.context.order_repository.mark_failed(conn, item.order_id)
                self._remove_locked(item.order_id)
                self.context.condition.notify_all()
                return

            backoff_sec = self._retry_backoff_sec(item.retry_count)
            item.schedule_retry(
                retry_count=item.retry_count + 1,
                next_retry_at=self.context.time_fn() + backoff_sec,
                exc=exc,
            )
            self.context.condition.notify_all()

        self.context.logger.warning(
            "order orchestration action failed order_id=%s retry_count=%s error=%s",
            item.order_id,
            item.retry_count,
            item.last_error,
        )

    def fail_in_progress_items(self) -> None:
        with self.context.lock:
            items = list(self.context.items.values())

        for item in items:
            with self.context.database.connect() as conn:
                failed = self.context.order_repository.mark_failed(conn, item.order_id)
            if failed:
                self.context.logger.info(
                    "order failed on runtime shutdown order_id=%s",
                    item.order_id,
                )
            else:
                self.context.logger.warning(
                    "order fail skipped on runtime shutdown order_id=%s",
                    item.order_id,
                )

        if items:
            with self.context.condition:
                for item in items:
                    self._remove_locked(item.order_id)
                self.context.condition.notify_all()

    def _retry_backoff_sec(self, retry_count: int) -> float:
        backoff_index = min(retry_count, len(self.context.backoff_sec) - 1)
        return self.context.backoff_sec[backoff_index]

    def _remove_locked(self, order_id: int) -> None:
        self.context.items.pop(order_id, None)
        self.queues.remove(order_id)


class OrderOrchestrationThread:
    """Small wrapper around a daemon thread bound to the shared context."""

    def __init__(
        self,
        context: OrderOrchestrationContext,
        *,
        name: str,
    ) -> None:
        self.context = context
        self.name = name
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_alive():
            return
        self._thread = threading.Thread(
            target=self.run,
            daemon=True,
            name=self.name,
        )
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        raise NotImplementedError


class OrderClaimThread(OrderOrchestrationThread):
    """Polls accepted orders, builds work items, and feeds manufacture work."""

    def __init__(
        self,
        context: OrderOrchestrationContext,
        queues: WorkQueues,
    ) -> None:
        super().__init__(context, name="order-orchestration-claim")
        self.queues = queues

    def run(self) -> None:
        while not self.context.stop_event.is_set():
            try:
                self.claim_new_orders()
            except Exception:
                self.context.logger.exception("order orchestration claim failed")
            self.context.stop_event.wait(self.context.tick_interval_sec)

    def claim_new_orders(self) -> None:
        with self.context.database.transaction() as conn:
            claimed = self.context.order_repository.claim_accepted_orders(
                conn,
                self.context.claim_limit,
            )
            if not claimed:
                return
            work_items = [
                self._build_work_item(conn, order)
                for order in claimed
            ]
        with self.context.condition:
            for work_item in work_items:
                order_id = work_item.order_id
                if order_id in self.context.items:
                    continue
                self.context.items[order_id] = work_item
                self.queues.manufacture.enqueue(order_id)
                self.context.logger.info(
                    "accepted order claimed order_id=%s receive_type=%s table_number=%s item_count=%s",
                    order_id,
                    work_item.receive_type,
                    work_item.table_number,
                    len(work_item.order_items),
                )
            self.context.condition.notify_all()

    def _build_work_item(self, conn: Connection, order: Any) -> WorkItem:
        order_id = int(order.order_id)
        order_items = [
            ManufactureOrderItem(
                product_id=int(item.product_id),
                product_name=str(item.product_name),
                selected_options=list(item.selected_options),
                quantity=int(item.quantity),
                unit_price=int(item.unit_price),
            )
            for item in self.context.order_item_repository.list_by_order_id(conn, order_id)
        ]
        return WorkItem(
            order_id=order_id,
            receive_type=str(getattr(order, "receive_type", "")),
            table_number=getattr(order, "table_number", None),
            order_items=order_items,
        )


class QueuedOrderWorker(OrderOrchestrationThread):
    """Base worker for sequential queue-driven order steps."""

    def __init__(
        self,
        context: OrderOrchestrationContext,
        lifecycle: OrderLifecycle,
        queue: WorkQueue,
        *,
        name: str,
    ) -> None:
        super().__init__(context, name=name)
        self.lifecycle = lifecycle
        self.queue = queue

    def run(self) -> None:
        while not self.context.stop_event.is_set():
            item = self.wait_for_queue_item()
            if item is None:
                continue
            if not self.start_item(item):
                continue

    def enqueue(self, order_id: int) -> None:
        self.queue.enqueue(order_id)

    def remove(self, order_id: int) -> None:
        self.queue.remove(order_id)

    def wait_for_queue_item(self) -> WorkItem | None:
        with self.context.condition:
            while not self.context.stop_event.is_set():
                if self.queue.current_order_id is not None:
                    self.context.condition.wait(timeout=self.context.tick_interval_sec)
                    continue
                while self.queue.pending:
                    order_id = self.queue.pending[0]
                    item = self.context.items.get(order_id)
                    if item is None:
                        self.queue.pending.popleft()
                        continue
                    delay = item.next_retry_at - self.context.time_fn()
                    if delay > 0:
                        self.context.condition.wait(
                            timeout=min(delay, self.context.tick_interval_sec)
                        )
                        break
                    self.queue.pop_next()
                    return item
                if not self.queue.pending:
                    self.context.condition.wait(timeout=self.context.tick_interval_sec)
            return None

    def start_item(self, item: WorkItem) -> bool:
        try:
            self.start_order(item)
        except Exception as exc:
            with self.context.condition:
                self.queue.retry_current(item.order_id)
            self.lifecycle.fail_order(item, exc)
            return False
        with self.context.condition:
            item.reset_retry_state()
        return True

    def start_order(self, item: WorkItem) -> None:
        raise NotImplementedError

    def _complete_current_locked(
        self,
        order_id: int,
        command_id: str | None,
        expected_command_id: str,
        action_name: str,
    ) -> WorkItem | None:
        if command_id is not None and command_id != expected_command_id:
            return None
        item = self.context.find_locked(order_id)
        if item is None:
            return None
        if not self.queue.complete_current(order_id):
            return None
        self.context.logger.info(
            "%s completed subscribed order_id=%s command_id=%s",
            action_name,
            order_id,
            command_id,
        )
        item.reset_retry_state()
        return item


class OrderManufactureThread(QueuedOrderWorker):
    """Runs manufacture commands and routes completed orders to serving or completion."""

    def __init__(
        self,
        context: OrderOrchestrationContext,
        lifecycle: OrderLifecycle,
        queues: WorkQueues,
    ) -> None:
        super().__init__(
            context,
            lifecycle,
            queues.manufacture,
            name="order-orchestration-manufacture",
        )
        self.queues = queues

    def start_order(self, item: WorkItem) -> None:
        self.context.logger.info(
            "manufacture command start order_id=%s command_id=%s item_count=%s",
            item.order_id,
            item.manufacture_command_id,
            len(item.order_items),
        )
        ok = self.context.manufacture_port.start_manufacture(
            item.manufacture_command_id,
            item.order_id,
            item.order_items,
        )
        if not ok:
            raise RuntimeError("manufacture start rejected")

    def on_completed(self, order_id: int, command_id: str | None = None) -> bool:
        with self.context.lock:
            item = self._complete_current_locked(
                order_id,
                command_id,
                expected_command_id=f"manufacture:{order_id}",
                action_name="manufacture",
            )
            if item is None:
                return False
            if item.receive_type == TAKE_OUT_RECEIVE_TYPE:
                complete_now = True
            else:
                self.queues.serving.enqueue(order_id)
                complete_now = False
            self.context.condition.notify_all()
        if complete_now:
            self.lifecycle.complete_order(item)
        return True


class OrderServingThread(QueuedOrderWorker):
    """Runs serving commands and completes orders after serving finishes."""

    def __init__(
        self,
        context: OrderOrchestrationContext,
        lifecycle: OrderLifecycle,
        queues: WorkQueues,
    ) -> None:
        super().__init__(
            context,
            lifecycle,
            queues.serving,
            name="order-orchestration-serving",
        )

    def start_order(self, item: WorkItem) -> None:
        self.context.logger.info(
            "serving command start order_id=%s command_id=%s table_number=%s",
            item.order_id,
            item.serving_command_id,
            item.table_number,
        )
        ok = self.context.serving_port.start_serving(
            item.serving_command_id,
            item.order_id,
            item.table_number,
        )
        if not ok:
            raise RuntimeError("serving start rejected")

    def on_completed(self, order_id: int, command_id: str | None = None) -> bool:
        with self.context.lock:
            item = self._complete_current_locked(
                order_id,
                command_id,
                expected_command_id=f"serving:{order_id}",
                action_name="serving",
            )
            if item is None:
                return False
            self.context.condition.notify_all()
        self.lifecycle.complete_order(item)
        return True


class OrderOrchestrationRuntime:
    """Public facade that wires claim, manufacture, and serving workers together."""

    def __init__(
        self,
        *,
        database: "Database",
        order_repository: OrderClaimRepository,
        order_item_repository: OrderItemLookup,
        manufacture_port: DDoobyManufacturePort,
        serving_port: DobyServingPort,
        logger: logging.Logger,
        tick_interval_sec: float = 1.0,
        claim_limit: int = 10,
        backoff_sec: tuple[float, ...] = (2.0, 5.0, 10.0),
        max_retry_count: int = 3,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.context = OrderOrchestrationContext(
            database=database,
            order_repository=order_repository,
            order_item_repository=order_item_repository,
            manufacture_port=manufacture_port,
            serving_port=serving_port,
            logger=logger,
            tick_interval_sec=tick_interval_sec,
            claim_limit=claim_limit,
            backoff_sec=backoff_sec,
            max_retry_count=max_retry_count,
            time_fn=time_fn,
        )
        self.queues = WorkQueues()
        self.lifecycle = OrderLifecycle(self.context, self.queues)
        self.claim_thread = OrderClaimThread(self.context, self.queues)
        self.manufacture_thread = OrderManufactureThread(
            self.context,
            self.lifecycle,
            self.queues,
        )
        self.serving_thread = OrderServingThread(
            self.context,
            self.lifecycle,
            self.queues,
        )

    def start(self) -> None:
        if self.claim_thread.is_alive():
            return
        self.context.stop_event.clear()
        self.claim_thread.start()
        self.manufacture_thread.start()
        self.serving_thread.start()
        self.context.logger.info("order orchestration runtime started")

    def stop(self) -> None:
        self.context.stop_event.set()
        with self.context.condition:
            self.context.condition.notify_all()
        for thread in (self.claim_thread, self.manufacture_thread, self.serving_thread):
            thread.join(timeout=2.0)
        self.lifecycle.fail_in_progress_items()
        self.context.logger.info("order orchestration runtime stopped")

    def tick(self) -> None:
        self.claim_thread.claim_new_orders()

    def on_manufacture_completed(self, order_id: int, command_id: str | None = None) -> bool:
        return self.manufacture_thread.on_completed(order_id, command_id)

    def on_serving_completed(self, order_id: int, command_id: str | None = None) -> bool:
        return self.serving_thread.on_completed(order_id, command_id)

    def list_work_items(self) -> list[WorkItem]:
        return self.context.list_work_items()
