import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MocaServiceConfig:
    service_name: str
    service_host: str
    service_port: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    admin_gui_listen_host: str
    admin_gui_listen_port: int
    admin_gui_host: str
    admin_gui_port: int
    tcp_timeout_sec: float


def load_config() -> MocaServiceConfig:
    return MocaServiceConfig(
        service_name=os.getenv("MOCA_SERVICE_NAME", "moca_service"),
        service_host=os.getenv("MOCA_SERVICE_HOST", "0.0.0.0"),
        service_port=int(os.getenv("MOCA_SERVICE_PORT", "9001")),
        db_host=os.getenv("MOCA_DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("MOCA_DB_PORT", "3306")),
        db_user=os.getenv("MOCA_DB_USER", "business_user"),
        db_password=os.getenv("MOCA_DB_PASSWORD", "business_password"),
        db_name=os.getenv("MOCA_DB_NAME", "business"),
        admin_gui_listen_host=os.getenv("MOCA_ADMIN_GUI_HOST", "0.0.0.0"),
        admin_gui_listen_port=int(os.getenv("MOCA_ADMIN_GUI_PORT", "9002")),
        admin_gui_host=os.getenv("ADMIN_GUI_HOST", "127.0.0.1"),
        admin_gui_port=int(os.getenv("ADMIN_GUI_PORT", "9000")),
        tcp_timeout_sec=float(os.getenv("MOCA_TCP_TIMEOUT_SEC", "3.0")),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
