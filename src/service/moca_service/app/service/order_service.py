import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.in_memory.table_inmemory_state import TableInmemoryState
from app.repository.order_repo import OrderRow
from app.repository.order_repo import OrderItemCreate
from app.service.request_models import OrderItemRequest, OrderRequest, TableAssignmentRequest

if TYPE_CHECKING:
    from app.repository.catalog_repo import ProductRepository
    from app.repository.db import Database
    from app.repository.order_repo import OrderItemRepository, OrderRepository
    from app.repository.table_repo import TableRepository


@dataclass(frozen=True)
class CreatedOrder:
    order_id: int
    total_price: int


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
class TableAssignmentResult:
    error_kind: str | None = None
    message: str = ""

    @classmethod
    def ok(cls) -> "TableAssignmentResult":
        return cls()

    @classmethod
    def not_found(cls, message: str) -> "TableAssignmentResult":
        return cls(error_kind="not_found", message=message)

    @classmethod
    def rejected(cls, message: str) -> "TableAssignmentResult":
        return cls(error_kind="rejected", message=message)

    @property
    def is_ok(self) -> bool:
        return self.error_kind is None


class OrderNotFound(Exception):
    pass


class TableAssignmentRejected(Exception):
    pass


class OrderService:
    def __init__(
        self,
        database: "Database",
        product_repository: "ProductRepository",
        order_repository: "OrderRepository",
        order_item_repository: "OrderItemRepository",
        table_repository: "TableRepository",
        table_inmemory_state: TableInmemoryState,
        logger: logging.Logger,
    ):
        self.database = database
        self.product_repository = product_repository
        self.order_repository = order_repository
        self.order_item_repository = order_item_repository
        self.table_repository = table_repository
        self.table_state = table_inmemory_state
        self.logger = logger

    def create_order(self, request: OrderRequest) -> CreateOrderResult:
        rejection = self._validate_order_request(request)
        if rejection is not None:
            return CreateOrderResult.rejected(rejection)

        product_ids = [item.product_id for item in request.items]

        with self.database.transaction() as conn:
            products = self.product_repository.list_by_ids_and_status(product_ids, "ON_SALE", conn)
            prices = {product.product_id: product.price for product in products}
            missing_product_id = self._first_missing_product_id(product_ids, prices)
            if missing_product_id is not None:
                return CreateOrderResult.rejected(f"unknown or unavailable product_id={missing_product_id}")

            total_price = self._calculate_total_price(request.items, prices)
            order_id = self.order_repository.create(
                "COUNTER",
                "PENDING",
                None,
                total_price,
                conn,
            )
            self.order_item_repository.create_many(
                self._build_order_items(order_id, request.items, prices),
                conn,
            )

        created = CreatedOrder(order_id=order_id, total_price=total_price)
        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s",
            created.order_id,
            created.total_price,
            len(request.items),
        )
        return CreateOrderResult.ok(created)

    def get_table_assignment(self):
        return self.table_state.get_states()

    def determine_receive_type(self, request: TableAssignmentRequest) -> TableAssignmentResult:
        order = self.order_repository.get(request.order_id)
        if order is None:
            return TableAssignmentResult.not_found(f"order {request.order_id} not found")

        order_source, receive_type, table_number = self._target_assignment(request)
        if self._has_assignment(order, order_source, receive_type, table_number):
            if order.order_status == "PENDING":
                self.order_repository.accept_if_pending(request.order_id)
            return TableAssignmentResult.ok()

        if not self._can_assign(order):
            return TableAssignmentResult.rejected(f"order {request.order_id} is already assigned")

        reservation = self._reserve_table_if_needed(request)
        if not reservation.is_ok:
            return TableAssignmentResult.rejected(reservation.message)

        latest_order = None
        try:
            with self.database.transaction() as conn:
                updated = self.order_repository.update_assignment_if_pending(
                    request.order_id,
                    order_source,
                    receive_type,
                    reservation.table_id,
                    conn,
                )
                if not updated:
                    latest_order = self.order_repository.get(request.order_id, conn)
        except Exception:
            reservation.release(self.table_state)
            raise

        if not updated:
            reservation.release(self.table_state)
            if latest_order is None:
                return TableAssignmentResult.not_found(f"order {request.order_id} not found")
            if self._has_assignment(latest_order, order_source, receive_type, table_number):
                return TableAssignmentResult.ok()
            return TableAssignmentResult.rejected(f"order {request.order_id} is already assigned")

        return TableAssignmentResult.ok()

    def _validate_order_request(self, request: OrderRequest) -> str | None:
        if not request.items:
            return "order must contain at least one item"
        for item in request.items:
            if item.product_id <= 0:
                return f"invalid product_id={item.product_id}"
            if item.quantity <= 0:
                return f"invalid quantity={item.quantity} for product_id={item.product_id}"
        return None

    def _first_missing_product_id(self, product_ids: list[int], prices: dict[int, int]) -> int | None:
        missing = sorted(set(product_ids) - set(prices))
        return missing[0] if missing else None

    def _calculate_total_price(self, items: list[OrderItemRequest], prices: dict[int, int]) -> int:
        return sum(prices[item.product_id] * item.quantity for item in items)

    def _build_order_items(
        self,
        order_id: int,
        items: list[OrderItemRequest],
        prices: dict[int, int],
    ) -> list[OrderItemCreate]:
        return [
            OrderItemCreate(
                order_id=order_id,
                product_id=item.product_id,
                selected_options=[],
                quantity=item.quantity,
                unit_price=prices[item.product_id],
            )
            for item in items
        ]

    def _can_assign(self, order: OrderRow) -> bool:
        return order.receive_type == "PENDING" and order.table_id is None

    def _has_assignment(
        self,
        order: OrderRow,
        order_source: str,
        receive_type: str,
        table_number: int | None,
    ) -> bool:
        return (
            order.order_source == order_source
            and order.receive_type == receive_type
            and self._convert_table_id_to_number(order.table_id) == table_number
        )

    def _target_assignment(self, request: TableAssignmentRequest) -> tuple[str, str, int | None]:
        if request.receive_type == "take_out":
            return "COUNTER", "TAKE_OUT", None
        return "COUNTER", "DINE_IN", request.table_number

    def _reserve_table_if_needed(self, request: TableAssignmentRequest) -> "_TableReservation":
        if request.receive_type == "take_out":
            return _TableReservation.ok()

        occupied_table_number, message = self.table_state.occupy(request.table_number)
        if occupied_table_number is None:
            return _TableReservation.rejected(message)

        table_id = self._convert_table_number_to_id(occupied_table_number)
        if table_id is None:
            self.table_state.release(occupied_table_number)
            return _TableReservation.rejected(f"unknown table_number={occupied_table_number}")

        return _TableReservation.ok(table_number=occupied_table_number, table_id=table_id)

    def _convert_table_number_to_id(self, table_number: int) -> int | None:
        for table in self.table_state.get_states():
            if table.table_number == table_number:
                return table.table_id
        return None

    def _convert_table_id_to_number(self, table_id: int | None) -> int | None:
        if table_id is None:
            return None
        for table in self.table_state.get_states():
            if table.table_id == table_id:
                return table.table_number
        return None


@dataclass(frozen=True)
class _TableReservation:
    table_number: int | None = None
    table_id: int | None = None
    message: str = ""

    @classmethod
    def ok(
        cls,
        table_number: int | None = None,
        table_id: int | None = None,
    ) -> "_TableReservation":
        return cls(table_number=table_number, table_id=table_id)

    @classmethod
    def rejected(cls, message: str) -> "_TableReservation":
        return cls(message=message)

    @property
    def is_ok(self) -> bool:
        return self.message == ""

    def release(self, table_state: TableInmemoryState) -> None:
        if self.table_number is not None:
            table_state.release(self.table_number)
