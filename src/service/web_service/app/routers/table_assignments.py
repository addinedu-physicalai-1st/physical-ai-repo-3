from fastapi import APIRouter, HTTPException

from app.models.table_assignment import TableAssignmentCreate, TableAssignmentResponse
from app.services import table_assignment_service
from app.services.table_assignment_service import (
    TableAssignmentError,
    TableAssignmentNotFound,
    TableAssignmentRejected,
    TableAssignmentServiceUnavailable,
)

router = APIRouter(prefix="/api/table-assignments", tags=["table-assignments"])


@router.post("", response_model=TableAssignmentResponse)
def create_table_assignment(payload: TableAssignmentCreate) -> TableAssignmentResponse:
    try:
        table_assignment_service.assign(payload)
    except TableAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TableAssignmentRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TableAssignmentServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except TableAssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TableAssignmentResponse()
