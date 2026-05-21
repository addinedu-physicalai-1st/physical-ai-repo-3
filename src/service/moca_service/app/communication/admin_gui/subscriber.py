import logging
import socketserver
import threading
from collections.abc import Callable
from typing import Any

from app.communication.admin_gui.protocol import AdminGuiFrame, FRAME_SIZE, decode_frame

FrameHandler = Callable[[AdminGuiFrame, tuple[str, int]], None]


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        frame_handler: FrameHandler,
        logger: logging.Logger,
        name: str,
    ) -> None:
        super().__init__(server_address, _TcpRequestHandler)
        self.frame_handler = frame_handler
        self.logger = logger
        self.name = name


class AdminGuiSubscriber:
    def __init__(
        self,
        host: str,
        port: int,
        frame_handler: FrameHandler,
        logger: logging.Logger,
        *,
        name: str = "moca-admin-gui-subscriber",
    ) -> None:
        self.host = host
        self.port = port
        self.frame_handler = frame_handler
        self.logger = logger
        self.name = name
        self._server: _ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = _ThreadingTcpServer((self.host, self.port), self.frame_handler, self.logger, self.name)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name=self.name)
        self._thread.start()
        self.logger.info("%s listening on %s", self.name, self._server.server_address)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def __enter__(self) -> "AdminGuiSubscriber":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


class _TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: _ThreadingTcpServer = self.server
        peer = self.client_address
        server.logger.info("%s client connected: %s", server.name, peer)
        try:
            while True:
                raw = self._read_exact(FRAME_SIZE)
                if raw is None:
                    return
                try:
                    frame = decode_frame(raw)
                except ValueError as exc:
                    server.logger.warning("invalid admin_gui frame from %s: %s", peer, exc)
                    continue
                server.frame_handler(frame, peer)
        finally:
            server.logger.info("%s client disconnected: %s", server.name, peer)

    def _read_exact(self, size: int) -> bytes | None:
        server: _ThreadingTcpServer = self.server
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self.request.recv(size - len(chunks))
            except OSError as exc:
                server.logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    server.logger.warning("partial admin_gui frame from %s: %s", self.client_address, bytes(chunks).hex(" "))
                return None
            chunks.extend(chunk)
        return bytes(chunks)
