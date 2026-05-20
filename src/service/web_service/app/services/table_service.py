import threading

from app.models.table import Table, TableStatus, TableAssignmentCreate
from app.clients.moca_shared import get_table_client
from app.clients.table_client import (
    MocaTableAssignmentNotFound,
    MocaTableAssignmentRejected,
    MocaTableClientError,
)

_INITIAL_TABLE_STATUS: list[TableStatus] = [
    "empty", "occupied", "empty", "occupied",
]

_lock = threading.Lock()
_status: list[TableStatus] = []


class TableServiceUnavailable(RuntimeError):
    pass


class TableAssignmentError(Exception):
    pass


class TableAssignmentNotFound(TableAssignmentError):
    pass


class TableAssignmentRejected(TableAssignmentError):
    pass


class TableAssignmentServiceUnavailable(TableAssignmentError):
    pass


def reset() -> None:
    global _status
    with _lock:
        _status = list(_INITIAL_TABLE_STATUS)


def list_tables() -> list[Table]:
    try:
        return [Table(id=int(table["id"]), status=table["status"]) for table in get_table_client().fetch_tables()]
    except MocaTableClientError as exc:
        raise TableServiceUnavailable(str(exc)) from exc


def get_status(table_no: int) -> TableStatus | None:
    if not 1 <= table_no <= len(_status):
        return None
    with _lock:
        return _status[table_no - 1]


def occupy(table_no: int) -> bool:
    """Mark table occupied. Returns False if invalid or already occupied."""
    with _lock:
        if not 1 <= table_no <= len(_status):
            return False
        if _status[table_no - 1] == "occupied":
            return False
        _status[table_no - 1] = "occupied"
        return True


def release(table_no: int) -> bool:
    with _lock:
        if not 1 <= table_no <= len(_status):
            return False
        _status[table_no - 1] = "empty"
        return True


def assign(payload: TableAssignmentCreate) -> None:
    if payload.receive_type == "dine_in" and payload.table_number is None:
        raise TableAssignmentError("table_number is required for dine_in")
    if payload.receive_type == "dine_in" and payload.table_number <= 0:
        raise TableAssignmentError("table_number must be greater than 0 for dine_in")
    if payload.receive_type == "take_out" and payload.table_number is not None and payload.table_number < 0:
        raise TableAssignmentError("table_number must be greater than or equal to 0")

    try:
        get_table_client().assign_table(payload.order_id, payload.receive_type, payload.table_number)
    except MocaTableAssignmentNotFound as exc:
        raise TableAssignmentNotFound(str(exc)) from exc
    except MocaTableAssignmentRejected as exc:
        raise TableAssignmentRejected(str(exc)) from exc
    except MocaTableClientError as exc:
        raise TableAssignmentServiceUnavailable(str(exc)) from exc


reset()
