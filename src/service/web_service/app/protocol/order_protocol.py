import struct
from dataclasses import dataclass

from app.protocol.header_protocol import STATUS_OK, decode_error_payload

MAX_U8 = 0xFF
MAX_U16 = 0xFFFF


@dataclass(frozen=True)
class MocaOrderItem:
    """One order line in the MOCA binary order payload."""

    product_id: int
    quantity: int


def encode_order_request_payload(items: list[MocaOrderItem]) -> bytes:
    """Encode order request payload."""

    _validate_order_header(len(items))

    payload = bytearray([len(items)])
    for item in items:
        _validate_order_item(item)
        payload.extend(struct.pack(">HB", item.product_id, item.quantity))
    return bytes(payload)


def encode_order_success_payload(order_id: int) -> bytes:
    """Encode a successful order response payload."""

    if not 1 <= order_id <= 0xFFFFFFFF:
        raise ValueError(f"invalid order_id={order_id}")
    return bytes([STATUS_OK]) + struct.pack(">I", order_id)


def decode_order_response_payload(payload: bytes) -> tuple[bool, int | None, str | None]:
    """Decode an order response into success flag, order_id, and optional rejection message."""

    if len(payload) == 5 and payload[0] == STATUS_OK:
        return True, struct.unpack(">I", payload[1:])[0], None
    _, message = decode_error_payload(payload)
    return False, None, message


def _validate_order_header(item_count: int) -> None:
    if not 1 <= item_count <= MAX_U8:
        raise ValueError(f"invalid item_count={item_count}")


def _validate_order_item(item: MocaOrderItem) -> None:
    if not 1 <= item.product_id <= MAX_U16:
        raise ValueError(f"invalid product_id={item.product_id}")
    if not 1 <= item.quantity <= MAX_U8:
        raise ValueError(f"invalid quantity={item.quantity}")
