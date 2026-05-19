import struct
from dataclasses import dataclass

from app.domain.table_assignment_runtime import StoreTable
from app.protocol.header_protocol import STATUS_OK, encode_error_payload

MAX_U16 = 0xFFFF
TABLE_STATUS_EMPTY = 0
TABLE_STATUS_OCCUPIED = 1


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


def encode_table_payload(tables: list[StoreTable]) -> bytes:
    """Encode all table runtime states into a MOCA table payload."""

    frame = bytearray([STATUS_OK])
    frame.extend(struct.pack(">H", _bounded_int(len(tables), "table_count", MAX_U16)))
    for table in tables:
        frame.extend(struct.pack(">H", _bounded_int(table.table_number, "table_number", MAX_U16)))
        frame.append(_encode_table_status(table.status))
    return bytes(frame)


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


def _bounded_int(value: int, field: str, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int")
    if not 0 <= value <= max_value:
        raise ValueError(f"invalid {field}={value}")
    return value
