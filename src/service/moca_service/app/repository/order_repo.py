import json
from dataclasses import dataclass

import pymysql
from pymysql.cursors import DictCursor

from app.protocol.order_protocol import OrderRequest
from app.repository.catalog_repo import DbConfig


@dataclass(frozen=True)
class CreatedOrder:
    order_id: int
    total_price: int


@dataclass(frozen=True)
class OrderAssignment:
    order_id: int
    order_source: str
    receive_type: str
    table_id: int | None
    table_number: int | None


class OrderRepository:
    def __init__(self, config: DbConfig):
        self.config = config

    def create_order(self, request: OrderRequest) -> CreatedOrder:
        product_ids = [item.product_id for item in request.items]
        placeholders = ", ".join(["%s"] * len(product_ids))

        with pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        ) as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT product_id, price
                        FROM product
                        WHERE menu_status = 'ON_SALE'
                          AND product_id IN ({placeholders})
                        """,
                        product_ids,
                    )
                    prices = {int(row["product_id"]): int(row["price"]) for row in cursor.fetchall()}
                    missing = sorted(set(product_ids) - set(prices))
                    if missing:
                        raise ValueError(f"unknown or unavailable product_id={missing[0]}")

                    total_price = sum(prices[item.product_id] * item.quantity for item in request.items)
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
                        (
                            "COUNTER",
                            "PENDING",
                            None,
                            total_price,
                        ),
                    )
                    order_id = int(cursor.lastrowid)
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
                                order_id,
                                item.product_id,
                                json.dumps([], separators=(",", ":")),
                                item.quantity,
                                prices[item.product_id],
                            )
                            for item in request.items
                        ],
                    )
                conn.commit()
                return CreatedOrder(order_id=order_id, total_price=total_price)
            except Exception:
                conn.rollback()
                raise

    def fetch_assignment(self, order_id: int) -> OrderAssignment | None:
        with pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        o.order_id,
                        o.order_source,
                        o.receive_type,
                        o.table_id,
                        st.table_number
                    FROM orders o
                    LEFT JOIN store_table st
                        ON st.table_id = o.table_id
                    WHERE o.order_id = %s
                    """,
                    (order_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return OrderAssignment(
                    order_id=int(row["order_id"]),
                    order_source=str(row["order_source"]),
                    receive_type=str(row["receive_type"]),
                    table_id=int(row["table_id"]) if row["table_id"] is not None else None,
                    table_number=int(row["table_number"]) if row["table_number"] is not None else None,
                )

    def update_assignment(self, order_id: int, order_source: str, receive_type: str, table_id: int | None) -> bool:
        with pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        ) as conn:
            try:
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
                    updated = cursor.rowcount > 0
                conn.commit()
                return updated
            except Exception:
                conn.rollback()
                raise
