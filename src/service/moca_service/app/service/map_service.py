import json
from decimal import Decimal
from typing import Any

from app.in_memory.map_runtime_state import ActiveMapRuntimeState
from app.repository.db import Database
from app.repository.map_repo import MapRepository, MapRow
from app.repository.table_repo import TableRepository


class MapService:
    def __init__(
        self,
        database: Database,
        map_repository: MapRepository,
        table_repository: TableRepository,
        runtime_state: ActiveMapRuntimeState,
        doby_runtime,
        logger,
    ) -> None:
        self.database = database
        self.map_repository = map_repository
        self.table_repository = table_repository
        self.runtime_state = runtime_state
        self.doby_runtime = doby_runtime
        self.logger = logger

    def get_snapshot(self) -> dict[str, Any]:
        with self.database.connect() as conn:
            maps = self.map_repository.list_all(conn)
        state = self.runtime_state.snapshot()
        return {
            "state": state,
            "maps": [self._map_summary(row, state) for row in maps],
        }

    def apply_map(self, map_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = self.map_repository.get(conn, map_id)
            if row is None:
                return {
                    "ok": False,
                    "code": "MAP_NOT_FOUND",
                    "message": f"map_id={map_id} not found",
                    "state": self.runtime_state.failed(map_id, "map not found"),
                }
            tables = self.table_repository.list_by_map_id(conn, map_id)

        validation_error = self._validate_map(row)
        if validation_error:
            return {
                "ok": False,
                "code": "INVALID_MAP",
                "message": validation_error,
                "state": self.runtime_state.failed(map_id, validation_error),
            }

        self.runtime_state.applying(map_id)
        tables_payload = [
            {
                "table_id": table.table_id,
                "table_number": table.table_number,
                "pos_x": float(table.pos_x),
                "pos_y": float(table.pos_y),
            }
            for table in tables
        ]
        result = self.doby_runtime.apply_map(
            map_id=row.map_id,
            map_name=row.name,
            image_format=row.image_format,
            image_data=row.image_blob or b"",
            yaml_config=row.yaml_config or {},
            tables=tables_payload,
        )
        ok = bool(result.get("ok"))
        if ok:
            state = self.runtime_state.applied(map_id)
        else:
            state = self.runtime_state.failed(
                map_id,
                str(result.get("message") or result.get("reason") or "map apply failed"),
            )
        return {
            **result,
            "ok": ok,
            "state": state,
        }

    def _map_summary(self, row: MapRow, state: dict[str, Any]) -> dict[str, Any]:
        yaml_config = row.yaml_config or {}
        return {
            "map_id": row.map_id,
            "name": row.name,
            "image_format": row.image_format,
            "has_image": bool(row.image_blob),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "resolution": yaml_config.get("resolution"),
            "origin": yaml_config.get("origin"),
            "active": state.get("active_map_id") == row.map_id,
            "applied": state.get("applied_map_id") == row.map_id,
        }

    @staticmethod
    def _validate_map(row: MapRow) -> str | None:
        if not row.image_blob:
            return "map image_blob is empty"
        if not row.yaml_config:
            return "yaml_config is empty"
        required = {"resolution", "origin", "negate", "occupied_thresh", "free_thresh"}
        missing = sorted(required - set(row.yaml_config))
        if missing:
            return f"yaml_config missing required keys: {', '.join(missing)}"
        origin = row.yaml_config.get("origin")
        if not isinstance(origin, list) or len(origin) != 3:
            return "yaml_config.origin must be a 3-element list"
        return None


def map_payload(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default).encode(
        "utf-8"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")
