from dataclasses import dataclass
from typing import Any

from pymysql.connections import Connection


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
    def list_by_status(self, conn: Connection, menu_status: str) -> list[ProductRow]:
        query = """
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE menu_status = %s
            ORDER BY product_id
        """
        return self._fetch_products(query, (menu_status,), conn)

    def list_products(self, conn: Connection, *, include_paused: bool = False) -> list[ProductRow]:
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

    def get(self, conn: Connection, product_id: int) -> ProductRow | None:
        query = """
            SELECT product_id, name, description, image_url, price, product_type, menu_status
            FROM product
            WHERE product_id = %s
        """
        products = self._fetch_products(query, (product_id,), conn)
        return products[0] if products else None

    def create(self, conn: Connection, product: dict[str, Any]) -> ProductRow:
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
        created = self.get(conn, product_id)
        if created is None:
            raise RuntimeError(f"created product {product_id} not found")
        return created

    def update(self, conn: Connection, product_id: int, product: dict[str, Any]) -> ProductRow | None:
        if not product:
            return self.get(conn, product_id)
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
            if cursor.rowcount == 0 and self.get(conn, product_id) is None:
                return None
        return self.get(conn, product_id)

    def soft_delete(self, conn: Connection, product_id: int) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE product
                SET menu_status = 'PAUSED'
                WHERE product_id = %s
                """,
                (product_id,),
            )
            return cursor.rowcount > 0 or self.get(conn, product_id) is not None

    def list_by_ids_and_status(
        self,
        conn: Connection,
        product_ids: list[int],
        menu_status: str,
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

    def _fetch_products(self, query: str, params: list[Any] | tuple[Any, ...], conn: Connection) -> list[ProductRow]:
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


class ProductOptionGroupRepository:
    def list_all(self, conn: Connection) -> list[ProductOptionGroupRow]:
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
    def list_all(self, conn: Connection) -> list[AllergyCategoryRow]:
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
    def list_all(self, conn: Connection) -> list[ProductAllergyRow]:
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
