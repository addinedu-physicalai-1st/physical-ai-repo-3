import json
from dataclasses import dataclass
from typing import Any

from pymysql.connections import Connection


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
class RecentOrderRow:
    order_id: int
    order_source: str
    receive_type: str
    table_number: int | None
    order_status: str
    payment_status: str
    total_price: int
    updated_at: str


@dataclass(frozen=True)
class ClaimedOrderRow:
    order_id: int
    receive_type: str
    table_number: int | None


@dataclass(frozen=True)
class OrderItemCreate:
    order_id: int
    product_id: int
    selected_options: list[Any]
    quantity: int
    unit_price: int


@dataclass(frozen=True)
class OrderItemRow:
    product_id: int
    product_name: str
    product_type: str
    selected_options: list[Any]
    quantity: int
    unit_price: int


class OrderRepository:
    def create(
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

    def get(self, conn: Connection, order_id: int) -> OrderRow | None:
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

    def list_recent(self, conn: Connection, limit: int = 20) -> list[RecentOrderRow]:
        bounded_limit = max(1, min(int(limit), 100))
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.order_source,
                    o.receive_type,
                    st.table_number,
                    o.order_status,
                    o.payment_status,
                    o.total_price,
                    DATE_FORMAT(o.updated_at, '%%H:%%i:%%s') AS updated_at
                FROM orders o
                LEFT JOIN store_table st ON st.table_id = o.table_id
                ORDER BY o.updated_at DESC, o.order_id DESC
                LIMIT %s
                """,
                (bounded_limit,),
            )
            return [
                RecentOrderRow(
                    order_id=int(row["order_id"]),
                    order_source=str(row["order_source"]),
                    receive_type=str(row["receive_type"]),
                    table_number=int(row["table_number"]) if row["table_number"] is not None else None,
                    order_status=str(row["order_status"]),
                    payment_status=str(row["payment_status"]),
                    total_price=int(row["total_price"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in cursor.fetchall()
            ]

    def update_assignment(
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

    def claim_accepted_orders(self, conn: Connection, limit: int = 10) -> list[ClaimedOrderRow]:
        bounded_limit = max(1, min(int(limit), 100))
        claimed: list[ClaimedOrderRow] = []
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.receive_type,
                    st.table_number
                FROM orders o
                LEFT JOIN store_table st ON st.table_id = o.table_id
                WHERE o.order_status = 'ACCEPTED'
                ORDER BY o.updated_at ASC, o.order_id ASC
                LIMIT %s
                """,
                (bounded_limit,),
            )
            rows = cursor.fetchall()

        for row in rows:
            order_id = int(row["order_id"])
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE orders
                    SET order_status = 'PROCESSING'
                    WHERE order_id = %s
                      AND order_status = 'ACCEPTED'
                    """,
                    (order_id,),
                )
                if cursor.rowcount > 0:
                    claimed.append(
                        ClaimedOrderRow(
                            order_id=order_id,
                            receive_type=str(row["receive_type"]),
                            table_number=(
                                int(row["table_number"])
                                if row["table_number"] is not None
                                else None
                            ),
                        )
                    )
        return claimed

    def mark_completed(self, conn: Connection, order_id: int) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET order_status = 'COMPLETED'
                WHERE order_id = %s
                  AND order_status = 'PROCESSING'
                """,
                (order_id,),
            )
            return cursor.rowcount > 0

    def mark_failed(self, conn: Connection, order_id: int) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET order_status = 'FAILED'
                WHERE order_id = %s
                  AND order_status = 'PROCESSING'
                """,
                (order_id,),
            )
            return cursor.rowcount > 0

    def update_assignment_if_pending(
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
                    table_id = %s,
                    order_status = 'ACCEPTED'
                WHERE order_id = %s
                  AND receive_type = 'PENDING'
                  AND order_status = 'PENDING'
                  AND table_id IS NULL
                """,
                (order_source, receive_type, table_id, order_id),
            )
            return cursor.rowcount > 0


class OrderItemRepository:
    def create_many(self, conn: Connection, items: list[OrderItemCreate]) -> None:
        if not items:
            return
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

    def list_by_order_id(self, conn: Connection, order_id: int) -> list[OrderItemRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    oi.product_id,
                    p.name AS product_name,
                    p.product_type,
                    oi.selected_options,
                    oi.quantity,
                    oi.unit_price
                FROM order_item oi
                JOIN product p ON p.product_id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id ASC
                """,
                (order_id,),
            )
            rows = cursor.fetchall()
        return [
            OrderItemRow(
                product_id=int(row["product_id"]),
                product_name=str(row["product_name"]),
                product_type=str(row["product_type"]),
                selected_options=_decode_json(row["selected_options"]),
                quantity=int(row["quantity"]),
                unit_price=int(row["unit_price"]),
            )
            for row in rows
        ]


def _decode_json(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []
