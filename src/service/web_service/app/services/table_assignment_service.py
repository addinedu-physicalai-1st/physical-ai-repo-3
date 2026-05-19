from app.clients.moca_shared import get_table_client
from app.clients.moca_tcp_client import (
    MocaTableAssignmentNotFound,
    MocaTableAssignmentRejected,
    MocaTableClientError,
)
from app.models.table_assignment import TableAssignmentCreate

_table_client = get_table_client()


class TableAssignmentError(Exception):
    pass


class TableAssignmentNotFound(TableAssignmentError):
    pass


class TableAssignmentRejected(TableAssignmentError):
    pass


class TableAssignmentServiceUnavailable(TableAssignmentError):
    pass


def set_table_client(client) -> None:
    global _table_client
    _table_client = client


def assign(payload: TableAssignmentCreate) -> None:
    if payload.receive_type == "dine_in" and payload.table_id is None:
        raise TableAssignmentError("table_id is required for dine_in")
    if payload.receive_type == "dine_in" and payload.table_id <= 0:
        raise TableAssignmentError("table_id must be greater than 0 for dine_in")
    if payload.receive_type == "take_out" and payload.table_id is not None and payload.table_id < 0:
        raise TableAssignmentError("table_id must be greater than or equal to 0")
    try:
        _table_client.assign_table(payload.order_id, payload.receive_type, payload.table_id)
    except MocaTableAssignmentNotFound as exc:
        raise TableAssignmentNotFound(str(exc)) from exc
    except MocaTableAssignmentRejected as exc:
        raise TableAssignmentRejected(str(exc)) from exc
    except MocaTableClientError as exc:
        raise TableAssignmentServiceUnavailable(str(exc)) from exc
