import logging
import socketserver
import threading
from collections.abc import Callable

from app.protocol.tcp_frame import FRAME_SIZE, parse_frame

FrameHandler = Callable[[int, int, tuple[str, int]], None]


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_request_handler(
    handle_frame: FrameHandler,
    logger: logging.Logger,
) -> type[socketserver.BaseRequestHandler]:
    class TcpRequestHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            peer = self.client_address
            logger.debug("tcp client connected: %s", peer)

            try:
                while True:
                    frame = self._read_exact()
                    if frame is None:
                        return

                    try:
                        cmd, seq = parse_frame(frame)
                    except ValueError as exc:
                        logger.warning("invalid tcp frame from %s: %s", peer, exc)
                        continue

                    handle_frame(cmd, seq, peer)
            finally:
                logger.debug("tcp client disconnected: %s", peer)

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
                            "partial tcp frame from %s: %s",
                            self.client_address,
                            bytes(chunks).hex(" "),
                        )
                    return None
                chunks.extend(chunk)
            return bytes(chunks)

    return TcpRequestHandler


class TcpServerThread:
    def __init__(
        self,
        host: str,
        port: int,
        handle_frame: FrameHandler,
        logger: logging.Logger,
    ) -> None:
        self.host = host
        self.port = port
        self.handle_frame = handle_frame
        self.logger = logger
        self._server: ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = ThreadingTcpServer(
            (self.host, self.port),
            create_request_handler(self.handle_frame, self.logger),
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="web-service-tcp-server",
            daemon=True,
        )
        self._thread.start()
        self.logger.info("web_service tcp listening on %s", self._server.server_address)

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
