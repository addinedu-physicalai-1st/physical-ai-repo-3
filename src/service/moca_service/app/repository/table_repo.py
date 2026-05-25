from dataclasses import dataclass
from decimal import Decimal

from pymysql.connections import Connection

from app.repository.db import Database, DbConfig


@dataclass(frozen=True)
class StoreTableRow:
    table_id: int
    map_id: int
    table_number: int
    pos_x: Decimal
    pos_y: Decimal


class TableRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def list_all(self, conn: Connection | None = None) -> list[StoreTableRow]:
        if conn is not None:
            return self._list_all_with_conn(conn)
        with self.database.connect() as own_conn:
            return self._list_all_with_conn(own_conn)

    def get(self, table_id: int, conn: Connection | None = None) -> StoreTableRow | None:
        if conn is not None:
            return self._get_with_conn(conn, table_id)
        with self.database.connect() as own_conn:
            return self._get_with_conn(own_conn, table_id)

    def list_by_map_id(self, map_id: int, conn: Connection | None = None) -> list[StoreTableRow]:
        if conn is not None:
            return self._list_by_map_id_with_conn(conn, map_id)
        with self.database.connect() as own_conn:
            return self._list_by_map_id_with_conn(own_conn, map_id)

    def _list_all_with_conn(self, conn: Connection) -> list[StoreTableRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_id, map_id, table_number, pos_x, pos_y
                FROM store_table
                ORDER BY table_id
                """
            )
            return [self._to_row(row) for row in cursor.fetchall()]

    def _get_with_conn(self, conn: Connection, table_id: int) -> StoreTableRow | None:
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

    def _list_by_map_id_with_conn(self, conn: Connection, map_id: int) -> list[StoreTableRow]:
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
