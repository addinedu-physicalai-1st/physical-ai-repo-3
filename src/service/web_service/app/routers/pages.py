from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from app.config import ORDER_VUI_DIR, TABLE_GUI_DIR

router = APIRouter(tags=["pages"])


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/kiosk")


@router.get("/kiosk", include_in_schema=False)
def kiosk_page() -> FileResponse:
    return FileResponse(ORDER_VUI_DIR / "kiosk.html")


@router.get("/table", include_in_schema=False)
def table_page() -> FileResponse:
    return FileResponse(TABLE_GUI_DIR / "table.html")
