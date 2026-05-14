import logging
import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[0]
PROJECT_ROOT = REPO_ROOT if (REPO_ROOT / "ui").exists() else SERVICE_DIR
UI_ROOT = PROJECT_ROOT / "ui"
ORDER_VUI_DIR = UI_ROOT / "order_vui"
TABLE_GUI_DIR = UI_ROOT / "table_gui"


@dataclass(frozen=True)
class WebServiceConfig:
    service_name: str
    http_host: str
    http_port: int
    tcp_host: str
    tcp_port: int
    operation_service_host: str
    operation_service_port: int


def load_config() -> WebServiceConfig:
    return WebServiceConfig(
        service_name=os.getenv("WEB_SERVICE_NAME", "web_service"),
        http_host=os.getenv("WEB_SERVICE_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("WEB_SERVICE_HTTP_PORT", "8000")),
        tcp_host=os.getenv("WEB_SERVICE_TCP_HOST", "0.0.0.0"),
        tcp_port=int(os.getenv("WEB_SERVICE_TCP_PORT", "9004")),
        operation_service_host=os.getenv(
            "WEB_SERVICE_OPERATION_SERVICE_HOST",
            os.getenv("WEB_SERVICE_BUSINESS_SERVICE_HOST", "business_service"),
        ),
        operation_service_port=int(
            os.getenv(
                "WEB_SERVICE_OPERATION_SERVICE_PORT",
                os.getenv("WEB_SERVICE_BUSINESS_SERVICE_PORT", "9001"),
            )
        ),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
