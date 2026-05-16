from app.config import configure_logging, load_config
from app.service import MocaService
from app.tcp import TcpEndpoint, TcpStatusNotifier, TcpServer


def main() -> None:
    # config 설정 로드 및 로깅 세팅
    config = load_config()
    logger = configure_logging(config.service_name)

    admin_gui = TcpEndpoint(
        host=config.admin_gui_host,
        port=config.admin_gui_port,
        name="AdminGUI",
    )
    web_service = TcpEndpoint(
        host=config.web_service_host,
        port=config.web_service_tcp_port,
        name="WebService",
    )
    cooking_controller_bridge = TcpEndpoint(
        host=config.cooking_controller_bridge_host,
        port=config.cooking_controller_bridge_port,
        name="CookingControllerBridge",
    )
    serving_controller_bridge = TcpEndpoint(
        host=config.serving_controller_bridge_host,
        port=config.serving_controller_bridge_port,
        name="ServingControllerBridge",
    )

    status_notifiers = [
        TcpStatusNotifier(admin_gui, logger),
        TcpStatusNotifier(web_service, logger),
        TcpStatusNotifier(cooking_controller_bridge, logger),
        TcpStatusNotifier(serving_controller_bridge, logger),
    ]

    service = MocaService(status_notifiers, logger)

    with TcpServer(
        config.server_host,
        config.server_port,
        service.run_health_test,
        service.handle_status,
        logger,
        "MocaService",
    ) as server:
        logger.info(
            "%s TCP listening on %s",
            config.service_name,
            server.server_address,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
