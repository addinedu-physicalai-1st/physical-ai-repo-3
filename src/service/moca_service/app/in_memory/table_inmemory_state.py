import threading
from dataclasses import dataclass
from typing import Literal

from app.repository.table_repo import TableRepository

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
    def __init__(self, table_repository: TableRepository):
        self.table_repository = table_repository
        self._lock = threading.RLock()
        self._tables: dict[int, TableItem] = {}
        self.reset(1)

    def reset(self, map_id: int) -> None:
        tables = self.table_repository.list_by_map_id(map_id)
        with self._lock:
            self._tables = {
                table.table_number: TableItem(
                    table_id=table.table_id,
                    table_number=table.table_number,
                    state="empty",
                )
                for table in tables
            }

    def list_tables(self) -> list[TableItem]:
        with self._lock:
            return [self._tables[table_number] for table_number in sorted(self._tables)]

    def occupy_by_table_number(self, table_number: int) -> int:
        with self._lock:
            self._require_available(table_number)
            self._set_state(table_number, "occupied")
            return self._table_id_for_number(table_number)

    def try_occupy_by_table_number(self, table_number: int) -> tuple[int | None, str]:
        with self._lock:
            if table_number not in self._tables:
                return None, f"unknown table_number={table_number}"
            if self._tables[table_number].state == "occupied":
                return None, f"table_number {table_number} is already occupied"
            self._set_state(table_number, "occupied")
            return self._table_id_for_number(table_number), ""

    def release_by_table_number(self, table_number: int) -> None:
        with self._lock:
            if table_number not in self._tables:
                raise TableUnavailable(f"unknown table_number={table_number}")
            self._set_state(table_number, "empty")

    def _require_available(self, table_number: int) -> None:
        if table_number not in self._tables:
            raise TableUnavailable(f"unknown table_number={table_number}")
        if self._tables[table_number].state == "occupied":
            raise TableUnavailable(f"table_number {table_number} is already occupied")

    def _table_id_for_number(self, table_number: int) -> int:
        try:
            return self._tables[table_number].table_id
        except KeyError as exc:
            raise TableUnavailable(f"unknown table_number={table_number}") from exc

    def _set_state(self, table_number: int, state: TableState) -> None:
        table = self._tables[table_number]
        self._tables[table_number] = TableItem(
            table_id=table.table_id,
            table_number=table.table_number,
            state=state,
        )
