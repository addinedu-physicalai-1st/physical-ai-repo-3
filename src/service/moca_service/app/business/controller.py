import logging

from app.protocol.health_status_protocol import build_status_frame
from app.protocol.catalog_protocol import CatalogResponse
from app.protocol.moca_protocol import (
    ERROR_CATALOG_UNAVAILABLE,
    ERROR_ORDER_REJECTED,
)
from app.protocol.order_protocol import OrderRequest, OrderResponse
from app.business.service import MocaService
from app.transport.tcp_sender import TcpSender


class MocaController:
    def __init__(
        self,
        service: MocaService,
        tcp_sender: TcpSender,
        logger: logging.Logger,
    ):
        self.service = service
        self.tcp_sender = tcp_sender
        self.logger = logger

    def run_health_test(self, seq: int) -> None:
        self.logger.info("running moca_service fan-out health test seq=%s", seq)
        self.tcp_sender.broadcast_frame(build_status_frame(seq))

    def handle_status(self, seq: int, peer: tuple[str, int]) -> None:
        self.logger.info("received STATUS seq=%s from %s:%s", seq, peer[0], peer[1])

    def get_catalog(self) -> CatalogResponse:
        try:
            return CatalogResponse.ok(self.service.get_catalog())
        except Exception as exc:
            self.logger.warning("catalog request failed: %s", exc)
            return CatalogResponse.error(ERROR_CATALOG_UNAVAILABLE, str(exc))

    def create_order(self, request: OrderRequest) -> OrderResponse:
        try:
            self.service.create_order(request)
        except Exception as exc:
            self.logger.warning("order request failed: %s", exc)
            return OrderResponse.error(ERROR_ORDER_REJECTED, str(exc))
        return OrderResponse.ok()
