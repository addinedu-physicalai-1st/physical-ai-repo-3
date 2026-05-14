import logging
from typing import Any

from app.config import WebServiceConfig
from app.protocol.tcp_frame import HEALTH_CMD, STATUS_CMD


class StatusService:
    def __init__(self, config: WebServiceConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(config.service_name)

    def status_data(self) -> dict[str, Any]:
        return {
            "role": "Accepts HTTP requests from app clients and communicates with OperationService over TCP.",
            "dependencies": {
                "operation_service": {
                    "host": self.config.operation_service_host,
                    "port": self.config.operation_service_port,
                },
            },
            "listeners": {
                "http": {"host": self.config.http_host, "port": self.config.http_port},
                "tcp": {"host": self.config.tcp_host, "port": self.config.tcp_port},
            },
            "http_routes": [
                "/",
                "/kiosk",
                "/table",
                "/api/menu",
                "/api/allergy",
                "/api/tables",
                "/api/orders",
                "/api/orders/{order_id}",
            ],
        }

    def handle_tcp_frame(self, cmd: int, seq: int, peer: tuple[str, int]) -> None:
        if cmd == HEALTH_CMD:
            self.logger.info("health frame accepted seq=%s status=ok", seq)
            return

        if cmd == STATUS_CMD:
            self.logger.info("received STATUS probe from %s seq=%s", peer, seq)
