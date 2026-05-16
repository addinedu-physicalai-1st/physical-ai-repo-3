"""Binary TCP communication-test frame helpers."""
import logging
import socket
import socketserver
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from config import AdminGuiConfig, load_config

# TCP contract
# Frame: [STX=0x02][CMD][SEQ][ETX=0x03]
# Commands:
#   HEALTH 0x01: inbound trigger that starts the moca_service status test
#   STATUS 0x10: status notification sent to moca_service or received from peers
STX = 0x02
HEALTH_CMD = 0x01
STATUS_CMD = 0x10
ETX = 0x03
FRAME_SIZE = 4

HealthHandler = Callable[[int], None]
StatusHandler = Callable[[int, tuple[str, int]], None]

logger = logging.getLogger('admin_gui.tcp_api')


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
        raise ValueError(f'invalid frame length: {len(frame)}')
    stx, cmd, seq, etx = frame
    if stx != STX:
        raise ValueError(f'invalid STX: 0x{stx:02X}')
    if cmd not in {HEALTH_CMD, STATUS_CMD}:
        raise ValueError(f'unsupported CMD: 0x{cmd:02X}')
    if etx != ETX:
        raise ValueError(f'invalid ETX: 0x{etx:02X}')
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
                'failed to send STATUS to %s at %s:%s: %s',
                self.endpoint.name,
                self.endpoint.host,
                self.endpoint.port,
                exc,
            )
            return False

        self.logger.info('sent STATUS to %s seq=%s', self.endpoint.name, seq)
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
        server.logger.info('%s TCP client connected: %s', server.name, peer)

        try:
            while True:
                frame = self._read_exact()
                if frame is None:
                    return

                try:
                    cmd, seq = parse_frame(frame)
                except ValueError as exc:
                    server.logger.warning('invalid tcp frame from %s: %s', peer, exc)
                    continue

                if cmd == HEALTH_CMD:
                    server.logger.info('received HEALTH trigger from %s seq=%s', peer, seq)
                    server.on_health(seq)
                elif cmd == STATUS_CMD:
                    server.logger.info('received STATUS frame from %s seq=%s', peer, seq)
                    server.on_status(seq, peer)
        finally:
            server.logger.info('%s TCP client disconnected: %s', server.name, peer)

    def _read_exact(self) -> bytes | None:
        server: TcpServer = self.server
        chunks = bytearray()
        while len(chunks) < FRAME_SIZE:
            try:
                chunk = self.request.recv(FRAME_SIZE - len(chunks))
            except OSError as exc:
                server.logger.warning('tcp read failed from %s: %s', self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    server.logger.warning(
                        'partial tcp frame from %s: %s',
                        self.client_address,
                        bytes(chunks).hex(' '),
                    )
                return None
            chunks.extend(chunk)
        return bytes(chunks)


class AdminGuiTcpHealthServer:
    def __init__(self, config: AdminGuiConfig | None = None):
        self.config = config or load_config()
        self.status_notifier = TcpStatusNotifier(
            TcpEndpoint(
                host=self.config.moca_service_host,
                port=self.config.moca_service_port,
                name='MocaService',
            ),
            logger,
            self.config.tcp_timeout_sec,
        )
        self._server: TcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        self._server = TcpServer(
            self.config.host,
            self.config.port,
            self._run_health_test,
            self._handle_status,
            logger,
            'AdminGUI',
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name='admin-gui-tcp-health-server',
            daemon=True,
        )
        self._thread.start()
        logger.info('admin_gui tcp health server listening on %s:%s', self.config.host, self.config.port)

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def _run_health_test(self, seq: int) -> None:
        logger.info('running admin_gui health test seq=%s', seq)
        self.status_notifier.notify_status(seq)

    def _handle_status(self, seq: int, peer: tuple[str, int]) -> None:
        logger.info('received STATUS seq=%s from %s:%s', seq, peer[0], peer[1])
