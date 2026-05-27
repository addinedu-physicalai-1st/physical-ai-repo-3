import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.in_memory.table_inmemory_state import TableInmemoryState
from app.in_memory.workflow_inmemory_state import ManufactureOrderItem
from app.repository.order_repo import OrderItemCreate
from app.service.request_models import OrderRequest, TableAssignmentRequest

if TYPE_CHECKING:
    from app.repository.catalog_repo import ProductRepository
    from app.repository.db import Database
    from app.repository.order_repo import OrderItemRepository, OrderRepository
    from pymysql.connections import Connection


@dataclass(frozen=True)
class CreatedOrder:
    order_id: int
    total_price: int


@dataclass(frozen=True)
class ClaimedWorkflowOrder:
    order_id: int
    receive_type: str
    table_number: int | None
    order_items: list[ManufactureOrderItem]


@dataclass(frozen=True)
class CreateOrderResult:
    created_order: CreatedOrder | None = None
    message: str = ""

    @classmethod
    def ok(cls, created_order: CreatedOrder) -> "CreateOrderResult":
        return cls(created_order=created_order)

    @classmethod
    def rejected(cls, message: str) -> "CreateOrderResult":
        return cls(message=message)

    @property
    def is_ok(self) -> bool:
        return self.created_order is not None


@dataclass(frozen=True)
class DetermineReceiveTypeResult:
    error_kind: str | None = None
    message: str = ""

    @classmethod
    def ok(cls) -> "DetermineReceiveTypeResult":
        return cls()

    @classmethod
    def not_found(cls, message: str) -> "DetermineReceiveTypeResult":
        return cls(error_kind="not_found", message=message)

    @classmethod
    def rejected(cls, message: str) -> "DetermineReceiveTypeResult":
        return cls(error_kind="rejected", message=message)

    @property
    def is_ok(self) -> bool:
        return self.error_kind is None


@dataclass(frozen=True)
class _AssignmentInfo:
    order_source: str
    receive_type: str
    table_number: int | None = None


@dataclass(frozen=True)
class _TableAssignmentResult:
    table_number: int | None = None
    table_id: int | None = None
    message: str = ""

    @classmethod
    def ok(
        cls,
        table_number: int | None = None,
        table_id: int | None = None,
    ) -> "_TableAssignmentResult":
        return cls(table_number=table_number, table_id=table_id)

    @classmethod
    def rejected(cls, message: str) -> "_TableAssignmentResult":
        return cls(message=message)

    @property
    def is_ok(self) -> bool:
        return self.message == ""


