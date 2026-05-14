#!/usr/bin/env python3
"""Send HEALTH checks to test-entry components."""
import argparse
import os
import socket
import sys
from dataclasses import dataclass
import urllib.error
import urllib.request
from urllib.parse import urlparse

STX = 0x02
HEALTH_CMD = 0x01
ETX = 0x03

DEFAULT_ADMIN_GUI_URL = "tcp://127.0.0.1:9000"
DEFAULT_WEB_SERVICE_HEALTH_URL = "http://127.0.0.1:8000/health"


class TcpHealthCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComponentEndpoint:
    name: str
    url: str
    host: str
    port: int


def build_health_frame(seq: int) -> bytes:
    return bytes([STX, HEALTH_CMD, seq & 0xFF, ETX])


def parse_tcp_url(name: str, url: str) -> ComponentEndpoint:
    parsed = urlparse(url)
    if parsed.scheme != "tcp":
        raise TcpHealthCheckError(f"{name}: URL scheme must be tcp: {url}")
    if not parsed.hostname:
        raise TcpHealthCheckError(f"{name}: URL host is required: {url}")
    if parsed.port is None:
        raise TcpHealthCheckError(f"{name}: URL port is required: {url}")
    return ComponentEndpoint(name=name, url=url, host=parsed.hostname, port=parsed.port)


def send_health(endpoint: ComponentEndpoint, seq: int, timeout_sec: float) -> None:
    frame = build_health_frame(seq)
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout_sec) as sock:
            sock.settimeout(timeout_sec)
            sock.sendall(frame)
    except OSError as exc:
        raise TcpHealthCheckError(
            f"{endpoint.name}: failed to send HEALTH to {endpoint.url}: {exc}"
        ) from exc


def send_http_health(name: str, url: str, timeout_sec: float) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            response.read()
            return response.status
    except (OSError, urllib.error.URLError) as exc:
        raise TcpHealthCheckError(
            f"{name}: failed to call HTTP health endpoint {url}: {exc}"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send HEALTH checks.")
    parser.add_argument(
        "--component",
        choices=["all", "admin_gui", "order_gui", "table_gui"],
        default="all",
        help="Component health check to run. Default: all.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TCP_HEALTH_CHECK_TIMEOUT_SEC", "3.0")),
        help="TCP connect/send timeout seconds. Default: 3.0",
    )
    return parser.parse_args()


def check_admin_gui(admin_gui_url: str, timeout_sec: float) -> bool:
    endpoint = parse_tcp_url("admin_gui", admin_gui_url)
    try:
        send_health(endpoint, 0, timeout_sec)
    except TcpHealthCheckError as exc:
        print(f"[tcp-health-check] {exc}", flush=True)
        return False

    print(
        f"[tcp-health-check] admin_gui: sent HEALTH seq=0 to {endpoint.url}",
        flush=True,
    )
    return True


def check_gui_http(component: str, web_service_url: str, timeout_sec: float) -> bool:
    try:
        status = send_http_health(component, web_service_url, timeout_sec)
    except TcpHealthCheckError as exc:
        print(f"[tcp-health-check] {exc}", flush=True)
        return False

    print(
        f"[tcp-health-check] {component}: HTTP /health status={status} url={web_service_url}",
        flush=True,
    )
    return True


def main() -> int:
    args = parse_args()

    checks = {
        "admin_gui": lambda: check_admin_gui(DEFAULT_ADMIN_GUI_URL, args.timeout),
        "order_gui": lambda: check_gui_http("order_gui", DEFAULT_WEB_SERVICE_HEALTH_URL, args.timeout),
        "table_gui": lambda: check_gui_http("table_gui", DEFAULT_WEB_SERVICE_HEALTH_URL, args.timeout),
    }

    if args.component == "all":
        results = [checks[name]() for name in ("admin_gui", "order_gui", "table_gui")]
        return 0 if all(results) else 1

    return 0 if checks[args.component]() else 1


if __name__ == "__main__":
    sys.exit(main())
