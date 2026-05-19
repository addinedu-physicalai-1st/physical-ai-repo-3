import struct
from dataclasses import dataclass
from typing import Any

from app.protocol.header_protocol import (
    STATUS_ERROR,
    STATUS_OK,
    decode_error_payload,
    encode_error_payload,
)

MENU_NAME_SIZE = 256
MENU_IMAGE_SIZE = 1020
ALLERGY_NAME_SIZE = 256
ALLERGY_ICON_SIZE = 64
SURCHARGE_KEY_SIZE = 256

FLAG_HOT = 1 << 0
FLAG_SHOT = 1 << 1
FLAG_ICE = 1 << 2
FLAG_MILK = 1 << 3

MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF


@dataclass(frozen=True)
class CatalogResponse:
    catalog: dict[str, Any] | None = None
    error_code: int | None = None
    message: str = ""

    @classmethod
    def ok(cls, catalog: dict[str, Any]) -> "CatalogResponse":
        return cls(catalog=catalog)

    @classmethod
    def error(cls, error_code: int, message: str) -> "CatalogResponse":
        return cls(error_code=error_code, message=message)

    @property
    def is_error(self) -> bool:
        return self.error_code is not None


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


def encode_catalog_response_payload(response: CatalogResponse) -> bytes:
    """Encode a catalog response payload."""

    if response.is_error:
        if response.error_code is None:
            raise ValueError("catalog response missing error code")
        return encode_error_payload(response.error_code, response.message)
    if response.catalog is None:
        raise ValueError("catalog response missing catalog data")
    return encode_catalog_payload(response.catalog)


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
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _append_count(frame: bytearray, value: int, field: str) -> None:
    frame.extend(struct.pack(">H", _bounded_int(value, field, MAX_U16)))


def _bounded_int(value: Any, field: str, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int")
    if not 0 <= value <= max_value:
        raise ValueError(f"invalid {field}={value}")
    return value


def _encode_fixed_string(value: str, size: int, field: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > size:
        raise ValueError(f"{field} exceeds {size} bytes")
    return encoded + (b"\x00" * (size - len(encoded)))


def _decode_fixed_string(value: bytes) -> str:
    return value.split(b"\x00", 1)[0].decode("utf-8")
