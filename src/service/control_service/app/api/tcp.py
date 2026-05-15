import logging
import socket
import socketserver
from collections.abc import Callable
from dataclasses import dataclass

from app.interface import StatusNotifier
from app.protocol.tcp_frame import (
    FRAME_SIZE,
    HEALTH_CMD,
    STATUS_CMD,
    build_status_frame,
    parse_frame,
)

HealthHandler = Callable[[int], None]
StatusHandler = Callable[[int, tuple[str, int]], None]


@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int
    name: str


class TcpStatusNotifier(StatusNotifier):
    """TCP adapter that sends STATUS frames to another service."""

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


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_health_request_handler(
    on_health: HealthHandler,
    on_status: StatusHandler,
    logger: logging.Logger,
) -> type[socketserver.BaseRequestHandler]:
    class RequestHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            peer = self.client_address
            logger.info("client connected: %s", peer)

            try:
                while True:
                    frame = self._read_exact()
                    if frame is None:
                        return

                    try:
                        cmd, seq = parse_frame(frame)
                    except ValueError as exc:
                        logger.warning("invalid tcp test frame from %s: %s", peer, exc)
                        continue

                    if cmd == HEALTH_CMD:
                        logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
                        on_health(seq)
                    elif cmd == STATUS_CMD:
                        logger.info("received STATUS frame from %s seq=%s", peer, seq)
                        on_status(seq, peer)
            finally:
                logger.info("client disconnected: %s", peer)

        def _read_exact(self) -> bytes | None:
            chunks = bytearray()
            while len(chunks) < FRAME_SIZE:
                try:
                    chunk = self.request.recv(FRAME_SIZE - len(chunks))
                except OSError as exc:
                    logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                    return None
                if not chunk:
                    if chunks:
                        logger.warning(
                            "partial tcp test frame from %s: %s",
                            self.client_address,
                            bytes(chunks).hex(" "),
                        )
                    return None
                chunks.extend(chunk)
            return bytes(chunks)

    return RequestHandler


def create_health_server(
    host: str,
    port: int,
    on_health: HealthHandler,
    on_status: StatusHandler,
    logger: logging.Logger,
) -> ThreadingTcpServer:
    return ThreadingTcpServer(
        (host, port),
        create_health_request_handler(on_health, on_status, logger),
    )
