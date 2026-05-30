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

TOPIC_MONITOR = 0x10
TOPIC_PRODUCTS = 0x11
TOPIC_ORDERS = 0x12
TOPIC_TABLES = 0x13
TOPIC_DOBY_CONTROLLER = 0x14
TOPIC_MAPS = 0x15

EVENT_START = 0x01
EVENT_STOP = 0x02
EVENT_SNAPSHOT = 0x03
EVENT_SET_MODE = 0x04
EVENT_EMERGENCY_STOP = 0x05
EVENT_APPLY_MAP = 0x06

FLAG_CHUNK_FIRST = 0x01
FLAG_CHUNK_LAST = 0x02

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


def chunk_payload(
    *,
    kind: int,
    topic: int,
    event: int,
    payload: bytes,
    sequence_start: int,
    correlation_id: int,
) -> list[AdminGuiFrame]:
    if not payload:
        return [
            AdminGuiFrame(
                kind=kind,
                topic=topic,
                event=event,
                flags=FLAG_CHUNK_FIRST | FLAG_CHUNK_LAST,
                sequence=sequence_start & 0xFFFF,
                correlation_id=correlation_id,
                payload=b"",
            )
        ]

    frames = []
    chunks = [payload[offset : offset + PAYLOAD_SIZE] for offset in range(0, len(payload), PAYLOAD_SIZE)]
    for index, chunk in enumerate(chunks):
        flags = 0
        if index == 0:
            flags |= FLAG_CHUNK_FIRST
        if index == len(chunks) - 1:
            flags |= FLAG_CHUNK_LAST
        frames.append(
            AdminGuiFrame(
                kind=kind,
                topic=topic,
                event=event,
                flags=flags,
                sequence=(sequence_start + index) & 0xFFFF,
                correlation_id=correlation_id,
                payload=chunk,
            )
        )
    return frames


class ChunkAssembler:
    def __init__(self) -> None:
        self._chunks: dict[tuple[int, int, int], bytearray] = {}

    def add(self, frame: AdminGuiFrame) -> bytes | None:
        key = (frame.topic, frame.event, frame.correlation_id)
        if frame.flags & FLAG_CHUNK_FIRST:
            self._chunks[key] = bytearray()

        chunk = self._chunks.get(key)
        if chunk is None:
            if frame.flags & FLAG_CHUNK_LAST:
                return frame.payload
            self._chunks[key] = bytearray(frame.payload)
            return None

        chunk.extend(frame.payload)
        if frame.flags & FLAG_CHUNK_LAST:
            return bytes(self._chunks.pop(key))
        return None


def _validate_u8(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{field} must be uint8")


def _validate_u16(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError(f"{field} must be uint16")
