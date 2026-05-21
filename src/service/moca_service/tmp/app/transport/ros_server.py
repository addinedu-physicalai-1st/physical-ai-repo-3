import logging
import threading

from app.protocol.ros_protocol import DEFAULT_ROS_STATUS_TOPIC


class RosServer:
    def __init__(
        self,
        node_name: str,
        logger: logging.Logger,
        *,
        enabled: bool = True,
    ):
        self.node_name = node_name
        self.status_topic = DEFAULT_ROS_STATUS_TOPIC
        self.logger = logger
        self.enabled = enabled
        self._started = False
        self._context = None
        self._node = None
        self._executor = None
        self._status_publisher = None
        self._spin_thread: threading.Thread | None = None
        self._status_msg_type = None

    def start(self) -> None:
        if not self.enabled:
            self.logger.info("ROS server disabled")
            return
        if self._started:
            return

        import rclpy
        from controller_status_msgs.msg import Status
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node

        self._context = Context()
        rclpy.init(context=self._context)
        self._node = Node(self.node_name, context=self._context)
        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)
        self._status_publisher = self._node.create_publisher(Status, self.status_topic, 10)
        self._status_msg_type = Status
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            daemon=True,
            name=f"{self.node_name}-spin",
        )
        self._spin_thread.start()
        self._started = True
        self.logger.info("ROS server started node=%s status_topic=%s", self.node_name, self.status_topic)

    def publish_status(self, seq: int) -> bool:
        if not self.enabled:
            self.logger.debug("skip ROS status publish because ROS server is disabled")
            return False
        if not self._started or self._status_publisher is None or self._status_msg_type is None:
            self.logger.warning("skip ROS status publish because ROS server is not started")
            return False

        message = self._status_msg_type()
        message.request_id = int(seq) & 0xFFFFFFFF
        self._status_publisher.publish(message)
        self.logger.info("published ROS status request_id=%s topic=%s", message.request_id, self.status_topic)
        return True

    def close(self) -> None:
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

        self._started = False
        self.logger.info("ROS server stopped node=%s", self.node_name)

    def __enter__(self) -> "RosServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
