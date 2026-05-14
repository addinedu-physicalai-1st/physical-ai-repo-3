from app.api.tcp import TcpEndpoint, TcpStatusNotifier, create_health_server
from app.config import configure_logging, load_config
from app.service import ControlService


def main() -> None:
    config = load_config()
    logger = configure_logging(config.service_name)
    admin_gui = TcpEndpoint(
        host=config.admin_gui_host,
        port=config.admin_gui_port,
        name="AdminGUI",
    )
    business_service = TcpEndpoint(
        host=config.business_service_host,
        port=config.business_service_port,
        name="BusinessService",
    )
    status_notifiers = [
        TcpStatusNotifier(admin_gui, logger),
        TcpStatusNotifier(business_service, logger),
    ]
    service = ControlService(status_notifiers, logger)

    with create_health_server(config.host, config.port, service.run_health_test, logger) as server:
        logger.info("%s listening on %s", config.service_name, server.server_address)
        server.serve_forever()


if __name__ == "__main__":
    main()
