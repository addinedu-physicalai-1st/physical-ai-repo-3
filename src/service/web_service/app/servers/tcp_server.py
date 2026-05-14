import json
import logging
import socketserver
import threading
from collections.abc import Callable
from typing import Any

MessageHandler = Callable[[dict[str, Any]], dict[str, Any]]
ErrorHandler = Callable[[str], dict[str, Any]]


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_request_handler(
    handle_message: MessageHandler,
    error_response: ErrorHandler,
    logger: logging.Logger,
) -> type[socketserver.StreamRequestHandler]:
    class TcpRequestHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            peer = self.client_address
            logger.info("tcp client connected: %s", peer)

            try:
                for raw_line in self.rfile:
                    line = raw_line.decode("utf-8")
                    try:
                        request = json.loads(line)
                        response = handle_message(request)
                    except json.JSONDecodeError as exc:
                        response = error_response(f"invalid json: {exc.msg}")

                    self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                    self.wfile.flush()
            finally:
                logger.info("tcp client disconnected: %s", peer)

    return TcpRequestHandler


class TcpServerThread:
    def __init__(
        self,
        host: str,
        port: int,
        handle_message: MessageHandler,
        error_response: ErrorHandler,
        logger: logging.Logger,
    ) -> None:
        self.host = host
        self.port = port
        self.handle_message = handle_message
        self.error_response = error_response
        self.logger = logger
        self._server: ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = ThreadingTcpServer(
            (self.host, self.port),
            create_request_handler(self.handle_message, self.error_response, self.logger),
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
