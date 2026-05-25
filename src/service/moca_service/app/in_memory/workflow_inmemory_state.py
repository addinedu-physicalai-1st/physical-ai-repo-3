import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


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


class WorkflowInmemoryState:
    """Thread-safe in-memory state shared by workflow scheduler workers."""

    def __init__(self) -> None:
        self.items: dict[int, WorkItem] = {}
        self.queues = WorkQueues()
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()

    def list_work_items(self) -> list[WorkItem]:
        with self.lock:
            return [item.snapshot() for item in self.items.values()]

    def find_locked(self, order_id: int) -> WorkItem | None:
        return self.items.get(order_id)

    def add_item_locked(self, item: WorkItem) -> bool:
        if item.order_id in self.items:
            return False
        self.items[item.order_id] = item
        return True

    def remove_order_locked(self, order_id: int) -> None:
        self.items.pop(order_id, None)
        self.queues.remove(order_id)

    def clear(self) -> None:
        with self.condition:
            self.items.clear()
            self.queues.clear()
            self.condition.notify_all()
