import logging
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int
    name: str


class TcpSender:
    def __init__(
        self,
        endpoints: dict[str, TcpEndpoint],
        logger: logging.Logger,
        default_targets: list[str] | None = None,
        timeout: float = 3.0,
    ):
        self.endpoints = endpoints
        self.logger = logger
        self.default_targets = default_targets or list(endpoints)
        self.timeout = timeout

    def send_frame(self, endpoint_name: str, frame: bytes) -> bool:
        endpoint = self.endpoints[endpoint_name]
        try:
            with socket.create_connection(
                (endpoint.host, endpoint.port),
                timeout=self.timeout,
            ) as sock:
                sock.sendall(frame)
        except OSError as exc:
            self.logger.warning(
                "failed to send TCP frame to %s at %s:%s: %s",
                endpoint.name,
                endpoint.host,
                endpoint.port,
                exc,
            )
            return False

        self.logger.info("sent TCP frame to %s size=%s", endpoint.name, len(frame))
        return True

    def broadcast_frame(self, frame: bytes, targets: list[str] | None = None) -> dict[str, bool]:
        selected_targets = targets or self.default_targets
        return {target: self.send_frame(target, frame) for target in selected_targets}


def build_moca_tcp_sender(config, logger: logging.Logger) -> TcpSender:
    endpoints = {
        "AdminGUI": TcpEndpoint(
            host=config.admin_gui_host,
            port=config.admin_gui_port,
            name="AdminGUI",
        ),
        "WebService": TcpEndpoint(
            host=config.web_service_host,
            port=config.web_service_tcp_port,
            name="WebService",
        ),
        "CookingControllerBridge": TcpEndpoint(
            host=config.cooking_controller_bridge_host,
            port=config.cooking_controller_bridge_port,
            name="CookingControllerBridge",
        ),
        "ServingControllerBridge": TcpEndpoint(
            host=config.serving_controller_bridge_host,
            port=config.serving_controller_bridge_port,
            name="ServingControllerBridge",
        ),
    }
    return TcpSender(endpoints, logger, default_targets=list(endpoints))
