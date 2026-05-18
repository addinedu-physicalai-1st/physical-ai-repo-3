from dataclasses import dataclass
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


class CatalogRepository:
    def __init__(self, config: DbConfig):
        self.config = config

    def fetch_catalog(self) -> dict[str, Any]:
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
                    SELECT id, name, emoji, price, hot, shot, ice, milk
                    FROM menu_items
                    ORDER BY id
                    """
                )
                menu = [
                    {
                        "id": int(row["id"]),
                        "name": row["name"],
                        "emoji": row["emoji"],
                        "price": int(row["price"]),
                        "hot": bool(row["hot"]),
                        "shot": bool(row["shot"]),
                        "ice": bool(row["ice"]),
                        "milk": bool(row["milk"]),
                    }
                    for row in cursor.fetchall()
                ]

                cursor.execute(
                    """
                    SELECT ac.name AS allergy_name, ac.icon, mi.name AS item_name
                    FROM allergy_categories ac
                    LEFT JOIN menu_item_allergies mia ON mia.allergy_category_id = ac.id
                    LEFT JOIN menu_items mi ON mi.id = mia.menu_item_id
                    ORDER BY ac.id, mi.id
                    """
                )
                allergy_by_name: dict[str, dict[str, Any]] = {}
                for row in cursor.fetchall():
                    allergy = allergy_by_name.setdefault(
                        row["allergy_name"],
                        {"name": row["allergy_name"], "icon": row["icon"], "items": []},
                    )
                    if row["item_name"]:
                        allergy["items"].append(row["item_name"])

                cursor.execute("SELECT option_key, price FROM option_surcharges ORDER BY option_key")
                surcharges = {
                    row["option_key"]: int(row["price"])
                    for row in cursor.fetchall()
                }

        return {
            "menu": menu,
            "allergy": list(allergy_by_name.values()),
            "surcharges": surcharges,
        }
