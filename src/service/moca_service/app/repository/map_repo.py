import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pymysql.connections import Connection


@dataclass(frozen=True)
class MapRow:
    map_id: int
    name: str
    image_blob: bytes | None
    image_format: str
    yaml_config: dict[str, Any] | None
    created_at: datetime | None


class MapRepository:
    def list_all(self, conn: Connection) -> list[MapRow]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT map_id, name, image_blob, image_format, yaml_config, created_at
                FROM map
                ORDER BY created_at DESC, map_id DESC
                """
            )
            return [self._to_row(row) for row in cursor.fetchall()]

    def get(self, conn: Connection, map_id: int) -> MapRow | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT map_id, name, image_blob, image_format, yaml_config, created_at
                FROM map
                WHERE map_id = %s
                """,
                (map_id,),
            )
            row = cursor.fetchone()
            return self._to_row(row) if row is not None else None

    def _to_row(self, row) -> MapRow:
        raw_yaml = row.get("yaml_config")
        yaml_config = None
        if isinstance(raw_yaml, str):
            parsed = json.loads(raw_yaml)
            yaml_config = parsed if isinstance(parsed, dict) else None
        elif isinstance(raw_yaml, dict):
            yaml_config = raw_yaml

        return MapRow(
            map_id=int(row["map_id"]),
            name=str(row["name"]),
            image_blob=row.get("image_blob"),
            image_format=str(row.get("image_format") or "pgm"),
            yaml_config=yaml_config,
            created_at=row.get("created_at"),
        )
