import logging

from app.communication.web_service.controller import WebServiceTcpController
from app.communication.web_service.tcp_server import WebServiceTcpServer
from app.service.menu_service import MenuService
from app.service.order_service import OrderService


def create_web_service_tcp_server(
    host: str,
    port: int,
    menu_service: MenuService,
    order_service: OrderService,
    logger: logging.Logger,
    *,
    name: str = "web_service",
) -> WebServiceTcpServer:
    controller = WebServiceTcpController(menu_service, order_service, logger)
    return WebServiceTcpServer(
        host=host,
        port=port,
        controller=controller,
        logger=logger,
        name=name,
    )
