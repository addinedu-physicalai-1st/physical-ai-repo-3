from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import configure_logging, load_config
from app.routers import menu as menu_router
from app.routers import orders as orders_router
from app.routers import pages as pages_router
from app.routers import tables as tables_router
from app.servers.tcp_server import TcpServerThread
from app.services.status_service import StatusService

config = load_config()
logger = configure_logging(config.service_name)
status_service = StatusService(config, logger)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tcp_server = TcpServerThread(
        config.tcp_host,
        config.tcp_port,
        status_service.handle_tcp_frame,
        logger,
    )
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
        "service": config.service_name,
    }


@app.get("/api/v1/status")
def get_status() -> dict[str, Any]:
    return {
        "service": config.service_name,
        **status_service.status_data(),
    }
