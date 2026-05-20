import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

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


class TableAssignmentRuntime:
    def __init__(self, tables: list[StoreTableDefinition]):
        self._lock = threading.RLock()
        self._tables = {table.table_id: table for table in tables}
        self._status: dict[int, TableStatus] = {table.table_id: "empty" for table in tables}

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

    def occupy_by_table_number(self, table_number: int) -> int:
        with self._lock:
            table_id = self._table_id_for_number(table_number)
            self._require_available(table_id)
            self._status[table_id] = "occupied"
            return table_id

    def release(self, table_id: int) -> None:
        with self._lock:
            if table_id not in self._tables:
                raise TableUnavailable(f"unknown table_id={table_id}")
            self._status[table_id] = "empty"

    def release_by_table_number(self, table_number: int) -> None:
        with self._lock:
            self.release(self._table_id_for_number(table_number))

    def _require_available(self, table_id: int) -> None:
        if table_id not in self._tables:
            raise TableUnavailable(f"unknown table_id={table_id}")
        if self._status[table_id] == "occupied":
            raise TableUnavailable(f"table {table_id} is already occupied")

    def _table_id_for_number(self, table_number: int) -> int:
        for table in self._tables.values():
            if table.table_number == table_number:
                return table.table_id
        raise TableUnavailable(f"unknown table_number={table_number}")
