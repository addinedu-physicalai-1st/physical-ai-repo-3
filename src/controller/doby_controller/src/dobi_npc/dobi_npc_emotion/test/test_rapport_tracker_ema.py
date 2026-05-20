"""rapport_tracker EMA smoothing 단위 테스트.

EMAState 를 pure dataclass 로 분리해 rclpy 의존 없이 검증.
spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md
"""
from dobi_npc_emotion.rapport_tracker_node import EMAState


ALPHA = 0.5
GATE = 0.3


def test_cold_start_adopts_raw():
    """첫 valid frame (no_signal=False, conf>=gate) → smoothed = raw."""
    s = EMAState()
    s.update(v_now=0.4, a_now=-0.2, conf=0.9,
             no_signal=False, alpha_base=ALPHA, conf_min_gate=GATE)
    assert s.v_smooth == 0.4
    assert s.a_smooth == -0.2
