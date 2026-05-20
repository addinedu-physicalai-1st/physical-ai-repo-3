from app.models.table_assignment import TableAssignmentCreate


class TableAssignmentError(Exception):
    pass


class TableAssignmentNotFound(TableAssignmentError):
    pass


class TableAssignmentRejected(TableAssignmentError):
    pass


class TableAssignmentServiceUnavailable(TableAssignmentError):
    pass


def assign(payload: TableAssignmentCreate) -> None:
    if payload.receive_type == "dine_in" and payload.table_id is None:
        raise TableAssignmentError("table_id is required for dine_in")
    if payload.receive_type == "dine_in" and payload.table_id <= 0:
        raise TableAssignmentError("table_id must be greater than 0 for dine_in")
    if payload.receive_type == "take_out" and payload.table_id is not None and payload.table_id < 0:
        raise TableAssignmentError("table_id must be greater than or equal to 0")
