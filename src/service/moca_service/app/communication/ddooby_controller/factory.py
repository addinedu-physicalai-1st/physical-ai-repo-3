import logging

from app.communication.ddooby_controller.runtime import DDoobyControllerRosRuntime


def create_ddooby_controller_runtime(
    *,
    logger: logging.Logger,
    node_name: str = "moca_ddooby_controller",
    enabled: bool = True,
    action_name: str = "ddooby/manifacture",
    action_timeout_sec: float = 2.0,
) -> DDoobyControllerRosRuntime:
    return DDoobyControllerRosRuntime(
        node_name=node_name,
        logger=logger,
        enabled=enabled,
        action_name=action_name,
        action_timeout_sec=action_timeout_sec,
    )
