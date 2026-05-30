from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pymysql.connections import Connection


@dataclass(frozen=True)
class StoreTableRow:
    table_id: int
    map_id: int
    table_number: int
    pos_x: Decimal
    pos_y: Decimal


class TableRepository:
    def list_all(self, conn: "Connection") -> list[StoreTableRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_id, map_id, table_number, pos_x, pos_y
                FROM store_table
                ORDER BY table_id
                """
            )
            return [self._to_row(row) for row in cursor.fetchall()]

    def get(self, conn: "Connection", table_id: int) -> StoreTableRow | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_id, map_id, table_number, pos_x, pos_y
                FROM store_table
                WHERE table_id = %s
                """,
                (table_id,),
            )
            row = cursor.fetchone()
            return self._to_row(row) if row is not None else None

    def list_by_map_id(self, conn: "Connection", map_id: int) -> list[StoreTableRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_id, map_id, table_number, pos_x, pos_y
                FROM store_table
                WHERE map_id = %s
                ORDER BY table_id
                """,
                (map_id,),
            )
            return [self._to_row(row) for row in cursor.fetchall()]

    def _to_row(self, row) -> StoreTableRow:
        return StoreTableRow(
            table_id=int(row["table_id"]),
            map_id=int(row["map_id"]),
            table_number=int(row["table_number"]),
            pos_x=Decimal(row["pos_x"]),
            pos_y=Decimal(row["pos_y"]),
        )
