import json
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
                    SELECT
                        product_id,
                        name,
                        image_url,
                        price,
                        product_type,
                        menu_status
                    FROM product
                    WHERE menu_status = 'ON_SALE'
                    ORDER BY product_id
                    """
                )
                menu = [
                    {
                        "id": int(row["product_id"]),
                        "name": row["name"],
                        "image": row["image_url"],
                        "price": int(row["price"]),
                        "options": [],
                    }
                    for row in cursor.fetchall()
                ]
                menu_by_id = {item["id"]: item for item in menu}

                cursor.execute(
                    """
                    SELECT product_id, name, options
                    FROM product_option_group
                    ORDER BY product_id, product_option_group_id
                    """
                )
                surcharges: dict[str, int] = {}
                for row in cursor.fetchall():
                    item = menu_by_id.get(int(row["product_id"]))
                    if item is None:
                        continue

                    group_name = str(row["name"])
                    options = _decode_options(row["options"])
                    item["options"].extend(_to_catalog_options(group_name, options))
                    for option in item["options"]:
                        if option["option_group"] == group_name and option["price"] > 0:
                            surcharges[f"{_legacy_option_key(group_name)}:{option['option_name']}"] = int(
                                option["price"]
                            )

                cursor.execute(
                    """
                    SELECT
                        ac.name AS allergy_name,
                        ac.icon,
                        p.name AS product_name
                    FROM allergy_category ac
                    LEFT JOIN product_allergy pa
                        ON pa.allergy_category_id = ac.allergy_category_id
                    LEFT JOIN product p
                        ON p.product_id = pa.product_id
                        AND p.menu_status = 'ON_SALE'
                    ORDER BY ac.allergy_category_id, p.product_id
                    """
                )
                allergy_by_name: dict[str, dict[str, Any]] = {}
                for row in cursor.fetchall():
                    allergy = allergy_by_name.setdefault(
                        row["allergy_name"],
                        {"name": row["allergy_name"], "icon": row["icon"], "items": []},
                    )
                    if row["product_name"]:
                        allergy["items"].append(row["product_name"])

        return {
            "menu": menu,
            "allergy": list(allergy_by_name.values()),
            "surcharges": surcharges,
        }


def _decode_options(options: Any) -> list[Any]:
    if isinstance(options, list):
        return options
    if isinstance(options, str):
        decoded = json.loads(options)
        return decoded if isinstance(decoded, list) else []
    return []


def _to_catalog_options(group_name: str, options: list[Any]) -> list[dict[str, Any]]:
    default_seen = any(isinstance(option, dict) and bool(option.get("is_default", False)) for option in options)
    catalog_options = []
    for index, option in enumerate(options):
        if isinstance(option, dict):
            option_name = str(option.get("name", ""))
            price = int(option.get("price", 0))
            is_default = bool(option.get("is_default", False)) if default_seen else index == 0
        else:
            option_name = str(option)
            price = 0
            is_default = index == 0 and not default_seen
        catalog_options.append(
            {
                "option_group": group_name,
                "option_name": option_name,
                "price": price,
                "is_default": is_default,
            }
        )
    return catalog_options


def _legacy_option_key(group_name: str) -> str:
    return {
        "에스프레소 샷": "shot",
        "우유": "milk",
        "온도": "temperature",
    }.get(group_name, group_name)
