import logging
import socket
import threading
from typing import Any

from app.protocol.catalog_protocol import decode_catalog_payload
from app.protocol.header_protocol import (
    CMD_ALLERGY,
    CMD_MENU,
    CMD_ORDER,
    CMD_TABLE,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    STATUS_ERROR,
    STATUS_OK,
    MocaHeader,
    decode_error_payload,
    decode_header,
    encode_frame,
)
from app.protocol.order_protocol import decode_order_response_payload
from app.protocol.table_protocol import decode_table_payload


class TcpBaseClient:
    """Small TCP client base for one-way request clients."""

    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._logger = logging.getLogger("web_service")

    def send(self, payload: bytes) -> None:
        with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
            sock.settimeout(self.timeout_sec)
            sock.sendall(payload)


class MocaTcpBaseClient:
    """Persistent TCP client for MOCA request/response frames.

    The wire format is:
    [7-byte MOCA header][command-specific raw binary payload].
    This base class owns connection reuse, sequence numbers, exact reads,
    and response header validation. Subclasses only encode/decode payloads.
    """

    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()
        self._sequence = 0
        self._sock: socket.socket | None = None
        self._logger = logging.getLogger("web_service")

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def request(self, cmd_type: int, method: int, payload: bytes) -> tuple[MocaHeader, bytes]:
        """Send one MOCA frame and return the validated response payload."""

        with self._lock:
            sequence = self._next_sequence_unlocked()
            sock = self._connect_unlocked()
            sock.sendall(encode_frame(cmd_type, method, sequence, payload))

            header = decode_header(self._read_exact_unlocked(HEADER_SIZE))
            if header.cmd_type != cmd_type:
                raise ValueError(f"moca response cmd_type mismatch: {header.cmd_type} != {cmd_type}")
            if header.method != method:
                raise ValueError(f"moca response method mismatch: {header.method} != {method}")
            if header.sequence != sequence:
                raise ValueError(f"moca response sequence mismatch: {header.sequence} != {sequence}")

            response_payload = self._read_exact_unlocked(header.payload_size)
            self._logger.info(
                "parsed MOCA response payload from moca_service: %s",
                _parse_received_response_payload(header, response_payload),
            )
            return header, response_payload

    def _next_sequence_unlocked(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    def _connect_unlocked(self) -> socket.socket:
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout_sec)
            self._sock.settimeout(self.timeout_sec)
        return self._sock

    def _close_unlocked(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None

    def _read_exact_unlocked(self, size: int) -> bytes:
        """Read exactly size bytes so TCP packet boundaries do not leak upward."""

        chunks = bytearray()
        while len(chunks) < size:
            sock = self._connect_unlocked()
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                self._close_unlocked()
                raise OSError(f"incomplete tcp read: {len(chunks)} of {size} bytes")
            chunks.extend(chunk)
        return bytes(chunks)


def _parse_received_response_payload(header: MocaHeader, payload: bytes) -> dict[str, Any]:
    try:
        if header.cmd_type in {CMD_MENU, CMD_ALLERGY}:
            return decode_catalog_payload(payload, header.cmd_type)
        if header.cmd_type == CMD_ORDER:
            return _parse_order_response_payload(payload)
        if header.cmd_type == CMD_TABLE and header.method == METHOD_GET:
            return {"tables": decode_table_payload(payload)}
        if header.cmd_type == CMD_TABLE and header.method == METHOD_SET:
            return _parse_table_assignment_response_payload(payload)
        raise ValueError(f"unsupported response payload cmd=0x{header.cmd_type:02X}")
    except Exception as exc:
        return {"parse_error": str(exc), "raw_payload_hex": payload.hex(" ")}


def _parse_order_response_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) == 5 and payload[0] == STATUS_OK:
        ok, order_id, _ = decode_order_response_payload(payload)
        if ok:
            return {"status": "ok", "order_id": order_id}
    if payload[:1] == bytes([STATUS_ERROR]):
        error_code, message = decode_error_payload(payload)
        return {"status": "error", "error_code": error_code, "message": message}
    raise ValueError(f"invalid order response payload length: {len(payload)}")


def _parse_table_assignment_response_payload(payload: bytes) -> dict[str, Any]:
    if payload == bytes([STATUS_OK]):
        return {"status": "ok"}
    error_code, message = decode_error_payload(payload)
    return {"status": "error", "error_code": error_code, "message": message}
