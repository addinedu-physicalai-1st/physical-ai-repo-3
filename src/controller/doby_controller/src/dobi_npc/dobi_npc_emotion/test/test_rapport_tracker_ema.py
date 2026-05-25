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


def test_sustained_high_conf_reaches_90pct_within_4_frames():
    """V=0.5 conf=1.0 sustained — α=0.5 EMA 가 4 frame 안에 90% 도달.

    수식: 1 - (1-0.5)^4 = 0.9375 (4 frame 누적 후 v_smooth ≈ 0.469).
    """
    s = EMAState()
    # cold start (frame 0): v_smooth = 0.5
    s.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # frame 1-3
    for _ in range(3):
        s.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # cold start 이미 0.5 라 frame 1-3 도 0.5 (변화 없음)
    assert abs(s.v_smooth - 0.5) < 1e-6

    # 다른 target 으로 변화 검증 — cold start 후 4 frame 동안 0 → 0.5 추적
    s2 = EMAState()
    s2.update(0.0, 0.0, 1.0, False, ALPHA, GATE)   # cold start at 0
    for _ in range(4):
        s2.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # 1 - (1-0.5)^4 = 0.9375 → v_smooth ≈ 0.4688
    assert s2.v_smooth > 0.46
    assert s2.v_smooth < 0.48


def test_conf_gate_skips_low_confidence():
    """conf=0.2 (gate=0.3 미만) frame → EMA update 안 됨."""
    s = EMAState()
    # cold start
    s.update(0.4, -0.2, 0.9, False, ALPHA, GATE)
    assert s.v_smooth == 0.4

    # low conf frame — 새 값 무시
    s.update(-0.9, 0.9, 0.2, False, ALPHA, GATE)
    assert s.v_smooth == 0.4    # 변경 없음
    assert s.a_smooth == -0.2

    # gate 경계 (conf=0.3) — gate 미만 X (>=0.3 OK)
    s.update(0.6, 0.0, 0.3, False, ALPHA, GATE)
    # weight = 0.5 * 0.3 = 0.15
    # v_smooth = 0.15*0.6 + 0.85*0.4 = 0.43
    assert abs(s.v_smooth - 0.43) < 1e-6


def test_no_signal_preserves_state():
    """no_signal=True (conf=0 또는 no_face flag) → EMA 변경 없음."""
    s = EMAState()
    s.update(0.4, -0.2, 0.9, False, ALPHA, GATE)   # cold start
    assert s.v_smooth == 0.4

    # no_signal — 새 값 완전 무시
    s.update(-1.0, 1.0, 0.0, True, ALPHA, GATE)
    assert s.v_smooth == 0.4
    assert s.a_smooth == -0.2

    # no_signal 후에도 다음 valid frame 정상 처리
    s.update(0.6, 0.0, 1.0, False, ALPHA, GATE)
    # weight = 0.5 * 1.0 = 0.5
    # v_smooth = 0.5*0.6 + 0.5*0.4 = 0.5
    assert s.v_smooth == 0.5


def test_no_signal_before_cold_start():
    """첫 frame 부터 no_signal — smoothed 가 None 유지."""
    s = EMAState()
    s.update(0.4, -0.2, 0.0, True, ALPHA, GATE)
    assert s.v_smooth is None
    assert s.a_smooth is None


def test_outlier_absorbed_one_frame_does_not_reach_abort_zone():
    """정상 4 frame + outlier 1 frame — smoothed 가 abort-zone 미달.

    abort-zone: V<-0.5 ∧ A>+0.4.
    정상 frame V=0.0 A=0.0 sustained → smoothed 가 0 근처.
    outlier 1 frame V=-1.0 A=+1.0 conf=1.0 → weight=0.5 → smoothed 가 절반만 이동.
    """
    s = EMAState()
    # cold start at neutral
    s.update(0.0, 0.0, 1.0, False, ALPHA, GATE)
    # 정상 3 frame 더
    for _ in range(3):
        s.update(0.0, 0.0, 1.0, False, ALPHA, GATE)
    assert s.v_smooth == 0.0

    # outlier 1 frame
    s.update(-1.0, 1.0, 1.0, False, ALPHA, GATE)
    # weight=0.5 → v_smooth = 0.5*-1.0 + 0.5*0 = -0.5
    # abort-zone 경계: V<-0.5 (strict less than), A>+0.4 — V=-0.5 미달
    assert s.v_smooth == -0.5
    assert s.a_smooth == 0.5
    # raw_abort 조건 (rapport_tracker_node.py 의 ABORT_VALENCE_MAX=-0.5) — v<-0.5 가 strict
    # v_smooth == -0.5 면 raw_abort=False
    assert not (s.v_smooth < -0.5 and s.a_smooth > 0.4)
