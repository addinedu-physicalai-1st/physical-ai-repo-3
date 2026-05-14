import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionServiceConfig:
    service_name: str
    tcp_host: str
    tcp_port: int
    udp_host: str
    udp_port: int
    control_service_host: str
    control_service_port: int


def load_config() -> VisionServiceConfig:
    return VisionServiceConfig(
        service_name=os.getenv("VISION_SERVICE_NAME", "vision_service"),
        tcp_host=os.getenv("VISION_SERVICE_TCP_HOST", "0.0.0.0"),
        tcp_port=int(os.getenv("VISION_SERVICE_TCP_PORT", "9003")),
        udp_host=os.getenv("VISION_SERVICE_UDP_HOST", "0.0.0.0"),
        udp_port=int(os.getenv("VISION_SERVICE_UDP_PORT", "9103")),
        control_service_host=os.getenv("VISION_SERVICE_CONTROL_SERVICE_HOST", "control_service"),
        control_service_port=int(os.getenv("VISION_SERVICE_CONTROL_SERVICE_PORT", "9002")),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
