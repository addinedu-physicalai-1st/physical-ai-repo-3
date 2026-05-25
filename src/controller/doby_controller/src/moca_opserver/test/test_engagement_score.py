"""opserver engagement_score helpers 단위 테스트.

ROS 노드 의존 없이 pure function 검증.
spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §4
"""
from moca_opserver.opserver_node import (
    compute_engagement_ema,
    should_reset_engagement_score,
    is_marker_eligible,
)


ALPHA = 0.1


def test_compute_ema_cold_start_first_update():
    """첫 update (prev=0.0) — weight 의 alpha 비율만 반영."""
    result = compute_engagement_ema(prev=0.0, weight=0.5, alpha=ALPHA)
    # 0.1*0.5 + 0.9*0.0 = 0.05
    assert abs(result - 0.05) < 1e-9


def test_compute_ema_accumulate_positive():
    """weight=+0.5 sustained — score 가 0.5 로 점근."""
    score = 0.0
    for _ in range(50):
        score = compute_engagement_ema(score, weight=0.5, alpha=ALPHA)
    # 50 frame 후 90% 도달 이상 — 0.45 < score < 0.5
    assert 0.45 < score < 0.5


def test_compute_ema_accumulate_negative():
    """weight=-1.0 sustained — score 가 -1.0 로 점근."""
    score = 0.0
    for _ in range(50):
        score = compute_engagement_ema(score, weight=-1.0, alpha=ALPHA)
    assert -1.0 < score < -0.9


def test_should_reset_on_first_valid_track():
    """last=-1, current=5 — first valid track, reset 안 함."""
    assert should_reset_engagement_score(last=-1, current=5) is False


def test_should_reset_on_track_change():
    """last=42, current=99 — 손님 전환, reset."""
    assert should_reset_engagement_score(last=42, current=99) is True


def test_should_reset_no_reset_on_unknown():
    """last=42, current=-1 — 일시 unknown, EMA 보존."""
    assert should_reset_engagement_score(last=42, current=-1) is False


def test_should_reset_no_reset_on_same():
    """last=42, current=42 — 같은 손님, reset 안 함."""
    assert should_reset_engagement_score(last=42, current=42) is False


def test_marker_eligible_filters_neutral_and_no_signal():
    """engagement_up/down/abort_trigger 만 marker. neutral_continue/no_signal 제외."""
    assert is_marker_eligible('engagement_up') is True
    assert is_marker_eligible('engagement_down') is True
    assert is_marker_eligible('abort_trigger') is True
    assert is_marker_eligible('neutral_continue') is False
    assert is_marker_eligible('') is False
    assert is_marker_eligible('unknown_type') is False
