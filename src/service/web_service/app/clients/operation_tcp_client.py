import json
import socket
from typing import Any


class OperationTcpClientError(RuntimeError):
    pass


class OperationTcpClient:
    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        payload = (json.dumps(message) + "\n").encode("utf-8")

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                sock.settimeout(self.timeout_sec)
                sock.sendall(payload)
                response = self._read_line(sock)
        except OSError as exc:
            raise OperationTcpClientError(
                f"operation service tcp request failed: {self.host}:{self.port}: {exc}"
            ) from exc

        try:
            decoded = json.loads(response.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OperationTcpClientError(f"invalid operation service json response: {exc.msg}") from exc

        if not isinstance(decoded, dict):
            raise OperationTcpClientError("operation service response must be a JSON object")
        return decoded

    def _read_line(self, sock: socket.socket) -> bytes:
        chunks = bytearray()
        while True:
            chunk = sock.recv(1)
            if not chunk:
                if chunks:
                    break
                raise OperationTcpClientError("operation service closed connection without response")
            chunks.extend(chunk)
            if chunk == b"\n":
                break
        return bytes(chunks)
