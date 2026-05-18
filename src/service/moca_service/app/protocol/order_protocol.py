import struct
from dataclasses import dataclass

ORDER_HEADER_SIZE = 3
ORDER_ITEM_SIZE = 3


@dataclass(frozen=True)
class OrderItemRequest:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class OrderRequest:
    receive_type: int
    table_id: int
    items: list[OrderItemRequest]


def parse_order_header(header: bytes) -> tuple[int, int, int]:
    if len(header) != ORDER_HEADER_SIZE:
        raise ValueError(f"invalid order header length: {len(header)}")
    receive_type, table_id, item_count = header
    if receive_type not in {0, 1}:
        raise ValueError(f"invalid receive_type={receive_type}")
    if item_count <= 0:
        raise ValueError("item_count must be greater than 0")
    return receive_type, table_id, item_count


def parse_order_request(header: bytes, item_bytes: bytes) -> OrderRequest:
    receive_type, table_id, item_count = parse_order_header(header)
    expected_size = item_count * ORDER_ITEM_SIZE
    if len(item_bytes) != expected_size:
        raise ValueError(f"invalid order items length: {len(item_bytes)}")

    items: list[OrderItemRequest] = []
    for offset in range(0, expected_size, ORDER_ITEM_SIZE):
        product_id, quantity = struct.unpack(">HB", item_bytes[offset : offset + ORDER_ITEM_SIZE])
        if product_id <= 0:
            raise ValueError("product_id must be greater than 0")
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0")
        items.append(OrderItemRequest(product_id=product_id, quantity=quantity))

    return OrderRequest(receive_type=receive_type, table_id=table_id, items=items)
