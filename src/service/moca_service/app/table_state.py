import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Literal

if TYPE_CHECKING:
    from app.repo.catalog_repo import DbConfig

TableStatus = Literal["empty", "occupied"]


class TableUnavailable(Exception):
    pass


@dataclass(frozen=True)
class StoreTable:
    table_id: int
    table_number: int
    pos_x: Decimal
    pos_y: Decimal
    status: TableStatus


@dataclass(frozen=True)
class StoreTableDefinition:
    table_id: int
    table_number: int
    pos_x: Decimal
    pos_y: Decimal


class TableStateStore:
    def __init__(self, tables: list[StoreTableDefinition]):
        self._lock = threading.RLock()
        self._tables = {table.table_id: table for table in tables}
        self._status: dict[int, TableStatus] = {table.table_id: "empty" for table in tables}

    @classmethod
    def from_database(cls, config: "DbConfig") -> "TableStateStore":
        import pymysql
        from pymysql.cursors import DictCursor

        with pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
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
                tables = [
                    StoreTableDefinition(
                        table_id=int(row["table_id"]),
                        table_number=int(row["table_number"]),
                        pos_x=Decimal(row["pos_x"]),
                        pos_y=Decimal(row["pos_y"]),
                    )
                    for row in cursor.fetchall()
                ]
        return cls(tables)

    def list_tables(self) -> list[StoreTable]:
        with self._lock:
            return [
                StoreTable(
                    table_id=table.table_id,
                    table_number=table.table_number,
                    pos_x=table.pos_x,
                    pos_y=table.pos_y,
                    status=self._status[table.table_id],
                )
                for table in self._tables.values()
            ]

    def occupy(self, table_id: int) -> None:
        with self._lock:
            self._require_available(table_id)
            self._status[table_id] = "occupied"

    def release(self, table_id: int) -> None:
        with self._lock:
            if table_id not in self._tables:
                raise TableUnavailable(f"unknown table_id={table_id}")
            self._status[table_id] = "empty"

    def _require_available(self, table_id: int) -> None:
        if table_id not in self._tables:
            raise TableUnavailable(f"unknown table_id={table_id}")
        if self._status[table_id] == "occupied":
            raise TableUnavailable(f"table {table_id} is already occupied")
