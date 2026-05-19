import struct
from dataclasses import dataclass

CMD_CATALOG = 0x20
CMD_ORDER = 0x21
CMD_TABLE = 0x22

METHOD_GET = 0x01
METHOD_SET = 0x02

HEADER_SIZE = 7
MAX_PAYLOAD_SIZE = 1024 * 1024

STATUS_OK = 0x00
STATUS_ERROR = 0x01

ERROR_CATALOG_UNAVAILABLE = 0x01
ERROR_ORDER_REJECTED = 0x02
ERROR_TABLE_UNAVAILABLE = 0x03
ERROR_MESSAGE_MAX_SIZE = 512


@dataclass(frozen=True)
class MocaHeader:
    cmd_type: int
    method: int
    sequence: int
    payload_size: int


def encode_header(cmd_type: int, method: int, sequence: int, payload_size: int) -> bytes:
    """Validate header fields and encode the fixed-size MOCA frame header."""

    if cmd_type not in {CMD_CATALOG, CMD_ORDER, CMD_TABLE}:
        raise ValueError(f"unsupported cmd_type: 0x{cmd_type:02X}")
    if method not in {METHOD_GET, METHOD_SET}:
        raise ValueError(f"unsupported method: 0x{method:02X}")
    if not 0 <= sequence <= 0xFF:
        raise ValueError(f"invalid sequence={sequence}")
    if not 0 <= payload_size <= MAX_PAYLOAD_SIZE:
        raise ValueError(f"invalid payload_size={payload_size}")
    return bytes([cmd_type, method, sequence]) + struct.pack(">I", payload_size)


def decode_header(header: bytes) -> MocaHeader:
    """Decode and validate a 7-byte MOCA frame header."""

    if len(header) != HEADER_SIZE:
        raise ValueError(f"invalid moca header length: {len(header)}")
    cmd_type, method, sequence = header[:3]
    payload_size = struct.unpack(">I", header[3:])[0]
    encode_header(cmd_type, method, sequence, payload_size)
    return MocaHeader(cmd_type, method, sequence, payload_size)


def encode_frame(cmd_type: int, method: int, sequence: int, payload: bytes = b"") -> bytes:
    """Build a complete MOCA frame from a header and raw payload bytes."""

    return encode_header(cmd_type, method, sequence, len(payload)) + payload


def encode_error_payload(error_code: int, message: str) -> bytes:
    """Encode a common MOCA error payload."""

    message_bytes = _truncate_utf8(message, ERROR_MESSAGE_MAX_SIZE)
    return bytes([STATUS_ERROR, error_code & 0xFF]) + struct.pack(">H", len(message_bytes)) + message_bytes


def decode_error_payload(payload: bytes) -> tuple[int, str]:
    """Decode a common MOCA error payload into error_code and message."""

    if len(payload) < 4:
        raise ValueError(f"invalid error payload length: {len(payload)}")
    status, error_code = payload[:2]
    if status != STATUS_ERROR:
        raise ValueError(f"invalid error status: 0x{status:02X}")
    message_size = struct.unpack(">H", payload[2:4])[0]
    if len(payload) != 4 + message_size:
        raise ValueError(f"invalid error payload length: {len(payload)}")
    return error_code, payload[4:].decode("utf-8")


def _truncate_utf8(value: str, max_size: int) -> bytes:
    """Trim UTF-8 bytes to max_size without splitting a multibyte character."""

    encoded = value.encode("utf-8")
    if len(encoded) <= max_size:
        return encoded
    end = max_size
    while end > 0:
        try:
            encoded[:end].decode("utf-8")
            return encoded[:end]
        except UnicodeDecodeError:
            end -= 1
    return b""
