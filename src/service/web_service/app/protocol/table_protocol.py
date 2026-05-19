import struct
from typing import Any, Literal

from app.protocol.header_protocol import STATUS_ERROR, STATUS_OK, decode_error_payload

MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF
TABLE_STATUS_EMPTY = 0
TABLE_STATUS_OCCUPIED = 1
RECEIVE_TAKE_OUT = 0
RECEIVE_DINE_IN = 1

TableStatus = Literal["empty", "occupied"]
ReceiveType = Literal["take_out", "dine_in"]


def decode_table_payload(payload: bytes) -> list[dict[str, Any]]:
    """Decode MOCA table status payload into web table dicts."""

    reader = _PayloadReader(payload)
    status = reader.u8("status")
    if status == STATUS_ERROR:
        error_code, message = decode_error_payload(payload)
        return [{"error": error_code, "message": message}]
    if status != STATUS_OK:
        raise ValueError(f"invalid table status: 0x{status:02X}")

    tables: list[dict[str, Any]] = []
    for _ in range(reader.u16("table_count")):
        table_number = reader.u16("table_number")
        table_status = _decode_table_status(reader.u8("table_status"))
        tables.append({"id": table_number, "status": table_status})

    reader.done()
    return tables


def encode_table_assignment_request_payload(order_id: int, receive_type: ReceiveType, table_number: int | None) -> bytes:
    if not 1 <= order_id <= MAX_U32:
        raise ValueError(f"invalid order_id={order_id}")
    receive_type_value = _encode_receive_type(receive_type)
    normalized_table_number = table_number or 0
    if receive_type == "dine_in" and normalized_table_number <= 0:
        raise ValueError("table_number must be greater than 0 for dine_in")
    if not 0 <= normalized_table_number <= MAX_U16:
        raise ValueError(f"invalid table_number={normalized_table_number}")
    return struct.pack(">IBH", order_id, receive_type_value, normalized_table_number)


def decode_table_assignment_response_payload(payload: bytes) -> tuple[bool, int | None, str | None]:
    if payload == bytes([STATUS_OK]):
        return True, None, None
    error_code, message = decode_error_payload(payload)
    return False, error_code, message


def _decode_table_status(value: int) -> TableStatus:
    if value == TABLE_STATUS_EMPTY:
        return "empty"
    if value == TABLE_STATUS_OCCUPIED:
        return "occupied"
    raise ValueError(f"invalid table_status={value}")


def _encode_receive_type(value: ReceiveType) -> int:
    if value == "take_out":
        return RECEIVE_TAKE_OUT
    if value == "dine_in":
        return RECEIVE_DINE_IN
    raise ValueError(f"invalid receive_type={value}")


class _PayloadReader:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    def read(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if end > len(self.payload):
            raise ValueError(f"incomplete {field}: need {size} bytes")
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def u8(self, field: str) -> int:
        return self.read(1, field)[0]

    def u16(self, field: str) -> int:
        return struct.unpack(">H", self.read(2, field))[0]

    def done(self) -> None:
        if self.offset != len(self.payload):
            raise ValueError(f"unexpected trailing payload bytes: {len(self.payload) - self.offset}")
