import logging

from app.protocol.health_status_protocol import build_status_frame
from app.protocol.catalog_protocol import CatalogResponse
from app.protocol.header_protocol import (
    ERROR_CATALOG_UNAVAILABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_ORDER_REJECTED,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    ERROR_TABLE_UNAVAILABLE,
)
from app.protocol.order_protocol import OrderRequest, OrderResponse
from app.protocol.table_protocol import TableAssignmentRequest, TableAssignmentResponse, TableResponse
from app.application.moca_service import MocaService, OrderNotFound, TableAssignmentRejected
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
            created = self.service.create_order(request)
        except Exception as exc:
            self.logger.warning("order request failed: %s", exc)
            return OrderResponse.error(ERROR_ORDER_REJECTED, str(exc))
        return OrderResponse.ok(created.order_id)

    def get_table_assignment(self) -> TableResponse:
        try:
            return TableResponse.ok(self.service.get_table_assignment())
        except Exception as exc:
            self.logger.warning("table request failed: %s", exc)
            return TableResponse.error(ERROR_TABLE_UNAVAILABLE, str(exc))

    def assign_table(self, request: TableAssignmentRequest) -> TableAssignmentResponse:
        try:
            self.service.assign_table(request)
        except OrderNotFound as exc:
            self.logger.warning("table assignment order not found: %s", exc)
            return TableAssignmentResponse.error(ERROR_ORDER_NOT_FOUND, str(exc))
        except TableAssignmentRejected as exc:
            self.logger.warning("table assignment rejected: %s", exc)
            return TableAssignmentResponse.error(ERROR_TABLE_ASSIGNMENT_REJECTED, str(exc))
        except Exception as exc:
            self.logger.warning("table assignment failed: %s", exc)
            return TableAssignmentResponse.error(ERROR_TABLE_UNAVAILABLE, str(exc))
        return TableAssignmentResponse.ok()
