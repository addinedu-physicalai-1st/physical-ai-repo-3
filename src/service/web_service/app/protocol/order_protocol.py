import struct
from dataclasses import dataclass

from app.protocol.header_protocol import STATUS_OK, decode_error_payload

MAX_U8 = 0xFF
MAX_U16 = 0xFFFF
RECEIVE_PICKUP = 0
RECEIVE_SERVING = 1


@dataclass(frozen=True)
class MocaOrderItem:
    """One order line in the MOCA binary order payload."""

    product_id: int
    quantity: int


def encode_order_request_payload(receive_type: int, table_id: int, items: list[MocaOrderItem]) -> bytes:
    """Encode order request payload."""

    _validate_order_header(receive_type, table_id, len(items))

    payload = bytearray([receive_type, table_id, len(items)])
    for item in items:
        _validate_order_item(item)
        payload.extend(struct.pack(">HB", item.product_id, item.quantity))
    return bytes(payload)


def encode_order_success_payload() -> bytes:
    """Encode a successful order response payload."""

    return bytes([STATUS_OK])


def decode_order_response_payload(payload: bytes) -> tuple[bool, str | None]:
    """Decode an order response into success flag and optional rejection message."""

    if payload == bytes([STATUS_OK]):
        return True, None
    _, message = decode_error_payload(payload)
    return False, message


def _validate_order_header(receive_type: int, table_id: int, item_count: int) -> None:
    if receive_type not in {RECEIVE_PICKUP, RECEIVE_SERVING}:
        raise ValueError(f"invalid receive_type={receive_type}")
    if not 0 <= table_id <= MAX_U8:
        raise ValueError(f"invalid table_id={table_id}")
    if not 1 <= item_count <= MAX_U8:
        raise ValueError(f"invalid item_count={item_count}")


def _validate_order_item(item: MocaOrderItem) -> None:
    if not 1 <= item.product_id <= MAX_U16:
        raise ValueError(f"invalid product_id={item.product_id}")
    if not 1 <= item.quantity <= MAX_U8:
        raise ValueError(f"invalid quantity={item.quantity}")
