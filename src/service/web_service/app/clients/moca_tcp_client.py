import socket
import threading
from typing import Any

from app.protocol.header_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    CMD_TABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    MocaHeader,
    decode_header,
    encode_frame,
)
from app.protocol.catalog_protocol import decode_catalog_payload
from app.protocol.order_protocol import (
    MocaOrderItem,
    decode_order_response_payload,
    encode_order_request_payload,
)
from app.protocol.table_protocol import (
    ReceiveType,
    decode_table_assignment_response_payload,
    decode_table_payload,
    encode_table_assignment_request_payload,
)


class MocaCatalogClientError(RuntimeError):
    pass


class MocaOrderClientError(RuntimeError):
    pass


class MocaOrderRejected(MocaOrderClientError):
    pass


class MocaTableClientError(RuntimeError):
    pass


class MocaTableAssignmentNotFound(MocaTableClientError):
    pass


class MocaTableAssignmentRejected(MocaTableClientError):
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

    def create_order(self, items: list[MocaOrderItem]) -> int:
        payload = self.encode_order_request(items)
        try:
            _, response_payload = self.request(CMD_ORDER, METHOD_SET, payload)
            return self._decode_order_response(response_payload)
        except MocaOrderRejected:
            raise
        except MocaOrderClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaOrderClientError(
                f"moca_service order request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def encode_order_request(self, items: list[MocaOrderItem]) -> bytes:
        return encode_order_request_payload(items)

    def _decode_order_response(self, payload: bytes) -> int:
        ok, order_id, message = decode_order_response_payload(payload)
        if not ok:
            raise MocaOrderRejected(message or "order rejected")
        if order_id is None:
            raise MocaOrderClientError("order response missing order_id")
        return order_id


class MocaTcpTableClient(MocaTcpBaseClient):
    """Fetches table assignment state from moca_service over raw TCP."""

    def fetch_tables(self) -> list[dict]:
        try:
            _, payload = self.request(CMD_TABLE, METHOD_GET, b"")
            return self._decode_table_response(payload)
        except MocaTableClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaTableClientError(
                f"moca_service table request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _decode_table_response(self, payload: bytes) -> list[dict]:
        tables = decode_table_payload(payload)
        if tables and "error" in tables[0]:
            message = tables[0].get("message", tables[0].get("error", "table error"))
            raise MocaTableClientError(str(message))
        return tables

    def assign_table(self, order_id: int, receive_type: ReceiveType, table_id: int | None) -> None:
        payload = encode_table_assignment_request_payload(order_id, receive_type, table_id)
        try:
            _, response_payload = self.request(CMD_TABLE, METHOD_SET, payload)
            self._raise_if_assignment_failed(response_payload)
        except (MocaTableAssignmentNotFound, MocaTableAssignmentRejected):
            raise
        except MocaTableClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaTableClientError(
                f"moca_service table assignment request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _raise_if_assignment_failed(self, payload: bytes) -> None:
        ok, error_code, message = decode_table_assignment_response_payload(payload)
        if ok:
            return
        if error_code == ERROR_ORDER_NOT_FOUND:
            raise MocaTableAssignmentNotFound(message or "order not found")
        if error_code == ERROR_TABLE_ASSIGNMENT_REJECTED:
            raise MocaTableAssignmentRejected(message or "table assignment rejected")
        raise MocaTableClientError(message or "table assignment failed")
