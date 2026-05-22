from dataclasses import dataclass
from typing import Any, Literal

ProductAction = Literal["create", "get", "list", "update", "delete"]
ReceiveType = Literal["take_out", "dine_in"]


@dataclass(frozen=True)
class ProductManagementRequest:
    action: ProductAction
    product_id: int = 0
    product: dict[str, Any] | None = None
    include_paused: bool = False


@dataclass(frozen=True)
class OrderItemRequest:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class OrderRequest:
    items: list[OrderItemRequest]


@dataclass(frozen=True)
class TableAssignmentRequest:
    order_id: int
    receive_type: ReceiveType
    table_number: int
