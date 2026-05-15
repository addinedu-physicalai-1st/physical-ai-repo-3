import logging
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.service import BusinessService

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
        service: "BusinessService",
        logger: logging.Logger,
    ):
        super().__init__((host, port), TcpRequestHandler)
        self.logger = logger

        # Business Logic
        self.on_health = service.run_health_test


class TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: TcpServer = self.server
        peer = self.client_address
        server.logger.info("TCP received from %s", peer)

        try:
            frame = self.request.recv(FRAME_SIZE)
        except OSError as exc:
            server.logger.warning("tcp read failed: %s", exc)
            return

        if not frame:
            server.logger.warning("tcp frame is empty: %s", frame.hex(" "))
            return
        if len(frame) != FRAME_SIZE:
            server.logger.warning("tcp frame size invalid: %s", frame.hex(" "))
            return

        try:
            cmd, seq = parse_frame(frame)
        except ValueError as exc:
            server.logger.warning("failed to parse tcp frame", exc)
            return

        # CMD에 따라 서비스 실행
        if cmd == HEALTH_CMD:
            server.logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
            server.on_health(seq)
        elif cmd == STATUS_CMD:
            server.logger.info("received STATUS probe from %s seq=%s", peer, seq)
