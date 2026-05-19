from fastapi import APIRouter, HTTPException

from app.models.table import Table
from app.services import table_service
from app.services.table_service import TableServiceUnavailable

router = APIRouter(prefix="/api", tags=["tables"])


@router.get("/tables", response_model=list[Table])
def get_tables() -> list[Table]:
    try:
        return table_service.list_tables()
    except TableServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
