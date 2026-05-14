import asyncio
import json
import logging
import os
from typing import Any

SERVICE_NAME = os.getenv("BUSINESS_SERVICE_NAME", "business_service")
HOST = os.getenv("BUSINESS_SERVICE_HOST", "0.0.0.0")
PORT = int(os.getenv("BUSINESS_SERVICE_PORT", "9001"))
BUSINESS_DB_HOST = os.getenv("BUSINESS_SERVICE_DB_HOST", "business_db")
BUSINESS_DB_PORT = int(os.getenv("BUSINESS_SERVICE_DB_PORT", "3306"))
CONTROL_SERVICE_HOST = os.getenv("BUSINESS_SERVICE_CONTROL_SERVICE_HOST", "control_service")
CONTROL_SERVICE_PORT = int(os.getenv("BUSINESS_SERVICE_CONTROL_SERVICE_PORT", "9002"))
WEB_SERVICE_HOST = os.getenv("BUSINESS_SERVICE_WEB_SERVICE_HOST", "web_service")
WEB_SERVICE_TCP_PORT = int(os.getenv("BUSINESS_SERVICE_WEB_SERVICE_TCP_PORT", "9004"))

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
                "role": "Coordinates business workflows and connects WebService, ControlService, and BusinessDB.",
                "dependencies": {
                    "business_db": {"host": BUSINESS_DB_HOST, "port": BUSINESS_DB_PORT},
                    "control_service": {"host": CONTROL_SERVICE_HOST, "port": CONTROL_SERVICE_PORT},
                    "web_service": {"host": WEB_SERVICE_HOST, "tcp_port": WEB_SERVICE_TCP_PORT},
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
