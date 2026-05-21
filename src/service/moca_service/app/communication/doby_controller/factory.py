import logging

from app.communication.doby_controller.runtime import DobyControllerRosRuntime


def create_doby_controller_runtime(
    *,
    logger: logging.Logger,
    node_name: str = "moca_doby_controller",
    enabled: bool = True,
) -> DobyControllerRosRuntime:
    return DobyControllerRosRuntime(
        node_name=node_name,
        logger=logger,
        enabled=enabled,
    )
