import socket
import threading
from typing import Any, Protocol

from app.protocol.business_tcp import (
    HEADER_SIZE,
    TYPE_CATALOG_REQUEST,
    TYPE_CATALOG_RESPONSE,
    TYPE_ERROR_RESPONSE,
    decode_header,
    decode_payload,
    encode_message,
)


class CatalogClient(Protocol):
    def fetch_catalog(self) -> dict[str, Any]:
        ...


class MocaCatalogClientError(RuntimeError):
    pass


class MocaCatalogClient:
    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()
        self._request_id = 0

    def fetch_catalog(self) -> dict[str, Any]:
        request_id = self._next_request_id()
        request = encode_message(
            TYPE_CATALOG_REQUEST,
            request_id,
            {"resource": "catalog"},
        )

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                sock.settimeout(self.timeout_sec)
                sock.sendall(request)
                header = self._read_exact(sock, HEADER_SIZE)
                message_type, response_id, payload_size = decode_header(header)
                if response_id != request_id:
                    raise MocaCatalogClientError(
                        f"moca_service response request_id mismatch: {response_id} != {request_id}"
                    )
                payload = decode_payload(self._read_exact(sock, payload_size))
        except (OSError, ValueError) as exc:
            raise MocaCatalogClientError(
                f"moca_service catalog request failed: {self.host}:{self.port}: {exc}"
            ) from exc

        if message_type == TYPE_ERROR_RESPONSE:
            raise MocaCatalogClientError(str(payload.get("message", payload.get("error", "catalog error"))))
        if message_type != TYPE_CATALOG_RESPONSE:
            raise MocaCatalogClientError(f"unexpected catalog response type: {message_type}")
        return payload

    def _next_request_id(self) -> int:
        with self._lock:
            self._request_id = (self._request_id + 1) & 0xFFFFFFFF
            return self._request_id

    def _read_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise MocaCatalogClientError(f"incomplete tcp read: {len(chunks)} of {size} bytes")
            chunks.extend(chunk)
        return bytes(chunks)
