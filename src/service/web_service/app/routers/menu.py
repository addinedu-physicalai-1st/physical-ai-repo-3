from fastapi import APIRouter, HTTPException

from app.models.menu import AllergyInfo, MenuItem
from app.services import menu_service
from app.services.menu_service import MenuServiceUnavailable

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu", response_model=list[MenuItem])
def get_menu() -> list[MenuItem]:
    try:
        return menu_service.list_menu()
    except MenuServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/allergy", response_model=list[AllergyInfo])
def get_allergy() -> list[AllergyInfo]:
    try:
        return menu_service.list_allergy()
    except MenuServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
