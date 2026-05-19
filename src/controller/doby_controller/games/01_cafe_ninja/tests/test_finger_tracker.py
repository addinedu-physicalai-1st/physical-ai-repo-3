"""
test_finger_tracker.py - 검지 추적 + 스와이프 단위 테스트
"""

import math

import pytest

from finger_tracker import (
    DEFAULT_SLICE_SPEED_THRESHOLD,
    DEFAULT_TRAIL_LENGTH,
    FingerTrail,
    point_to_segment_distance,
    segment_speed,
)


class TestSegmentSpeed:
    def test_zero_distance(self):
        assert segment_speed((10, 10), (10, 10)) == 0.0

    @pytest.mark.parametrize("p1,p2,expected", [
        ((0, 0), (3, 4), 5.0),
        ((0, 0), (5, 0), 5.0),
        ((0, 0), (0, -7), 7.0),
        ((100, 100), (103, 104), 5.0),
    ])
    def test_known_distances(self, p1, p2, expected):
        assert segment_speed(p1, p2) == pytest.approx(expected)

    def test_symmetry(self):
        assert segment_speed((1, 2), (10, 20)) == segment_speed((10, 20), (1, 2))


class TestPointToSegmentDistance:
    def test_zero_length_segment_is_point_distance(self):
        # 선분이 한 점일 때 점-점 거리
        d = point_to_segment_distance((3, 4), (0, 0), (0, 0))
        assert d == pytest.approx(5.0)

    def test_point_on_segment(self):
        d = point_to_segment_distance((5, 0), (0, 0), (10, 0))
        assert d == pytest.approx(0.0)

    def test_perpendicular_distance(self):
        # 가로 선분 (0,0)-(10,0), 점 (5, 4) → 거리 4
        d = point_to_segment_distance((5, 4), (0, 0), (10, 0))
        assert d == pytest.approx(4.0)

    def test_clamped_to_start(self):
        # 점이 선분 시작점 너머 → 시작점까지 거리
        d = point_to_segment_distance((-3, 4), (0, 0), (10, 0))
        assert d == pytest.approx(5.0)

    def test_clamped_to_end(self):
        # 점이 선분 끝점 너머 → 끝점까지 거리
        d = point_to_segment_distance((13, 4), (0, 0), (10, 0))
        assert d == pytest.approx(5.0)

    def test_diagonal_segment(self):
        # 대각선 선분 (0,0)-(10,10), 점 (10, 0) → 수직 거리 = 5√2
        d = point_to_segment_distance((10, 0), (0, 0), (10, 10))
        assert d == pytest.approx(5.0 * math.sqrt(2))


class TestFingerTrailBasic:
    def test_initial_state(self):
        t = FingerTrail()
        assert t.get_trail() == []
        assert t.get_segment() is None
        assert t.get_current_speed() == 0.0
        assert not t.is_slicing()

    def test_update_appends(self):
        t = FingerTrail(max_length=5)
        t.update((10, 10))
        t.update((20, 20))
        assert t.get_trail() == [(10, 10), (20, 20)]

    def test_max_length_evicts_oldest(self):
        t = FingerTrail(max_length=3)
        for i in range(5):
            t.update((i, i))
        trail = t.get_trail()
        assert len(trail) == 3
        # 가장 오래된 (0,0), (1,1)은 빠지고 (2,2)부터 남음
        assert trail == [(2, 2), (3, 3), (4, 4)]

    def test_none_clears_trail(self):
        t = FingerTrail()
        t.update((10, 10))
        t.update((20, 20))
        assert len(t.get_trail()) == 2
        t.update(None)
        assert t.get_trail() == [], "None은 트레일을 끊어야 함"

    def test_reset(self):
        t = FingerTrail()
        for i in range(5):
            t.update((i, i))
        t.reset()
        assert t.get_trail() == []


class TestFingerTrailSegment:
    def test_segment_needs_two_points(self):
        t = FingerTrail()
        assert t.get_segment() is None
        t.update((1, 1))
        assert t.get_segment() is None  # 1점만으로는 선분 X
        t.update((2, 2))
        assert t.get_segment() == ((1, 1), (2, 2))

    def test_segment_uses_last_two(self):
        t = FingerTrail()
        for p in [(0, 0), (1, 1), (2, 2), (3, 3)]:
            t.update(p)
        # 항상 최신 두 점
        assert t.get_segment() == ((2, 2), (3, 3))


class TestFingerTrailSpeed:
    def test_speed_zero_for_stationary(self):
        t = FingerTrail()
        t.update((100, 100))
        t.update((100, 100))
        assert t.get_current_speed() == 0.0
        assert not t.is_slicing()

    def test_speed_below_threshold(self):
        t = FingerTrail(slice_speed_threshold=25.0)
        t.update((0, 0))
        t.update((10, 0))  # 10 px < 25 px
        assert t.get_current_speed() == 10.0
        assert not t.is_slicing()

    def test_speed_above_threshold_triggers_slicing(self):
        t = FingerTrail(slice_speed_threshold=25.0)
        t.update((0, 0))
        t.update((30, 40))  # 거리 50 > 25
        assert t.get_current_speed() == pytest.approx(50.0)
        assert t.is_slicing()

    def test_threshold_boundary_inclusive(self):
        t = FingerTrail(slice_speed_threshold=25.0)
        t.update((0, 0))
        t.update((25, 0))  # 정확히 임계값
        assert t.is_slicing(), "임계값 동등 시 슬라이스로 인정"

    def test_default_threshold_value(self):
        # 의도된 기본값을 회귀 방지로 못박음
        assert DEFAULT_SLICE_SPEED_THRESHOLD == 25.0
        assert DEFAULT_TRAIL_LENGTH == 10

    def test_slicing_resets_when_hand_disappears(self):
        t = FingerTrail(slice_speed_threshold=25.0)
        t.update((0, 0))
        t.update((30, 40))
        assert t.is_slicing()
        t.update(None)  # 손 사라짐
        assert not t.is_slicing()
        assert t.get_segment() is None
