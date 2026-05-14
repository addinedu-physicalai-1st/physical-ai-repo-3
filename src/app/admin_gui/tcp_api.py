"""Line-delimited JSON TCP client helpers for backend services."""
import json
import socket
from typing import Any

from config import AdminGuiConfig, load_config


class TcpApiError(RuntimeError):
    """Raised when a TCP API request cannot complete successfully."""


class TcpApiClient:
    def __init__(self, config: AdminGuiConfig | None = None):
        self.config = config or load_config()

    def request(self, host: str, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        body = (json.dumps(payload) + '\n').encode('utf-8')
        try:
            with socket.create_connection(
                (host, port),
                timeout=self.config.tcp_timeout_sec,
            ) as sock:
                sock.settimeout(self.config.tcp_timeout_sec)
                sock.sendall(body)
                response = self._readline(sock)
        except OSError as exc:
            raise TcpApiError(f'tcp request failed: {host}:{port}: {exc}') from exc

        try:
            return json.loads(response.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise TcpApiError(f'invalid json response: {exc.msg}') from exc

    def health(self, service: str) -> dict[str, Any]:
        host, port = self._service_endpoint(service)
        return self.request(host, port, {'type': 'health'})

    def status(self, service: str) -> dict[str, Any]:
        host, port = self._service_endpoint(service)
        return self.request(host, port, {'type': 'status'})

    def _service_endpoint(self, service: str) -> tuple[str, int]:
        endpoints = {
            'business': (
                self.config.business_service_host,
                self.config.business_service_port,
            ),
            'control': (
                self.config.control_service_host,
                self.config.control_service_port,
            ),
        }
        try:
            return endpoints[service]
        except KeyError as exc:
            raise ValueError(f'unknown service: {service}') from exc

    @staticmethod
    def _readline(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(1)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk == b'\n':
                break
        if not chunks:
            raise TcpApiError('empty tcp response')
        return b''.join(chunks)
