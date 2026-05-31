#!/usr/bin/env python3
"""Apply maps from the upper controller to the local Nav2 map server."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import rclpy
from dobi_npc_msgs.srv import ApplyMap
from nav2_msgs.srv import LoadMap
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


class NavMapApplyAdapterNode(Node):
    def __init__(self) -> None:
        super().__init__("nav_map_apply_adapter")
        self.declare_parameter(
            "active_map_dir",
            os.path.expanduser("~/.moca/doby/maps/active"),
        )
        self.declare_parameter("load_map_timeout_sec", 5.0)
        self._callback_group = ReentrantCallbackGroup()
        self._load_map_client = self.create_client(
            LoadMap,
            "/map_server/load_map",
            callback_group=self._callback_group,
        )
        self._service = self.create_service(
            ApplyMap,
            "/map/apply",
            self._on_apply_map,
            callback_group=self._callback_group,
        )
        self.get_logger().info("nav_map_apply_adapter ready: service=/map/apply")

    def _on_apply_map(self, request: ApplyMap.Request, response: ApplyMap.Response):
        try:
            yaml_config = _json_object(request.yaml_config_json, "yaml_config_json")
            tables = _json_array(request.tables_json, "tables_json")
            image_ext = _sanitize_image_format(request.image_format)
            image_data = bytes(request.image_data)
            if not image_data:
                raise ValueError("image_data is empty")

            active_dir = Path(
                self.get_parameter("active_map_dir").get_parameter_value().string_value
            ).expanduser()
            map_yaml = self._materialize_map(
                active_dir=active_dir,
                image_ext=image_ext,
                image_data=image_data,
                yaml_config=yaml_config,
                tables=tables,
                map_id=int(request.map_id),
                map_name=str(request.map_name),
            )
            load_result = self._load_map(map_yaml)
            if not load_result[0]:
                response.success = False
                response.applied_map_path = str(map_yaml)
                response.reason = load_result[1]
                return response

            response.success = True
            response.applied_map_path = str(map_yaml)
            response.reason = "applied"
            return response
        except Exception as exc:
            response.success = False
            response.applied_map_path = ""
            response.reason = str(exc)
            self.get_logger().warning("map apply failed: %s", exc)
            return response

    def _materialize_map(
        self,
        *,
        active_dir: Path,
        image_ext: str,
        image_data: bytes,
        yaml_config: dict[str, Any],
        tables: list[Any],
        map_id: int,
        map_name: str,
    ) -> Path:
        _validate_yaml_config(yaml_config)
        parent = active_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix=".nav_map_apply_", dir=str(parent)))
        try:
            image_name = f"map.{image_ext}"
            (tmp_dir / image_name).write_bytes(image_data)
            (tmp_dir / "map.yaml").write_text(
                _render_map_yaml(image_name, yaml_config),
                encoding="utf-8",
            )
            (tmp_dir / "tables.json").write_text(
                json.dumps(tables, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            (tmp_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "map_id": map_id,
                        "map_name": map_name,
                        "applied_at": time.time(),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            backup_dir = parent / f".active_backup_{int(time.time() * 1000)}"
            if active_dir.exists():
                active_dir.replace(backup_dir)
            tmp_dir.replace(active_dir)
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
        except Exception:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            raise
        return active_dir / "map.yaml"

    def _load_map(self, map_yaml: Path) -> tuple[bool, str]:
        timeout = float(
            self.get_parameter("load_map_timeout_sec").get_parameter_value().double_value
        )
        if not self._load_map_client.wait_for_service(timeout_sec=timeout):
            return False, "/map_server/load_map service unavailable"

        request = LoadMap.Request()
        request.map_url = str(map_yaml)
        future = self._load_map_client.call_async(request)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if future.done():
                break
            time.sleep(0.02)
        if not future.done():
            return False, "/map_server/load_map timed out"

        result = future.result()
        if result is None:
            return False, "/map_server/load_map returned no response"
        success_code = getattr(result, "RESULT_SUCCESS", 0)
        if int(result.result) != int(success_code):
            return False, f"/map_server/load_map failed result={result.result}"
        return True, "loaded"


def _json_object(raw: str, field: str) -> dict[str, Any]:
    parsed = json.loads(raw or "{}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object")
    return parsed


def _json_array(raw: str, field: str) -> list[Any]:
    parsed = json.loads(raw or "[]")
    if not isinstance(parsed, list):
        raise ValueError(f"{field} must be a JSON array")
    return parsed


def _sanitize_image_format(value: str) -> str:
    ext = (value or "pgm").strip().lower().lstrip(".")
    if ext not in {"pgm", "png"}:
        raise ValueError("image_format must be pgm or png")
    return ext


def _validate_yaml_config(config: dict[str, Any]) -> None:
    required = ["resolution", "origin", "negate", "occupied_thresh", "free_thresh"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"yaml_config missing required keys: {', '.join(missing)}")
    origin = config["origin"]
    if not isinstance(origin, list) or len(origin) != 3:
        raise ValueError("yaml_config.origin must be a 3-element list")


def _render_map_yaml(image_name: str, config: dict[str, Any]) -> str:
    lines = [
        f"image: {image_name}",
        f"resolution: {float(config['resolution'])}",
        f"origin: [{float(config['origin'][0])}, {float(config['origin'][1])}, {float(config['origin'][2])}]",
        f"negate: {int(config['negate'])}",
        f"occupied_thresh: {float(config['occupied_thresh'])}",
        f"free_thresh: {float(config['free_thresh'])}",
    ]
    mode = config.get("mode")
    if mode:
        lines.append(f"mode: {mode}")
    return "\n".join(lines) + "\n"


def main() -> None:
    rclpy.init()
    node = NavMapApplyAdapterNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
