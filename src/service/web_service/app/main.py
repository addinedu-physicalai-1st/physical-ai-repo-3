from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


from app.dependencies import config, logger, status_service
from app.config import ORDER_VUI_DIR
from app.routers import menu as menu_router
from app.routers import orders as orders_router
from app.routers import pages as pages_router
from app.routers import status as status_router
from app.routers import tables as tables_router
from app.servers.tcp_server import TcpServerThread


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
app.include_router(status_router.router)

app.mount("/audio", StaticFiles(directory=ORDER_VUI_DIR / "audio"), name="audio")
app.mount("/order_vui", StaticFiles(directory=ORDER_VUI_DIR), name="order_vui")
