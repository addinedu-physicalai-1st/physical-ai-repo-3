import logging
import threading
import time
from typing import Any, Callable


class DDoobyControllerRosRuntime:
    """ROS2 action runtime for the DDooby manufacture controller."""

    def __init__(
        self,
        *,
        node_name: str,
        logger: logging.Logger,
        enabled: bool = True,
        action_name: str = "ddooby/manifacture",
        action_timeout_sec: float = 2.0,
    ) -> None:
        self.node_name = node_name
        self.logger = logger
        self.enabled = enabled
        self.action_name = action_name
        self.action_timeout_sec = action_timeout_sec
        self._started = False
        self._context: Any | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._spin_thread: threading.Thread | None = None
        self._action_client: Any | None = None
        self._goal_type: Any | None = None
        self._item_type: Any | None = None

    def start(self) -> None:
        if not self.enabled:
            self.logger.info("ddooby_controller ROS runtime disabled")
            return
        if self._started:
            return

        import rclpy
        from custom_msg.action import Manifacture
        from custom_msg.msg import ManufactureItem
        from rclpy.action import ActionClient
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node

        self._context = Context()
        rclpy.init(context=self._context)
        self._node = Node(self.node_name, context=self._context)
        self._executor = SingleThreadedExecutor(context=self._context)
        self._action_client = ActionClient(self._node, Manifacture, self.action_name)
        self._goal_type = Manifacture.Goal
        self._item_type = ManufactureItem
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            daemon=True,
            name=f"{self.node_name}-spin",
        )
        self._spin_thread.start()
        self._started = True
        self.logger.info(
            "ddooby_controller ROS runtime started node=%s action=%s",
            self.node_name,
            self.action_name,
        )

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
        self._action_client = None
        self._goal_type = None
        self._item_type = None
        self._started = False
        self.logger.info("ddooby_controller ROS runtime stopped node=%s", self.node_name)

    def request_manufacture(
        self,
        *,
        command_id: str,
        order_id: int,
        items: list[dict[str, Any]],
        on_completed: Callable[[int, str], Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "code": "ROS_DISABLED",
                "message": "ddooby_controller ROS runtime disabled",
            }
        if (
            not self._started
            or self._action_client is None
            or self._goal_type is None
            or self._item_type is None
        ):
            return {
                "ok": False,
                "code": "ROS_NOT_STARTED",
                "message": "ddooby_controller ROS runtime not started",
            }

        timeout = self.action_timeout_sec if timeout_sec is None else timeout_sec
        if not self._action_client.wait_for_server(timeout_sec=timeout):
            return {
                "ok": False,
                "code": "ACTION_UNAVAILABLE",
                "message": f"{self.action_name} action server unavailable",
            }

        goal = self._goal_type()
        goal.items = []
        for item in items:
            message = self._item_type()
            message.name = str(item["name"])
            message.count = int(item["count"])
            goal.items.append(message)

        goal_future = self._action_client.send_goal_async(
            goal,
            feedback_callback=self._on_feedback,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if goal_future.done():
                goal_handle = goal_future.result()
                if goal_handle is None:
                    return {
                        "ok": False,
                        "code": "NULL_GOAL_HANDLE",
                        "message": f"{self.action_name} returned no goal handle",
                    }
                if not goal_handle.accepted:
                    return {
                        "ok": False,
                        "code": "GOAL_REJECTED",
                        "message": f"{self.action_name} rejected manufacture goal",
                    }
                result_future = goal_handle.get_result_async()
                result_future.add_done_callback(
                    lambda future: self._on_result(
                        future,
                        command_id=command_id,
                        order_id=order_id,
                        on_completed=on_completed,
                    )
                )
                return {"ok": True, "accepted": True}
            time.sleep(0.02)

        return {
            "ok": False,
            "code": "TIMEOUT",
            "message": f"{self.action_name} goal request timed out",
        }

    def _on_feedback(self, feedback_message: Any) -> None:
        feedback = getattr(feedback_message, "feedback", None)
        status = getattr(feedback, "status", "")
        if status:
            self.logger.info(
                "ddooby manufacture feedback action=%s status=%s",
                self.action_name,
                status,
            )

    def _on_result(
        self,
        future: Any,
        *,
        command_id: str,
        order_id: int,
        on_completed: Callable[[int, str], Any] | None,
    ) -> None:
        try:
            response = future.result()
            result = response.result
        except Exception as exc:
            self.logger.warning(
                "ddooby manufacture result failed command_id=%s order_id=%s error=%s",
                command_id,
                order_id,
                exc,
            )
            return

        if not bool(result.success):
            self.logger.warning(
                "ddooby manufacture result rejected command_id=%s order_id=%s message=%s",
                command_id,
                order_id,
                result.message,
            )
            return

        self.logger.info(
            "ddooby manufacture result succeeded command_id=%s order_id=%s message=%s",
            command_id,
            order_id,
            result.message,
        )
        if on_completed is not None:
            on_completed(order_id, command_id)

    def __enter__(self) -> "DDoobyControllerRosRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
