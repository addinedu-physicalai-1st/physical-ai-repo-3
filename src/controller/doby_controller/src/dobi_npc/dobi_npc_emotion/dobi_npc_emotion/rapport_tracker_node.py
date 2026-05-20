#!/usr/bin/env python3
"""rapport_tracker — V·A → RapportEvent 분류 및 발행 (hysteresis 적용).

Phase 2 W4 + 후속. CLAUDE.md §4.3 명세:
  발행: /rapport/event (dobi_npc_msgs/RapportEvent)
  구독: /emotion/state (dobi_npc_msgs/EmotionState)

분류 룰 (raw):
  V<-0.5 ∧ A>+0.4  → raw abort 조건       (CLAUDE.md §2 학술 임계값)
  V>+0.3           → engagement_up
  V<-0.3           → engagement_down
  그 외             → neutral_continue

abort hysteresis (false positive 방지, Phase 2 W4-D):
  ON  — raw abort 조건이 abort_on_count(기본 5) 프레임 연속 충족 → abort_trigger
  OFF — raw 정상이 abort_off_count(기본 5) 프레임 연속 → abort 해제
  no_face/conf=0 — 카운트 변경 없음 (사람 안 보일 때 abort 자동 해제 방지)

10Hz GEVA 입력 가정 시 5프레임 ≈ 0.5초. 짧은 outlier 흡수 + 빠른 반응 균형.

Phase 후속 확장:
  - 윈도우 평균 V·A (현재는 카운트 기반)
  - GEFA(자세) source까지 fusion
  - Salichs 2014 Decision Rule
"""
from __future__ import annotations

from dataclasses import dataclass

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from dobi_npc_msgs.msg import EmotionState, RapportEvent


@dataclass
class EMAState:
    """V·A 의 confidence-weighted EMA 상태.

    spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md §3
    """
    v_smooth: float | None = None
    a_smooth: float | None = None

    def update(self, v_now: float, a_now: float, conf: float,
               no_signal: bool, alpha_base: float,
               conf_min_gate: float) -> None:
        if no_signal:
            return  # 사람 안 보임 — state 보존
        if conf < conf_min_gate:
            return  # 자신없는 frame skip
        if self.v_smooth is None:
            # cold start — 첫 valid frame 그대로 채택
            self.v_smooth = v_now
            self.a_smooth = a_now
            return
        weight = alpha_base * conf
        self.v_smooth = weight * v_now + (1 - weight) * self.v_smooth
        self.a_smooth = weight * a_now + (1 - weight) * self.a_smooth


# CLAUDE.md §2 학술 임계값
ABORT_VALENCE_MAX = -0.5
ABORT_AROUSAL_MIN = +0.4
ENGAGE_UP_VALENCE_MIN = +0.3
ENGAGE_DOWN_VALENCE_MAX = -0.3


class RapportTrackerNode(Node):
    """V·A → RapportEvent 분류기 (hysteresis 적용)."""

    def __init__(self):
        super().__init__('rapport_tracker_node')

        self.declare_parameter('input_topic', '/emotion/state')
        self.declare_parameter('output_topic', '/rapport/event')
        # hysteresis: ON/OFF 둘 다 연속 카운트 임계 (10Hz @ 5프레임 ≈ 0.5초)
        self.declare_parameter('abort_on_count', 5)
        self.declare_parameter('abort_off_count', 5)

        in_topic = self.get_parameter('input_topic').value
        out_topic = self.get_parameter('output_topic').value
        self._abort_on_count = int(self.get_parameter('abort_on_count').value)
        self._abort_off_count = int(self.get_parameter('abort_off_count').value)

        self.sub = self.create_subscription(
            EmotionState, in_topic, self._on_emotion, 10
        )
        self.pub = self.create_publisher(RapportEvent, out_topic, 10)

        # hysteresis 상태
        self._abort_streak = 0
        self._normal_streak = 0
        self._currently_aborting = False

        self._last_event_type = None
        self.get_logger().info(
            f"rapport_tracker: {in_topic} -> {out_topic}, "
            f"hysteresis on={self._abort_on_count} off={self._abort_off_count}"
        )

    def _on_emotion(self, msg: EmotionState):
        event = RapportEvent()
        event.header.stamp = self.get_clock().now().to_msg()
        event.header.frame_id = msg.header.frame_id
        event.emotion = msg

        v = msg.valence
        a = msg.arousal

        no_signal = (msg.confidence <= 0.0) or ("no_face" in msg.flags)
        raw_abort = (
            (not no_signal) and
            (v < ABORT_VALENCE_MAX) and (a > ABORT_AROUSAL_MIN)
        )

        # === streak 갱신 ===
        if no_signal:
            # 카운트 변경 없음 — 사람 안 보이는 동안 abort 자동 해제 방지
            pass
        elif raw_abort:
            self._abort_streak += 1
            self._normal_streak = 0
        else:
            self._normal_streak += 1
            self._abort_streak = 0

        # === 상태 전이 (hysteresis) ===
        if (not self._currently_aborting and
                self._abort_streak >= self._abort_on_count):
            self._currently_aborting = True
            self.get_logger().warning(
                f"abort streak {self._abort_streak} ≥ {self._abort_on_count} "
                f"→ ENTER abort (V={v:.2f}, A={a:.2f})"
            )
        elif (self._currently_aborting and
                self._normal_streak >= self._abort_off_count):
            self._currently_aborting = False
            self.get_logger().info(
                f"normal streak {self._normal_streak} ≥ {self._abort_off_count} "
                f"→ LEAVE abort (V={v:.2f}, A={a:.2f})"
            )

        # === event_type 결정 ===
        if no_signal:
            event.event_type = "neutral_continue"
            event.weight = 0.0
            event.reason = "no_signal"
        elif self._currently_aborting:
            event.event_type = "abort_trigger"
            event.weight = -1.0
            event.reason = "negative_high_arousal_sustained"
        elif v > ENGAGE_UP_VALENCE_MIN:
            event.event_type = "engagement_up"
            event.weight = +0.5
            event.reason = "positive_valence"
        elif v < ENGAGE_DOWN_VALENCE_MAX:
            event.event_type = "engagement_down"
            event.weight = -0.5
            event.reason = "negative_valence"
        else:
            event.event_type = "neutral_continue"
            event.weight = 0.0
            event.reason = "within_neutral_band"

        self.pub.publish(event)

        # event_type 전이만 INFO 로깅 (스팸 방지)
        if event.event_type != self._last_event_type:
            self.get_logger().info(
                f"event: {self._last_event_type} -> {event.event_type} "
                f"(V={v:.2f}, A={a:.2f}, conf={msg.confidence:.2f}, "
                f"abort_streak={self._abort_streak}, "
                f"normal_streak={self._normal_streak}, "
                f"reason={event.reason})"
            )
            self._last_event_type = event.event_type


def main(args=None):
    rclpy.init(args=args)
    node = RapportTrackerNode()
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
