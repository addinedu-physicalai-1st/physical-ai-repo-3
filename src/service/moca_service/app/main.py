import signal
import threading

from app.config import configure_logging, load_config
from app.communication.admin_gui import create_admin_gui_communication_runtime
from app.communication.web_service import create_web_service_tcp_server
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
from app.service.menu_service import MenuService
from app.service.order_service import OrderService


def main() -> None:
    # config 설정 로드 및 로깅 세팅
    config = load_config()
    logger = configure_logging(config.service_name)

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
        [
            StoreTableDefinition(
                table_id=table.table_id,
                table_number=table.table_number,
                pos_x=table.pos_x,
                pos_y=table.pos_y,
            )
            for table in store_table_repository.list_all()
        ]
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

    logger.info(
        "%s initialized business services: order_service=%s menu_service=%s",
        config.service_name,
        order_service.__class__.__name__,
        menu_service.__class__.__name__,
    )

    web_service_server = create_web_service_tcp_server(
        host=config.service_host,
        port=config.service_port,
        menu_service=menu_service,
        order_service=order_service,
        logger=logger,
        name="web_service",
    )
    admin_gui_runtime = create_admin_gui_communication_runtime(
        listen_host=config.admin_gui_listen_host,
        listen_port=config.admin_gui_listen_port,
        peer_host=config.admin_gui_host,
        peer_port=config.admin_gui_port,
        logger=logger,
        peer_name="AdminGUI",
        timeout=config.tcp_timeout_sec,
    )

    stop_event = threading.Event()

    def request_shutdown(signum, _frame):
        logger.info("received shutdown signal=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    web_service_server.start()
    admin_gui_runtime.start()
    logger.info(
        "%s communication started: web_service=%s:%s admin_gui_subscriber=%s:%s admin_gui_peer=%s:%s",
        config.service_name,
        config.service_host,
        config.service_port,
        config.admin_gui_listen_host,
        config.admin_gui_listen_port,
        config.admin_gui_host,
        config.admin_gui_port,
    )

    try:
        stop_event.wait()
    finally:
        admin_gui_runtime.stop()
        web_service_server.stop()
        logger.info("%s stopped communication servers", config.service_name)


if __name__ == "__main__":
    main()
