import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.table_assignment_runtime import TableAssignmentRuntime
from app.repository.order_repo import OrderItemCreate
from app.service.request_models import OrderRequest, TableAssignmentRequest

if TYPE_CHECKING:
    from app.repository.catalog_repo import ProductRepository
    from app.repository.db import Database
    from app.repository.order_repo import OrderItemRepository, OrderRepository
    from app.repository.table_repo import StoreTableRepository


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
        store_table_repository: "StoreTableRepository",
        table_assignment_runtime: TableAssignmentRuntime,
        logger: logging.Logger,
    ):
        self.database = database
        self.product_repository = product_repository
        self.order_repository = order_repository
        self.order_item_repository = order_item_repository
        self.store_table_repository = store_table_repository
        self.table_assignment_runtime = table_assignment_runtime
        self.logger = logger

    def create_order(self, request: OrderRequest) -> CreateOrderResult:
        product_ids = [item.product_id for item in request.items]

        with self.database.transaction() as conn:
            products = self.product_repository.list_by_ids_and_status(product_ids, "ON_SALE", conn)
            prices = {product.product_id: product.price for product in products}
            missing = sorted(set(product_ids) - set(prices))
            if missing:
                return CreateOrderResult.rejected(f"unknown or unavailable product_id={missing[0]}")

            total_price = sum(prices[item.product_id] * item.quantity for item in request.items)
            order_id = self.order_repository.create(
                "COUNTER",
                "PENDING",
                None,
                total_price,
                conn,
            )
            self.order_item_repository.create_many(
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
        return self.table_assignment_runtime.list_tables()

    def determine_receive_type(self, request: TableAssignmentRequest) -> TableAssignmentResult:
        # order 조회
        order = self.order_repository.get(request.order_id)
        if order is None:
            return TableAssignmentResult.not_found(f"order {request.order_id} not found")

        # table_id에서 table_number 추출
        order_source, receive_type, table_number = self._target_assignment(request)
        current_table_number = self._table_number_for_table_id(order.table_id)

        # 
        if (
            order.order_source == order_source
            and order.receive_type == receive_type
            and current_table_number == table_number
        ):
            if order.order_status == "PENDING":
                self.order_repository.accept_if_pending(request.order_id)
            return TableAssignmentResult.ok()

        if order.receive_type != "PENDING" or order.table_id is not None:
            return TableAssignmentResult.rejected(f"order {request.order_id} is already assigned")

        occupied_table_id: int | None = None
        if request.receive_type == "dine_in":
            occupied_table_id, message = self.table_assignment_runtime.try_occupy_by_table_number(request.table_number)
            if occupied_table_id is None:
                return TableAssignmentResult.rejected(message)

        latest_order = None
        try:
            with self.database.transaction() as conn:
                updated = self.order_repository.update_assignment_if_pending(
                    request.order_id,
                    order_source,
                    receive_type,
                    occupied_table_id,
                    conn,
                )
                if not updated:
                    latest_order = self.order_repository.get(request.order_id, conn)
        except Exception:
            if occupied_table_id is not None:
                self.table_assignment_runtime.release(occupied_table_id)
            raise

        if not updated:
            if occupied_table_id is not None:
                self.table_assignment_runtime.release(occupied_table_id)
            if latest_order is None:
                return TableAssignmentResult.not_found(f"order {request.order_id} not found")
            latest_table_number = self._table_number_for_table_id(latest_order.table_id)
            if (
                latest_order.order_source == order_source
                and latest_order.receive_type == receive_type
                and latest_table_number == table_number
            ):
                return TableAssignmentResult.ok()
            return TableAssignmentResult.rejected(f"order {request.order_id} is already assigned")

        return TableAssignmentResult.ok()

    def _target_assignment(self, request: TableAssignmentRequest) -> tuple[str, str, int | None]:
        if request.receive_type == "take_out":
            return "COUNTER", "TAKE_OUT", None
        return "COUNTER", "DINE_IN", request.table_number

    def _table_number_for_table_id(self, table_id: int | None) -> int | None:
        if table_id is None:
            return None
        table = self.store_table_repository.get(table_id)
        return table.table_number if table is not None else None
