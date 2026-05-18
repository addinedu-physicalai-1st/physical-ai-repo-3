import json
import struct
from dataclasses import dataclass
from typing import Any

MAGIC = b"MB"
VERSION = 0x01
TYPE_CATALOG_REQUEST = 0x01
TYPE_CATALOG_RESPONSE = 0x02
TYPE_ERROR_RESPONSE = 0x7F
HEADER_SIZE = 12
MAX_PAYLOAD_SIZE = 1024 * 1024


@dataclass(frozen=True)
class BusinessMessage:
    message_type: int
    request_id: int
    payload: dict[str, Any]


def encode_message(message_type: int, request_id: int, payload: dict[str, Any]) -> bytes:
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = MAGIC + bytes([VERSION, message_type & 0xFF]) + struct.pack(
        ">II",
        request_id & 0xFFFFFFFF,
        len(payload_bytes),
    )
    return header + payload_bytes


def decode_header(header: bytes) -> tuple[int, int, int]:
    if len(header) != HEADER_SIZE:
        raise ValueError(f"invalid business header length: {len(header)}")
    if header[:2] != MAGIC:
        raise ValueError("invalid business magic")
    version = header[2]
    if version != VERSION:
        raise ValueError(f"unsupported business version: {version}")
    message_type = header[3]
    request_id, payload_size = struct.unpack(">II", header[4:])
    if payload_size > MAX_PAYLOAD_SIZE:
        raise ValueError(f"business payload too large: {payload_size}")
    return message_type, request_id, payload_size


def decode_payload(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("business payload must be a JSON object")
    return value
