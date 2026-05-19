"""
test_falling_object.py - 포물선 운동 단위 테스트
"""

import math

import pytest

from falling_object import (
    ALL_KINDS,
    CAKE_RADIUS,
    DEFAULT_GRAVITY,
    DEFAULT_RADIUS,
    DESPAWN_MARGIN,
    FallingObject,
    KIND_BOMB,
    KIND_CAKE,
    MENU_KINDS,
    initial_velocity_for_peak,
)


class TestKinds:
    def test_all_kinds_count(self):
        assert len(ALL_KINDS) == 6
        assert KIND_BOMB in ALL_KINDS

    def test_menu_kinds_excludes_bomb(self):
        assert KIND_BOMB not in MENU_KINDS
        assert len(MENU_KINDS) == 5


class TestStep:
    def test_step_advances_position(self):
        obj = FallingObject(kind="latte", x=100, y=400, vx=2.0, vy=-10.0)
        obj.step()
        # vy가 -10 + 0.5 = -9.5로 갱신된 후 위치 적용
        assert obj.x == pytest.approx(102.0)
        assert obj.y == pytest.approx(400 + (-10.0 + DEFAULT_GRAVITY))
        assert obj.age == 1

    def test_gravity_pulls_down(self):
        obj = FallingObject(kind="latte", x=100, y=400, vx=0.0, vy=-20.0)
        for _ in range(60):
            obj.step()
        # 중력에 의해 vy가 충분히 양수로 변해야 함
        assert obj.vy > 0
        assert obj.vy == pytest.approx(-20.0 + DEFAULT_GRAVITY * 60)

    def test_parabolic_peak(self):
        # vy가 양수로 전환되는 시점 직전이 peak
        obj = FallingObject(kind="americano", x=320, y=520, vx=0.0, vy=-15.0)
        prev_y = obj.y
        peak_y = obj.y
        for _ in range(200):
            obj.step()
            if obj.y < peak_y:
                peak_y = obj.y
        # peak는 시작점보다 위에 있어야 함 (y가 더 작음)
        assert peak_y < 520

    def test_angle_wraps_to_360(self):
        obj = FallingObject(kind="latte", x=0, y=0, vx=0, vy=0,
                            angular_vel=100.0)
        obj.step()
        obj.step()
        obj.step()
        obj.step()
        # 4 * 100 = 400 → 360 + 40 → 40
        assert obj.angle == pytest.approx(40.0)

    def test_zero_angular_velocity(self):
        obj = FallingObject(kind="cake", x=0, y=0, vx=0, vy=0)
        for _ in range(10):
            obj.step()
        assert obj.angle == 0.0


class TestOffScreen:
    def test_inside_screen(self):
        obj = FallingObject(kind="latte", x=320, y=240, vx=0, vy=0)
        assert not obj.is_off_screen(640, 480)

    def test_below_screen(self):
        obj = FallingObject(kind="latte", x=320, y=480 + DESPAWN_MARGIN + 1,
                            vx=0, vy=0)
        assert obj.is_off_screen(640, 480)

    def test_above_screen_safety(self):
        # 비정상적으로 위로 사라진 경우 (테스트용)
        obj = FallingObject(kind="latte", x=320, y=-DESPAWN_MARGIN * 3 - 1,
                            vx=0, vy=0)
        assert obj.is_off_screen(640, 480)

    def test_left_screen(self):
        obj = FallingObject(kind="latte", x=-DESPAWN_MARGIN - 1, y=240,
                            vx=0, vy=0)
        assert obj.is_off_screen(640, 480)

    def test_right_screen(self):
        obj = FallingObject(kind="latte", x=640 + DESPAWN_MARGIN + 1, y=240,
                            vx=0, vy=0)
        assert obj.is_off_screen(640, 480)


class TestDefaults:
    def test_default_radius(self):
        obj = FallingObject(kind="latte", x=0, y=0, vx=0, vy=0)
        assert obj.radius == DEFAULT_RADIUS
        assert obj.sliced is False
        assert obj.age == 0

    def test_cake_uses_larger_radius(self):
        # spawner.py에서 케이크는 CAKE_RADIUS로 만들어지지만,
        # 데이터클래스 자체에 강제는 없음 — 호출자 책임
        obj = FallingObject(kind=KIND_CAKE, x=0, y=0, vx=0, vy=0,
                            radius=CAKE_RADIUS)
        assert obj.radius == CAKE_RADIUS
        assert obj.radius > DEFAULT_RADIUS

    def test_position_returns_int_tuple(self):
        obj = FallingObject(kind="latte", x=100.7, y=200.3, vx=0, vy=0)
        pos = obj.position()
        assert pos == (100, 200)
        assert isinstance(pos[0], int)


class TestInitialVelocityForPeak:
    def test_zero_height_returns_zero(self):
        # peak가 현재 위치와 같거나 위에 있지 않으면 0
        assert initial_velocity_for_peak(500, 500) == 0.0
        assert initial_velocity_for_peak(600, 500) == 0.0  # peak가 더 아래

    def test_velocity_is_negative_upward(self):
        # 화면 좌표: peak < current → 위로 이동 → vy 음수
        v = initial_velocity_for_peak(target_peak_y=100, current_y=500)
        assert v < 0

    def test_velocity_reaches_target(self):
        # 운동방정식 검증: 시작 (y=500, vy=v0)에서 중력 0.5로 peak=100까지
        gravity = 0.5
        target = 100.0
        start = 500.0
        v0 = initial_velocity_for_peak(target, start, gravity)

        # 시뮬레이션으로 peak y 추적
        y = start
        vy = v0
        peak = y
        for _ in range(200):
            vy += gravity
            y += vy
            if y < peak:
                peak = y
            if vy > 0:
                break

        # Euler 적분(vy → y 순서)의 이산화 오차로 연속 공식 대비
        # 약 g/2 만큼 더 낮게(=y가 더 큼) 도달. 게임 물리 용도로는 충분.
        # 화면 480px 기준 ~3% 오차는 허용 범위.
        assert abs(peak - target) < 15.0

    def test_higher_peak_means_faster(self):
        v1 = initial_velocity_for_peak(300, 500)
        v2 = initial_velocity_for_peak(100, 500)
        # 더 높이 솟구치려면 vy 절댓값이 커야 함
        assert abs(v2) > abs(v1)
