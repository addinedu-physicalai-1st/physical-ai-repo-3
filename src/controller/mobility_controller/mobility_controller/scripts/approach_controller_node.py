#!/usr/bin/env python3
"""
approach_controller_node — customer_pose → /bt/cmd_vel PD제어 접근 컨트롤러

구독: /customer_pose                     (geometry_msgs/PoseStamped, 정규화 픽셀 좌표)
      /person_tracking/approach_target   (std_msgs/Int32, -1=없음)
발행: /bt/cmd_vel                        (geometry_msgs/Twist)

각속도 제어: angular.z = -(Kp * err_x) - (Kd * d_err_x_filtered)
  - d_err_x는 EMA 필터로 카메라 노이즈 억제
  - dead_zone 적용 후 미분 계산 (무감대 내에선 오차=0으로 고정)
"""
from __future__ import annotations

import time
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from geometry_msgs.msg import PoseStamped, Twist
from std_msgs.msg import Int32
from rclpy.qos import QoSProfile, ReliabilityPolicy


class ApproachControllerNode(Node):
    """customer_pose 정규화 좌표 기반 PD제어로 /bt/cmd_vel 발행."""

    def __init__(self):
        super().__init__('approach_controller_node')

        self.declare_parameter('linear_speed',    0.15)  # 전진 속도 (m/s)
        self.declare_parameter('angular_gain',    1.2)   # 각속도 P 게인 (Kp)
        self.declare_parameter('derivative_gain', 0.3)   # 각속도 D 게인 (Kd)
        self.declare_parameter('ema_alpha',       0.3)   # D항 EMA 필터 계수 (0~1, 작을수록 강한 필터)
        self.declare_parameter('dead_zone',       0.05)  # x 오차 무감대 (정규화)
        self.declare_parameter('close_threshold', 0.72)  # cy 이상이면 전진 정지
        self.declare_parameter('pose_timeout',    1.0)   # 포즈 미수신 정지 (초)
        self.declare_parameter('cmd_rate',        10.0)  # 발행 주파수 (Hz)

        self._linear_speed = float(self.get_parameter('linear_speed').value)
        self._kp           = float(self.get_parameter('angular_gain').value)
        self._kd           = float(self.get_parameter('derivative_gain').value)
        self._ema_alpha    = float(self.get_parameter('ema_alpha').value)
        self._dead_zone    = float(self.get_parameter('dead_zone').value)
        self._close_thresh = float(self.get_parameter('close_threshold').value)
        self._pose_timeout = float(self.get_parameter('pose_timeout').value)

        self._target: int        = -1
        self._cx: float          = 0.5
        self._cy: float          = 0.5
        self._bh: float          = 0.0   # bbox 높이 비율 (거리 프록시)
        self._last_pose_t: float = 0.0

        # PD 상태
        self._prev_err_x: float  = 0.0
        self._prev_tick_t: float = time.time()
        self._d_filtered: float  = 0.0  # EMA 필터링된 미분값

        self._sub_target = self.create_subscription(
            Int32, '/person_tracking/approach_target', self._cb_target, 10)
        self._sub_pose = self.create_subscription(
            PoseStamped, '/customer_pose', self._cb_pose, 10)
        _qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._pub = self.create_publisher(Twist, '/bt/cmd_vel', _qos)

        rate = float(self.get_parameter('cmd_rate').value)
        self._timer = self.create_timer(1.0 / rate, self._tick)

        self.get_logger().info('approach_controller_node 준비 완료 (PD제어)')

    def _cb_target(self, msg: Int32) -> None:
        self._target = msg.data

    def _cb_pose(self, msg: PoseStamped) -> None:
        self._cx = float(msg.pose.position.x)
        self._cy = float(msg.pose.position.y)
        self._bh = float(msg.pose.position.z)
        self._last_pose_t = time.time()

    def _tick(self) -> None:
        now = time.time()
        twist = Twist()

        pose_stale = (now - self._last_pose_t) > self._pose_timeout
        if self._target < 0 or pose_stale:
            # 타깃 없을 때 PD 상태 리셋 (재진입 시 튀는 D항 방지).
            # publish 하지 않고 return → twist_mux pose_timeout(0.5s) 후 /bt/cmd_vel
            # 비활성화 → follow/cmd_vel 등 하위 채널이 우선권 확보.
            self._prev_err_x = 0.0
            self._d_filtered = 0.0
            self._prev_tick_t = now
            return

        err_x = self._cx - 0.5
        if abs(err_x) < self._dead_zone:
            err_x = 0.0

        # D항: EMA 필터로 카메라 노이즈 억제
        dt = max(now - self._prev_tick_t, 1e-3)  # 0 나누기 방지
        raw_d = (err_x - self._prev_err_x) / dt
        self._d_filtered = (
            self._ema_alpha * raw_d + (1.0 - self._ema_alpha) * self._d_filtered
        )

        twist.angular.z = -(self._kp * err_x) - (self._kd * self._d_filtered)

        # bbox 높이 비율(bh)이 close_threshold 미만일 때만 전진 (bh 클수록 가까움)
        if self._bh < self._close_thresh:
            twist.linear.x = self._linear_speed

        self._prev_err_x = err_x
        self._prev_tick_t = now

        self._pub.publish(twist)
        self.get_logger().debug(
            f'cmd_vel: linear={twist.linear.x:.2f} angular={twist.angular.z:.2f} '
            f'(cx={self._cx:.2f} bh={self._bh:.2f} '
            f'err={err_x:.3f} d_f={self._d_filtered:.3f})'
        )


def main(args=None):
    rclpy.init(args=args)
    node = ApproachControllerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
