import struct
from dataclasses import dataclass
from typing import Any

CMD_CATALOG = 0x20
CMD_ORDER = 0x21

METHOD_GET = 0x01
METHOD_SET = 0x02

HEADER_SIZE = 7
MAX_PAYLOAD_SIZE = 1024 * 1024

STATUS_OK = 0x00
STATUS_ERROR = 0x01

ERROR_CATALOG_UNAVAILABLE = 0x01
ERROR_ORDER_REJECTED = 0x02

MENU_NAME_SIZE = 256
MENU_IMAGE_SIZE = 1020
ALLERGY_NAME_SIZE = 256
ALLERGY_ICON_SIZE = 64
SURCHARGE_KEY_SIZE = 256
ERROR_MESSAGE_MAX_SIZE = 512

FLAG_HOT = 1 << 0
FLAG_SHOT = 1 << 1
FLAG_ICE = 1 << 2
FLAG_MILK = 1 << 3

MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Header codec
# ---------------------------------------------------------------------------
# Every MOCA TCP frame starts with this fixed 7-byte header:
# [cmd_type u8][method u8][sequence u8][payload_size u32 big-endian].
@dataclass(frozen=True)
class MocaHeader:
    cmd_type: int
    method: int
    sequence: int
    payload_size: int


def encode_header(cmd_type: int, method: int, sequence: int, payload_size: int) -> bytes:
    """Validate header fields and encode the fixed-size MOCA frame header."""

    if cmd_type not in {CMD_CATALOG, CMD_ORDER}:
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


# ---------------------------------------------------------------------------
# Common response payload codec
# ---------------------------------------------------------------------------
# Responses start with status=0x00 for success or status=0x01 for failure.
# Failure payloads carry a small error code plus a length-prefixed UTF-8 message.
def encode_error_payload(error_code: int, message: str) -> bytes:
    """Encode a common error payload without JSON."""

    message_bytes = _truncate_utf8(message, ERROR_MESSAGE_MAX_SIZE)
    return bytes([STATUS_ERROR, error_code & 0xFF]) + struct.pack(">H", len(message_bytes)) + message_bytes


def decode_error_payload(payload: bytes) -> tuple[int, str]:
    """Decode a common error payload into error_code and message."""

    if len(payload) < 4:
        raise ValueError(f"invalid error payload length: {len(payload)}")
    status, error_code = payload[:2]
    if status != STATUS_ERROR:
        raise ValueError(f"invalid error status: 0x{status:02X}")
    message_size = struct.unpack(">H", payload[2:4])[0]
    if len(payload) != 4 + message_size:
        raise ValueError(f"invalid error payload length: {len(payload)}")
    return error_code, payload[4:].decode("utf-8")


def encode_order_success_payload() -> bytes:
    """Encode a successful order response payload."""

    return bytes([STATUS_OK])


def decode_order_response_payload(payload: bytes) -> tuple[bool, str | None]:
    """Decode an order response into success flag and optional rejection message."""

    if payload == bytes([STATUS_OK]):
        return True, None
    _, message = decode_error_payload(payload)
    return False, message


# ---------------------------------------------------------------------------
# Catalog payload codec
# ---------------------------------------------------------------------------
# Catalog responses preserve the existing HTTP-facing dict shape, but encode it
# as count-prefixed records and fixed-width UTF-8 strings on the TCP wire.
def encode_catalog_payload(catalog: dict[str, Any]) -> bytes:
    """Encode catalog dict data into the MOCA raw binary catalog payload."""

    frame = bytearray([STATUS_OK])
    menu = _as_list(catalog.get("menu", []), "menu")
    allergy = _as_list(catalog.get("allergy", []), "allergy")
    surcharges = catalog.get("surcharges", {})
    if not isinstance(surcharges, dict):
        raise ValueError("surcharges must be a dict")

    _append_count(frame, len(menu), "menu_count")
    for item in menu:
        if not isinstance(item, dict):
            raise ValueError("menu item must be a dict")
        product_id = _bounded_int(item.get("id"), "product_id", MAX_U16)
        price = _bounded_int(item.get("price"), "price", MAX_U32)
        flags = 0
        if bool(item.get("hot", False)):
            flags |= FLAG_HOT
        if bool(item.get("shot", False)):
            flags |= FLAG_SHOT
        if bool(item.get("ice", False)):
            flags |= FLAG_ICE
        if bool(item.get("milk", False)):
            flags |= FLAG_MILK
        frame.extend(struct.pack(">HIB", product_id, price, flags))
        frame.extend(_encode_fixed_string(str(item.get("name", "")), MENU_NAME_SIZE, "menu.name"))
        frame.extend(_encode_fixed_string(str(item.get("emoji", "")), MENU_IMAGE_SIZE, "menu.emoji"))

    _append_count(frame, len(allergy), "allergy_count")
    for category in allergy:
        if not isinstance(category, dict):
            raise ValueError("allergy item must be a dict")
        items = _as_list(category.get("items", []), "allergy.items")
        frame.extend(_encode_fixed_string(str(category.get("name", "")), ALLERGY_NAME_SIZE, "allergy.name"))
        frame.extend(_encode_fixed_string(str(category.get("icon", "")), ALLERGY_ICON_SIZE, "allergy.icon"))
        _append_count(frame, len(items), "allergy.item_count")
        for item_name in items:
            frame.extend(_encode_fixed_string(str(item_name), MENU_NAME_SIZE, "allergy.item"))

    _append_count(frame, len(surcharges), "surcharge_count")
    for key, value in surcharges.items():
        frame.extend(_encode_fixed_string(str(key), SURCHARGE_KEY_SIZE, "surcharge.key"))
        frame.extend(struct.pack(">I", _bounded_int(value, "surcharge.price", MAX_U32)))

    return bytes(frame)


