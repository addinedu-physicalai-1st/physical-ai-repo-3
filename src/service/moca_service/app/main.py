import time

import pymysql

from app.config import configure_logging, load_config
from app.application.tcp_controller import MocaTcpController
from app.application.ros_controller import MocaRosController
from app.application.menu_service import MenuService
from app.application.order_service import OrderService
from app.domain.table_assignment_runtime import StoreTableDefinition, TableAssignmentRuntime
from app.repository.catalog_repo import (
    AllergyCategoryRepository,
    ProductAllergyRepository,
    ProductOptionGroupRepository,
    ProductRepository,
)
from app.repository.db import Database, DbConfig
from app.repository.order_repo import OrderItemRepository, OrderRepository
from app.repository.table_repo import StoreTableRepository
from app.transport.tcp_receiver import TcpServer
from app.transport.tcp_sender import build_moca_tcp_sender
from app.transport.ros_server import RosServer


def fetch_table_definitions_with_retry(
    store_table_repository: StoreTableRepository,
    logger,
    *,
    attempts: int = 30,
    delay_seconds: float = 2.0,
):
    for attempt in range(1, attempts + 1):
        try:
            return [
                StoreTableDefinition(
                    table_id=table.table_id,
                    table_number=table.table_number,
                    pos_x=table.pos_x,
                    pos_y=table.pos_y,
                )
                for table in store_table_repository.list_all()
            ]
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
    database = Database(db_config)
    product_repository = ProductRepository(database)
    product_option_group_repository = ProductOptionGroupRepository(database)
    allergy_category_repository = AllergyCategoryRepository(database)
    product_allergy_repository = ProductAllergyRepository(database)
    order_repository = OrderRepository(database)
    order_item_repository = OrderItemRepository(database)
    store_table_repository = StoreTableRepository(database)
    table_assignment_runtime = TableAssignmentRuntime(
        fetch_table_definitions_with_retry(store_table_repository, logger)
    )
    order_service = OrderService(
        database,
        product_repository,
        order_repository,
        order_item_repository,
        store_table_repository,
        table_assignment_runtime,
        logger,
    )
    menu_service = MenuService(
        product_repository,
        product_option_group_repository,
        allergy_category_repository,
        product_allergy_repository,
        logger,
    )
    controller = MocaTcpController(order_service, menu_service, tcp_sender, logger)
    ros_server = RosServer(
        config.ros_node_name,
        logger,
        enabled=config.ros_enabled,
    )
    ros_controller = MocaRosController(ros_server, logger)

    def handle_health(seq: int) -> None:
        controller.run_health_test(seq)
        ros_controller.publish_health_status(seq)

    # TCP server
    with ros_server:
        with TcpServer(
            config.server_host,
            config.server_port,
            handle_health,
            controller.handle_status,
            controller.get_catalog,
            controller.manage_product,
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
