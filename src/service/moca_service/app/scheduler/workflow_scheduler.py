import logging
import threading
import time
from typing import Any, Callable, Protocol

from app.in_memory.workflow_inmemory_state import (
    ManufactureOrderItem,
    RetryDecision,
    WorkItem,
    WorkflowInmemoryState,
)


TAKE_OUT_RECEIVE_TYPE = "TAKE_OUT"


class OrderWorkflowService(Protocol):
    """Order service operations required by the runtime."""

    def claim_workflow_orders(self, limit: int = 10) -> list[Any]:
        ...

    def complete_workflow_order(self, order_id: int) -> bool:
        ...

    def fail_workflow_order(self, order_id: int) -> bool:
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

    def start_serving(
        self,
        command_id: str,
        order_id: int,
        table_number: int | None,
        order_items: list | None = None,
    ) -> bool:
        ...


class OrderWorkflowScheduler:
    """Public facade that claims orders and drives manufacture/serving queues."""

    def __init__(
        self,
        *,
        order_service: OrderWorkflowService,
        manufacture_port: DDoobyManufacturePort,
        serving_port: DobyServingPort,
        logger: logging.Logger,
        tick_interval_sec: float = 1.0,
        claim_limit: int = 10,
        backoff_sec: tuple[float, ...] = (2.0, 5.0, 10.0),
        max_retry_count: int = 3,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.state = WorkflowInmemoryState()
        self.order_service = order_service
        self.manufacture_port = manufacture_port
        self.serving_port = serving_port
        self.logger = logger
        self.tick_interval_sec = tick_interval_sec
        self.claim_limit = claim_limit
        self.backoff_sec = backoff_sec
        self.max_retry_count = max_retry_count
        self.time_fn = time_fn

        self._claim_thread: threading.Thread | None = None
        self._manufacture_thread: threading.Thread | None = None
        self._serving_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._claim_thread is not None and self._claim_thread.is_alive():
            return
        self.state.clear_stop_requested()
        self._claim_thread = self._start_thread(
            "order-orchestration-claim",
            self._claim_loop,
        )
        self._manufacture_thread = self._start_thread(
            "order-orchestration-manufacture",
            self._manufacture_loop,
        )
        self._serving_thread = self._start_thread(
            "order-orchestration-serving",
            self._serving_loop,
        )
        self.logger.info("order orchestration runtime started")

    def stop(self) -> None:
        self.state.request_stop()
        for thread in (self._claim_thread, self._manufacture_thread, self._serving_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self._fail_in_progress_items()
        self.logger.info("order orchestration runtime stopped")

    def tick(self) -> None:
        self._claim_new_orders()

    def on_manufacture_completed(self, order_id: int, command_id: str | None = None) -> bool:
        item = self.state.complete_current_manufacture(order_id, command_id)
        if item is None:
            return False
        self.logger.info(
            "manufacture completed subscribed order_id=%s command_id=%s",
            order_id,
            command_id,
        )
        complete_now = item.receive_type == TAKE_OUT_RECEIVE_TYPE
        if complete_now:
            self._mark_order_completed(item, completed_after="manufacture")
        else:
            self.state.enqueue_serving(order_id)
        return True

    def on_serving_completed(self, order_id: int, command_id: str | None = None) -> bool:
        item = self.state.complete_current_serving(order_id, command_id)
        if item is None:
            return False
        self.logger.info(
            "serving completed subscribed order_id=%s command_id=%s",
            order_id,
            command_id,
        )
        self._mark_order_completed(item, completed_after="serving")
        return True

    def on_serving_failed(
        self,
        order_id: int,
        command_id: str | None = None,
        reason: str = "serving action failed",
    ) -> bool:
        decision = self.state.retry_serving_current_or_exhaust(
            order_id,
            RuntimeError(reason),
            self.max_retry_count,
            self.backoff_sec,
            self.time_fn(),
        )
        if decision is None:
            return False
        self.logger.warning(
            "serving failed subscribed order_id=%s command_id=%s reason=%s",
            order_id,
            command_id,
            reason,
        )
        self._handle_retry_decision(decision)
        return True

    def list_work_items(self) -> list[WorkItem]:
        return self.state.list_work_items()

    def _start_thread(self, name: str, target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(target=target, daemon=True, name=name)
        thread.start()
        return thread

    def _claim_loop(self) -> None:
        while not self.state.is_stop_requested():
            try:
                self._claim_new_orders()
            except Exception:
                self.logger.exception("order orchestration claim failed")
            self.state.wait_for_stop_requested(self.tick_interval_sec)

    def _claim_new_orders(self) -> None:
        claimed = self.order_service.claim_workflow_orders(self.claim_limit)
        if not claimed:
            return
        work_items = [self._build_work_item(order) for order in claimed]
        added_items = self.state.add_manufacture_work_items(work_items)
        for work_item in added_items:
            self.logger.info(
                "accepted order claimed order_id=%s receive_type=%s table_number=%s item_count=%s",
                work_item.order_id,
                work_item.receive_type,
                work_item.table_number,
                len(work_item.order_items),
            )

    def _build_work_item(self, order: Any) -> WorkItem:
        order_id = int(order.order_id)
        order_items = [
            ManufactureOrderItem(
                product_id=int(item.product_id),
                product_name=str(item.product_name),
                product_type=str(item.product_type),
                selected_options=list(item.selected_options),
                quantity=int(item.quantity),
                unit_price=int(item.unit_price),
            )
            for item in order.order_items
        ]
        return WorkItem(
            order_id=order_id,
            receive_type=str(getattr(order, "receive_type", "")),
            table_number=getattr(order, "table_number", None),
            order_items=order_items,
        )

    def _manufacture_loop(self) -> None:
        while not self.state.is_stop_requested():
            item = self.state.wait_for_next_manufacture_item(
                self.tick_interval_sec,
                self.time_fn,
            )
            if item is None:
                continue
            try:
                self._start_manufacture(item)
            except Exception as exc:
                decision = self.state.retry_manufacture_current_or_exhaust(
                    item.order_id,
                    exc,
                    self.max_retry_count,
                    self.backoff_sec,
                    self.time_fn(),
                )
                self._handle_retry_decision(decision)
                continue
            self.state.mark_item_started(item.order_id)

    def _serving_loop(self) -> None:
        while not self.state.is_stop_requested():
            item = self.state.wait_for_next_serving_item(
                self.tick_interval_sec,
                self.time_fn,
            )
            if item is None:
                continue
            try:
                self._start_serving(item)
            except Exception as exc:
                decision = self.state.retry_serving_current_or_exhaust(
                    item.order_id,
                    exc,
                    self.max_retry_count,
                    self.backoff_sec,
                    self.time_fn(),
                )
                self._handle_retry_decision(decision)
                continue
            self.state.mark_item_started(item.order_id)

    def _start_manufacture(self, item: WorkItem) -> None:
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

    def _start_serving(self, item: WorkItem) -> None:
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
            item.order_items,
        )
        if not ok:
            raise RuntimeError("serving start rejected")

    def _mark_order_completed(self, item: WorkItem, *, completed_after: str) -> None:
        completed = self.order_service.complete_workflow_order(item.order_id)
        if completed:
            self.state.remove_order(item.order_id)
            self.logger.info(
                "order completed order_id=%s completed_after=%s receive_type=%s "
                "table_number=%s manufacture_command_id=%s serving_command_id=%s",
                item.order_id,
                completed_after,
                item.receive_type,
                item.table_number,
                item.manufacture_command_id,
                item.serving_command_id,
            )

    def _handle_retry_decision(self, decision: RetryDecision | None) -> None:
        if decision is None:
            return
        item = decision.item
        if decision.exhausted:
            self.logger.error(
                "order orchestration action exhausted retries order_id=%s error=%s",
                item.order_id,
                item.last_error,
            )
            self.order_service.fail_workflow_order(item.order_id)
            return
        self.logger.warning(
            "order orchestration action failed order_id=%s retry_count=%s error=%s",
            item.order_id,
            item.retry_count,
            item.last_error,
        )

    def _fail_in_progress_items(self) -> None:
        items = self.state.list_work_items()

        for item in items:
            failed = self.order_service.fail_workflow_order(item.order_id)
            if failed:
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
            self.state.remove_orders([item.order_id for item in items])
