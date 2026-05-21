import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MocaServiceConfig:
    service_name: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str


def load_config() -> MocaServiceConfig:
    return MocaServiceConfig(
        service_name=os.getenv("MOCA_SERVICE_NAME", "moca_service"),
        db_host=os.getenv("MOCA_DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("MOCA_DB_PORT", "3306")),
        db_user=os.getenv("MOCA_DB_USER", "business_user"),
        db_password=os.getenv("MOCA_DB_PASSWORD", "business_password"),
        db_name=os.getenv("MOCA_DB_NAME", "business"),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)
