from dataclasses import dataclass
from typing import Any

from pymysql.connections import Connection

from app.repository.db import Database, DbConfig


@dataclass(frozen=True)
class ProductRow:
    product_id: int
    name: str
    description: str
    image_url: str
    price: int
    product_type: str
    menu_status: str


@dataclass(frozen=True)
class ProductOptionGroupRow:
    product_option_group_id: int
    product_id: int
    name: str
    options: Any
    required: bool
    max_select_count: int


@dataclass(frozen=True)
class AllergyCategoryRow:
    allergy_category_id: int
    name: str
    icon: str


@dataclass(frozen=True)
class ProductAllergyRow:
    product_id: int
    allergy_category_id: int


class ProductRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def list_by_status(self, menu_status: str, conn: Connection | None = None) -> list[ProductRow]:
        query = """
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE menu_status = %s
            ORDER BY product_id
        """
        return self._fetch_products(query, (menu_status,), conn)

    def list_products(self, *, include_paused: bool = False, conn: Connection | None = None) -> list[ProductRow]:
        if include_paused:
            query = """
                SELECT product_id, name, description, image_url, price, product_type, menu_status
                FROM product
                ORDER BY product_id
            """
            return self._fetch_products(query, (), conn)
        query = """
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE menu_status <> 'PAUSED'
            ORDER BY product_id
        """
        return self._fetch_products(query, (), conn)

    def get(self, product_id: int, conn: Connection | None = None) -> ProductRow | None:
        query = """
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE product_id = %s
        """
        products = self._fetch_products(query, (product_id,), conn)
        return products[0] if products else None

    def create(self, product: dict[str, Any], conn: Connection | None = None) -> ProductRow:
        if conn is not None:
            return self._create_with_conn(conn, product)
        with self.database.connect() as own_conn:
            return self._create_with_conn(own_conn, product)

    def update(self, product_id: int, product: dict[str, Any], conn: Connection | None = None) -> ProductRow | None:
        if conn is not None:
            return self._update_with_conn(conn, product_id, product)
        with self.database.connect() as own_conn:
            return self._update_with_conn(own_conn, product_id, product)

    def soft_delete(self, product_id: int, conn: Connection | None = None) -> bool:
        if conn is not None:
            return self._soft_delete_with_conn(conn, product_id)
        with self.database.connect() as own_conn:
            return self._soft_delete_with_conn(own_conn, product_id)

    def list_by_ids_and_status(
        self,
        product_ids: list[int],
        menu_status: str,
        conn: Connection | None = None,
    ) -> list[ProductRow]:
        if not product_ids:
            return []
        placeholders = ", ".join(["%s"] * len(product_ids))
        query = f"""
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE menu_status = %s
              AND product_id IN ({placeholders})
            ORDER BY product_id
        """
        return self._fetch_products(query, [menu_status, *product_ids], conn)

    def _fetch_products(self, query: str, params: list[Any] | tuple[Any, ...], conn: Connection | None) -> list[ProductRow]:
        if conn is not None:
            return self._fetch_products_with_conn(conn, query, params)
        with self.database.connect() as own_conn:
            return self._fetch_products_with_conn(own_conn, query, params)

    def _fetch_products_with_conn(self, conn: Connection, query: str, params: list[Any] | tuple[Any, ...]) -> list[ProductRow]:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return [
                ProductRow(
                    product_id=int(row["product_id"]),
                    name=str(row["name"]),
                    description=str(row["description"]),
                    image_url=str(row["image_url"]),
                    price=int(row["price"]),
                    product_type=str(row["product_type"]),
                    menu_status=str(row["menu_status"]),
                )
                for row in cursor.fetchall()
            ]

    def _create_with_conn(self, conn: Connection, product: dict[str, Any]) -> ProductRow:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO product (
                    name,
                    description,
                    image_url,
                    price,
                    product_type,
                    menu_status
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    product["name"],
                    product["description"],
                    product["image_url"],
                    product["price"],
                    product["product_type"],
                    product["menu_status"],
                ),
            )
            product_id = int(cursor.lastrowid)
        created = self.get(product_id, conn)
        if created is None:
            raise RuntimeError(f"created product {product_id} not found")
        return created

    def _update_with_conn(self, conn: Connection, product_id: int, product: dict[str, Any]) -> ProductRow | None:
        if not product:
            return self.get(product_id, conn)
        assignments = ", ".join(f"{field} = %s" for field in product)
        values = [product[field] for field in product]
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE product
                SET {assignments}
                WHERE product_id = %s
                """,
                [*values, product_id],
            )
            if cursor.rowcount == 0 and self.get(product_id, conn) is None:
                return None
        return self.get(product_id, conn)

    def _soft_delete_with_conn(self, conn: Connection, product_id: int) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE product
                SET menu_status = 'PAUSED'
                WHERE product_id = %s
                """,
                (product_id,),
            )
            return cursor.rowcount > 0 or self.get(product_id, conn) is not None


class ProductOptionGroupRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def list_all(self, conn: Connection | None = None) -> list[ProductOptionGroupRow]:
        if conn is not None:
            return self._list_all_with_conn(conn)
        with self.database.connect() as own_conn:
            return self._list_all_with_conn(own_conn)

    def _list_all_with_conn(self, conn: Connection) -> list[ProductOptionGroupRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_option_group_id, product_id, name, options, required, max_select_count
                FROM product_option_group
                ORDER BY product_id, product_option_group_id
                """
            )
            return [
                ProductOptionGroupRow(
                    product_option_group_id=int(row["product_option_group_id"]),
                    product_id=int(row["product_id"]),
                    name=str(row["name"]),
                    options=row["options"],
                    required=bool(row["required"]),
                    max_select_count=int(row["max_select_count"]),
                )
                for row in cursor.fetchall()
            ]


class AllergyCategoryRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def list_all(self, conn: Connection | None = None) -> list[AllergyCategoryRow]:
        if conn is not None:
            return self._list_all_with_conn(conn)
        with self.database.connect() as own_conn:
            return self._list_all_with_conn(own_conn)

    def _list_all_with_conn(self, conn: Connection) -> list[AllergyCategoryRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT allergy_category_id, name, icon
                FROM allergy_category
                ORDER BY allergy_category_id
                """
            )
            return [
                AllergyCategoryRow(
                    allergy_category_id=int(row["allergy_category_id"]),
                    name=str(row["name"]),
                    icon=str(row["icon"]),
                )
                for row in cursor.fetchall()
            ]


class ProductAllergyRepository:
    def __init__(self, database: Database | DbConfig):
        self.database = database if isinstance(database, Database) else Database(database)

    def list_all(self, conn: Connection | None = None) -> list[ProductAllergyRow]:
        if conn is not None:
            return self._list_all_with_conn(conn)
        with self.database.connect() as own_conn:
            return self._list_all_with_conn(own_conn)

    def _list_all_with_conn(self, conn: Connection) -> list[ProductAllergyRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_id, allergy_category_id
                FROM product_allergy
                ORDER BY allergy_category_id, product_id
                """
            )
            return [
                ProductAllergyRow(
                    product_id=int(row["product_id"]),
                    allergy_category_id=int(row["allergy_category_id"]),
                )
                for row in cursor.fetchall()
            ]
