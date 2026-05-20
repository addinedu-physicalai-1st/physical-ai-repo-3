from fastapi import APIRouter, HTTPException, Query

from app.models.table import (
    Table,
    TableAssignmentCreate,
    TableAssignmentRequest,
    TableAssignmentResponse,
)
from app.services import table_service
from app.services.table_service import (
    TableAssignmentError,
    TableAssignmentNotFound,
    TableAssignmentRejected,
    TableAssignmentServiceUnavailable,
    TableServiceUnavailable,
)

router = APIRouter(prefix="/api", tags=["tables"])


@router.get("/tables", response_model=list[Table])
def get_tables() -> list[Table]:
    try:
        return table_service.list_tables()
    except TableServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/tables", response_model=TableAssignmentResponse)
def create_table_assignment(
    payload: TableAssignmentRequest,
    table_number: int | None = Query(None, gt=0),
) -> TableAssignmentResponse:
    try:
        table_service.assign(
            TableAssignmentCreate(
                order_id=payload.order_id,
                receive_type=payload.receive_type,
                table_number=payload.table_number if payload.table_number is not None else table_number,
            )
        )
    except TableAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TableAssignmentRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TableAssignmentServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except TableAssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TableAssignmentResponse()
