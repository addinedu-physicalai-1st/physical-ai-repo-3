import logging
import socket
from dataclasses import dataclass

from app.communication.admin_gui.protocol import AdminGuiFrame, encode_frame


@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int
    name: str = "AdminGUI"


class AdminGuiPublisher:
    def __init__(
        self,
        endpoint: TcpEndpoint,
        logger: logging.Logger,
        *,
        timeout: float = 3.0,
    ) -> None:
        self.endpoint = endpoint
        self.logger = logger
        self.timeout = timeout

    def publish_frame(self, frame: AdminGuiFrame) -> bool:
        raw = encode_frame(frame)
        try:
            with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout) as sock:
                sock.sendall(raw)
        except OSError as exc:
            self.logger.warning(
                "failed to publish admin_gui frame to %s at %s:%s: %s",
                self.endpoint.name,
                self.endpoint.host,
                self.endpoint.port,
                exc,
            )
            return False
        self.logger.info(
            "published admin_gui frame to %s kind=%s topic=%s event=%s correlation_id=%s",
            self.endpoint.name,
            frame.kind,
            frame.topic,
            frame.event,
            frame.correlation_id,
        )
        return True
