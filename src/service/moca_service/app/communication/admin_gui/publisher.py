import logging
import socket
import threading
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
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> bool:
        if self._sock is not None:
            return True
        try:
            self._sock = socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout)
            return True
        except OSError as exc:
            self.logger.warning(
                "failed to connect admin_gui publisher to %s at %s:%s: %s",
                self.endpoint.name,
                self.endpoint.host,
                self.endpoint.port,
                exc,
            )
            return False

    def publish_frame(self, frame: AdminGuiFrame) -> bool:
        raw = encode_frame(frame)
        with self._lock:
            if not self._connect():
                return False
            try:
                if self._sock:
                    self._sock.sendall(raw)
            except OSError as exc:
                self.logger.warning(
                    "failed to publish admin_gui frame to %s at %s:%s: %s",
                    self.endpoint.name,
                    self.endpoint.host,
                    self.endpoint.port,
                    exc,
                )
                if self._sock:
                    self._sock.close()
                self._sock = None
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

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                self._sock.close()
                self._sock = None
