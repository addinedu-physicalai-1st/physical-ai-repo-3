"""Binary TCP communication-test frame helpers."""
import logging
import socket
import socketserver
import threading

from config import AdminGuiConfig, load_config

STX = 0x02
HEALTH_CMD = 0x01
STATUS_CMD = 0x10
ETX = 0x03
FRAME_SIZE = 4

logger = logging.getLogger('admin_gui.tcp_api')


class TcpApiError(RuntimeError):
    """Raised when a TCP API request cannot complete successfully."""


def _resolve_host_addresses(host: str) -> set[str]:
    try:
        return {
            result[4][0]
            for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError:
        return set()


class TcpPeerNameResolver:
    def __init__(self, config: AdminGuiConfig):
        self.peer_names = self._build_peer_names(config)

    def format_peer(self, peer: tuple[str, int]) -> str:
        host, port = peer
        name = self.peer_names.get(host)
        if name:
            return f'{name}:{port}'
        return f'{host}:{port}'

    def _build_peer_names(self, config: AdminGuiConfig) -> dict[str, str]:
        candidates = [
            ('business_service', config.business_service_host),
            ('control_service', config.control_service_host),
        ]

        names_by_address: dict[str, list[str]] = {}
        for name, host in candidates:
            addresses = _resolve_host_addresses(host)
            if not addresses:
                addresses = {host}
            for address in addresses:
                names_by_address.setdefault(address, []).append(name)

        return {
            address: names[0]
            for address, names in names_by_address.items()
            if len(names) == 1
        }


def build_frame(cmd: int, seq: int) -> bytes:
    return bytes([STX, cmd & 0xFF, seq & 0xFF, ETX])


def build_health_frame(seq: int) -> bytes:
    return build_frame(HEALTH_CMD, seq)


def build_status_frame(seq: int) -> bytes:
    return build_frame(STATUS_CMD, seq)


def parse_frame(frame: bytes, expected_cmd: int | None = None) -> tuple[int, int]:
    if len(frame) != FRAME_SIZE:
        raise TcpApiError(f'invalid frame length: {len(frame)}')
    stx, cmd, seq, etx = frame
    if stx != STX:
        raise TcpApiError(f'invalid STX: 0x{stx:02X}')
    if cmd not in {HEALTH_CMD, STATUS_CMD}:
        raise TcpApiError(f'unsupported CMD: 0x{cmd:02X}')
    if expected_cmd is not None and cmd != expected_cmd:
        raise TcpApiError(f'unexpected CMD: 0x{cmd:02X}')
    if etx != ETX:
        raise TcpApiError(f'invalid ETX: 0x{etx:02X}')
    return cmd, seq


class TcpStatusClient:
    def __init__(self, config: AdminGuiConfig | None = None):
        self.config = config or load_config()

    def send_status_to_business(self, seq: int) -> None:
        self.send_status(
            self.config.business_service_host,
            self.config.business_service_port,
            seq,
            'business_service',
        )

    def send_status_to_control(self, seq: int) -> None:
        self.send_status(
            self.config.control_service_host,
            self.config.control_service_port,
            seq,
            'control_service',
        )

    def send_status(self, host: str, port: int, seq: int, target_name: str) -> None:
        frame = build_status_frame(seq)
        try:
            with socket.create_connection(
                (host, port),
                timeout=self.config.tcp_timeout_sec,
            ) as sock:
                sock.settimeout(self.config.tcp_timeout_sec)
                sock.sendall(frame)
        except OSError as exc:
            raise TcpApiError(f'tcp status test failed: {target_name}:{port}: {exc}') from exc

        logger.info('sent STATUS to %s seq=%s', target_name, seq)


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _HealthRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: _ThreadingTcpServer = self.server
        config: AdminGuiConfig = server.config
        peer = server.peer_name_resolver.format_peer(self.client_address)

        while True:
            frame = self._read_exact()
            if not frame:
                return

            try:
                cmd, seq = parse_frame(frame)
            except TcpApiError as exc:
                logger.warning('invalid tcp test frame from %s: %s', peer, exc)
                continue

            if cmd == HEALTH_CMD:
                logger.info('received HEALTH trigger from %s seq=%s', peer, seq)
                client = TcpStatusClient(config)
                self._send_status(client.send_status_to_business, 'business_service', seq)
                self._send_status(client.send_status_to_control, 'control_service', seq)
            elif cmd == STATUS_CMD:
                logger.info('received STATUS probe from %s seq=%s', peer, seq)

    def _read_exact(self) -> bytes | None:
        chunks = bytearray()
        while len(chunks) < FRAME_SIZE:
            chunk = self.request.recv(FRAME_SIZE - len(chunks))
            if not chunk:
                if chunks:
                    logger.warning(
                        'partial tcp test frame from %s: %s',
                        self._format_peer(),
                        bytes(chunks).hex(' '),
                    )
                return None
            chunks.extend(chunk)
        return bytes(chunks)

    def _format_peer(self) -> str:
        server: _ThreadingTcpServer = self.server
        return server.peer_name_resolver.format_peer(self.client_address)

    def _send_status(self, send_fn, target_name: str, seq: int) -> None:
        try:
            send_fn(seq)
        except TcpApiError as exc:
            logger.warning('failed to send STATUS to %s seq=%s: %s', target_name, seq, exc)


class AdminGuiTcpHealthServer:
    def __init__(self, config: AdminGuiConfig | None = None):
        self.config = config or load_config()
        self._server: _ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        self._server = _ThreadingTcpServer((self.config.host, self.config.port), _HealthRequestHandler)
        self._server.config = self.config
        self._server.peer_name_resolver = TcpPeerNameResolver(self.config)
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
