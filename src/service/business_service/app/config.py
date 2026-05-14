import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessServiceConfig:
    service_name: str
    host: str
    port: int
    control_service_host: str
    control_service_port: int
    web_service_host: str
    web_service_tcp_port: int


def load_config() -> BusinessServiceConfig:
    return BusinessServiceConfig(
        service_name=os.getenv("BUSINESS_SERVICE_NAME", "business_service"),
        host=os.getenv("BUSINESS_SERVICE_HOST", "0.0.0.0"),
        port=int(os.getenv("BUSINESS_SERVICE_PORT", "9001")),
        control_service_host=os.getenv("BUSINESS_SERVICE_CONTROL_SERVICE_HOST", "control_service"),
        control_service_port=int(os.getenv("BUSINESS_SERVICE_CONTROL_SERVICE_PORT", "9002")),
        web_service_host=os.getenv("BUSINESS_SERVICE_WEB_SERVICE_HOST", "web_service"),
        web_service_tcp_port=int(os.getenv("BUSINESS_SERVICE_WEB_SERVICE_TCP_PORT", "9004")),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
