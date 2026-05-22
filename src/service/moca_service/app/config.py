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
    admin_gui_doby_ros_enabled: bool
    admin_gui_doby_node_name: str
    admin_gui_doby_setmode_timeout_sec: float
    tcp_timeout_sec: float
    doby_controller_ros_enabled: bool
    doby_controller_node_name: str
    doby_controller_setmode_timeout_sec: float
    ddooby_controller_ros_enabled: bool
    ddooby_controller_node_name: str
    ddooby_controller_action_name: str
    ddooby_controller_action_timeout_sec: float
    order_orchestration_enabled: bool
    order_orchestration_tick_sec: float


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
        admin_gui_doby_ros_enabled=_env_bool("MOCA_ADMIN_GUI_DOBY_ROS_ENABLED", True),
        admin_gui_doby_node_name=os.getenv("MOCA_ADMIN_GUI_DOBY_NODE_NAME", "moca_admin_gui_doby"),
        admin_gui_doby_setmode_timeout_sec=float(
            os.getenv("MOCA_ADMIN_GUI_DOBY_SETMODE_TIMEOUT_SEC", "2.0")
        ),
        tcp_timeout_sec=float(os.getenv("MOCA_TCP_TIMEOUT_SEC", "3.0")),
        doby_controller_ros_enabled=_env_bool("MOCA_DOBY_CONTROLLER_ROS_ENABLED", True),
        doby_controller_node_name=os.getenv("MOCA_DOBY_CONTROLLER_NODE_NAME", "moca_doby_controller"),
        doby_controller_setmode_timeout_sec=float(
            os.getenv("MOCA_DOBY_CONTROLLER_SETMODE_TIMEOUT_SEC", "2.0")
        ),
        ddooby_controller_ros_enabled=_env_bool("MOCA_DDOOBY_CONTROLLER_ROS_ENABLED", True),
        ddooby_controller_node_name=os.getenv(
            "MOCA_DDOOBY_CONTROLLER_NODE_NAME",
            "moca_ddooby_controller",
        ),
        ddooby_controller_action_name=os.getenv(
            "MOCA_DDOOBY_CONTROLLER_ACTION_NAME",
            "ddooby/manifacture",
        ),
        ddooby_controller_action_timeout_sec=float(
            os.getenv("MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC", "2.0")
        ),
        order_orchestration_enabled=_env_bool("MOCA_ORDER_ORCHESTRATION_ENABLED", True),
        order_orchestration_tick_sec=float(
            os.getenv("MOCA_ORDER_ORCHESTRATION_TICK_SEC", "1.0")
        ),
    )


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(service_name)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
