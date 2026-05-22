"""
test_zombie_spawner.py — Spawn 로직 단위 테스트
=====================================================

검증:
- 시간 누적 → spawn (interval 도달)
- 짧은 dt 누적해도 spawn (interval 동안)
- 시드 재현성 + 인스턴스 격리
- 난이도별 단조성 (interval 감소, speed 증가)
- 종류 분포 (easy는 normal 위주, hard는 fast 비중 ↑)
- 잘못된 입력 예외
"""

from collections import Counter

import pytest

from zombie import KIND_BIG, KIND_FAST, KIND_NORMAL
from zombie_spawner import (
    DEFAULT_X_MARGIN_RATIO,
    DIFFICULTIES,
    DIFFICULTY_CONFIG,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    Spawner,
)


# ============================================================
# 1. spawn 동작
# ============================================================
class TestSpawning:
    def test_first_spawn_after_short_dt(self):
        # 첫 spawn은 interval의 절반 (시작 직후 정적 방지)
        sp = Spawner(DIFFICULTY_NORMAL, frame_width=640, frame_height=480,
                     seed=0)
        # NORMAL interval 1.0초, 첫 next_interval = 0.5
        new = sp.update(0.6)
        assert len(new) >= 1
        assert sp.spawned_total >= 1

    def test_no_spawn_before_interval(self):
        sp = Spawner(DIFFICULTY_NORMAL, seed=0)
        new = sp.update(0.2)  # < 0.5 (first interval)
        assert new == []

    def test_multiple_spawns_in_one_update(self):
        # 큰 dt 한 번에 여러 마리 생성 가능
        sp = Spawner(DIFFICULTY_NORMAL, seed=0)
        new = sp.update(5.0)  # ~ 5초 → 4~5마리
        assert len(new) >= 3

    def test_x_within_frame(self):
        sp = Spawner(DIFFICULTY_NORMAL, frame_width=640, frame_height=480,
                     seed=0)
        new = sp.update(5.0)
        for z in new:
            # margin 적용 후 좌우 안에
            margin = int(640 * DEFAULT_X_MARGIN_RATIO)
            assert margin <= z.x <= 640 - margin

    def test_y_starts_above_screen(self):
        sp = Spawner(DIFFICULTY_NORMAL, seed=0)
        new = sp.update(2.0)
        for z in new:
            # 위에서 떨어지므로 시작 y는 음수
            assert z.y <= 0


# ============================================================
# 2. 시드 재현성 / 격리
# ============================================================
class TestSeed:
    def test_same_seed_same_sequence(self):
        a = Spawner(DIFFICULTY_NORMAL, seed=777)
        b = Spawner(DIFFICULTY_NORMAL, seed=777)
        za = a.update(10.0)
        zb = b.update(10.0)
        assert len(za) == len(zb)
        for z1, z2 in zip(za, zb):
            assert z1.kind == z2.kind
            assert z1.x == z2.x

    def test_instance_isolation(self):
        # 두 인스턴스가 같은 시드라도 한쪽 진행이 다른 쪽에 영향 X
        a = Spawner(DIFFICULTY_NORMAL, seed=42)
        b = Spawner(DIFFICULTY_NORMAL, seed=42)
        a.update(10.0)
        zb = b.update(2.0)
        c = Spawner(DIFFICULTY_NORMAL, seed=42)
        zc = c.update(2.0)
        # b와 c (둘 다 신선)는 동일 결과
        assert len(zb) == len(zc)
        for z1, z2 in zip(zb, zc):
            assert z1.kind == z2.kind
            assert z1.x == z2.x


# ============================================================
# 3. 난이도 단조성
# ============================================================
class TestDifficultyMonotonic:
    def test_spawn_interval_decreases(self):
        e = DIFFICULTY_CONFIG[DIFFICULTY_EASY]["spawn_interval"]
        n = DIFFICULTY_CONFIG[DIFFICULTY_NORMAL]["spawn_interval"]
        h = DIFFICULTY_CONFIG[DIFFICULTY_HARD]["spawn_interval"]
        assert e > n > h

    def test_base_speed_increases(self):
        e = DIFFICULTY_CONFIG[DIFFICULTY_EASY]["base_speed"]
        n = DIFFICULTY_CONFIG[DIFFICULTY_NORMAL]["base_speed"]
        h = DIFFICULTY_CONFIG[DIFFICULTY_HARD]["base_speed"]
        assert e < n < h

    def test_fast_only_in_normal_and_hard(self):
        # EASY는 fast 가중치 0
        assert DIFFICULTY_CONFIG[DIFFICULTY_EASY]["kind_weights"][KIND_FAST] == 0
        # HARD는 fast 가중치가 NORMAL보다 큼
        n_fast = DIFFICULTY_CONFIG[DIFFICULTY_NORMAL]["kind_weights"][KIND_FAST]
        h_fast = DIFFICULTY_CONFIG[DIFFICULTY_HARD]["kind_weights"][KIND_FAST]
        assert h_fast > n_fast


# ============================================================
# 4. 종류 분포
# ============================================================
class TestKindDistribution:
    def test_easy_has_no_fast(self):
        sp = Spawner(DIFFICULTY_EASY, seed=42)
        # 100마리 정도 뽑아서 fast가 나오는지
        z_list = []
        for _ in range(30):
            z_list.extend(sp.update(1.4))
        kinds = Counter(z.kind for z in z_list)
        assert kinds[KIND_FAST] == 0
        # normal 비중 압도적
        if z_list:
            assert kinds[KIND_NORMAL] >= len(z_list) * 0.7

    def test_hard_has_fast(self):
        sp = Spawner(DIFFICULTY_HARD, seed=42)
        z_list = []
        for _ in range(30):
            z_list.extend(sp.update(0.7))
        kinds = Counter(z.kind for z in z_list)
        # hard는 fast 35% 비중이라 충분한 표본에서 다수 등장
        assert kinds[KIND_FAST] > 0


# ============================================================
# 5. Reset / 예외
# ============================================================
class TestMisc:
    def test_reset_clears_counters(self):
        sp = Spawner(DIFFICULTY_NORMAL, seed=42)
        sp.update(5.0)
        assert sp.spawned_total > 0
        sp.reset()
        assert sp.spawned_total == 0
        assert sp.time_since_last == 0.0

    def test_invalid_difficulty(self):
        with pytest.raises(ValueError):
            Spawner("apocalypse", seed=0)

    def test_all_difficulties_in_config(self):
        assert set(DIFFICULTIES) == set(DIFFICULTY_CONFIG.keys())
