import struct
from dataclasses import dataclass

from app.protocol.header_protocol import STATUS_OK, decode_error_payload, encode_error_payload

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


@dataclass(frozen=True)
class OrderResponse:
    error_code: int | None = None
    message: str = ""

    @classmethod
    def ok(cls) -> "OrderResponse":
        return cls()

    @classmethod
    def error(cls, error_code: int, message: str) -> "OrderResponse":
        return cls(error_code=error_code, message=message)

    @property
    def is_error(self) -> bool:
        return self.error_code is not None


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


def parse_order_payload(payload: bytes) -> OrderRequest:
    if len(payload) < ORDER_HEADER_SIZE:
        raise ValueError(f"invalid order payload length: {len(payload)}")

    order_header = payload[:ORDER_HEADER_SIZE]
    _, _, item_count = parse_order_header(order_header)
    expected_size = ORDER_HEADER_SIZE + item_count * ORDER_ITEM_SIZE
    if len(payload) != expected_size:
        raise ValueError(f"invalid order payload length: {len(payload)}")

    return parse_order_request(order_header, payload[ORDER_HEADER_SIZE:])


def encode_order_success_payload() -> bytes:
    """Encode a successful order response payload."""

    return bytes([STATUS_OK])


def encode_order_response_payload(response: OrderResponse) -> bytes:
    """Encode an order response payload."""

    if response.is_error:
        if response.error_code is None:
            raise ValueError("order response missing error code")
        return encode_error_payload(response.error_code, response.message)
    return encode_order_success_payload()


def decode_order_response_payload(payload: bytes) -> tuple[bool, str | None]:
    """Decode an order response into success flag and optional rejection message."""

    if payload == bytes([STATUS_OK]):
        return True, None
    _, message = decode_error_payload(payload)
    return False, message
