import json
import logging
import math
import threading
import time
from collections import deque
from typing import Any


class AdminGuiDobyRosRuntime:
    """ROS2 runtime used by admin_gui communication to read doby state."""

    def __init__(
        self,
        *,
        node_name: str,
        logger: logging.Logger,
        enabled: bool = True,
        setmode_timeout_sec: float = 2.0,
        robot_offline_threshold_sec: float = 3.0,
    ) -> None:
        self.node_name = node_name
        self.logger = logger
        self.enabled = enabled
        self.setmode_timeout_sec = setmode_timeout_sec
        self.robot_offline_threshold_sec = robot_offline_threshold_sec
        self._started = False
        self._context: Any | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._spin_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._mode_state: dict[str, Any] | None = None
        self._battery: dict[str, Any] | None = None
        self._robot_pose: dict[str, Any] | None = None
        self._has_amcl_pose = False
        self._tables: dict[str, dict[str, Any]] = {
            table_id: {
                "id": table_id,
                "occupancy": "unknown",
                "person_count": 0,
                "dishes_detected": False,
                "confidence": 0.0,
                "last_update": "",
            }
            for table_id in ("T01", "T02", "T03", "T04", "T05")
        }
        self._serving_state: dict[str, Any] = {}
        self._patrol_state: dict[str, Any] = {}
        self._guiding_state: dict[str, Any] = {}
        self._alarm: dict[str, Any] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._set_mode_client: Any | None = None
        self._set_mode_request_type: Any | None = None
        self._operator_command_publisher: Any | None = None
        self._operator_command_type: Any | None = None

    def start(self) -> None:
        if not self.enabled:
            self.logger.info("admin_gui doby ROS runtime disabled")
            return
        if self._started:
            return

        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from std_msgs.msg import String
        from sensor_msgs.msg import BatteryState
        from dobi_npc_msgs.msg import (
            GuidingState,
            ModeState,
            OperatorCommand,
            PatrolState,
            RapportEvent,
            TableReport,
        )
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
        self._node.create_subscription(
            String,
            "/serving/state",
            self._on_serving_state,
            10,
        )
        self._node.create_subscription(
            PatrolState,
            "/patrol/state",
            self._on_patrol_state,
            10,
        )
        self._node.create_subscription(
            TableReport,
            "/patrol/table_report",
            self._on_table_report,
            10,
        )
        self._node.create_subscription(
            GuidingState,
            "/guiding/state",
            self._on_guiding_state,
            10,
        )
        self._node.create_subscription(
            BatteryState,
            "/battery_state",
            self._on_battery,
            10,
        )
        self._node.create_subscription(
            RapportEvent,
            "/rapport/event",
            self._on_rapport,
            10,
        )
        self._set_mode_client = self._node.create_client(SetMode, "/mode/request")
        self._set_mode_request_type = SetMode.Request
        self._operator_command_publisher = self._node.create_publisher(
            OperatorCommand,
            "/operator/command",
            10,
        )
        self._operator_command_type = OperatorCommand
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            daemon=True,
            name=f"{self.node_name}-spin",
        )
        self._spin_thread.start()
        self._started = True
        self.logger.info("admin_gui doby ROS runtime started node=%s", self.node_name)

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
        self._operator_command_publisher = None
        self._operator_command_type = None
        self._started = False
        self.logger.info("admin_gui doby ROS runtime stopped node=%s", self.node_name)

    def get_current_mode(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._mode_state) if self._mode_state is not None else None

    def get_robot_pose(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._robot_pose) if self._robot_pose is not None else None

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            robot_online = self._robot_online_locked()
            return {
                "mode": dict(self._mode_state) if self._mode_state is not None else None,
                "battery": dict(self._battery) if self._battery is not None else None,
                "robot_online": robot_online,
                "pose": dict(self._robot_pose) if self._robot_pose is not None else None,
                "tables": [dict(table) for table in self._tables.values()],
                "serving_state": dict(self._serving_state),
                "patrol_state": dict(self._patrol_state),
                "guiding_state": dict(self._guiding_state),
                "alarm": dict(self._alarm) if self._alarm is not None else None,
                "events": list(self._events),
            }

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
                "message": "admin_gui doby ROS runtime disabled",
            }
        if (
            not self._started
            or self._set_mode_client is None
            or self._set_mode_request_type is None
        ):
            return {
                "ok": False,
                "code": "ROS_NOT_STARTED",
                "message": "admin_gui doby ROS runtime not started",
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

    def request_emergency_stop(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "code": "ROS_DISABLED",
                "message": "admin_gui doby ROS runtime disabled",
            }
        if (
            not self._started
            or self._operator_command_publisher is None
            or self._operator_command_type is None
        ):
            return {
                "ok": False,
                "code": "ROS_NOT_STARTED",
                "message": "admin_gui doby ROS runtime not started",
            }

        msg = self._operator_command_type()
        msg.command_type = "stop_emergency"
        msg.payload = "{}"
        self._operator_command_publisher.publish(msg)
        self._append_event("warn", "operator", "emergency stop requested", "control")
        return {"ok": True, "reason": "emergency_stop_published"}

    def _on_mode_state(self, msg: Any) -> None:
        params = self._shorten(msg.params)
        with self._lock:
            previous_mode = self._mode_state.get("current") if self._mode_state is not None else None
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
            if previous_mode != msg.current_mode:
                self._append_event_locked("info", "mode", f"{msg.current_mode} mode entered", "mode")
            if not bool(msg.safety_ok):
                alarm_was_active = self._alarm is not None and self._alarm.get("code") == "safety_alarm"
                self._alarm = {
                    "code": "safety_alarm",
                    "value": False,
                    "severity": "high",
                    "last_seen": time.time(),
                }
                if not alarm_was_active:
                    self._append_event_locked("warn", "safety", "safety alarm active", "safety")
            elif self._alarm and self._alarm.get("code") == "safety_alarm":
                self._alarm = None
        self.logger.debug(
            "admin_gui doby mode_state received current=%s params=%s battery_ok=%s safety_ok=%s last_reject_reason=%s",
            msg.current_mode,
            params,
            bool(msg.battery_ok),
            bool(msg.safety_ok),
            msg.last_reject_reason,
        )

    def _on_battery(self, msg: Any) -> None:
        percentage = float(getattr(msg, "percentage", -1.0))
        voltage = float(getattr(msg, "voltage", 0.0))
        with self._lock:
            previous = self._battery.get("percentage") if self._battery is not None else None
            self._battery = {
                "percentage": percentage,
                "voltage": voltage,
                "last_seen": time.time(),
            }
            if previous is None or abs(previous - percentage) >= 0.01:
                self._append_event_locked("info", "battery", f"battery {percentage * 100:.0f}%", "battery")

    def _on_serving_state(self, msg: Any) -> None:
        try:
            parsed = json.loads(msg.data) if msg.data else {}
        except (TypeError, ValueError):
            parsed = {"raw": msg.data}
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        with self._lock:
            self._serving_state = parsed

    def _on_patrol_state(self, msg: Any) -> None:
        with self._lock:
            self._patrol_state = {
                "state": msg.current_state,
                "current_table": msg.current_table,
                "tables_visited": int(msg.tables_visited),
                "tables_total": int(msg.tables_total),
                "progress": float(msg.progress),
                "started_at": self._stamp_to_epoch(msg.started_at),
                "last_seen": time.time(),
            }

    def _on_table_report(self, msg: Any) -> None:
        with self._lock:
            table = self._tables.setdefault(
                msg.table_id,
                {
                    "id": msg.table_id,
                    "occupancy": "unknown",
                    "person_count": 0,
                    "dishes_detected": False,
                    "confidence": 0.0,
                    "last_update": "",
                },
            )
            table.update(
                {
                    "occupancy": msg.occupancy,
                    "person_count": int(msg.person_count),
                    "dishes_detected": bool(msg.dishes_detected),
                    "confidence": float(msg.confidence),
                    "last_update": time.time(),
                }
            )
            self._append_event_locked(
                "info",
                "table",
                f"{msg.table_id} {msg.occupancy} ({float(msg.confidence):.2f})",
                "table",
            )

    def _on_guiding_state(self, msg: Any) -> None:
        with self._lock:
            self._guiding_state = {
                "state": msg.current_state,
                "target_table": msg.target_table,
                "customer_id": msg.customer_id,
                "customer_in_sight": bool(msg.customer_in_sight),
                "distance_to_customer": float(msg.distance_to_customer),
                "customer_lag_m": float(msg.customer_lag_m),
                "distance_to_target": float(msg.distance_to_target),
                "progress": float(msg.progress),
                "started_at": self._stamp_to_epoch(msg.started_at),
                "last_utter_text": msg.last_utter_text,
                "last_seen": time.time(),
            }

    def _on_rapport(self, msg: Any) -> None:
        if msg.event_type != "abort_trigger":
            return
        with self._lock:
            self._alarm = {
                "code": "rapport_abort",
                "value": float(msg.weight),
                "severity": "high",
                "reason": msg.reason,
                "last_seen": time.time(),
            }
            self._append_event_locked(
                "warn",
                "rapport",
                f"abort_trigger weight={float(msg.weight):.2f}",
                "safety",
            )

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
        self.logger.debug(
            "admin_gui doby robot_pose received frame=%s x=%.3f y=%.3f yaw=%.3f",
            pose["frame"],
            pose["x"],
            pose["y"],
            pose["yaw"],
        )

    def _on_amcl_pose(self, msg: Any) -> None:
        with self._lock:
            self._robot_pose = self._pose_payload(
                msg.pose.pose.position,
                msg.pose.pose.orientation,
                "map",
            )
            self._has_amcl_pose = True
            pose = dict(self._robot_pose)
        self.logger.debug(
            "admin_gui doby robot_pose received frame=%s x=%.3f y=%.3f yaw=%.3f",
            pose["frame"],
            pose["x"],
            pose["y"],
            pose["yaw"],
        )

    @staticmethod
    def _pose_payload(position: Any, orientation: Any, frame: str) -> dict[str, Any]:
        return {
            "x": float(position.x),
            "y": float(position.y),
            "yaw": AdminGuiDobyRosRuntime._yaw_from_quaternion(orientation),
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

    def _robot_online_locked(self) -> bool:
        if self._mode_state is None:
            return False
        last_seen = self._mode_state.get("last_seen")
        if not isinstance(last_seen, (int, float)):
            return False
        return time.time() - last_seen < self.robot_offline_threshold_sec

    def _append_event(self, level: str, source: str, message: str, category: str) -> None:
        with self._lock:
            self._append_event_locked(level, source, message, category)

    def _append_event_locked(self, level: str, source: str, message: str, category: str) -> None:
        self._events.appendleft(
            {
                "ts": time.time(),
                "level": level,
                "source": source,
                "message": message,
                "category": category,
            }
        )

    def __enter__(self) -> "AdminGuiDobyRosRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
