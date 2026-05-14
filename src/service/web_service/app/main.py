import json
import logging
import os
import socketserver
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import menu as menu_router
from app.routers import orders as orders_router
from app.routers import pages as pages_router
from app.routers import tables as tables_router

SERVICE_NAME = os.getenv("WEB_SERVICE_NAME", "web_service")
HTTP_HOST = os.getenv("WEB_SERVICE_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("WEB_SERVICE_HTTP_PORT", "8000"))
TCP_HOST = os.getenv("WEB_SERVICE_TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("WEB_SERVICE_TCP_PORT", "9004"))
BUSINESS_SERVICE_HOST = os.getenv("WEB_SERVICE_BUSINESS_SERVICE_HOST", "business_service")
BUSINESS_SERVICE_PORT = int(os.getenv("WEB_SERVICE_BUSINESS_SERVICE_PORT", "9001"))

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


def status_data() -> dict[str, Any]:
    return {
        "role": "Accepts HTTP requests from OrderVUI/TableGUI and communicates with BusinessService over TCP.",
        "dependencies": {
            "business_service": {"host": BUSINESS_SERVICE_HOST, "port": BUSINESS_SERVICE_PORT},
        },
        "listeners": {
            "http": {"host": HTTP_HOST, "port": HTTP_PORT},
            "tcp": {"host": TCP_HOST, "port": TCP_PORT},
        },
        "http_routes": [
            "/",
            "/kiosk",
            "/table",
            "/api/menu",
            "/api/allergy",
            "/api/tables",
            "/api/orders",
            "/api/orders/{order_id}",
        ],
    }


def handle_tcp_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")

    if message_type == "health":
        return success_response("health", {"status": "ok"})

    if message_type == "status":
        return success_response("status", status_data())

    return error_response(f"unsupported message type: {message_type}")


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
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
                    response = handle_tcp_message(request)
                except json.JSONDecodeError as exc:
                    response = error_response(f"invalid json: {exc.msg}")

                self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                self.wfile.flush()
        finally:
            logger.info("tcp client disconnected: %s", peer)


class TcpServerThread:
    def __init__(self) -> None:
        self._server: ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = ThreadingTcpServer((TCP_HOST, TCP_PORT), TcpRequestHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="web-service-tcp-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("%s tcp listening on %s", SERVICE_NAME, self._server.server_address)

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tcp_server = TcpServerThread()
    tcp_server.start()

    try:
        yield
    finally:
        tcp_server.stop()


app = FastAPI(title="Web Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(menu_router.router)
app.include_router(tables_router.router)
app.include_router(orders_router.router)
app.include_router(pages_router.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    logger.info("received HTTP /health request")
    return {
        "status": "ok",
        "service": SERVICE_NAME,
    }


@app.get("/api/v1/status")
def get_status() -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        **status_data(),
    }
