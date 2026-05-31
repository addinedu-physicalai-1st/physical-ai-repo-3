import logging

from app.communication.doby_controller.runtime import DobyControllerRosRuntime


def create_doby_controller_runtime(
    *,
    logger: logging.Logger,
    node_name: str = "moca_doby_controller",
    enabled: bool = True,
    setmode_timeout_sec: float = 2.0,
    serving_action_name: str = "/serving/execute",
    serving_action_timeout_sec: float = 2.0,
) -> DobyControllerRosRuntime:
    return DobyControllerRosRuntime(
        node_name=node_name,
        logger=logger,
        enabled=enabled,
        setmode_timeout_sec=setmode_timeout_sec,
        serving_action_name=serving_action_name,
        serving_action_timeout_sec=serving_action_timeout_sec,
    )
