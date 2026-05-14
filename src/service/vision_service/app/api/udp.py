import json
import logging
import socketserver
from collections.abc import Callable
from typing import Any

MessageHandler = Callable[[dict[str, Any]], dict[str, Any]]
ErrorHandler = Callable[[str], dict[str, Any]]


class ThreadingUdpServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_request_handler(
    handle_message: MessageHandler,
    error_response: ErrorHandler,
    logger: logging.Logger,
) -> type[socketserver.DatagramRequestHandler]:
    class UdpRequestHandler(socketserver.DatagramRequestHandler):
        def handle(self) -> None:
            data = self.rfile.read()
            try:
                request = json.loads(data.decode("utf-8"))
                response = handle_message(request)
            except json.JSONDecodeError as exc:
                response = error_response(f"invalid json: {exc.msg}")

            logger.info("udp message from %s: %s", self.client_address, data.decode("utf-8", errors="replace"))
            self.wfile.write(json.dumps(response).encode("utf-8"))

    return UdpRequestHandler


def create_server(
    host: str,
    port: int,
    handle_message: MessageHandler,
    error_response: ErrorHandler,
    logger: logging.Logger,
) -> ThreadingUdpServer:
    return ThreadingUdpServer((host, port), create_request_handler(handle_message, error_response, logger))
