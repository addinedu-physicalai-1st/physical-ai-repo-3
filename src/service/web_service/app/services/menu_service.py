from typing import Any

from app.data.seed import DUMMY_CATALOG
from app.models.menu import AllergyInfo, MenuItem

class MenuServiceUnavailable(RuntimeError):
    pass


def fetch_catalog() -> dict[str, Any]:
    return DUMMY_CATALOG


def list_menu() -> list[MenuItem]:
    catalog = fetch_catalog()
    return [MenuItem.model_validate(item) for item in catalog.get("menu", [])]


def get_menu(menu_id: int) -> MenuItem | None:
    return next((m for m in list_menu() if m.id == menu_id), None)


def list_allergy() -> list[AllergyInfo]:
    catalog = fetch_catalog()
    return [AllergyInfo.model_validate(item) for item in catalog.get("allergy", [])]


def get_surcharges() -> dict[str, int]:
    catalog = fetch_catalog()
    return {str(key): int(value) for key, value in catalog.get("surcharges", {}).items()}
