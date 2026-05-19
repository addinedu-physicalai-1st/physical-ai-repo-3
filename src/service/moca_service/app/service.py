import logging
from typing import TYPE_CHECKING
from typing import Any

from app.tcp import StatusNotifier
from app.protocol.order_protocol import OrderRequest
from app.table_state import TableStateStore

if TYPE_CHECKING:
    from app.repo.catalog_repo import CatalogRepository
    from app.repo.order_repo import OrderRepository


class MocaService:
    def __init__(
        self,
        status_notifiers: list[StatusNotifier],
        catalog_repository: "CatalogRepository",
        order_repository: "OrderRepository",
        table_state_store: TableStateStore,
        logger: logging.Logger,
    ):
        self.status_notifiers = status_notifiers
        self.catalog_repository = catalog_repository
        self.order_repository = order_repository
        self.table_state_store = table_state_store
        self.logger = logger

    def run_health_test(self, seq: int) -> None:
        self.logger.info("running moca_service fan-out health test seq=%s", seq)
        for status_notifier in self.status_notifiers:
            status_notifier.notify_status(seq)

    def handle_status(self, seq: int, peer: tuple[str, int]) -> None:
        self.logger.info("received STATUS seq=%s from %s:%s", seq, peer[0], peer[1])

    def get_catalog(self) -> dict[str, Any]:
        return self.catalog_repository.fetch_catalog()

    def create_order(self, request: OrderRequest) -> None:
        reserved_table_id = request.table_id if request.receive_type == 1 and request.table_id > 0 else None
        if reserved_table_id is not None:
            self.table_state_store.occupy(reserved_table_id)

        try:
            created = self.order_repository.create_order(request)
        except Exception:
            if reserved_table_id is not None:
                self.table_state_store.release(reserved_table_id)
            raise

        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s table_id=%s",
            created.order_id,
            created.total_price,
            len(request.items),
            request.table_id,
        )
