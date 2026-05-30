from typing import TYPE_CHECKING

from app.repository.table_repo import StoreTableRow

if TYPE_CHECKING:
    from app.repository.db import Database
    from app.repository.table_repo import TableRepository


class TableService:
    def __init__(
        self,
        database: "Database",
        table_repository: "TableRepository",
    ) -> None:
        self.database = database
        self.table_repository = table_repository

    def get_tables(self) -> list[StoreTableRow]:
        with self.database.connect() as conn:
            return self.table_repository.list_all(conn)
