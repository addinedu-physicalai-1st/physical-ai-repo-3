from typing import Any

from app.models.menu import AllergyInfo, MenuItem
from app.clients.catalog_client import MocaCatalogClientError
from app.clients.moca_shared import get_catalog_client


class MenuServiceUnavailable(RuntimeError):
    pass


class ProductManagementRejected(RuntimeError):
    pass


def manage_product(
    action: str,
    *,
    product_id: int | None = None,
    product: dict[str, Any] | None = None,
    include_paused: bool = False,
) -> dict[str, Any]:
    if action not in {"create", "list", "update", "delete"}:
        raise ProductManagementRejected(f"unsupported product action={action}")
    try:
        return get_catalog_client().manage_product(
            action,
            product_id=product_id,
            product=product,
            include_paused=include_paused,
        )
    except MocaCatalogClientError as exc:
        raise MenuServiceUnavailable(str(exc)) from exc


def create_product(product: dict[str, Any]) -> dict[str, Any]:
    return manage_product("create", product=product)


def list_products(*, include_paused: bool = False) -> dict[str, Any]:
    return manage_product("list", include_paused=include_paused)


def update_product(product_id: int, product: dict[str, Any]) -> dict[str, Any]:
    return manage_product("update", product_id=product_id, product=product)


def delete_product(product_id: int) -> dict[str, Any]:
    return manage_product("delete", product_id=product_id)


def fetch_catalog() -> dict[str, Any]:
    return {
        "menu": [item.model_dump() for item in list_menu()],
        "allergy": [item.model_dump() for item in list_allergy()],
        "surcharges": get_surcharges(),
    }


def list_menu() -> list[MenuItem]:
    return [
        MenuItem(id=1, name="아메리카노", aliases=["아메", "아아", "따아"], emoji="☕", price=3500, hot=True, shot=True, ice=True, milk=False),
        MenuItem(id=2, name="카페라떼", aliases=["라떼"], emoji="☕", price=4500, hot=True, shot=True, ice=True, milk=True),
        MenuItem(id=3, name="카푸치노", aliases=["카푸"], emoji="🫧", price=4500, hot=True, shot=True, ice=False, milk=True),
        MenuItem(id=4, name="바닐라라떼", aliases=["바닐라"], emoji="🌼", price=5000, hot=True, shot=True, ice=True, milk=True),
        MenuItem(id=5, name="카라멜마키아토", aliases=["카라멜", "마키아또"], emoji="🍮", price=5500, hot=True, shot=True, ice=True, milk=True),
        MenuItem(id=6, name="말차라떼", aliases=["말차"], emoji="🍵", price=5500, hot=True, shot=False, ice=True, milk=True),
        MenuItem(id=7, name="딸기스무디", aliases=["딸기"], emoji="🍓", price=6000, hot=False, shot=False, ice=True, milk=False),
        MenuItem(id=8, name="치즈케이크", aliases=["치즈"], emoji="🍰", price=7000, hot=False, shot=False, ice=False, milk=False),
    ]


def get_menu(menu_id: int) -> MenuItem | None:
    return next((m for m in list_menu() if m.id == menu_id), None)


def list_allergy() -> list[AllergyInfo]:
    return [
        AllergyInfo(name="유제품", icon="🥛", items=["카페라떼", "카푸치노", "바닐라라떼", "카라멜마키아토", "말차라떼"]),
        AllergyInfo(name="글루텐", icon="🌾", items=["치즈케이크"]),
        AllergyInfo(name="견과류", icon="🥜", items=["치즈케이크"]),
        AllergyInfo(name="계란", icon="🥚", items=["치즈케이크"]),
        AllergyInfo(name="대두", icon="🌱", items=["말차라떼"]),
        AllergyInfo(name="과일류", icon="🍓", items=["딸기스무디"]),
    ]


def get_surcharges() -> dict[str, int]:
    return {"shot:추가": 500, "milk:저지방": 300}
