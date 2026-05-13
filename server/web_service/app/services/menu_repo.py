from app.data.seed import ALLERGY, MENU
from app.models.menu import AllergyInfo, MenuItem


def list_menu() -> list[MenuItem]:
    return list(MENU)


def get_menu(menu_id: int) -> MenuItem | None:
    return next((m for m in MENU if m.id == menu_id), None)


def list_allergy() -> list[AllergyInfo]:
    return list(ALLERGY)
