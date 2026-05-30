import time
from dataclasses import asdict, dataclass
from threading import RLock


@dataclass
class ActiveMapRuntimeSnapshot:
    active_map_id: int | None = None
    applied_map_id: int | None = None
    apply_status: str = "idle"
    last_error: str | None = None
    updated_at: float = 0.0


class ActiveMapRuntimeState:
    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot = ActiveMapRuntimeSnapshot(updated_at=time.time())

    def snapshot(self) -> dict:
        with self._lock:
            return asdict(self._snapshot)

    def applying(self, map_id: int) -> dict:
        with self._lock:
            self._snapshot.active_map_id = map_id
            self._snapshot.apply_status = "applying"
            self._snapshot.last_error = None
            self._snapshot.updated_at = time.time()
            return asdict(self._snapshot)

    def applied(self, map_id: int) -> dict:
        with self._lock:
            self._snapshot.active_map_id = map_id
            self._snapshot.applied_map_id = map_id
            self._snapshot.apply_status = "applied"
            self._snapshot.last_error = None
            self._snapshot.updated_at = time.time()
            return asdict(self._snapshot)

    def failed(self, map_id: int, error: str) -> dict:
        with self._lock:
            self._snapshot.active_map_id = map_id
            self._snapshot.apply_status = "failed"
            self._snapshot.last_error = error
            self._snapshot.updated_at = time.time()
            return asdict(self._snapshot)
