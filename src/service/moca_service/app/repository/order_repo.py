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
                            table_number,
                            order_status,
                            payment_status,
                            total_price
                        ) VALUES (%s, %s, %s, 'PENDING', 'PENDING', %s)
                        """,
                        (
                            "COUNTER",
                            "TAKE_OUT",
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
