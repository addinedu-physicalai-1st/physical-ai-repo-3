import json
from dataclasses import dataclass
from typing import Any

from pymysql.connections import Connection

from app.repository.db import Database, DbConfig


@dataclass(frozen=True)
class OrderRow:
    order_id: int
    order_source: str
    receive_type: str
    table_id: int | None
    order_status: str
    payment_status: str
    total_price: int


@dataclass(frozen=True)
class OrderItemCreate:
    order_id: int
    product_id: int
    selected_options: list[Any]
    quantity: int
    unit_price: int


class OrderRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def create(
        self,
        order_source: str,
        receive_type: str,
        table_id: int | None,
        total_price: int,
        conn: Connection | None = None,
    ) -> int:
        if conn is not None:
            return self._create_with_conn(conn, order_source, receive_type, table_id, total_price)
        with self.database.connect() as own_conn:
            return self._create_with_conn(own_conn, order_source, receive_type, table_id, total_price)

    def get(self, order_id: int, conn: Connection | None = None) -> OrderRow | None:
        if conn is not None:
            return self._get_with_conn(conn, order_id)
        with self.database.connect() as own_conn:
            return self._get_with_conn(own_conn, order_id)

    def update_assignment(
        self,
        order_id: int,
        order_source: str,
        receive_type: str,
        table_id: int | None,
        conn: Connection | None = None,
    ) -> bool:
        if conn is not None:
            return self._update_assignment_with_conn(conn, order_id, order_source, receive_type, table_id)
        with self.database.connect() as own_conn:
            return self._update_assignment_with_conn(own_conn, order_id, order_source, receive_type, table_id)

    def update_assignment_if_pending(
        self,
        order_id: int,
        order_source: str,
        receive_type: str,
        table_id: int | None,
        conn: Connection | None = None,
    ) -> bool:
        if conn is not None:
            return self._update_assignment_if_pending_with_conn(conn, order_id, order_source, receive_type, table_id)
        with self.database.connect() as own_conn:
            return self._update_assignment_if_pending_with_conn(own_conn, order_id, order_source, receive_type, table_id)

    def _create_with_conn(
        self,
        conn: Connection,
        order_source: str,
        receive_type: str,
        table_id: int | None,
        total_price: int,
    ) -> int:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO orders (
                    order_source,
                    receive_type,
                    table_id,
                    order_status,
                    payment_status,
                    total_price
                ) VALUES (%s, %s, %s, 'PENDING', 'PENDING', %s)
                """,
                (order_source, receive_type, table_id, total_price),
            )
            return int(cursor.lastrowid)

    def _get_with_conn(self, conn: Connection, order_id: int) -> OrderRow | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    order_id,
                    order_source,
                    receive_type,
                    table_id,
                    order_status,
                    payment_status,
                    total_price
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return OrderRow(
                order_id=int(row["order_id"]),
                order_source=str(row["order_source"]),
                receive_type=str(row["receive_type"]),
                table_id=int(row["table_id"]) if row["table_id"] is not None else None,
                order_status=str(row["order_status"]),
                payment_status=str(row["payment_status"]),
                total_price=int(row["total_price"]),
            )

    def _update_assignment_with_conn(
        self,
        conn: Connection,
        order_id: int,
        order_source: str,
        receive_type: str,
        table_id: int | None,
    ) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET order_source = %s,
                    receive_type = %s,
                    table_id = %s
                WHERE order_id = %s
                """,
                (order_source, receive_type, table_id, order_id),
            )
            return cursor.rowcount > 0

    def _update_assignment_if_pending_with_conn(
        self,
        conn: Connection,
        order_id: int,
        order_source: str,
        receive_type: str,
        table_id: int | None,
    ) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET order_source = %s,
                    receive_type = %s,
                    table_id = %s
                WHERE order_id = %s
                  AND receive_type = 'PENDING'
                  AND table_id IS NULL
                """,
                (order_source, receive_type, table_id, order_id),
            )
            return cursor.rowcount > 0


class OrderItemRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def create_many(self, items: list[OrderItemCreate], conn: Connection | None = None) -> None:
        if not items:
            return
        if conn is not None:
            self._create_many_with_conn(conn, items)
            return
        with self.database.connect() as own_conn:
            self._create_many_with_conn(own_conn, items)

    def _create_many_with_conn(self, conn: Connection, items: list[OrderItemCreate]) -> None:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO order_item (
                    order_id,
                    product_id,
                    selected_options,
                    quantity,
                    unit_price
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        item.order_id,
                        item.product_id,
                        json.dumps(item.selected_options, separators=(",", ":")),
                        item.quantity,
                        item.unit_price,
                    )
                    for item in items
                ],
            )
