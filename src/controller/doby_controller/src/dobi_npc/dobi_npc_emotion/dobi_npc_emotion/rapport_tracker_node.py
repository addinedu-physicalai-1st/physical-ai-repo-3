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
  - [x] 윈도우 평균 V·A (2026-05-20 confidence-weighted EMA 도입, spec §3)
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
        """confidence-weighted EMA update.

        no_signal=True (caller 가 conf<=0 또는 'no_face' flag 감지) → state 보존.
        conf < conf_min_gate → update skip.
        cold start (v_smooth=None) → raw 채택. 이후 weight=alpha_base*conf EMA.
        """
        if no_signal:
            return  # 사람 안 보임 — state 보존
        if conf < conf_min_gate:
            return  # 자신없는 frame skip
        if self.v_smooth is None:
            # cold start — 첫 valid frame 그대로 채택
            if self.a_smooth is not None:
                raise RuntimeError(
                    "EMAState invariant 위반: v_smooth is None 이나 a_smooth 가 set"
                )
            self.v_smooth = v_now
            self.a_smooth = a_now
            return
        # weight clamp — 미래 source (GEFA 등) 의 conf > 1.0 또는 alpha 잘못된 값 방어
        weight = min(alpha_base * conf, 1.0)
        self.v_smooth = weight * v_now + (1 - weight) * self.v_smooth
        self.a_smooth = weight * a_now + (1 - weight) * self.a_smooth


def should_reset_ema_on_track_change(last: int, current: int) -> bool:
    """track_id 변경 시 EMA cold start 여부 판정.

    - last == current: 같은 손님 — reset 안 함
    - last == -1: 첫 valid track — fallback 채택, reset 안 함 (cold start 가 EMAState 의
      v_smooth=None 자연 처리)
    - current == -1: 일시적 unknown (person_tracking 끊김) — EMA 보존
    - last != current 둘 다 valid: 손님 전환 — reset

    spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §6
    """
    if current == -1:
        return False
    if last == -1:
        return False
    return last != current


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
        # 2026-05-20 — confidence-weighted EMA 파라미터 (spec §5)
        self.declare_parameter('ema_alpha_base', 0.5)
        self.declare_parameter('conf_min_gate', 0.3)

        in_topic = self.get_parameter('input_topic').value
        out_topic = self.get_parameter('output_topic').value
        self._abort_on_count = int(self.get_parameter('abort_on_count').value)
        self._abort_off_count = int(self.get_parameter('abort_off_count').value)
        self._ema_alpha_base = float(self.get_parameter('ema_alpha_base').value)
        self._conf_min_gate = float(self.get_parameter('conf_min_gate').value)
        self._ema = EMAState()

        self.sub = self.create_subscription(
            EmotionState, in_topic, self._on_emotion, 10
        )
        self.pub = self.create_publisher(RapportEvent, out_topic, 10)

        # hysteresis 상태
        self._abort_streak = 0
        self._normal_streak = 0
        self._currently_aborting = False

        self._last_event_type = None
        # 2026-05-21 Track B — 손님 전환 감지
        self._last_track_id: int = -1
        self.get_logger().info(
            f"rapport_tracker: {in_topic} -> {out_topic}, "
            f"hysteresis on={self._abort_on_count} off={self._abort_off_count}, "
            f"EMA α_base={self._ema_alpha_base} gate={self._conf_min_gate}"
        )

    def _on_emotion(self, msg: EmotionState):
        event = RapportEvent()
        event.header.stamp = self.get_clock().now().to_msg()
        event.header.frame_id = msg.header.frame_id
        event.emotion = msg

        # 2026-05-21 Track B — track_id 변경 시 EMA cold start
        if should_reset_ema_on_track_change(self._last_track_id, msg.track_id):
            self.get_logger().info(
                f"customer 전환: track_id {self._last_track_id} → {msg.track_id} "
                f"(EMA cold start)")
            self._ema = EMAState()
        if msg.track_id != -1:
            self._last_track_id = msg.track_id

        no_signal = (msg.confidence <= 0.0) or ("no_face" in msg.flags)

        # 2026-05-20 EMA update (spec §3) — smoothed V·A 로 분류
        self._ema.update(
            v_now=msg.valence, a_now=msg.arousal, conf=msg.confidence,
            no_signal=no_signal,
            alpha_base=self._ema_alpha_base,
            conf_min_gate=self._conf_min_gate,
        )
        # smoothed 가 아직 없으면 (전부 no_signal/low_conf) raw 사용 — cold start fallback
        v = self._ema.v_smooth if self._ema.v_smooth is not None else msg.valence
        a = self._ema.a_smooth if self._ema.a_smooth is not None else msg.arousal

        # 2026-05-20 — RapportEvent.emotion.valence/arousal 만 smoothed (spec §6)
        # confidence/source/flags 는 raw 그대로 (운영자 디버깅)
        event.emotion.valence = v
        event.emotion.arousal = a

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
