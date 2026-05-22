import signal
import threading

from app.config import configure_logging, load_config
from app.communication.admin_gui import (
    create_admin_gui_communication_runtime,
    create_admin_gui_doby_runtime,
)
from app.communication.admin_gui.monitor import AdminGuiMonitorPublisher
from app.communication.controller_ports import DDoobyActionManufacturePort, DobyModeServingPort
from app.communication.ddooby_controller import create_ddooby_controller_runtime
from app.communication.doby_controller import create_doby_controller_runtime
from app.domain.order_orchestration_runtime import OrderOrchestrationRuntime
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
    admin_gui_doby_runtime = create_admin_gui_doby_runtime(
        logger=logger,
        node_name=config.admin_gui_doby_node_name,
        enabled=config.admin_gui_doby_ros_enabled,
        setmode_timeout_sec=config.admin_gui_doby_setmode_timeout_sec,
    )
    admin_gui_monitor = AdminGuiMonitorPublisher(
        admin_gui_runtime,
        menu_service,
        order_service,
        logger,
        admin_gui_doby_runtime,
    )
    admin_gui_monitor.register()
    doby_controller_runtime = create_doby_controller_runtime(
        logger=logger,
        node_name=config.doby_controller_node_name,
        enabled=config.doby_controller_ros_enabled,
        setmode_timeout_sec=config.doby_controller_setmode_timeout_sec,
    )
    ddooby_controller_runtime = create_ddooby_controller_runtime(
        logger=logger,
        node_name=config.ddooby_controller_node_name,
        enabled=config.ddooby_controller_ros_enabled,
        action_name=config.ddooby_controller_action_name,
        action_timeout_sec=config.ddooby_controller_action_timeout_sec,
    )
    manufacture_port = DDoobyActionManufacturePort(ddooby_controller_runtime, logger)
    order_orchestration_runtime = OrderOrchestrationRuntime(
        order_repository=order_repository,
        order_item_repository=order_item_repository,
        manufacture_port=manufacture_port,
        serving_port=DobyModeServingPort(doby_controller_runtime, logger),
        logger=logger,
        tick_interval_sec=config.order_orchestration_tick_sec,
    )
    manufacture_port.set_completion_callback(
        order_orchestration_runtime.on_manufacture_completed
    )

    stop_event = threading.Event()

    def request_shutdown(signum, _frame):
        logger.info("received shutdown signal=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    web_service_server.start()
    admin_gui_runtime.start()
    admin_gui_doby_runtime.start()
    doby_controller_runtime.start()
    ddooby_controller_runtime.start()
    if config.order_orchestration_enabled:
        order_orchestration_runtime.start()
    logger.info(
        "%s communication started: web_service=%s:%s admin_gui_subscriber=%s:%s "
        "admin_gui_peer=%s:%s admin_gui_doby_ros=%s doby_controller_ros=%s "
        "ddooby_controller_ros=%s order_orchestration=%s",
        config.service_name,
        config.service_host,
        config.service_port,
        config.admin_gui_listen_host,
        config.admin_gui_listen_port,
        config.admin_gui_host,
        config.admin_gui_port,
        config.admin_gui_doby_ros_enabled,
        config.doby_controller_ros_enabled,
        config.ddooby_controller_ros_enabled,
        config.order_orchestration_enabled,
    )

    try:
        stop_event.wait()
    finally:
        order_orchestration_runtime.stop()
        ddooby_controller_runtime.stop()
        doby_controller_runtime.stop()
        admin_gui_doby_runtime.stop()
        admin_gui_monitor.stop()
        admin_gui_runtime.stop()
        web_service_server.stop()
        logger.info("%s stopped communication servers", config.service_name)


if __name__ == "__main__":
    main()
