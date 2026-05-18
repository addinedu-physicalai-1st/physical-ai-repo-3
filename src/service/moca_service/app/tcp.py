import logging
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from app.business_tcp import (
    HEADER_SIZE,
    MAGIC,
    TYPE_CATALOG_REQUEST,
    TYPE_CATALOG_RESPONSE,
    TYPE_ERROR_RESPONSE,
    decode_header,
    decode_payload,
    encode_message,
)
from app.order_protocol import (
    ACK,
    NAK,
    ORDER_HEADER_SIZE,
    ORDER_ITEM_SIZE,
    OrderRequest,
    parse_order_header,
    parse_order_request,
)

# TCP contract
# Frame: [STX=0x02][CMD][SEQ][ETX=0x03]
# Commands:
#   HEALTH 0x01: inbound trigger that starts the fan-out health test
#   STATUS 0x10: outbound status notification sent to downstream services
STX = 0x02
HEALTH_CMD = 0x01
STATUS_CMD = 0x10
ETX = 0x03
FRAME_SIZE = 4

HealthHandler = Callable[[int], None]
StatusHandler = Callable[[int, tuple[str, int]], None]
CatalogHandler = Callable[[], dict[str, Any]]
OrderHandler = Callable[[OrderRequest], None]


class StatusNotifier(Protocol):
    def notify_status(self, seq: int) -> bool:
        """Send a STATUS notification for the received health-check sequence."""
        ...


@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int
    name: str


def build_frame(cmd: int, seq: int) -> bytes:
    return bytes([STX, cmd & 0xFF, seq & 0xFF, ETX])


def build_status_frame(seq: int) -> bytes:
    return build_frame(STATUS_CMD, seq)


def parse_frame(frame: bytes) -> tuple[int, int]:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"invalid frame length: {len(frame)}")
    stx, cmd, seq, etx = frame
    if stx != STX:
        raise ValueError(f"invalid STX: 0x{stx:02X}")
    if cmd not in {HEALTH_CMD, STATUS_CMD}:
        raise ValueError(f"unsupported CMD: 0x{cmd:02X}")
    if etx != ETX:
        raise ValueError(f"invalid ETX: 0x{etx:02X}")
    return cmd, seq


class TcpStatusNotifier(StatusNotifier):
    def __init__(
        self,
        endpoint: TcpEndpoint,
        logger: logging.Logger,
        timeout: float = 3.0,
    ):
        self.endpoint = endpoint
        self.logger = logger
        self.timeout = timeout

    def notify_status(self, seq: int) -> bool:
        try:
            with socket.create_connection(
                (self.endpoint.host, self.endpoint.port),
                timeout=self.timeout,
            ) as sock:
                sock.sendall(build_status_frame(seq))
        except OSError as exc:
            self.logger.warning(
                "failed to send STATUS to %s at %s:%s: %s",
                self.endpoint.name,
                self.endpoint.host,
                self.endpoint.port,
                exc,
            )
            return False

        self.logger.info("sent STATUS to %s seq=%s", self.endpoint.name, seq)
        return True


class TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host: str,
        port: int,
        on_health: HealthHandler,
        on_status: StatusHandler,
        on_catalog: CatalogHandler,
        on_order: OrderHandler,
        logger: logging.Logger,
        name: str,
    ):
        super().__init__((host, port), TcpRequestHandler)
        self.logger = logger
        self.name = name
        self.on_health = on_health
        self.on_status = on_status
        self.on_catalog = on_catalog
        self.on_order = on_order


class TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: TcpServer = self.server
        peer = self.client_address
        server.logger.info("%s TCP client connected: %s", server.name, peer)

        try:
            while True:
                first = self._read_exact(1)
                if first is None:
                    return

                if first == bytes([STX]):
                    frame_tail = self._read_exact(FRAME_SIZE - 1)
                    if frame_tail is None:
                        return
                    try:
                        cmd, seq = parse_frame(first + frame_tail)
                    except ValueError as exc:
                        server.logger.warning("invalid tcp frame from %s: %s", peer, exc)
                        continue

                    if cmd == HEALTH_CMD:
                        server.logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
                        server.on_health(seq)
                    elif cmd == STATUS_CMD:
                        server.logger.info("received STATUS frame from %s seq=%s", peer, seq)
                        server.on_status(seq, peer)
                    continue

                if first == MAGIC[:1]:
                    self._handle_business_frame(first)
                    continue

                if first in {bytes([0]), bytes([1])}:
                    self._handle_order_frame(first)
                    continue

                server.logger.warning("invalid tcp prefix from %s: %s", peer, first.hex(" "))
        finally:
            server.logger.info("%s TCP client disconnected: %s", server.name, peer)

    def _handle_business_frame(self, first: bytes) -> None:
        server: TcpServer = self.server
        header_tail = self._read_exact(HEADER_SIZE - 1)
        if header_tail is None:
            return

        try:
            message_type, request_id, payload_size = decode_header(first + header_tail)
        except ValueError as exc:
            server.logger.warning("invalid business tcp header from %s: %s", self.client_address, exc)
            return

        payload_bytes = self._read_exact(payload_size)
        if payload_bytes is None:
            return

        try:
            payload = decode_payload(payload_bytes)
            if message_type != TYPE_CATALOG_REQUEST or payload.get("resource") != "catalog":
                raise ValueError(f"unsupported business request type={message_type}")
            response = server.on_catalog()
            self.request.sendall(encode_message(TYPE_CATALOG_RESPONSE, request_id, response))
        except Exception as exc:
            server.logger.warning("business tcp request failed from %s: %s", self.client_address, exc)
            self.request.sendall(
                encode_message(
                    TYPE_ERROR_RESPONSE,
                    request_id,
                    {"error": "catalog_unavailable", "message": str(exc)},
                )
            )

    def _handle_order_frame(self, first: bytes) -> None:
        server: TcpServer = self.server
        header_tail = self._read_exact(ORDER_HEADER_SIZE - 1)
        if header_tail is None:
            return
        header = first + header_tail

        try:
            _, _, item_count = parse_order_header(header)
            item_bytes = self._read_exact(item_count * ORDER_ITEM_SIZE)
            if item_bytes is None:
                return
            request = parse_order_request(header, item_bytes)
            server.on_order(request)
            self.request.sendall(bytes([ACK]))
        except Exception as exc:
            server.logger.warning("order tcp request failed from %s: %s", self.client_address, exc)
            self.request.sendall(bytes([NAK]))

    def _read_exact(self, size: int) -> bytes | None:
        server: TcpServer = self.server
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self.request.recv(size - len(chunks))
            except OSError as exc:
                server.logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    server.logger.warning(
                        "partial tcp frame from %s: %s",
                        self.client_address,
                        bytes(chunks).hex(" "),
                    )
                return None
            chunks.extend(chunk)
        return bytes(chunks)
