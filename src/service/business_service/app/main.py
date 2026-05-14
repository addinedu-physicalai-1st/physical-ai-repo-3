from app.api.tcp import TcpEndpoint, TcpStatusNotifier, create_health_server
from app.config import configure_logging, load_config
from app.service import BusinessService


def main() -> None:
    config = load_config()
    logger = configure_logging(config.service_name)
    control_service = TcpEndpoint(
        host=config.control_service_host,
        port=config.control_service_port,
        name="ControlService",
    )
    status_notifier = TcpStatusNotifier(control_service, logger)
    service = BusinessService(status_notifier)

    with create_health_server(config.host, config.port, service.run_health_test, logger) as server:
        logger.info("%s listening on %s", config.service_name, server.server_address)
        server.serve_forever()


if __name__ == "__main__":
    main()
