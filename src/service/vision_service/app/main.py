import json
import logging
import os
import socketserver
import threading
from typing import Any

SERVICE_NAME = os.getenv("VISION_SERVICE_NAME", "vision_service")
TCP_HOST = os.getenv("VISION_SERVICE_TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("VISION_SERVICE_TCP_PORT", "9003"))
UDP_HOST = os.getenv("VISION_SERVICE_UDP_HOST", "0.0.0.0")
UDP_PORT = int(os.getenv("VISION_SERVICE_UDP_PORT", "9103"))
CONTROL_SERVICE_HOST = os.getenv("VISION_SERVICE_CONTROL_SERVICE_HOST", "control_service")
CONTROL_SERVICE_PORT = int(os.getenv("VISION_SERVICE_CONTROL_SERVICE_PORT", "9002"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(SERVICE_NAME)


def success_response(message_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "type": message_type,
        "service": SERVICE_NAME,
        "data": data or {},
    }


def error_response(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "service": SERVICE_NAME,
        "error": message,
    }


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")

    if message_type == "health":
        return success_response("health", {"status": "ok"})

    if message_type == "status":
        return success_response(
            "status",
            {
                "role": "Receives hall vision events over UDP and coordinates with ControlService over TCP.",
                "dependencies": {
                    "control_service": {"host": CONTROL_SERVICE_HOST, "port": CONTROL_SERVICE_PORT},
                },
                "listeners": {
                    "tcp": {"host": TCP_HOST, "port": TCP_PORT},
                    "udp": {"host": UDP_HOST, "port": UDP_PORT},
                },
            },
        )

    return error_response(f"unsupported message type: {message_type}")


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ThreadingUdpServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


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


def serve(server: socketserver.BaseServer, label: str) -> None:
    logger.info("%s %s listening on %s", SERVICE_NAME, label, server.server_address)
    server.serve_forever()


def main() -> None:
    tcp_server = ThreadingTcpServer((TCP_HOST, TCP_PORT), TcpRequestHandler)
    udp_server = ThreadingUdpServer((UDP_HOST, UDP_PORT), UdpRequestHandler)
    tcp_thread = threading.Thread(
        target=serve,
        args=(tcp_server, "tcp"),
        name="vision-service-tcp-server",
        daemon=True,
    )
    udp_thread = threading.Thread(
        target=serve,
        args=(udp_server, "udp"),
        name="vision-service-udp-server",
        daemon=True,
    )

    try:
        tcp_thread.start()
        udp_thread.start()
        tcp_thread.join()
    finally:
        tcp_server.shutdown()
        udp_server.shutdown()
        tcp_server.server_close()
        udp_server.server_close()


if __name__ == "__main__":
    main()
