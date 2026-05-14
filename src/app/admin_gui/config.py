"""Environment-backed configuration for the admin GUI."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AdminGuiConfig:
    host: str = '0.0.0.0'
    port: int = 9000
    business_service_host: str = '127.0.0.1'
    business_service_port: int = 9001
    control_service_host: str = '127.0.0.1'
    control_service_port: int = 9002
    tcp_timeout_sec: float = 3.0


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def load_config() -> AdminGuiConfig:
    return AdminGuiConfig(
        host=os.getenv('ADMIN_GUI_HOST', '0.0.0.0'),
        port=_get_int('ADMIN_GUI_PORT', 9000),
        business_service_host=os.getenv('ADMIN_GUI_BUSINESS_SERVICE_HOST', '127.0.0.1'),
        business_service_port=_get_int('ADMIN_GUI_BUSINESS_SERVICE_PORT', 9001),
        control_service_host=os.getenv('ADMIN_GUI_CONTROL_SERVICE_HOST', '127.0.0.1'),
        control_service_port=_get_int('ADMIN_GUI_CONTROL_SERVICE_PORT', 9002),
        tcp_timeout_sec=_get_float('ADMIN_GUI_TCP_TIMEOUT_SEC', 3.0),
    )
