import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.repository.table_repo import TableRepository

if TYPE_CHECKING:
    from app.repository.db import Database

TableState = Literal["empty", "occupied"]


class TableUnavailable(Exception):
    pass


@dataclass(frozen=True)
class TableItem:
    table_id: int
    table_number: int
    state: TableState

    @property
    def status(self) -> TableState:
        return self.state


class TableInmemoryState:
    def __init__(self, database: "Database", table_repository: TableRepository):
        self.database = database
        self.table_repository = table_repository
        self._lock = threading.RLock()
        self._tables: dict[int, TableItem] = {}
        self.reset(1)

    def reset(self, map_id: int) -> None:
        with self.database.connect() as conn:
            tables = self.table_repository.list_by_map_id(conn, map_id)
        with self._lock:
            self._tables = {
                table.table_number: TableItem(
                    table_id=table.table_id,
                    table_number=table.table_number,
                    state="empty",
                )
                for table in tables
            }

    def get_states(self) -> list[TableItem]:
        with self._lock:
            return [self._tables[table_number] for table_number in sorted(self._tables)]

    def occupy(self, table_number: int) -> tuple[int | None, str]:
        with self._lock:
            if not self._is_valid_number(table_number):
                return None, f"unknown table_number={table_number}"
            elif not self._is_available(table_number):
                return None, f"table_number {table_number} is already occupied"
            else:
                self._set_state(table_number, "occupied")
                return table_number, ""

    def release(self, table_number: int) -> bool:
        with self._lock:
            if not self._is_valid_number(table_number):
                return False
            self._set_state(table_number, "empty")
            return True

    def _is_valid_number(self, table_number: int) -> bool:
        return table_number in self._tables

    def _is_available(self, table_number: int) -> bool:
        return self._tables[table_number].state == "empty"

    def _set_state(self, table_number: int, state: TableState) -> None:
        table = self._tables[table_number]
        self._tables[table_number] = TableItem(
            table_id=table.table_id,
            table_number=table.table_number,
            state=state,
        )
