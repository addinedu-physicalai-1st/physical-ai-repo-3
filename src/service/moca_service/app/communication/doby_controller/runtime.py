import logging
import threading
from typing import Any


class DobyControllerRosRuntime:
    """Empty ROS2 communication runtime for the doby controller device."""

    def __init__(
        self,
        *,
        node_name: str,
        logger: logging.Logger,
        enabled: bool = True,
    ) -> None:
        self.node_name = node_name
        self.logger = logger
        self.enabled = enabled
        self._started = False
        self._context: Any | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._spin_thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            self.logger.info("doby_controller ROS runtime disabled")
            return
        if self._started:
            return

        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node

        self._context = Context()
        rclpy.init(context=self._context)
        self._node = Node(self.node_name, context=self._context)
        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            daemon=True,
            name=f"{self.node_name}-spin",
        )
        self._spin_thread.start()
        self._started = True
        self.logger.info("doby_controller ROS runtime started node=%s", self.node_name)

    def stop(self) -> None:
        if not self._started:
            return

        if self._executor is not None:
            self._executor.shutdown()
        if self._spin_thread is not None and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)
        if self._node is not None:
            self._node.destroy_node()
        if self._context is not None:
            import rclpy

            if self._context.ok():
                rclpy.shutdown(context=self._context)

        self._context = None
        self._node = None
        self._executor = None
        self._spin_thread = None
        self._started = False
        self.logger.info("doby_controller ROS runtime stopped node=%s", self.node_name)

    def __enter__(self) -> "DobyControllerRosRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
