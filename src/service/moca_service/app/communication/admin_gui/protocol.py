import struct
from dataclasses import dataclass

MAGIC = b"AG"
VERSION = 1
FRAME_SIZE = 64

KIND_PUBLISH = 0x01
KIND_REQUEST = 0x02
KIND_RESPONSE = 0x03
KIND_ERROR = 0x04

TOPIC_TEST = 0x01
EVENT_PING = 0x01
EVENT_NOTICE = 0x02

HEADER_FORMAT = ">2sBBBBBHHH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
PAYLOAD_SIZE = FRAME_SIZE - HEADER_SIZE


@dataclass(frozen=True)
class AdminGuiFrame:
    kind: int
    topic: int
    event: int
    flags: int = 0
    sequence: int = 0
    correlation_id: int = 0
    payload: bytes = b""


def encode_frame(frame: AdminGuiFrame) -> bytes:
    payload = bytes(frame.payload)
    if len(payload) > PAYLOAD_SIZE:
        raise ValueError(f"payload exceeds {PAYLOAD_SIZE} bytes")
    _validate_u8(frame.kind, "kind")
    _validate_u8(frame.topic, "topic")
    _validate_u8(frame.event, "event")
    _validate_u8(frame.flags, "flags")
    _validate_u16(frame.sequence, "sequence")
    _validate_u16(frame.correlation_id, "correlation_id")
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        VERSION,
        frame.kind,
        frame.topic,
        frame.event,
        frame.flags,
        frame.sequence,
        frame.correlation_id,
        len(payload),
    )
    return header + payload + (b"\x00" * (PAYLOAD_SIZE - len(payload)))


def decode_frame(raw: bytes) -> AdminGuiFrame:
    if len(raw) != FRAME_SIZE:
        raise ValueError(f"invalid frame length: {len(raw)}")
    magic, version, kind, topic, event, flags, sequence, correlation_id, payload_length = struct.unpack(
        HEADER_FORMAT,
        raw[:HEADER_SIZE],
    )
    if magic != MAGIC:
        raise ValueError(f"invalid magic: {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported version: {version}")
    if kind not in {KIND_PUBLISH, KIND_REQUEST, KIND_RESPONSE, KIND_ERROR}:
        raise ValueError(f"unsupported kind: 0x{kind:02X}")
    if payload_length > PAYLOAD_SIZE:
        raise ValueError(f"invalid payload_length={payload_length}")
    payload = raw[HEADER_SIZE : HEADER_SIZE + payload_length]
    return AdminGuiFrame(
        kind=kind,
        topic=topic,
        event=event,
        flags=flags,
        sequence=sequence,
        correlation_id=correlation_id,
        payload=payload,
    )


def _validate_u8(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{field} must be uint8")


def _validate_u16(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError(f"{field} must be uint16")
