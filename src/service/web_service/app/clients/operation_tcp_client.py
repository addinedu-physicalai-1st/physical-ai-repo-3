from typing import Any

from app.clients.base_tcp_client import TcpBaseClient
from app.protocol.health_protocol import HEALTH_CMD, STATUS_CMD, build_frame


class OperationTcpClientError(RuntimeError):
    pass


class OperationTcpClient(TcpBaseClient):
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
            self.send(payload)
        except OSError as exc:
            raise OperationTcpClientError(
                f"operation service tcp request failed: {self.host}:{self.port}: {exc}"
            ) from exc

        return {"ok": True, "type": message_type, "seq": seq}
