from app.config import configure_logging, load_config
from app.service import BusinessService
from app.tcp import TcpEndpoint, TcpStatusNotifier, TcpServer


def main() -> None:
    # config 설정 로드 및 로깅 세팅
    config = load_config()
    logger = configure_logging(config.service_name)

    # TCP 통신 엔드포인트 정의
    admin_gui = TcpEndpoint(
        host=config.admin_gui_host,
        port=config.admin_gui_port,
        name="AdminGUI",
    )
    control_service = TcpEndpoint(
        host=config.control_service_host,
        port=config.control_service_port,
        name="ControlService",
    )
    web_service = TcpEndpoint(
        host=config.web_service_host,
        port=config.web_service_tcp_port,
        name="WebService",
    )
    status_notifiers = [
        TcpStatusNotifier(admin_gui, logger),
        TcpStatusNotifier(control_service, logger),
        TcpStatusNotifier(web_service, logger),
    ]

    # 비지니스 로직 서비스 객체 생성
    service = BusinessService(status_notifiers, logger)

    # TCP 서버 생성
    with TcpServer(config.server_host, config.server_port, service, logger) as server:
        logger.info("%s listening on %s", config.service_name, server.server_address)
        server.serve_forever()


if __name__ == "__main__":
    main()
