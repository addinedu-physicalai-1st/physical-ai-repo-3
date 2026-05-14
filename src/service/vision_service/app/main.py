import socketserver
import threading
from logging import Logger

from app.api import tcp, udp
from app.config import configure_logging, load_config
from app.service import VisionService


def serve(server: socketserver.BaseServer, label: str, service_name: str, logger: Logger) -> None:
    logger.info("%s %s listening on %s", service_name, label, server.server_address)
    server.serve_forever()


def main() -> None:
    config = load_config()
    logger = configure_logging(config.service_name)
    service = VisionService(config)
    tcp_server = tcp.create_server(
        config.tcp_host,
        config.tcp_port,
        service.handle_message,
        service.error_response,
        logger,
    )
    udp_server = udp.create_server(
        config.udp_host,
        config.udp_port,
        service.handle_message,
        service.error_response,
        logger,
    )
    tcp_thread = threading.Thread(
        target=serve,
        args=(tcp_server, "tcp", config.service_name, logger),
        name="vision-service-tcp-server",
        daemon=True,
    )
    udp_thread = threading.Thread(
        target=serve,
        args=(udp_server, "udp", config.service_name, logger),
        name="vision-service-udp-server",
        daemon=True,
    )

    try:
        tcp_thread.start()
        udp_thread.start()
        tcp_thread.join()
    finally:
        tcp_server.shutdown()
        udp_server.shutdown()
        tcp_server.server_close()
        udp_server.server_close()


if __name__ == "__main__":
    main()
