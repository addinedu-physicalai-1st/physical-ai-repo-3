import logging
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from app.protocol.moca_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    HEADER_SIZE as MOCA_HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    decode_header as decode_moca_header,
    encode_catalog_payload,
    encode_error_payload,
    encode_frame as encode_moca_frame,
    encode_order_success_payload,
    ERROR_CATALOG_UNAVAILABLE,
    ERROR_ORDER_REJECTED,
)
from app.protocol.order_protocol import (
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

                if first[0] in {CMD_CATALOG, CMD_ORDER}:
                    self._handle_moca_frame(first)
                    continue

                server.logger.warning("invalid tcp prefix from %s: %s", peer, first.hex(" "))
        finally:
            server.logger.info("%s TCP client disconnected: %s", server.name, peer)

    def _handle_moca_frame(self, first: bytes) -> None:
        server: TcpServer = self.server
        header_tail = self._read_exact(MOCA_HEADER_SIZE - 1)
        if header_tail is None:
            return

        try:
            header = decode_moca_header(first + header_tail)
        except ValueError as exc:
            server.logger.warning("invalid moca tcp header from %s: %s", self.client_address, exc)
            return

        if not (
            (header.cmd_type == CMD_CATALOG and header.method == METHOD_GET)
            or (header.cmd_type == CMD_ORDER and header.method == METHOD_SET)
        ):
            server.logger.warning(
                "unsupported moca tcp method for cmd from %s: cmd=0x%02X method=0x%02X",
                self.client_address,
                header.cmd_type,
                header.method,
            )
            return

        payload_bytes = self._read_exact(header.payload_size)
        if payload_bytes is None:
            return

        if header.cmd_type == CMD_CATALOG:
            self._handle_catalog_frame(header.sequence)
            return
        if header.cmd_type == CMD_ORDER:
            self._handle_order_frame(header.sequence, payload_bytes)
            return

        server.logger.warning("unsupported moca tcp cmd from %s: 0x%02X", self.client_address, header.cmd_type)

    def _handle_catalog_frame(self, sequence: int) -> None:
        server: TcpServer = self.server
        try:
            response = server.on_catalog()
            payload = encode_catalog_payload(response)
            self.request.sendall(encode_moca_frame(CMD_CATALOG, METHOD_GET, sequence, payload))
        except Exception as exc:
            server.logger.warning("catalog tcp request failed from %s: %s", self.client_address, exc)
            payload = encode_error_payload(ERROR_CATALOG_UNAVAILABLE, str(exc))
            self.request.sendall(
                encode_moca_frame(CMD_CATALOG, METHOD_GET, sequence, payload)
            )

    def _handle_order_frame(self, sequence: int, payload: bytes) -> None:
        server: TcpServer = self.server

        try:
            if len(payload) < ORDER_HEADER_SIZE:
                raise ValueError(f"invalid order payload length: {len(payload)}")
            order_header = payload[:ORDER_HEADER_SIZE]
            _, _, item_count = parse_order_header(order_header)
            expected_size = ORDER_HEADER_SIZE + item_count * ORDER_ITEM_SIZE
            if len(payload) != expected_size:
                raise ValueError(f"invalid order payload length: {len(payload)}")
            request = parse_order_request(order_header, payload[ORDER_HEADER_SIZE:])
            server.on_order(request)
            self.request.sendall(
                encode_moca_frame(CMD_ORDER, METHOD_SET, sequence, encode_order_success_payload())
            )
        except Exception as exc:
            server.logger.warning("order tcp request failed from %s: %s", self.client_address, exc)
            payload = encode_error_payload(ERROR_ORDER_REJECTED, str(exc))
            self.request.sendall(encode_moca_frame(CMD_ORDER, METHOD_SET, sequence, payload))

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
