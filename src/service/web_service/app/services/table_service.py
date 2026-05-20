import threading

from app.models.table import Table, TableStatus

_INITIAL_TABLE_STATUS: list[TableStatus] = [
    "empty", "occupied", "empty", "occupied",
]

_lock = threading.Lock()
_status: list[TableStatus] = []


class TableServiceUnavailable(RuntimeError):
    pass


def reset() -> None:
    global _status
    with _lock:
        _status = list(_INITIAL_TABLE_STATUS)


def list_tables() -> list[Table]:
    with _lock:
        return [Table(id=index + 1, status=status) for index, status in enumerate(_status)]


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


reset()
