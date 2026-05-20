import time

import pymysql

from app.config import configure_logging, load_config
from app.application.moca_controller import MocaController
from app.application.moca_service import MocaService
from app.domain.table_assignment_runtime import TableAssignmentRuntime
from app.repository.catalog_repo import CatalogRepository, DbConfig
from app.repository.order_repo import OrderRepository
from app.repository.table_repo import TableRepository
from app.transport.tcp_receiver import TcpServer
from app.transport.tcp_sender import build_moca_tcp_sender


def fetch_table_definitions_with_retry(
    table_repository: TableRepository,
    logger,
    *,
    attempts: int = 30,
    delay_seconds: float = 2.0,
):
    for attempt in range(1, attempts + 1):
        try:
            return table_repository.fetch_table_definitions()
        except pymysql.MySQLError as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "Waiting for MySQL before loading table definitions (%s/%s): %s",
                attempt,
                attempts,
                exc,
            )
            time.sleep(delay_seconds)


def main() -> None:
    # config 설정 로드 및 로깅 세팅
    config = load_config()
    logger = configure_logging(config.service_name)
    tcp_sender = build_moca_tcp_sender(config, logger)

    # Database Config
    db_config = DbConfig(
        host=config.db_host,
        port=config.db_port,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
    )

    # create Service, Repo
    catalog_repository = CatalogRepository(db_config)
    order_repository = OrderRepository(db_config)
    table_repository = TableRepository(db_config)
    table_assignment_runtime = TableAssignmentRuntime(
        fetch_table_definitions_with_retry(table_repository, logger)
    )
    service = MocaService(
        catalog_repository,
        order_repository,
        table_assignment_runtime,
        logger,
    )
    controller = MocaController(service, tcp_sender, logger)

    # TCP server
    with TcpServer(
        config.server_host,
        config.server_port,
        controller.run_health_test,
        controller.handle_status,
        controller.get_catalog,
        controller.create_order,
        controller.get_table_assignment,
        controller.assign_table,
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
