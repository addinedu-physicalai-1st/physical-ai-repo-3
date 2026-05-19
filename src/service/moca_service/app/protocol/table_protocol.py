import struct
from dataclasses import dataclass
from typing import Literal

from app.domain.table_assignment_runtime import StoreTable
from app.protocol.header_protocol import STATUS_OK, decode_error_payload, encode_error_payload

MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF
TABLE_STATUS_EMPTY = 0
TABLE_STATUS_OCCUPIED = 1
RECEIVE_TAKE_OUT = 0
RECEIVE_DINE_IN = 1

ReceiveType = Literal["take_out", "dine_in"]


@dataclass(frozen=True)
class TableResponse:
    tables: list[StoreTable] | None = None
    error_code: int | None = None
    message: str = ""

    @classmethod
    def ok(cls, tables: list[StoreTable]) -> "TableResponse":
        return cls(tables=tables)

    @classmethod
    def error(cls, error_code: int, message: str) -> "TableResponse":
        return cls(error_code=error_code, message=message)

    @property
    def is_error(self) -> bool:
        return self.error_code is not None


@dataclass(frozen=True)
class TableAssignmentRequest:
    order_id: int
    receive_type: ReceiveType
    table_number: int


@dataclass(frozen=True)
class TableAssignmentResponse:
    error_code: int | None = None
    message: str = ""

    @classmethod
    def ok(cls) -> "TableAssignmentResponse":
        return cls()

    @classmethod
    def error(cls, error_code: int, message: str) -> "TableAssignmentResponse":
        return cls(error_code=error_code, message=message)

    @property
    def is_error(self) -> bool:
        return self.error_code is not None


def encode_table_payload(tables: list[StoreTable]) -> bytes:
    """Encode all table runtime states into a MOCA table payload."""

    frame = bytearray([STATUS_OK])
    frame.extend(struct.pack(">H", _bounded_int(len(tables), "table_count", MAX_U16)))
    for table in tables:
        frame.extend(struct.pack(">H", _bounded_int(table.table_number, "table_number", MAX_U16)))
        frame.append(_encode_table_status(table.status))
    return bytes(frame)


def parse_table_assignment_payload(payload: bytes) -> TableAssignmentRequest:
    if len(payload) != 7:
        raise ValueError(f"invalid table assignment payload length: {len(payload)}")
    order_id, receive_type_value, table_number = struct.unpack(">IBH", payload)
    if not 1 <= order_id <= MAX_U32:
        raise ValueError(f"invalid order_id={order_id}")
    receive_type = _decode_receive_type(receive_type_value)
    if receive_type == "dine_in" and table_number <= 0:
        raise ValueError("table_number must be greater than 0 for dine_in")
    return TableAssignmentRequest(order_id=order_id, receive_type=receive_type, table_number=table_number)


def encode_table_assignment_success_payload() -> bytes:
    return bytes([STATUS_OK])


def encode_table_assignment_response_payload(response: TableAssignmentResponse) -> bytes:
    if response.is_error:
        if response.error_code is None:
            raise ValueError("table assignment response missing error code")
        return encode_error_payload(response.error_code, response.message)
    return encode_table_assignment_success_payload()


def decode_table_assignment_response_payload(payload: bytes) -> tuple[bool, int | None, str | None]:
    if payload == bytes([STATUS_OK]):
        return True, None, None
    error_code, message = decode_error_payload(payload)
    return False, error_code, message


def encode_table_response_payload(response: TableResponse) -> bytes:
    """Encode a table response payload."""

    if response.is_error:
        if response.error_code is None:
            raise ValueError("table response missing error code")
        return encode_error_payload(response.error_code, response.message)
    if response.tables is None:
        raise ValueError("table response missing table data")
    return encode_table_payload(response.tables)


def _encode_table_status(status: str) -> int:
    if status == "empty":
        return TABLE_STATUS_EMPTY
    if status == "occupied":
        return TABLE_STATUS_OCCUPIED
    raise ValueError(f"invalid table status={status}")


def _decode_receive_type(value: int) -> ReceiveType:
    if value == RECEIVE_TAKE_OUT:
        return "take_out"
    if value == RECEIVE_DINE_IN:
        return "dine_in"
    raise ValueError(f"invalid receive_type={value}")


def _bounded_int(value: int, field: str, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int")
    if not 0 <= value <= max_value:
        raise ValueError(f"invalid {field}={value}")
    return value
