import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.repository.table_repo import StoreTableRow, TableRepository

if TYPE_CHECKING:
    from app.repository.db import Database

TableState = Literal["empty", "occupied"]

# store_table.occupancy ENUM 값 <-> 외부 표현(empty/occupied) 매핑.
# DB 는 대문자 ENUM('EMPTY','OCCUPIED'), 외부 계약(web_service/kiosk)은 소문자 유지.
_DB_TO_STATE: dict[str, TableState] = {"OCCUPIED": "occupied", "EMPTY": "empty"}


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
    """테이블 점유 상태의 단일 소스 = store_table.occupancy 컬럼 (DB 영속).

    클래스명은 호환을 위해 유지하지만 더 이상 in-memory 가 아니라 DB 를 읽고/쓴다.
    moca_service 단일 프로세스 내 동시 주문 직렬화를 위해 read+write 를 RLock 으로 감싼다.
    재기동해도 점유 상태가 DB 에 보존된다(기존 in-memory 구현은 기동 시 전부 empty 로 초기화됐음).
    """

    def __init__(self, database: "Database", table_repository: TableRepository):
        self.database = database
        self.table_repository = table_repository
        self._lock = threading.RLock()

    def reset(self, map_id: int) -> None:
        """해당 맵의 모든 테이블 점유를 EMPTY 로 (명시 호출 전용 — 기동 시 자동 호출하지 않음)."""
        with self._lock, self.database.connect() as conn:
            for table in self.table_repository.list_by_map_id(conn, map_id):
                self.table_repository.set_occupancy(conn, table.table_number, "EMPTY")

    def get_states(self) -> list[TableItem]:
        with self._lock, self.database.connect() as conn:
            rows = self.table_repository.list_all(conn)
        return [self._to_item(row) for row in rows]

    def occupy(self, table_number: int) -> tuple[int | None, str]:
        with self._lock, self.database.connect() as conn:
            row = self._find(conn, table_number)
            if row is None:
                return None, f"unknown table_number={table_number}"
            if row.occupancy == "OCCUPIED":
                return None, f"table_number {table_number} is already occupied"
            self.table_repository.set_occupancy(conn, table_number, "OCCUPIED")
            return table_number, ""

    def release(self, table_number: int) -> bool:
        with self._lock, self.database.connect() as conn:
            if self._find(conn, table_number) is None:
                return False
            self.table_repository.set_occupancy(conn, table_number, "EMPTY")
            return True

    def _find(self, conn, table_number: int) -> "StoreTableRow | None":
        for row in self.table_repository.list_all(conn):
            if row.table_number == table_number:
                return row
        return None

    def _to_item(self, row: "StoreTableRow") -> TableItem:
        return TableItem(
            table_id=row.table_id,
            table_number=row.table_number,
            state=_DB_TO_STATE.get(row.occupancy, "empty"),
        )
