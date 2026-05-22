import logging
from typing import Any

from app.domain.order_orchestration_runtime import ManufactureOrderItem


class LoggingDDoobyManufacturePort:
    """Temporary queue-registration adapter until the DDooby service API is available."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._registered: set[str] = set()

    def enqueue_manufacture(
        self,
        command_id: str,
        order_id: int,
        order_items: list[ManufactureOrderItem],
    ) -> bool:
        if command_id in self._registered:
            return True
        self._registered.add(command_id)
        self.logger.info(
            "ddooby manufacture queue registered command_id=%s order_id=%s item_count=%s",
            command_id,
            order_id,
            len(order_items),
        )
        return True


class DobyModeServingPort:
    def __init__(self, doby_runtime: Any, logger: logging.Logger) -> None:
        self.doby_runtime = doby_runtime
        self.logger = logger
        self._registered: set[str] = set()

    def enqueue_serving(self, command_id: str, order_id: int, table_number: int | None) -> bool:
        if command_id in self._registered:
            return True
        result = self.doby_runtime.request_mode_change(
            "serving",
            {"command_id": command_id, "order_id": order_id, "table_number": table_number},
        )
        ok = bool(result.get("ok"))
        if ok:
            self._registered.add(command_id)
        else:
            self.logger.warning(
                "doby serving queue registration failed command_id=%s order_id=%s result=%s",
                command_id,
                order_id,
                result,
            )
        return ok
