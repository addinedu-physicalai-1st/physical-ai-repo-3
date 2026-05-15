import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlServiceConfig:
    service_name: str
    host: str
    port: int
    admin_gui_host: str
    admin_gui_port: int
    business_service_host: str
    business_service_port: int
    cooking_controller_bridge_host: str
    cooking_controller_bridge_port: int
    serving_controller_bridge_host: str
    serving_controller_bridge_port: int
    vision_service_host: str
    vision_service_tcp_port: int
    ros_domain_id: int


def load_config() -> ControlServiceConfig:
    return ControlServiceConfig(
        service_name=os.getenv("CONTROL_SERVICE_NAME", "control_service"),
        host=os.getenv("CONTROL_SERVICE_HOST", "0.0.0.0"),
        port=int(os.getenv("CONTROL_SERVICE_PORT", "9002")),
        admin_gui_host=os.getenv("CONTROL_SERVICE_ADMIN_GUI_HOST", "127.0.0.1"),
        admin_gui_port=int(os.getenv("CONTROL_SERVICE_ADMIN_GUI_PORT", "9000")),
        business_service_host=os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_HOST", "business_service"),
        business_service_port=int(os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_PORT", "9001")),
        cooking_controller_bridge_host=os.getenv(
            "CONTROL_SERVICE_COOKING_CONTROLLER_BRIDGE_HOST",
            "127.0.0.1",
        ),
        cooking_controller_bridge_port=int(
            os.getenv("CONTROL_SERVICE_COOKING_CONTROLLER_BRIDGE_PORT", "9005")
        ),
        serving_controller_bridge_host=os.getenv(
            "CONTROL_SERVICE_SERVING_CONTROLLER_BRIDGE_HOST",
            "127.0.0.1",
        ),
        serving_controller_bridge_port=int(
            os.getenv("CONTROL_SERVICE_SERVING_CONTROLLER_BRIDGE_PORT", "9006")
        ),
        vision_service_host=os.getenv("CONTROL_SERVICE_VISION_SERVICE_HOST", "vision_service"),
        vision_service_tcp_port=int(os.getenv("CONTROL_SERVICE_VISION_SERVICE_TCP_PORT", "9003")),
        ros_domain_id=int(os.getenv("CONTROL_SERVICE_ROS_DOMAIN_ID", "0")),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
