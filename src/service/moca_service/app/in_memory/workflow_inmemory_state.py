import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


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


@dataclass(frozen=True)
class RetryDecision:
    """Result of applying retry policy to a failed queue action."""

    item: WorkItem
    exhausted: bool


class WorkflowInmemoryState:
    """Thread-safe in-memory state shared by workflow scheduler workers."""

    def __init__(self) -> None:
        self.items: dict[int, WorkItem] = {}
        self.manufacture_queue = WorkQueue("manufacture")
        self.serving_queue = WorkQueue("serving")
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()

    def list_work_items(self) -> list[WorkItem]:
        with self.lock:
            return [item.snapshot() for item in self.items.values()]

    def clear_stop_requested(self) -> None:
        self.stop_event.clear()

    def request_stop(self) -> None:
        with self.condition:
            self.stop_event.set()
            self.condition.notify_all()

    def is_stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def wait_for_stop_requested(self, timeout: float) -> bool:
        return self.stop_event.wait(timeout)

    def add_manufacture_work_items(self, work_items: list[WorkItem]) -> list[WorkItem]:
        added: list[WorkItem] = []
        with self.condition:
            for work_item in work_items:
                if not self._add_item_locked(work_item):
                    continue
                self.manufacture_queue.enqueue(work_item.order_id)
                added.append(work_item.snapshot())
            if added:
                self.condition.notify_all()
        return added

    def wait_for_next_manufacture_item(
        self,
        timeout: float,
        time_fn: Callable[[], float],
    ) -> WorkItem | None:
        return self._wait_for_next_queue_item(self.manufacture_queue, timeout, time_fn)

    def wait_for_next_serving_item(
        self,
        timeout: float,
        time_fn: Callable[[], float],
    ) -> WorkItem | None:
        return self._wait_for_next_queue_item(self.serving_queue, timeout, time_fn)

    def mark_item_started(self, order_id: int) -> bool:
        with self.condition:
            item = self.items.get(order_id)
            if item is None:
                return False
            item.reset_retry_state()
            return True

    def retry_manufacture_current_or_exhaust(
        self,
        order_id: int,
        exc: Exception,
        max_retry_count: int,
        backoff_sec: tuple[float, ...],
        now: float,
    ) -> RetryDecision | None:
        return self._retry_current_or_exhaust(
            self.manufacture_queue,
            order_id,
            exc,
            max_retry_count,
            backoff_sec,
            now,
        )

    def retry_serving_current_or_exhaust(
        self,
        order_id: int,
        exc: Exception,
        max_retry_count: int,
        backoff_sec: tuple[float, ...],
        now: float,
    ) -> RetryDecision | None:
        return self._retry_current_or_exhaust(
            self.serving_queue,
            order_id,
            exc,
            max_retry_count,
            backoff_sec,
            now,
        )

    def complete_current_manufacture(
        self,
        order_id: int,
        command_id: str | None = None,
    ) -> WorkItem | None:
        return self._complete_current_queue_item(
            self.manufacture_queue,
            order_id,
            command_id,
            expected_command_id_fn=lambda item: item.manufacture_command_id,
        )

    def complete_current_serving(
        self,
        order_id: int,
        command_id: str | None = None,
    ) -> WorkItem | None:
        return self._complete_current_queue_item(
            self.serving_queue,
            order_id,
            command_id,
            expected_command_id_fn=lambda item: item.serving_command_id,
        )

    def enqueue_serving(self, order_id: int) -> bool:
        with self.condition:
            if order_id not in self.items:
                return False
            self.serving_queue.enqueue(order_id)
            self.condition.notify_all()
            return True

    def remove_order(self, order_id: int) -> None:
        with self.condition:
            self._remove_order_locked(order_id)
            self.condition.notify_all()

    def remove_orders(self, order_ids: list[int]) -> None:
        with self.condition:
            for order_id in order_ids:
                self._remove_order_locked(order_id)
            self.condition.notify_all()

    def _add_item_locked(self, item: WorkItem) -> bool:
        if item.order_id in self.items:
            return False
        self.items[item.order_id] = item
        return True

    def _remove_order_locked(self, order_id: int) -> None:
        self.items.pop(order_id, None)
        self.manufacture_queue.remove(order_id)
        self.serving_queue.remove(order_id)

    def clear(self) -> None:
        with self.condition:
            self.items.clear()
            self.manufacture_queue.clear()
            self.serving_queue.clear()
            self.condition.notify_all()

    def _wait_for_next_queue_item(
        self,
        queue: WorkQueue,
        timeout: float,
        time_fn: Callable[[], float],
    ) -> WorkItem | None:
        with self.condition:
            while not self.stop_event.is_set():
                if queue.current_order_id is not None:
                    self.condition.wait(timeout=timeout)
                    continue
                while queue.pending:
                    order_id = queue.pending[0]
                    item = self.items.get(order_id)
                    if item is None:
                        queue.pending.popleft()
                        continue
                    delay = item.next_retry_at - time_fn()
                    if delay > 0:
                        self.condition.wait(timeout=min(delay, timeout))
                        break
                    queue.pop_next()
                    return item.snapshot()
                if not queue.pending:
                    self.condition.wait(timeout=timeout)
            return None

    def _retry_current_or_exhaust(
        self,
        queue: WorkQueue,
        order_id: int,
        exc: Exception,
        max_retry_count: int,
        backoff_sec: tuple[float, ...],
        now: float,
    ) -> RetryDecision | None:
        with self.condition:
            if not queue.retry_current(order_id):
                return None

            item = self.items.get(order_id)
            if item is None:
                queue.remove(order_id)
                self.condition.notify_all()
                return None

            if item.retry_count >= max_retry_count:
                item.exhaust_retries(exc)
                decision = RetryDecision(item=item.snapshot(), exhausted=True)
                self._remove_order_locked(order_id)
                self.condition.notify_all()
                return decision

            item.schedule_retry(
                retry_count=item.retry_count + 1,
                next_retry_at=now + self._retry_backoff_sec(item.retry_count, backoff_sec),
                exc=exc,
            )
            decision = RetryDecision(item=item.snapshot(), exhausted=False)
            self.condition.notify_all()
            return decision

    def _complete_current_queue_item(
        self,
        queue: WorkQueue,
        order_id: int,
        command_id: str | None,
        expected_command_id_fn: Callable[[WorkItem], str],
    ) -> WorkItem | None:
        with self.condition:
            item = self.items.get(order_id)
            if item is None:
                return None
            if command_id is not None and command_id != expected_command_id_fn(item):
                return None
            if not queue.complete_current(order_id):
                return None
            item.reset_retry_state()
            completed_item = item.snapshot()
            self.condition.notify_all()
            return completed_item

    def _retry_backoff_sec(
        self,
        retry_count: int,
        backoff_sec: tuple[float, ...],
    ) -> float:
        backoff_index = min(retry_count, len(backoff_sec) - 1)
        return backoff_sec[backoff_index]
