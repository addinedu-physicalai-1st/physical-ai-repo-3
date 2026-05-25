"""
test_zombie.py — Zombie dataclass + 운동 단위 테스트
=======================================================

검증:
- step()으로 y 증가
- position() 정수 변환
- is_off_screen / has_passed_bottom
- kind별 radius·속도
- make_zombie 기본값 + 잘못된 kind 예외
- dodged·passed flag 초기 False
"""

import pytest

from zombie import (
    ALL_KINDS,
    KIND_BIG,
    KIND_FAST,
    KIND_NORMAL,
    KIND_RADIUS,
    KIND_SPEED_MULTIPLIER,
    Zombie,
    make_zombie,
)


# ============================================================
# 1. step / position
# ============================================================
class TestStep:
    def test_step_increases_y_by_vy(self):
        z = make_zombie(x=100.0, y=50.0, vy=5.0)
        z.step()
        assert z.y == 55.0

    def test_step_multiple_times(self):
        z = make_zombie(x=100.0, y=0.0, vy=3.0)
        for _ in range(10):
            z.step()
        assert z.y == 30.0

    def test_position_returns_int_tuple(self):
        z = make_zombie(x=100.7, y=50.3, vy=5.0)
        p = z.position()
        assert p == (100, 50)
        assert isinstance(p[0], int)


# ============================================================
# 2. is_off_screen / has_passed_bottom
# ============================================================
class TestBoundary:
    def test_off_screen_when_above_screen(self):
        z = make_zombie(x=100.0, y=600.0, vy=5.0, kind=KIND_NORMAL)
        # frame_h=480, y=600 > 480 + radius
        assert z.is_off_screen(640, 480) is True

    def test_not_off_screen_when_visible(self):
        z = make_zombie(x=100.0, y=200.0, vy=5.0, kind=KIND_NORMAL)
        assert z.is_off_screen(640, 480) is False

    def test_has_passed_bottom_true(self):
        z = make_zombie(x=100.0, y=400.0, vy=5.0)
        assert z.has_passed_bottom(480, dodge_y_threshold=350) is True

    def test_has_passed_bottom_false(self):
        z = make_zombie(x=100.0, y=300.0, vy=5.0)
        assert z.has_passed_bottom(480, dodge_y_threshold=350) is False


# ============================================================
# 3. kind별 속성
# ============================================================
class TestKinds:
    def test_normal_radius(self):
        z = make_zombie(x=0, y=0, vy=1.0, kind=KIND_NORMAL)
        assert z.radius == KIND_RADIUS[KIND_NORMAL]

    def test_fast_smaller(self):
        # fast는 normal보다 작음 (빠른 객체 시각화)
        assert KIND_RADIUS[KIND_FAST] < KIND_RADIUS[KIND_NORMAL]

    def test_big_bigger(self):
        assert KIND_RADIUS[KIND_BIG] > KIND_RADIUS[KIND_NORMAL]

    def test_fast_speed_multiplier(self):
        assert KIND_SPEED_MULTIPLIER[KIND_FAST] > 1.0

    def test_big_slower(self):
        assert KIND_SPEED_MULTIPLIER[KIND_BIG] < 1.0

    def test_all_kinds_present_in_maps(self):
        for k in ALL_KINDS:
            assert k in KIND_RADIUS
            assert k in KIND_SPEED_MULTIPLIER


# ============================================================
# 4. make_zombie 헬퍼
# ============================================================
class TestMakeZombie:
    def test_basic(self):
        z = make_zombie(x=100, y=50, vy=4.0)
        assert isinstance(z, Zombie)
        assert z.kind == KIND_NORMAL
        assert z.dodged is False
        assert z.passed is False

    def test_explicit_kind(self):
        z = make_zombie(x=0, y=0, vy=1.0, kind=KIND_FAST)
        assert z.kind == KIND_FAST
        assert z.radius == KIND_RADIUS[KIND_FAST]

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            make_zombie(x=0, y=0, vy=1.0, kind="boss")
