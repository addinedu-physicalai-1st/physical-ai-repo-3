import threading

from app.data.seed import INITIAL_TABLE_STATUS
from app.models.table import Table, TableStatus

_lock = threading.Lock()
_status: list[TableStatus] = []


def reset() -> None:
    global _status
    with _lock:
        _status = list(INITIAL_TABLE_STATUS)


def list_tables() -> list[Table]:
    with _lock:
        return [Table(id=i + 1, status=s) for i, s in enumerate(_status)]


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


reset()
