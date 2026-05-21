import json
import struct
from dataclasses import dataclass
from typing import Any
from typing import Literal

from app.protocol.header_protocol import (
    STATUS_ERROR,
    STATUS_OK,
    decode_error_payload,
    encode_error_payload,
)

MENU_NAME_SIZE = 256
MENU_IMAGE_SIZE = 1020
OPTION_GROUP_SIZE = 256
OPTION_NAME_SIZE = 256
ALLERGY_NAME_SIZE = 256
ALLERGY_ICON_SIZE = 64

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


ProductAction = Literal["create", "get", "list", "update", "delete"]


@dataclass(frozen=True)
class ProductManagementRequest:
    action: ProductAction
    product_id: int = 0
    product: dict[str, Any] | None = None
    include_paused: bool = False


@dataclass(frozen=True)
class ProductManagementResponse:
    result: dict[str, Any] | None = None
    error_code: int | None = None
    message: str = ""

    @classmethod
    def ok(cls, result: dict[str, Any]) -> "ProductManagementResponse":
        return cls(result=result)

    @classmethod
    def error(cls, error_code: int, message: str) -> "ProductManagementResponse":
        return cls(error_code=error_code, message=message)

    @property
    def is_error(self) -> bool:
        return self.error_code is not None


def encode_catalog_response_payload(response: CatalogResponse, cmd_type: int) -> bytes:
    from app.protocol.header_protocol import CMD_ALLERGY, CMD_MENU

    if response.is_error:
        if response.error_code is None:
            raise ValueError("catalog response missing error code")
        return encode_error_payload(response.error_code, response.message)
    if response.catalog is None:
        raise ValueError("catalog response missing catalog data")
    if cmd_type == CMD_MENU:
        return encode_menu_option_payload(response.catalog)
    if cmd_type == CMD_ALLERGY:
        return encode_allergy_payload(response.catalog)
    raise ValueError(f"unsupported catalog cmd_type: 0x{cmd_type:02X}")


def encode_menu_option_payload(catalog: dict[str, Any]) -> bytes:
    frame = bytearray([STATUS_OK])
    menu = _as_list(catalog.get("menu", []), "menu")

    _append_count(frame, len(menu), "menu_count")
    for item in menu:
        if not isinstance(item, dict):
            raise ValueError("menu item must be a dict")
        frame.extend(struct.pack(">HI", _bounded_int(item.get("id"), "product_id", MAX_U16), _bounded_int(item.get("price"), "price", MAX_U32)))
        frame.extend(_encode_fixed_string(str(item.get("name", "")), MENU_NAME_SIZE, "menu.name"))
        frame.extend(_encode_fixed_string(str(item.get("image", item.get("emoji", ""))), MENU_IMAGE_SIZE, "menu.image"))

        options = _as_list(item.get("options", []), "menu.options")
        _append_count(frame, len(options), "option_count")
        for option in options:
            if not isinstance(option, dict):
                raise ValueError("menu option must be a dict")
            frame.extend(_encode_fixed_string(str(option.get("option_group", "")), OPTION_GROUP_SIZE, "option.option_group"))
            frame.extend(_encode_fixed_string(str(option.get("option_name", "")), OPTION_NAME_SIZE, "option.option_name"))
            frame.extend(struct.pack(">I", _bounded_int(option.get("price", 0), "option.price", MAX_U32)))
            frame.append(0x01 if bool(option.get("is_default", False)) else 0x00)

    return bytes(frame)


def encode_allergy_payload(catalog: dict[str, Any]) -> bytes:
    frame = bytearray([STATUS_OK])
    allergy = _as_list(catalog.get("allergy", []), "allergy")

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

    return bytes(frame)


def decode_catalog_payload(payload: bytes, cmd_type: int) -> dict[str, Any]:
    from app.protocol.header_protocol import CMD_ALLERGY, CMD_MENU

    if payload[:1] == bytes([STATUS_ERROR]):
        error_code, message = decode_error_payload(payload)
        return {"error": error_code, "message": message}
    if cmd_type == CMD_MENU:
        return {"menu": decode_menu_option_payload(payload)}
    if cmd_type == CMD_ALLERGY:
        return {"allergy": decode_allergy_payload(payload)}
    raise ValueError(f"unsupported catalog cmd_type: 0x{cmd_type:02X}")


