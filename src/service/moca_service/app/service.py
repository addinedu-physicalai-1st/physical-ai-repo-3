import logging
from typing import Any

from app.tcp import StatusNotifier
from app.catalog_repo import CatalogRepository
from app.order_protocol import OrderRequest
from app.order_repo import OrderRepository


class MocaService:
    def __init__(
        self,
        status_notifiers: list[StatusNotifier],
        catalog_repository: CatalogRepository,
        order_repository: OrderRepository,
        logger: logging.Logger,
    ):
        self.status_notifiers = status_notifiers
        self.catalog_repository = catalog_repository
        self.order_repository = order_repository
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
        created = self.order_repository.create_order(request)
        self.logger.info(
            "created order order_id=%s total_price=%s item_count=%s",
            created.order_id,
            created.total_price,
            len(request.items),
        )
