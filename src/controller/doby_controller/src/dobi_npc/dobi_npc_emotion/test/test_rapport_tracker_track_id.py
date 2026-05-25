#!/usr/bin/env python3
"""rapport_tracker track_id 변경 시 EMA cold start 검증.

EMA 자체는 test_rapport_tracker_ema.py 가 검증. 본 파일은 reset trigger 만.
spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §6, §10.1
"""
from dobi_npc_emotion.rapport_tracker_node import (
    EMAState,
    should_reset_ema_on_track_change,
)


def test_reset_on_first_valid_track():
    """이전 track_id=-1, 새 track_id 가 valid (예: 5) — 첫 valid 채택,
    reset 안 함 (cold start fallback 이 EMAState 첫 update 에서 자연 처리)."""
    assert should_reset_ema_on_track_change(last=-1, current=5) is False


def test_reset_on_track_change_valid_to_valid():
    """이전 track_id=5, 새 track_id=7 — 손님 전환, reset."""
    assert should_reset_ema_on_track_change(last=5, current=7) is True


def test_no_reset_on_unknown_track():
    """이전 track_id=5, 새 track_id=-1 (person_tracking 일시 끊김)
    — EMA 보존 (fallback)."""
    assert should_reset_ema_on_track_change(last=5, current=-1) is False


def test_no_reset_on_same_track():
    """이전 track_id=5, 새 track_id=5 — 같은 손님, reset 안 함."""
    assert should_reset_ema_on_track_change(last=5, current=5) is False
