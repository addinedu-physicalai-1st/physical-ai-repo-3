from app.config import configure_logging, load_config
from app.service.menu_service import MenuService
from app.service.order_service import OrderService
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


if __name__ == "__main__":
    main()
