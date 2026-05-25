"""geva_node 의 select_closest_track helper 단위 테스트.

PersonTrack ROS msg 의존 없이 duck typing (SimpleNamespace) 으로 검증.
spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §5.2, §10.1
"""
from types import SimpleNamespace as NS

from dobi_npc_emotion.geva_node import select_closest_track


def _track(track_id: int, group_id: int, bbox: list) -> NS:
    return NS(track_id=track_id, group_id=group_id, bbox=bbox)


def test_closest_empty_returns_none():
    """tracks=[] → None."""
    assert select_closest_track([]) is None


def test_closest_single_returns_only_track():
    """tracks 1개 → 그 track 반환."""
    t = _track(7, -1, [0.0, 0.0, 100.0, 100.0])
    result = select_closest_track([t])
    assert result is t


def test_closest_multi_largest_bbox_wins():
    """bbox area 가장 큰 track 선택."""
    tracks = [
        _track(1, -1, [0.0, 0.0, 10.0, 10.0]),    # area=100
        _track(2, 0, [0.0, 0.0, 50.0, 50.0]),     # area=2500 (largest)
        _track(3, 0, [0.0, 0.0, 30.0, 30.0]),     # area=900
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 2
    assert result.group_id == 0


def test_closest_negative_bbox_clamped_to_zero():
    """bbox 가 inverted (x2<x1) 인 경우 area=0 — 무시."""
    tracks = [
        _track(1, -1, [50.0, 50.0, 10.0, 10.0]),  # inverted → 0
        _track(2, -1, [0.0, 0.0, 5.0, 5.0]),      # area=25
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 2


def test_closest_tie_picks_first():
    """동일 bbox 크기 면 첫 번째 선택 (Python max stable)."""
    tracks = [
        _track(10, -1, [0.0, 0.0, 20.0, 20.0]),
        _track(20, -1, [100.0, 100.0, 120.0, 120.0]),
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 10
