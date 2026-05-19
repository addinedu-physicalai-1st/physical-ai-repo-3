import struct
from typing import Any, Literal

from app.protocol.header_protocol import STATUS_ERROR, STATUS_OK, decode_error_payload

MAX_U16 = 0xFFFF
TABLE_STATUS_EMPTY = 0
TABLE_STATUS_OCCUPIED = 1

TableStatus = Literal["empty", "occupied"]


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


def _decode_table_status(value: int) -> TableStatus:
    if value == TABLE_STATUS_EMPTY:
        return "empty"
    if value == TABLE_STATUS_OCCUPIED:
        return "occupied"
    raise ValueError(f"invalid table_status={value}")


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
