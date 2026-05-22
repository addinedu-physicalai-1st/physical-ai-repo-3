import logging
from dataclasses import dataclass
from typing import Any

from app.communication.web_service.protocol.catalog_protocol import (
    CatalogResponse,
    ProductManagementResponse,
)
from app.communication.web_service.protocol.header_protocol import (
    ERROR_CATALOG_UNAVAILABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_ORDER_REJECTED,
    ERROR_PRODUCT_MANAGEMENT_FAILED,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    ERROR_TABLE_UNAVAILABLE,
)
from app.communication.web_service.protocol.order_protocol import OrderResponse
from app.communication.web_service.protocol.table_protocol import TableAssignmentResponse, TableResponse
from app.service.menu_service import MenuService
from app.service.order_service import OrderService
from app.service.request_models import OrderRequest, ProductManagementRequest, TableAssignmentRequest


@dataclass(frozen=True)
class ServiceError:
    error_code: int
    message: str


class WebServiceTcpController:
    def __init__(
        self,
        menu_service: MenuService,
        order_service: OrderService,
        logger: logging.Logger,
    ) -> None:
        self.menu_service = menu_service
        self.order_service = order_service
        self.logger = logger

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
        return ProductManagementResponse.ok(_result_dict(result.result))

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

    def determine_receive_type(self, request: TableAssignmentRequest) -> TableAssignmentResponse:
        try:
            result = self.order_service.determine_receive_type(request)
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


def _result_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if value is not None else {}
