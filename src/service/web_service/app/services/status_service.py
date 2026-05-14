from typing import Any

from app.config import WebServiceConfig


class StatusService:
    def __init__(self, config: WebServiceConfig):
        self.config = config

    def success_response(self, message_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "type": message_type,
            "service": self.config.service_name,
            "data": data or {},
        }

    def error_response(self, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "service": self.config.service_name,
            "error": message,
        }

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

    def handle_tcp_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = message.get("type")

        if message_type == "health":
            return self.success_response("health", {"status": "ok"})

        if message_type == "status":
            return self.success_response("status", self.status_data())

        return self.error_response(f"unsupported message type: {message_type}")
