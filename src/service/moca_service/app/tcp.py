import logging
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
        logger: logging.Logger,
        name: str,
    ):
        super().__init__((host, port), TcpRequestHandler)
        self.logger = logger
        self.name = name
        self.on_health = on_health
        self.on_status = on_status


class TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: TcpServer = self.server
        peer = self.client_address
        server.logger.info("%s TCP client connected: %s", server.name, peer)

        try:
            while True:
                frame = self._read_exact()
                if frame is None:
                    return

                try:
                    cmd, seq = parse_frame(frame)
                except ValueError as exc:
                    server.logger.warning("invalid tcp frame from %s: %s", peer, exc)
                    continue

                if cmd == HEALTH_CMD:
                    server.logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
                    server.on_health(seq)
                elif cmd == STATUS_CMD:
                    server.logger.info("received STATUS frame from %s seq=%s", peer, seq)
                    server.on_status(seq, peer)
        finally:
            server.logger.info("%s TCP client disconnected: %s", server.name, peer)

    def _read_exact(self) -> bytes | None:
        server: TcpServer = self.server
        chunks = bytearray()
        while len(chunks) < FRAME_SIZE:
            try:
                chunk = self.request.recv(FRAME_SIZE - len(chunks))
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
