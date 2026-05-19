import threading

from app.clients.moca_shared import get_table_client
from app.clients.moca_tcp_client import MocaTableClientError
from app.data.seed import INITIAL_TABLE_STATUS
from app.models.table import Table, TableStatus

_lock = threading.Lock()
_status: list[TableStatus] = []
_table_client = get_table_client()


class TableServiceUnavailable(RuntimeError):
    pass


def set_table_client(client) -> None:
    global _table_client
    _table_client = client


def reset() -> None:
    global _status
    with _lock:
        _status = list(INITIAL_TABLE_STATUS)


def list_tables() -> list[Table]:
    try:
        return [Table.model_validate(table) for table in _table_client.fetch_tables()]
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


reset()
