from typing import Any

from app.config import VisionServiceConfig


class VisionService:
    def __init__(self, config: VisionServiceConfig):
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

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = message.get("type")

        if message_type == "health":
            return self.success_response("health", {"status": "ok"})

        if message_type == "status":
            return self.success_response(
                "status",
                {
                    "role": "Receives hall vision events over UDP and coordinates with ControlService over TCP.",
                    "dependencies": {
                        "control_service": {
                            "host": self.config.control_service_host,
                            "port": self.config.control_service_port,
                        },
                    },
                    "listeners": {
                        "tcp": {"host": self.config.tcp_host, "port": self.config.tcp_port},
                        "udp": {"host": self.config.udp_host, "port": self.config.udp_port},
                    },
                },
            )

        return self.error_response(f"unsupported message type: {message_type}")
