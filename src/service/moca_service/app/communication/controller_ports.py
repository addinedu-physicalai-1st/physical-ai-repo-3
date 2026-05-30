import json
import logging
import urllib.request
import urllib.error
from typing import Any, Callable

from app.in_memory.workflow_inmemory_state import ManufactureOrderItem


class LoggingDDoobyManufacturePort:
    """Temporary start-command adapter until the DDooby service API is available."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def start_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        self.logger.info(
            "ddooby manufacture start requested command_id=%s order_id=%s item_count=%s",
            command_id,
            order_id,
            len(order_items),
        )
        return True


class DDoobyActionManufacturePort:
    """Manufacture start-command adapter backed by the DDooby ROS2 action server."""

    def __init__(
        self,
        runtime: Any,
        logger: logging.Logger,
        on_completed: Callable[[int, str], Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.logger = logger
        self._on_completed = on_completed

    def set_completion_callback(self, callback: Callable[[int, str], Any]) -> None:
        self._on_completed = callback

    def start_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        items = self._manufacture_items(order_items)
        self.logger.info(
            "ddooby manufacture action send action=%s command_id=%s order_id=%s items=%s",
            getattr(self.runtime, "action_name", "ddooby/manifacture"),
            command_id,
            order_id,
            items,
        )
        result = self.runtime.request_manufacture(
            command_id=command_id,
            order_id=order_id,
            items=items,
            on_completed=self._on_completed,
        )
        ok = bool(result.get("ok"))
        if not ok:
            self.logger.warning(
                "ddooby manufacture action request failed command_id=%s order_id=%s result=%s",
                command_id,
                order_id,
                result,
            )
        return ok

    @staticmethod
    def _manufacture_items(order_items: list[ManufactureOrderItem]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in order_items:
            name = DDoobyActionManufacturePort._canonical_manufacture_name(item.product_name)
            counts[name] = counts.get(name, 0) + int(item.quantity)
        return [{"name": name, "count": count} for name, count in counts.items()]

    @staticmethod
    def _canonical_manufacture_name(product_name: str) -> str:
        name = product_name.strip()
        lowered = name.lower()
        if lowered in {"hotdog", "hot dog", "new york hotdog", "new york hot dog"}:
            return "hotdog"
        if lowered in {"coke", "cola"}:
            return "coke"
        if lowered == "coffee":
            return "coffee"
        if any(token in name for token in ("핫도그", "뉴욕")):
            return "hotdog"
        if any(token in name for token in ("콜라", "코카콜라")):
            return "coke"
        if "커피" in name:
            return "coffee"
        return lowered


class DobyModeServingPort:
    def __init__(
        self,
        doby_runtime: Any,
        logger: logging.Logger,
        opserver_url: str = "http://localhost:8800",
    ) -> None:
        self.doby_runtime = doby_runtime
        self.logger = logger
        self.opserver_url = opserver_url.rstrip("/")

    def start_serving(
        self,
        command_id: str,
        order_id: int,
        table_number: int | None,
        order_items: list[ManufactureOrderItem] | None = None,
    ) -> bool:
        waypoint = self._table_number_to_waypoint(table_number)
        if waypoint is None:
            self.logger.warning(
                "doby serving start request rejected command_id=%s order_id=%s table_number=%s",
                command_id,
                order_id,
                table_number,
            )
            return False

        has_drink = any(
            item.product_type == 'DRINK' for item in (order_items or [])
        )
        payload = {
            "event_id": f"serving:{command_id}",
            "drink_id": command_id,
            "order_id": str(order_id),
            "target_table": waypoint,
            "via_pickup": True,
            "has_drink": has_drink,
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.opserver_url}/api/v1/pickup",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read())
            ok = data.get("status") == "ok"
        except urllib.error.HTTPError as e:
            self.logger.warning(
                "doby serving start request http error command_id=%s order_id=%s status=%s",
                command_id,
                order_id,
                e.code,
            )
            ok = False
        except Exception as e:
            self.logger.warning(
                "doby serving start request failed command_id=%s order_id=%s error=%s",
                command_id,
                order_id,
                e,
            )
            ok = False

        if not ok:
            self.logger.warning(
                "doby serving start request failed command_id=%s order_id=%s has_drink=%s",
                command_id,
                order_id,
                has_drink,
            )
        else:
            self.logger.info(
                "doby serving start request accepted command_id=%s order_id=%s "
                "waypoint=%s has_drink=%s",
                command_id,
                order_id,
                waypoint,
                has_drink,
            )
        return ok

    @staticmethod
    def _table_number_to_waypoint(table_number: int | None) -> str | None:
        if table_number is None or int(table_number) <= 0:
            return None
        return f"T{int(table_number):02d}"
