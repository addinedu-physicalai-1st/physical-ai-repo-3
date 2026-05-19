from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

from app.repo.catalog_repo import DbConfig
from app.business.table_assignment_runtime import StoreTableDefinition


class TableRepository:
    def __init__(self, config: DbConfig):
        self.config = config

    def fetch_table_definitions(self) -> list[StoreTableDefinition]:
        with pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_id, table_number, pos_x, pos_y
                    FROM store_table
                    ORDER BY table_id
                    """
                )
                return [
                    StoreTableDefinition(
                        table_id=int(row["table_id"]),
                        table_number=int(row["table_number"]),
                        pos_x=Decimal(row["pos_x"]),
                        pos_y=Decimal(row["pos_y"]),
                    )
                    for row in cursor.fetchall()
                ]
