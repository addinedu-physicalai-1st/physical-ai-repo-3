import asyncio
import json
import logging
import os
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


async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    logger.info("tcp client connected: %s", peer)

    try:
        while line := await reader.readline():
            try:
                request = json.loads(line.decode("utf-8"))
                response = handle_message(request)
            except json.JSONDecodeError as exc:
                response = error_response(f"invalid json: {exc.msg}")

            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
        logger.info("tcp client disconnected: %s", peer)


class VisionDatagramProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport
        logger.info("%s udp listening on %s:%s", SERVICE_NAME, UDP_HOST, UDP_PORT)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            request = json.loads(data.decode("utf-8"))
            response = handle_message(request)
        except json.JSONDecodeError as exc:
            response = error_response(f"invalid json: {exc.msg}")

        logger.info("udp message from %s: %s", addr, data.decode("utf-8", errors="replace"))
        self.transport.sendto(json.dumps(response).encode("utf-8"), addr)


async def main() -> None:
    tcp_server = await asyncio.start_server(handle_tcp_client, TCP_HOST, TCP_PORT)
    loop = asyncio.get_running_loop()
    udp_transport, _ = await loop.create_datagram_endpoint(
        VisionDatagramProtocol,
        local_addr=(UDP_HOST, UDP_PORT),
    )

    sockets = ", ".join(str(sock.getsockname()) for sock in tcp_server.sockets or [])
    logger.info("%s tcp listening on %s", SERVICE_NAME, sockets)

    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        udp_transport.close()


if __name__ == "__main__":
    asyncio.run(main())
