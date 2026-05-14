import socket
from typing import Any

from app.protocol.tcp_frame import HEALTH_CMD, STATUS_CMD, build_frame


class OperationTcpClientError(RuntimeError):
    pass


class OperationTcpClient:
    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = message.get("type")
        seq = int(message.get("seq", 0))

        if message_type == "health":
            cmd = HEALTH_CMD
        elif message_type == "status":
            cmd = STATUS_CMD
        else:
            raise OperationTcpClientError(f"unsupported operation service message type: {message_type}")

        payload = build_frame(cmd, seq)

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                sock.settimeout(self.timeout_sec)
                sock.sendall(payload)
        except OSError as exc:
            raise OperationTcpClientError(
                f"operation service tcp request failed: {self.host}:{self.port}: {exc}"
            ) from exc

        return {"ok": True, "type": message_type, "seq": seq}
