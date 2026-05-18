import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MocaServiceConfig:
    service_name: str
    server_host: str
    server_port: int
    admin_gui_host: str
    admin_gui_port: int
    web_service_host: str
    web_service_tcp_port: int
    cooking_controller_bridge_host: str
    cooking_controller_bridge_port: int
    serving_controller_bridge_host: str
    serving_controller_bridge_port: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str


def load_config() -> MocaServiceConfig:
    return MocaServiceConfig(
        service_name=os.getenv(
            "MOCA_SERVICE_NAME",
            os.getenv("BUSINESS_SERVICE_NAME", "moca_service"),
        ),
        server_host=os.getenv(
            "MOCA_SERVICE_HOST",
            os.getenv(
                "BUSINESS_SERVICE_HOST",
                os.getenv("CONTROL_SERVICE_HOST", "0.0.0.0"),
            ),
        ),
        server_port=int(
            os.getenv(
                "MOCA_SERVICE_PORT",
                os.getenv(
                    "BUSINESS_SERVICE_PORT",
                    os.getenv("CONTROL_SERVICE_PORT", "9001"),
                ),
            )
        ),

        admin_gui_host=os.getenv(
            "BUSINESS_SERVICE_ADMIN_GUI_HOST",
            os.getenv("CONTROL_SERVICE_ADMIN_GUI_HOST", "127.0.0.1"),
        ),
        admin_gui_port=int(
            os.getenv(
                "BUSINESS_SERVICE_ADMIN_GUI_PORT",
                os.getenv("CONTROL_SERVICE_ADMIN_GUI_PORT", "9000"),
            )
        ),

        web_service_host=os.getenv("BUSINESS_SERVICE_WEB_SERVICE_HOST", "web_service"),
        web_service_tcp_port=int(os.getenv("BUSINESS_SERVICE_WEB_SERVICE_TCP_PORT", "9004")),

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
        db_host=os.getenv("BUSINESS_SERVICE_DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("BUSINESS_SERVICE_DB_PORT", "3306")),
        db_user=os.getenv("BUSINESS_SERVICE_DB_USER", "business_user"),
        db_password=os.getenv("BUSINESS_SERVICE_DB_PASSWORD", "business_password"),
        db_name=os.getenv("BUSINESS_SERVICE_DB_NAME", "business"),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