def decode_catalog_payload(payload: bytes) -> dict[str, Any]:
    """Decode a MOCA raw binary catalog payload back into catalog dict data."""

    reader = _PayloadReader(payload)
    status = reader.u8("status")
    if status == STATUS_ERROR:
        error_code, message = decode_error_payload(payload)
        return {"error": error_code, "message": message}
    if status != STATUS_OK:
        raise ValueError(f"invalid catalog status: 0x{status:02X}")

    menu = []
    for _ in range(reader.u16("menu_count")):
        product_id = reader.u16("product_id")
        price = reader.u32("price")
        flags = reader.u8("flags")
        menu.append(
            {
                "id": product_id,
                "name": reader.fixed_string(MENU_NAME_SIZE, "menu.name"),
                "emoji": reader.fixed_string(MENU_IMAGE_SIZE, "menu.emoji"),
                "price": price,
                "hot": bool(flags & FLAG_HOT),
                "shot": bool(flags & FLAG_SHOT),
                "ice": bool(flags & FLAG_ICE),
                "milk": bool(flags & FLAG_MILK),
            }
        )

    allergy = []
    for _ in range(reader.u16("allergy_count")):
        name = reader.fixed_string(ALLERGY_NAME_SIZE, "allergy.name")
        icon = reader.fixed_string(ALLERGY_ICON_SIZE, "allergy.icon")
        item_count = reader.u16("allergy.item_count")
        items = [reader.fixed_string(MENU_NAME_SIZE, "allergy.item") for _ in range(item_count)]
        allergy.append({"name": name, "icon": icon, "items": items})

    surcharges = {}
    for _ in range(reader.u16("surcharge_count")):
        key = reader.fixed_string(SURCHARGE_KEY_SIZE, "surcharge.key")
        surcharges[key] = reader.u32("surcharge.price")

    reader.done()
    return {"menu": menu, "allergy": allergy, "surcharges": surcharges}


# ---------------------------------------------------------------------------
# Internal binary parsing helpers
# ---------------------------------------------------------------------------
class _PayloadReader:
    """Small cursor-based reader for sequential binary payload parsing."""

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

    def u32(self, field: str) -> int:
        return struct.unpack(">I", self.read(4, field))[0]

    def fixed_string(self, size: int, field: str) -> str:
        return _decode_fixed_string(self.read(size, field))

    def done(self) -> None:
        if self.offset != len(self.payload):
            raise ValueError(f"unexpected trailing payload bytes: {len(self.payload) - self.offset}")


def _as_list(value: Any, field: str) -> list[Any]:
    """Validate a value that must be encoded as a counted list."""

    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _append_count(frame: bytearray, value: int, field: str) -> None:
    """Append a u16 count field after validating its range."""

    frame.extend(struct.pack(">H", _bounded_int(value, field, MAX_U16)))


def _bounded_int(value: Any, field: str, max_value: int) -> int:
    """Validate that value is an integer in the unsigned field range."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int")
    if not 0 <= value <= max_value:
        raise ValueError(f"invalid {field}={value}")
    return value


def _encode_fixed_string(value: str, size: int, field: str) -> bytes:
    """Encode a UTF-8 string into a fixed-width NUL-padded field."""

    encoded = value.encode("utf-8")
    if len(encoded) > size:
        raise ValueError(f"{field} exceeds {size} bytes")
    return encoded + (b"\x00" * (size - len(encoded)))


def _decode_fixed_string(value: bytes) -> str:
    """Decode a fixed-width NUL-padded UTF-8 string field."""

    return value.split(b"\x00", 1)[0].decode("utf-8")


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
