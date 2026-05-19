import logging
from typing import TYPE_CHECKING
from typing import Any

from app.protocol.order_protocol import OrderRequest
from app.domain.table_assignment_runtime import TableAssignmentRuntime

if TYPE_CHECKING:
    from app.repository.catalog_repo import CatalogRepository
    from app.repository.order_repo import CreatedOrder
    from app.repository.order_repo import OrderRepository


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

    def create_order(self, request: OrderRequest) -> bool:
        created = self.order_repository.create_order(request)

        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s",
            created.order_id,
            created.total_price,
            len(request.items),
        )

        return True

    def get_table_assignment():
        pass

    def assign_table():
        pass