class OrderService:
    def __init__(
        self,
        database: "Database",
        product_repository: "ProductRepository",
        order_repository: "OrderRepository",
        order_item_repository: "OrderItemRepository",
        table_inmemory_state: TableInmemoryState,
        logger: logging.Logger,
    ):
        self.database = database
        self.product_repository = product_repository
        self.order_repository = order_repository
        self.order_item_repository = order_item_repository
        self.table_state = table_inmemory_state
        self.logger = logger

    def create_order(self, request: OrderRequest) -> CreateOrderResult:
        # 1. Validate the request payload.
        rejection = self._validate_order_request(request)
        if rejection is not None:
            return CreateOrderResult.rejected(rejection)

        # 2. Fetch products, create the order, and insert order items in one transaction.
        with self.database.transaction() as conn:
            result = self._create_order_in_transaction(request, conn)

        # 3. Return any business rejection produced inside the transaction.
        if not result.is_ok or result.created_order is None:
            return result

        # 4. Log the created order and return a successful result.
        created = result.created_order
        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s",
            created.order_id,
            created.total_price,
            len(request.items),
        )
        return CreateOrderResult.ok(created)

    def get_table_assignment(self):
        # 1. Return the current in-memory table state.
        return self.table_state.get_states()

    def determine_receive_type(self, request: TableAssignmentRequest) -> DetermineReceiveTypeResult:
        # 1. Load the order and reject unknown order IDs.
        with self.database.connect() as conn:
            order = self.order_repository.get(conn, request.order_id)
        if order is None:
            return DetermineReceiveTypeResult.not_found(f"order {request.order_id} not found")

        # 2. Convert the request into the assignment info stored in the database.
        assignment_info = _AssignmentInfo(
            order_source="COUNTER",
            receive_type="TAKE_OUT" if request.receive_type == "take_out" else "DINE_IN",
            table_number=None if request.receive_type == "take_out" else request.table_number,
        )

        # 3. Return success immediately if the order already has the same assignment.
        if (
            order.order_source == assignment_info.order_source
            and order.receive_type == assignment_info.receive_type
            and self._convert_table_id_to_number(order.table_id) == assignment_info.table_number
        ):
            return DetermineReceiveTypeResult.ok()

        # 4. Reject orders that already have a different assignment.
        if order.receive_type != "PENDING" or order.table_id is not None:
            return DetermineReceiveTypeResult.rejected(f"order {request.order_id} is already assigned")

        # 5. Assign an in-memory table first for dine-in orders.
        assignment_result = self._assign_table(request)
        if not assignment_result.is_ok:
            return DetermineReceiveTypeResult.rejected(assignment_result.message)

        # 6. Persist the assignment and release the reservation if the DB update fails.
        return self._update_receive_type(request, assignment_info, assignment_result)

    def _create_order_in_transaction(
        self,
        request: OrderRequest,
        conn: "Connection",
    ) -> CreateOrderResult:
        product_ids = [item.product_id for item in request.items]
        products = self.product_repository.list_by_ids_and_status(
            conn,
            product_ids,
            "ON_SALE",
        )
        prices = {product.product_id: product.price for product in products}

        missing_product_ids = sorted(set(product_ids) - set(prices))
        if missing_product_ids:
            return CreateOrderResult.rejected(
                f"unknown or unavailable product_id={missing_product_ids[0]}"
            )

        total_price = sum(prices[item.product_id] * item.quantity for item in request.items)
        order_id = self.order_repository.create(
            conn,
            "COUNTER",
            "PENDING",
            None,
            total_price,
        )
        self.order_item_repository.create_many(
            conn,
            [
                OrderItemCreate(
                    order_id=order_id,
                    product_id=item.product_id,
                    selected_options=[],
                    quantity=item.quantity,
                    unit_price=prices[item.product_id],
                )
                for item in request.items
            ],
        )
        return CreateOrderResult.ok(
            CreatedOrder(order_id=order_id, total_price=total_price)
        )

    def _update_receive_type(
        self,
        request: TableAssignmentRequest,
        assignment_info: "_AssignmentInfo",
        assignment_result: "_TableAssignmentResult",
    ) -> DetermineReceiveTypeResult:
        with self.database.transaction() as conn:
            updated = self.order_repository.update_assignment_if_pending(
                conn,
                request.order_id,
                assignment_info.order_source,
                assignment_info.receive_type,
                assignment_result.table_id,
            )
            latest_order = None if updated else self.order_repository.get(conn, request.order_id)

        if updated:
            return DetermineReceiveTypeResult.ok()

        if assignment_result.table_number is not None:
            self.table_state.release(assignment_result.table_number)

        if latest_order is None:
            return DetermineReceiveTypeResult.not_found(f"order {request.order_id} not found")
        elif (
            latest_order.order_source == assignment_info.order_source
            and latest_order.receive_type == assignment_info.receive_type
            and latest_order.table_id == assignment_result.table_id
        ):
            return DetermineReceiveTypeResult.ok()
        else:
            return DetermineReceiveTypeResult.rejected(f"order {request.order_id} is already assigned")

    def _validate_order_request(self, request: OrderRequest) -> str | None:
        if not request.items:
            return "order must contain at least one item"
        for item in request.items:
            if item.product_id <= 0:
                return f"invalid product_id={item.product_id}"
            if item.quantity <= 0:
                return f"invalid quantity={item.quantity} for product_id={item.product_id}"
        return None

    def _assign_table(self, request: TableAssignmentRequest) -> "_TableAssignmentResult":
        if request.receive_type == "take_out":
            return _TableAssignmentResult.ok()

        occupied_table_number, message = self.table_state.occupy(request.table_number)
        if occupied_table_number is None:
            return _TableAssignmentResult.rejected(message)

        table_id = None
        for table in self.table_state.get_states():
            if table.table_number == occupied_table_number:
                table_id = table.table_id
                break

        if table_id is None:
            self.table_state.release(occupied_table_number)
            return _TableAssignmentResult.rejected(f"unknown table_number={occupied_table_number}")

        return _TableAssignmentResult.ok(table_number=occupied_table_number, table_id=table_id)

    def _convert_table_id_to_number(self, table_id: int | None) -> int | None:
        if table_id is None:
            return None
        for table in self.table_state.get_states():
            if table.table_id == table_id:
                return table.table_number
        return None

    def list_recent_orders(self, limit: int = 20):
        with self.database.connect() as conn:
            return self.order_repository.list_recent(conn, limit)

    def claim_workflow_orders(self, limit: int = 10) -> list[ClaimedWorkflowOrder]:
        with self.database.transaction() as conn:
            claimed = self.order_repository.claim_accepted_orders(conn, limit)
            return [
                ClaimedWorkflowOrder(
                    order_id=int(order.order_id),
                    receive_type=str(order.receive_type),
                    table_number=order.table_number,
                    order_items=[
                        ManufactureOrderItem(
                            product_id=int(item.product_id),
                            product_name=str(item.product_name),
                            selected_options=list(item.selected_options),
                            quantity=int(item.quantity),
                            unit_price=int(item.unit_price),
                        )
                        for item in self.order_item_repository.list_by_order_id(
                            conn,
                            int(order.order_id),
                        )
                    ],
                )
                for order in claimed
            ]

    def complete_workflow_order(self, order_id: int) -> bool:
        with self.database.connect() as conn:
            return self.order_repository.mark_completed(conn, order_id)

    def fail_workflow_order(self, order_id: int) -> bool:
        with self.database.connect() as conn:
            return self.order_repository.mark_failed(conn, order_id)
