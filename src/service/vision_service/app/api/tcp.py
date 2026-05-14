import json
import logging
import socketserver
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


def create_server(
    host: str,
    port: int,
    handle_message: MessageHandler,
    error_response: ErrorHandler,
    logger: logging.Logger,
) -> ThreadingTcpServer:
    return ThreadingTcpServer((host, port), create_request_handler(handle_message, error_response, logger))
