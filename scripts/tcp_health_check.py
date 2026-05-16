#!/usr/bin/env python3
"""Send health-check frames to MOCA architecture components."""
import argparse
import os
import socket
import sys
import time
from dataclasses import dataclass
import urllib.error
import urllib.request
from urllib.parse import urlparse

STX = 0x02
HEALTH_CMD = 0x01
STATUS_CMD = 0x10
ETX = 0x03

DEFAULT_ADMIN_GUI_URL = os.getenv("ADMIN_GUI_HEALTH_URL", "tcp://127.0.0.1:9000")
DEFAULT_MOCA_SERVICE_URL = os.getenv("MOCA_SERVICE_HEALTH_URL", "tcp://127.0.0.1:9001")
DEFAULT_MOCA_SERVICE_ROBOT_URL = os.getenv(
    "MOCA_SERVICE_ROBOT_HEALTH_URL",
    "tcp://127.0.0.1:9002",
)
DEFAULT_WEB_SERVICE_HEALTH_URL = os.getenv(
    "WEB_SERVICE_HEALTH_URL",
    "http://127.0.0.1:8000/health",
)
DEFAULT_WEB_SERVICE_TCP_URL = os.getenv("WEB_SERVICE_TCP_HEALTH_URL", "tcp://127.0.0.1:9004")
DEFAULT_VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_HEALTH_URL", "tcp://127.0.0.1:9003")
DEFAULT_TUBI_CONTROLLER_BRIDGE_URL = os.getenv(
    "TUBI_CONTROLLER_BRIDGE_HEALTH_URL",
    "tcp://127.0.0.1:9005",
)
DEFAULT_DOBI_CONTROLLER_BRIDGE_URL = os.getenv(
    "DOBI_CONTROLLER_BRIDGE_HEALTH_URL",
    "tcp://127.0.0.1:9006",
)

CONTROLLER_HEALTH_SERVICES = {
    "tubi_controller": "/tubi_controller/health_check",
    "dobi_controller": "/dobi_controller/health_check",
}

LEGACY_COMPONENT_ALIASES = {
    "business_service": "moca_service",
    "control_service": "moca_service_robot_port",
    "cooking_controller": "tubi_controller",
    "serving_controller": "dobi_controller",
    "table_gui": "web_service_http",
}


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


def build_status_frame(seq: int) -> bytes:
    return bytes([STX, STATUS_CMD, seq & 0xFF, ETX])


def parse_tcp_url(name: str, url: str) -> ComponentEndpoint:
    parsed = urlparse(url)
    if parsed.scheme != "tcp":
        raise TcpHealthCheckError(f"{name}: URL scheme must be tcp: {url}")
    if not parsed.hostname:
        raise TcpHealthCheckError(f"{name}: URL host is required: {url}")
    if parsed.port is None:
        raise TcpHealthCheckError(f"{name}: URL port is required: {url}")
    return ComponentEndpoint(name=name, url=url, host=parsed.hostname, port=parsed.port)


def send_tcp_frame(endpoint: ComponentEndpoint, frame: bytes, timeout_sec: float, label: str) -> None:
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout_sec) as sock:
            sock.settimeout(timeout_sec)
            sock.sendall(frame)
    except OSError as exc:
        raise TcpHealthCheckError(
            f"{endpoint.name}: failed to send {label} to {endpoint.url}: {exc}"
        ) from exc


def send_health(endpoint: ComponentEndpoint, seq: int, timeout_sec: float) -> None:
    send_tcp_frame(endpoint, build_health_frame(seq), timeout_sec, "HEALTH")


def send_status(endpoint: ComponentEndpoint, seq: int, timeout_sec: float) -> None:
    send_tcp_frame(endpoint, build_status_frame(seq), timeout_sec, "STATUS")


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
    parser = argparse.ArgumentParser(description="Send MOCA architecture health checks.")
    parser.add_argument(
        "--component",
        choices=[
            "all",
            "admin_gui",
            "order_vui",
            "web_service",
            "web_service_http",
            "web_service_tcp",
            "moca_service",
            "moca_service_robot_port",
            "voice_service",
            "tubi_controller",
            "dobi_controller",
            "tubi_controller_bridge",
            "dobi_controller_bridge",
            "controller_bridges",
            "controllers",
            "business_service",
            "control_service",
            "cooking_controller",
            "serving_controller",
            "table_gui",
        ],
        default="all",
        help="Component health check to run. Default: all.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TCP_HEALTH_CHECK_TIMEOUT_SEC", "3.0")),
        help="TCP/HTTP/ROS timeout seconds. Default: 3.0",
    )
    return parser.parse_args()


def check_tcp_health(component: str, url: str, timeout_sec: float) -> bool:
    endpoint = parse_tcp_url(component, url)
    try:
        send_health(endpoint, 0, timeout_sec)
    except TcpHealthCheckError as exc:
        print(f"[tcp-health-check] {exc}", flush=True)
        return False

    print(
        f"[tcp-health-check] {component}: sent HEALTH seq=0 to {endpoint.url}",
        flush=True,
    )
    return True