def parse_product_management_payload(payload: bytes) -> ProductManagementRequest:
    if not payload:
        raise ValueError("product management payload must not be empty")
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid product management JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError("product management payload must be a JSON object")

    action = str(body.get("action", ""))
    if action not in {"create", "get", "list", "update", "delete"}:
        raise ValueError(f"invalid product action={action}")

    product_id = 0
    if action in {"get", "update", "delete"}:
        raw_product_id = body.get("product_id")
        if isinstance(raw_product_id, bool) or not isinstance(raw_product_id, int) or raw_product_id <= 0:
            raise ValueError("product_id must be a positive int")
        product_id = raw_product_id

    product = body.get("product")
    if action in {"create", "update"}:
        if not isinstance(product, dict):
            raise ValueError("product must be an object")
    elif product is not None:
        raise ValueError("product is only supported for create/update")

    return ProductManagementRequest(
        action=action,
        product_id=product_id,
        product=product,
        include_paused=bool(body.get("include_paused", False)),
    )


def encode_product_management_response_payload(response: ProductManagementResponse) -> bytes:
    if response.is_error:
        if response.error_code is None:
            raise ValueError("product management response missing error code")
        return encode_error_payload(response.error_code, response.message)
    if response.result is None:
        raise ValueError("product management response missing result")
    return bytes([STATUS_OK]) + json.dumps(response.result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_product_management_response_payload(payload: bytes) -> dict[str, Any]:
    if payload[:1] == bytes([STATUS_ERROR]):
        error_code, message = decode_error_payload(payload)
        return {"error": error_code, "message": message}
    if payload[:1] != bytes([STATUS_OK]):
        raise ValueError(f"invalid product management status: 0x{payload[:1].hex()}")
    if len(payload) == 1:
        return {}
    decoded = json.loads(payload[1:].decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("product management response must be a JSON object")
    return decoded


def decode_menu_option_payload(payload: bytes) -> list[dict[str, Any]]:
    reader = _PayloadReader(payload)
    _read_ok_status(reader)
    menu = []
    for _ in range(reader.u16("menu_count")):
        product_id = reader.u16("product_id")
        price = reader.u32("price")
        name = reader.fixed_string(MENU_NAME_SIZE, "menu.name")
        image = reader.fixed_string(MENU_IMAGE_SIZE, "menu.image")
        options = []
        for _ in range(reader.u16("option_count")):
            options.append(
                {
                    "option_group": reader.fixed_string(OPTION_GROUP_SIZE, "option.option_group"),
                    "option_name": reader.fixed_string(OPTION_NAME_SIZE, "option.option_name"),
                    "price": reader.u32("option.price"),
                    "is_default": reader.u8("option.is_default") == 0x01,
                }
            )
        menu.append({"id": product_id, "name": name, "image": image, "price": price, "options": options})
    reader.done()
    return menu


def decode_allergy_payload(payload: bytes) -> list[dict[str, Any]]:
    reader = _PayloadReader(payload)
    _read_ok_status(reader)
    allergy = []
    for _ in range(reader.u16("allergy_count")):
        name = reader.fixed_string(ALLERGY_NAME_SIZE, "allergy.name")
        icon = reader.fixed_string(ALLERGY_ICON_SIZE, "allergy.icon")
        items = [reader.fixed_string(MENU_NAME_SIZE, "allergy.item") for _ in range(reader.u16("allergy.item_count"))]
        allergy.append({"name": name, "icon": icon, "items": items})
    reader.done()
    return allergy


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

    def u32(self, field: str) -> int:
        return struct.unpack(">I", self.read(4, field))[0]

    def fixed_string(self, size: int, field: str) -> str:
        return _decode_fixed_string(self.read(size, field))

    def done(self) -> None:
        if self.offset != len(self.payload):
            raise ValueError(f"unexpected trailing payload bytes: {len(self.payload) - self.offset}")


def _read_ok_status(reader: _PayloadReader) -> None:
    status = reader.u8("status")
    if status != STATUS_OK:
        raise ValueError(f"invalid catalog status: 0x{status:02X}")


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
