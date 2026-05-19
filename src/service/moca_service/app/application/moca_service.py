import logging
from typing import TYPE_CHECKING
from typing import Any

from app.domain.table_assignment_runtime import TableAssignmentRuntime, TableUnavailable
from app.protocol.order_protocol import OrderRequest
from app.protocol.table_protocol import TableAssignmentRequest

if TYPE_CHECKING:
    from app.repository.catalog_repo import CatalogRepository
    from app.repository.order_repo import CreatedOrder
    from app.repository.order_repo import OrderRepository


class OrderNotFound(Exception):
    pass


class TableAssignmentRejected(Exception):
    pass


class MocaService:
    def __init__(
        self,
        catalog_repository: "CatalogRepository",
        order_repository: "OrderRepository",
        table_assignment_runtime: TableAssignmentRuntime,
        logger: logging.Logger,
    ):
        self.catalog_repository = catalog_repository
        self.order_repository = order_repository
        self.table_assignment_runtime = table_assignment_runtime
        self.logger = logger

    def get_catalog(self) -> dict[str, Any]:
        return self.catalog_repository.fetch_catalog()

    def get_table_assignment(self):
        return self.table_assignment_runtime.list_tables()

    def create_order(self, request: OrderRequest) -> "CreatedOrder":
        created = self.order_repository.create_order(request)

        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s",
            created.order_id,
            created.total_price,
            len(request.items),
        )

        return created

    def assign_table(self, request: TableAssignmentRequest) -> None:
        assignment = self.order_repository.fetch_assignment(request.order_id)
        if assignment is None:
            raise OrderNotFound(f"order {request.order_id} not found")

        order_source, receive_type, table_number = self._target_assignment(request)
        if (
            assignment.order_source == order_source
            and assignment.receive_type == receive_type
            and assignment.table_number == table_number
        ):
            return

        if assignment.receive_type != "TAKE_OUT" or assignment.table_id is not None:
            raise TableAssignmentRejected(f"order {request.order_id} is already assigned")

        occupied_table_id: int | None = None
        if request.receive_type == "dine_in":
            try:
                occupied_table_id = self.table_assignment_runtime.occupy_by_table_number(request.table_number)
            except TableUnavailable as exc:
                raise TableAssignmentRejected(str(exc)) from exc

        try:
            updated = self.order_repository.update_assignment(
                request.order_id,
                order_source,
                receive_type,
                occupied_table_id,
            )
        except Exception:
            if occupied_table_id is not None:
                self.table_assignment_runtime.release(occupied_table_id)
            raise

        if not updated:
            if occupied_table_id is not None:
                self.table_assignment_runtime.release(occupied_table_id)
            raise OrderNotFound(f"order {request.order_id} not found")

    def _target_assignment(self, request: TableAssignmentRequest) -> tuple[str, str, int | None]:
        if request.receive_type == "take_out":
            return "COUNTER", "TAKE_OUT", None
        return "TABLE", "DINE_IN", request.table_number