def check_tcp_status(component: str, url: str, timeout_sec: float) -> bool:
    endpoint = parse_tcp_url(component, url)
    try:
        send_status(endpoint, 0, timeout_sec)
    except TcpHealthCheckError as exc:
        print(f"[tcp-health-check] {exc}", flush=True)
        return False

    print(
        f"[tcp-health-check] {component}: sent STATUS seq=0 to {endpoint.url}",
        flush=True,
    )
    return True


def check_http_health(component: str, web_service_url: str, timeout_sec: float) -> bool:
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


def check_controller_health(component: str, timeout_sec: float) -> bool:
    try:
        import rclpy
        from std_srvs.srv import Trigger
    except ImportError as exc:
        print(
            f"[tcp-health-check] {component}: failed to import ROS2 health dependencies: {exc}",
            flush=True,
        )
        return False

    service_name = CONTROLLER_HEALTH_SERVICES[component]
    rclpy.init(args=None)
    node = rclpy.create_node("tcp_health_check_client")
    try:
        client = node.create_client(Trigger, service_name)
        if not client.wait_for_service(timeout_sec=timeout_sec):
            print(
                f"[tcp-health-check] {component}: service unavailable {service_name}",
                flush=True,
            )
            return False

        future = client.call_async(Trigger.Request())
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)

        if not future.done():
            print(
                f"[tcp-health-check] {component}: timed out waiting for {service_name}",
                flush=True,
            )
            return False

        response = future.result()
        if response is None:
            print(
                f"[tcp-health-check] {component}: service call failed {service_name}",
                flush=True,
            )
            return False

        if not response.success:
            print(
                f"[tcp-health-check] {component}: health check failed: {response.message}",
                flush=True,
            )
            return False

        print(
            f"[tcp-health-check] {component}: {service_name} success: {response.message}",
            flush=True,
        )
        return True
    finally:
        node.destroy_node()
        rclpy.shutdown()


def check_controllers(timeout_sec: float) -> bool:
    return all(
        check_controller_health(component, timeout_sec)
        for component in ("tubi_controller", "dobi_controller")
    )


def check_controller_bridges(timeout_sec: float) -> bool:
    return all(
        [
            check_tcp_status(
                "tubi_controller_bridge",
                DEFAULT_TUBI_CONTROLLER_BRIDGE_URL,
                timeout_sec,
            ),
            check_tcp_status(
                "dobi_controller_bridge",
                DEFAULT_DOBI_CONTROLLER_BRIDGE_URL,
                timeout_sec,
            ),
        ]
    )


def main() -> int:
    args = parse_args()
    component = LEGACY_COMPONENT_ALIASES.get(args.component, args.component)

    checks = {
        "admin_gui": lambda: check_tcp_health("admin_gui", DEFAULT_ADMIN_GUI_URL, args.timeout),
        "order_vui": lambda: all(
            [
                check_http_health("order_vui_http", DEFAULT_WEB_SERVICE_HEALTH_URL, args.timeout),
                check_tcp_health("order_vui_voice_tcp", DEFAULT_VOICE_SERVICE_URL, args.timeout),
            ]
        ),
        "web_service": lambda: all(
            [
                check_http_health("web_service_http", DEFAULT_WEB_SERVICE_HEALTH_URL, args.timeout),
                check_tcp_health("web_service_tcp", DEFAULT_WEB_SERVICE_TCP_URL, args.timeout),
            ]
        ),
        "web_service_http": lambda: check_http_health(
            "web_service_http",
            DEFAULT_WEB_SERVICE_HEALTH_URL,
            args.timeout,
        ),
        "web_service_tcp": lambda: check_tcp_health(
            "web_service_tcp",
            DEFAULT_WEB_SERVICE_TCP_URL,
            args.timeout,
        ),
        "moca_service": lambda: check_tcp_health(
            "moca_service",
            DEFAULT_MOCA_SERVICE_URL,
            args.timeout,
        ),
        "moca_service_robot_port": lambda: check_tcp_health(
            "moca_service_robot_port",
            DEFAULT_MOCA_SERVICE_ROBOT_URL,
            args.timeout,
        ),
        "voice_service": lambda: check_tcp_health(
            "voice_service",
            DEFAULT_VOICE_SERVICE_URL,
            args.timeout,
        ),
        "tubi_controller": lambda: check_controller_health("tubi_controller", args.timeout),
        "dobi_controller": lambda: check_controller_health("dobi_controller", args.timeout),
        "tubi_controller_bridge": lambda: check_tcp_status(
            "tubi_controller_bridge",
            DEFAULT_TUBI_CONTROLLER_BRIDGE_URL,
            args.timeout,
        ),
        "dobi_controller_bridge": lambda: check_tcp_status(
            "dobi_controller_bridge",
            DEFAULT_DOBI_CONTROLLER_BRIDGE_URL,
            args.timeout,
        ),
        "controller_bridges": lambda: check_controller_bridges(args.timeout),
        "controllers": lambda: check_controllers(args.timeout),
    }

    if component == "all":
        results = [
            checks[name]()
            for name in (
                "admin_gui",
                "order_vui",
                "web_service",
                "moca_service",
                "moca_service_robot_port",
            )
        ]
        return 0 if all(results) else 1

    return 0 if checks[component]() else 1


if __name__ == "__main__":
    sys.exit(main())
