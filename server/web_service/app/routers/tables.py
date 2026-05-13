from fastapi import APIRouter

from app.models.table import Table
from app.services import table_repo

router = APIRouter(prefix="/api", tags=["tables"])


@router.get("/tables", response_model=list[Table])
def get_tables() -> list[Table]:
    return table_repo.list_tables()
