import logging
from typing import TYPE_CHECKING
from typing import Any

from app.protocol.order_protocol import OrderRequest
from app.business.table_assignment_runtime import TableAssignmentRuntime

if TYPE_CHECKING:
    from app.repo.catalog_repo import CatalogRepository
    from app.repo.order_repo import OrderRepository


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

    def create_order(self, request: OrderRequest) -> None:
        reserved_table_id = request.table_id if request.receive_type == 1 and request.table_id > 0 else None
        if reserved_table_id is not None:
            self.table_assignment_runtime.occupy(reserved_table_id)

        try:
            created = self.order_repository.create_order(request)
        except Exception:
            if reserved_table_id is not None:
                self.table_assignment_runtime.release(reserved_table_id)
            raise

        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s table_id=%s",
            created.order_id,
            created.total_price,
            len(request.items),
            request.table_id,
        )
