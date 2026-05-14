import asyncio
import json
import logging
import os
from typing import Any

SERVICE_NAME = os.getenv("CONTROL_SERVICE_NAME", "control_service")
HOST = os.getenv("CONTROL_SERVICE_HOST", "0.0.0.0")
PORT = int(os.getenv("CONTROL_SERVICE_PORT", "9002"))
BUSINESS_SERVICE_HOST = os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_HOST", "business_service")
BUSINESS_SERVICE_PORT = int(os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_PORT", "9001"))
VISION_SERVICE_HOST = os.getenv("CONTROL_SERVICE_VISION_SERVICE_HOST", "vision_service")
VISION_SERVICE_TCP_PORT = int(os.getenv("CONTROL_SERVICE_VISION_SERVICE_TCP_PORT", "9003"))
ROS_DOMAIN_ID = int(os.getenv("CONTROL_SERVICE_ROS_DOMAIN_ID", "0"))

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
                "role": "Coordinates robot control workflows and connects BusinessService, VisionService, and ROS controllers.",
                "dependencies": {
                    "business_service": {"host": BUSINESS_SERVICE_HOST, "port": BUSINESS_SERVICE_PORT},
                    "vision_service": {"host": VISION_SERVICE_HOST, "tcp_port": VISION_SERVICE_TCP_PORT},
                    "ros": {"domain_id": ROS_DOMAIN_ID},
                },
            },
        )

    return error_response(f"unsupported message type: {message_type}")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    logger.info("client connected: %s", peer)

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
        logger.info("client disconnected: %s", peer)


async def main() -> None:
    server = await asyncio.start_server(handle_client, HOST, PORT)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info("%s listening on %s", SERVICE_NAME, sockets)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
