import logging
import json
import math
import threading
import time
from typing import Any


class DobyControllerRosRuntime:
    """ROS2 communication runtime for the doby controller device."""

    def __init__(
        self,
        *,
        node_name: str,
        logger: logging.Logger,
        enabled: bool = True,
        setmode_timeout_sec: float = 2.0,
    ) -> None:
        self.node_name = node_name
        self.logger = logger
        self.enabled = enabled
        self.setmode_timeout_sec = setmode_timeout_sec
        self._started = False
        self._context: Any | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._spin_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._mode_state: dict[str, Any] | None = None
        self._robot_pose: dict[str, Any] | None = None
        self._has_amcl_pose = False
        self._set_mode_client: Any | None = None
        self._set_mode_request_type: Any | None = None

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
        from dobi_npc_msgs.msg import ModeState
        from dobi_npc_msgs.srv import SetMode
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from nav_msgs.msg import Odometry

        self._context = Context()
        rclpy.init(context=self._context)
        self._node = Node(self.node_name, context=self._context)
        self._executor = SingleThreadedExecutor(context=self._context)
        self._node.create_subscription(
            ModeState,
            "/mode/state",
            self._on_mode_state,
            10,
        )
        self._node.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self._on_amcl_pose,
            10,
        )
        self._node.create_subscription(
            Odometry,
            "/odom",
            self._on_odom,
            10,
        )
        self._set_mode_client = self._node.create_client(SetMode, "/mode/request")
        self._set_mode_request_type = SetMode.Request
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
        self._set_mode_client = None
        self._set_mode_request_type = None
        self._started = False
        self.logger.info("doby_controller ROS runtime stopped node=%s", self.node_name)

    def get_current_mode(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._mode_state) if self._mode_state is not None else None

    def get_robot_pose(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._robot_pose) if self._robot_pose is not None else None

    def request_mode_change(
        self,
        mode: str,
        params: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "code": "ROS_DISABLED",
                "message": "doby_controller ROS runtime disabled",
            }
        if (
            not self._started
            or self._set_mode_client is None
            or self._set_mode_request_type is None
        ):
            return {
                "ok": False,
                "code": "ROS_NOT_STARTED",
                "message": "doby_controller ROS runtime not started",
            }

        params_json = json.dumps(params or {}, ensure_ascii=False) if params else ""
        request = self._set_mode_request_type()
        request.requested_mode = mode
        request.params = params_json

        timeout = self.setmode_timeout_sec if timeout_sec is None else timeout_sec
        if not self._set_mode_client.wait_for_service(timeout_sec=timeout):
            return {
                "ok": False,
                "code": "SERVICE_UNAVAILABLE",
                "message": "/mode/request service unavailable",
            }

        future = self._set_mode_client.call_async(request)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if future.done():
                response = future.result()
                if response is None:
                    return {
                        "ok": False,
                        "code": "NULL_RESPONSE",
                        "message": "/mode/request returned no response",
                    }
                return {
                    "ok": bool(response.success),
                    "current_mode": response.current_mode,
                    "reason": response.reason,
                }
            time.sleep(0.02)

        return {
            "ok": False,
            "code": "TIMEOUT",
            "message": "/mode/request timed out",
        }

    def _on_mode_state(self, msg: Any) -> None:
        params = self._shorten(msg.params)
        with self._lock:
            self._mode_state = {
                "current": msg.current_mode,
                "entered_at": self._stamp_to_epoch(msg.entered_at),
                "params": self._parse_params(msg.params),
                "params_raw": msg.params,
                "battery_ok": bool(msg.battery_ok),
                "safety_ok": bool(msg.safety_ok),
                "last_reject_reason": msg.last_reject_reason,
                "last_seen": time.time(),
            }
        # self.logger.info(
        #     "doby_controller mode_state received current=%s params=%s battery_ok=%s safety_ok=%s last_reject_reason=%s",
        #     msg.current_mode,
        #     params,
        #     bool(msg.battery_ok),
        #     bool(msg.safety_ok),
        #     msg.last_reject_reason,
        # )

    def _on_odom(self, msg: Any) -> None:
        with self._lock:
            if self._has_amcl_pose:
                return
            self._robot_pose = self._pose_payload(
                msg.pose.pose.position,
                msg.pose.pose.orientation,
                "odom",
            )
            pose = dict(self._robot_pose)
        # self.logger.info(
        #     "doby_controller robot_pose received frame=%s x=%.3f y=%.3f yaw=%.3f",
        #     pose["frame"],
        #     pose["x"],
        #     pose["y"],
        #     pose["yaw"],
        # )

    def _on_amcl_pose(self, msg: Any) -> None:
        with self._lock:
            self._robot_pose = self._pose_payload(
                msg.pose.pose.position,
                msg.pose.pose.orientation,
                "map",
            )
            self._has_amcl_pose = True
            pose = dict(self._robot_pose)
        # self.logger.info(
        #     "doby_controller robot_pose received frame=%s x=%.3f y=%.3f yaw=%.3f",
        #     pose["frame"],
        #     pose["x"],
        #     pose["y"],
        #     pose["yaw"],
        # )

    @staticmethod
    def _pose_payload(position: Any, orientation: Any, frame: str) -> dict[str, Any]:
        return {
            "x": float(position.x),
            "y": float(position.y),
            "yaw": DobyControllerRosRuntime._yaw_from_quaternion(orientation),
            "frame": frame,
            "last_seen": time.time(),
        }

    @staticmethod
    def _yaw_from_quaternion(q: Any) -> float:
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny, cosy)

    @staticmethod
    def _parse_params(params: str) -> dict[str, Any]:
        if not params:
            return {}
        try:
            parsed = json.loads(params)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _stamp_to_epoch(stamp: Any) -> float | None:
        if stamp is None:
            return None
        try:
            return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _shorten(value: str, limit: int = 160) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    def __enter__(self) -> "DobyControllerRosRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
