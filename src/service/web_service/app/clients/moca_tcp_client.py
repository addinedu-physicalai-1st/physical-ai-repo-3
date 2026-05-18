import socket
import struct
import threading
from dataclasses import dataclass
from typing import Any

from app.protocol.moca_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    MocaHeader,
    decode_catalog_payload,
    decode_header,
    decode_order_response_payload,
    encode_frame,
)


MAX_U8 = 0xFF
MAX_U16 = 0xFFFF
RECEIVE_PICKUP = 0
RECEIVE_SERVING = 1


@dataclass(frozen=True)
class MocaOrderItem:
    """One order line in the MOCA binary order payload."""

    product_id: int
    quantity: int


class MocaCatalogClientError(RuntimeError):
    pass


class MocaOrderClientError(RuntimeError):
    pass


class MocaOrderRejected(MocaOrderClientError):
    pass


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


class MocaTcpCatalogClient(MocaTcpBaseClient):
    """Fetches product catalog data from moca_service over raw TCP."""

    def fetch_catalog(self) -> dict[str, Any]:
        try:
            _, payload = self.request(CMD_CATALOG, METHOD_GET, b"")
            return self._decode_catalog_response(payload)
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service catalog request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _decode_catalog_response(self, payload: bytes) -> dict[str, Any]:
        catalog = decode_catalog_payload(payload)
        if "error" in catalog:
            message = catalog.get("message", catalog.get("error", "catalog error"))
            raise MocaCatalogClientError(str(message))
        return catalog


class MocaTcpOrderClient(MocaTcpBaseClient):
    """Creates orders in moca_service using the MOCA raw TCP order payload."""

    def create_order(self, receive_type: int, table_id: int, items: list[MocaOrderItem]) -> None:
        payload = self.encode_order_request(receive_type, table_id, items)
        try:
            _, response_payload = self.request(CMD_ORDER, METHOD_SET, payload)
            self._raise_if_order_rejected(response_payload)
        except MocaOrderRejected:
            raise
        except MocaOrderClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaOrderClientError(
                f"moca_service order request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def encode_order_request(self, receive_type: int, table_id: int, items: list[MocaOrderItem]) -> bytes:
        """Encode order request payload.

        Payload layout:
        [receive_type u8][table_id u8][item_count u8]
        repeated [product_id u16 big-endian][quantity u8].
        """

        self._validate_order_header(receive_type, table_id, len(items))

        payload = bytearray([receive_type, table_id, len(items)])
        for item in items:
            self._validate_order_item(item)
            payload.extend(struct.pack(">HB", item.product_id, item.quantity))
        return bytes(payload)

    def _raise_if_order_rejected(self, payload: bytes) -> None:
        ok, message = decode_order_response_payload(payload)
        if not ok:
            raise MocaOrderRejected(message or "order rejected")

    def _validate_order_header(self, receive_type: int, table_id: int, item_count: int) -> None:
        if receive_type not in {RECEIVE_PICKUP, RECEIVE_SERVING}:
            raise ValueError(f"invalid receive_type={receive_type}")
        if not 0 <= table_id <= MAX_U8:
            raise ValueError(f"invalid table_id={table_id}")
        if not 1 <= item_count <= MAX_U8:
            raise ValueError(f"invalid item_count={item_count}")

    def _validate_order_item(self, item: MocaOrderItem) -> None:
        if not 1 <= item.product_id <= MAX_U16:
            raise ValueError(f"invalid product_id={item.product_id}")
        if not 1 <= item.quantity <= MAX_U8:
            raise ValueError(f"invalid quantity={item.quantity}")
