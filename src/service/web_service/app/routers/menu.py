from fastapi import APIRouter

from app.models.menu import AllergyInfo, MenuItem
from app.services import menu_repo

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu", response_model=list[MenuItem])
def get_menu() -> list[MenuItem]:
    return menu_repo.list_menu()


@router.get("/allergy", response_model=list[AllergyInfo])
def get_allergy() -> list[AllergyInfo]:
    return menu_repo.list_allergy()
