import logging

from app.protocol.health_status_protocol import build_status_frame
from app.protocol.catalog_protocol import CatalogResponse, ProductManagementRequest, ProductManagementResponse
from app.protocol.header_protocol import (
    ERROR_CATALOG_UNAVAILABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_ORDER_REJECTED,
    ERROR_PRODUCT_MANAGEMENT_FAILED,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    ERROR_TABLE_UNAVAILABLE,
)
from app.protocol.order_protocol import OrderRequest, OrderResponse
from app.protocol.table_protocol import TableAssignmentRequest, TableAssignmentResponse, TableResponse
from app.application.menu_service import MenuService
from app.application.order_service import OrderService
from app.transport.tcp_sender import TcpSender


class MocaTcpController:
    def __init__(
        self,
        order_service: OrderService,
        menu_service: MenuService,
        tcp_sender: TcpSender,
        logger: logging.Logger,
    ):
        self.order_service = order_service
        self.menu_service = menu_service
        self.tcp_sender = tcp_sender
        self.logger = logger

    def run_health_test(self, seq: int) -> None:
        self.logger.info("running moca_service fan-out health test seq=%s", seq)
        self.tcp_sender.broadcast_frame(build_status_frame(seq))

    def handle_status(self, seq: int, peer: tuple[str, int]) -> None:
        self.logger.info("received STATUS seq=%s from %s:%s", seq, peer[0], peer[1])

    def get_catalog(self) -> CatalogResponse:
        try:
            return CatalogResponse.ok(self.menu_service.get_catalog())
        except Exception as exc:
            self.logger.warning("catalog request failed: %s", exc)
            return CatalogResponse.error(ERROR_CATALOG_UNAVAILABLE, str(exc))

    def manage_product(self, request: ProductManagementRequest) -> ProductManagementResponse:
        try:
            result = self.menu_service.manage_product(request)
        except Exception as exc:
            self.logger.warning("product management failed: %s", exc)
            return ProductManagementResponse.error(ERROR_PRODUCT_MANAGEMENT_FAILED, str(exc))
        if not result.is_ok:
            self.logger.warning("product management rejected: %s", result.message)
            return ProductManagementResponse.error(ERROR_PRODUCT_MANAGEMENT_FAILED, result.message)
        return ProductManagementResponse.ok(result.result or {})

    def create_order(self, request: OrderRequest) -> OrderResponse:
        try:
            result = self.order_service.create_order(request)
        except Exception as exc:
            self.logger.warning("order request failed: %s", exc)
            return OrderResponse.error(ERROR_ORDER_REJECTED, str(exc))
        if not result.is_ok or result.created_order is None:
            self.logger.warning("order request rejected: %s", result.message)
            return OrderResponse.error(ERROR_ORDER_REJECTED, result.message)
        return OrderResponse.ok(result.created_order.order_id)

    def get_table_assignment(self) -> TableResponse:
        try:
            return TableResponse.ok(self.order_service.get_table_assignment())
        except Exception as exc:
            self.logger.warning("table request failed: %s", exc)
            return TableResponse.error(ERROR_TABLE_UNAVAILABLE, str(exc))

    def assign_table(self, request: TableAssignmentRequest) -> TableAssignmentResponse:
        try:
            result = self.order_service.assign_table(request)
        except Exception as exc:
            self.logger.warning("table assignment failed: %s", exc)
            return TableAssignmentResponse.error(ERROR_TABLE_UNAVAILABLE, str(exc))
        if result.is_ok:
            return TableAssignmentResponse.ok()
        if result.error_kind == "not_found":
            self.logger.warning("table assignment order not found: %s", result.message)
            return TableAssignmentResponse.error(ERROR_ORDER_NOT_FOUND, result.message)
        self.logger.warning("table assignment rejected: %s", result.message)
        return TableAssignmentResponse.error(ERROR_TABLE_ASSIGNMENT_REJECTED, result.message)
