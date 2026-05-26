#!/usr/bin/env python3
"""target_selector_node — /emotion/state + /customer/registry → /follow/target.

GEVA 가 발행한 /emotion/state (track_id + valence) 와
customer_identity_node 의 /customer/registry (track_id → customer_id) 를 보고
valence > threshold 인 사람의 customer_id 를 /follow/target 으로 발행.

follow_controller 가 /follow/target 구독 → target_customer_id 자동 갱신.

흐름:
  /emotion/state (valence, track_id)
        +
  /customer/registry (customer_id ↔ track_id)
        ↓
  valence > valence_threshold 이면
        ↓
  /follow/target (std_msgs/String, customer_id)
        ↓
  follow_controller → 자동으로 해당 customer_id 추종
"""
from __future__ import annotations

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

from dobi_npc_msgs.msg import EmotionState, CustomerRegistry


class TargetSelectorNode(Node):
    """감정 분석 결과 → 추종 대상 customer_id 자동 선택."""

    def __init__(self):
        super().__init__('target_selector_node')

        # valence 이 값 이상이면 추종 대상으로 선택
        self.declare_parameter('valence_threshold', 0.3)
        # 한 번 선택된 target 은 이 시간(초) 동안 유지 (재선택 방지)
        self.declare_parameter('lock_duration_sec', 5.0)

        self._valence_threshold = float(
            self.get_parameter('valence_threshold').value)
        self._lock_duration = float(
            self.get_parameter('lock_duration_sec').value)

        # track_id → customer_id 매핑 캐시
        self._track_to_customer: dict[int, str] = {}

        # 현재 선택된 target customer_id + lock 만료 시각
        self._current_target: str = ''
        self._lock_until: float = 0.0

        self.create_subscription(
            EmotionState, '/emotion/state', self._on_emotion, 10)
        self.create_subscription(
            CustomerRegistry, '/customer/registry', self._on_registry, 10)

        self._pub = self.create_publisher(String, '/follow/target', 10)

        self.get_logger().info(
            f'target_selector_node ready '
            f'(valence_threshold={self._valence_threshold:.2f}, '
            f'lock={self._lock_duration:.1f}s)'
        )

    def _on_registry(self, msg: CustomerRegistry):
        """track_id → customer_id 매핑 갱신."""
        self._track_to_customer = {
            int(c.track_id): c.customer_id
            for c in msg.customers
        }

    def _on_emotion(self, msg: EmotionState):
        """valence > threshold 이면 해당 track 의 customer_id 를 /follow/target 발행."""
        import time
        now = time.monotonic()

        # track_id 없으면 무시 (-1 = 미식별)
        if msg.track_id < 0:
            return

        # valence 임계값 미만이면 무시
        if msg.valence < self._valence_threshold:
            return

        # lock 중이면 현재 target 유지 (흔들림 방지)
        if now < self._lock_until and self._current_target:
            return

        # track_id → customer_id 변환
        customer_id = self._track_to_customer.get(msg.track_id)
        if not customer_id:
            self.get_logger().warn(
                f'track_id={msg.track_id} 에 매칭되는 customer_id 없음 '
                f'(registry 아직 미수신?)')
            return

        # 새 target 선택
        self._current_target = customer_id
        self._lock_until = now + self._lock_duration

        target_msg = String()
        target_msg.data = customer_id
        self._pub.publish(target_msg)

        self.get_logger().info(
            f'추종 대상 선택: customer_id={customer_id} '
            f'(track_id={msg.track_id}, valence={msg.valence:.2f})'
        )


def main(args=None):
    rclpy.init(args=args)
    node = TargetSelectorNode()
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
