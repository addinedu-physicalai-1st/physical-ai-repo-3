"""
test_spawner.py - 객체 출현 단위 테스트
"""

from collections import Counter

import pytest

from falling_object import KIND_BOMB, MENU_KINDS
from spawner import (
    BOMB_RATIO,
    DIFFICULTIES,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    MENU_WEIGHTS,
    MULTI_SPAWN_DIST,
    SPAWN_INTERVAL,
    Spawner,
)


class TestConstants:
    def test_difficulty_keys_match(self):
        assert set(SPAWN_INTERVAL) == set(DIFFICULTIES)
        assert set(BOMB_RATIO) == set(DIFFICULTIES)
        assert set(MULTI_SPAWN_DIST) == set(DIFFICULTIES)

    def test_intervals_decrease_with_difficulty(self):
        assert SPAWN_INTERVAL[DIFFICULTY_EASY] > SPAWN_INTERVAL[DIFFICULTY_NORMAL] > SPAWN_INTERVAL[DIFFICULTY_HARD]

    def test_bomb_ratios_increase_with_difficulty(self):
        assert BOMB_RATIO[DIFFICULTY_EASY] < BOMB_RATIO[DIFFICULTY_NORMAL] < BOMB_RATIO[DIFFICULTY_HARD]

    def test_multi_spawn_probabilities_sum_to_1(self):
        for diff, dist in MULTI_SPAWN_DIST.items():
            assert sum(dist) == pytest.approx(1.0), f"{diff}: 합 {sum(dist)}"

    def test_menu_weights_cover_all_menu_kinds(self):
        assert set(MENU_WEIGHTS.keys()) == set(MENU_KINDS)


class TestInit:
    def test_unknown_difficulty_raises(self):
        with pytest.raises(ValueError):
            Spawner(difficulty="insane")

    def test_initial_state(self):
        sp = Spawner(seed=1)
        assert sp.spawn_count == 0
        assert sp._accumulator == 0.0

    def test_reset(self):
        sp = Spawner(seed=1)
        sp.update(10.0)  # 충분한 시간 경과
        assert sp.spawn_count > 0
        sp.reset()
        assert sp.spawn_count == 0
        assert sp._accumulator == 0.0


class TestUpdateTiming:
    def test_no_spawn_before_interval(self):
        sp = Spawner(difficulty=DIFFICULTY_NORMAL, seed=1)
        # interval = 0.9 → 0.5초로는 spawn 없음
        spawned = sp.update(0.5)
        assert spawned == []
        assert sp.spawn_count == 0

    def test_spawn_after_interval(self):
        sp = Spawner(difficulty=DIFFICULTY_NORMAL, seed=1)
        spawned = sp.update(1.0)  # 0.9 초과
        assert len(spawned) >= 1
        assert sp.spawn_count == len(spawned)

    def test_multiple_intervals_in_one_update(self):
        sp = Spawner(difficulty=DIFFICULTY_NORMAL, seed=1)
        # 5초 → 5번 이상 spawn 누적
        spawned = sp.update(5.0)
        # interval 0.9초 기준 5초 동안 5번 spawn 발생
        # 각 spawn은 1~3개 객체이므로 최소 5개
        assert len(spawned) >= 5

    def test_force_spawn(self):
        sp = Spawner(seed=1)
        objs = sp.force_spawn()
        assert len(objs) >= 1
        assert sp.spawn_count == len(objs)


class TestSpawnContent:
    def test_objects_within_screen_bounds(self):
        sp = Spawner(screen_w=640, screen_h=480, seed=42)
        for _ in range(50):
            for o in sp.force_spawn():
                # x는 spawn 시점에 화면 안 (40 ~ screen_w-40)
                assert 40 <= o.x <= 600
                # y는 화면 하단 근처
                assert o.y >= 480

    def test_objects_have_upward_initial_vy(self):
        sp = Spawner(seed=42)
        for _ in range(20):
            for o in sp.force_spawn():
                # 화면 좌표에서 위로 솟구치려면 vy < 0
                assert o.vy < 0, f"{o.kind}: vy={o.vy}"

    def test_kinds_are_valid(self):
        sp = Spawner(seed=42)
        for _ in range(50):
            for o in sp.force_spawn():
                assert o.kind in (*MENU_KINDS, KIND_BOMB)

    def test_bomb_ratio_approximately_correct(self):
        # 큰 표본으로 폭탄 비율 검증 (난이도 hard에서 ~8%)
        sp = Spawner(difficulty=DIFFICULTY_HARD, seed=2026)
        kinds = []
        for _ in range(2000):
            kinds.extend(o.kind for o in sp.force_spawn())
        bomb_count = sum(1 for k in kinds if k == KIND_BOMB)
        ratio = bomb_count / len(kinds)
        target = BOMB_RATIO[DIFFICULTY_HARD]
        # ±50% 허용 범위 (랜덤 노이즈 감안)
        assert target * 0.5 <= ratio <= target * 1.5, (
            f"폭탄 비율 {ratio:.3f}이 기대 {target} 범위 밖"
        )

    def test_seed_reproducibility(self):
        a = Spawner(difficulty=DIFFICULTY_NORMAL, seed=999)
        b = Spawner(difficulty=DIFFICULTY_NORMAL, seed=999)
        for _ in range(10):
            la = a.force_spawn()
            lb = b.force_spawn()
            assert len(la) == len(lb)
            for oa, ob in zip(la, lb):
                assert oa.kind == ob.kind
                assert oa.x == ob.x
                assert oa.y == ob.y


class TestBatchSize:
    def test_easy_rarely_multispawns(self):
        # easy: (0.85, 0.15, 0.0) — 거의 1개씩
        sp = Spawner(difficulty=DIFFICULTY_EASY, seed=2026)
        size_dist = Counter()
        for _ in range(2000):
            objs = sp.force_spawn()
            size_dist[len(objs)] += 1
        # 1개 spawn이 압도적이어야 함
        assert size_dist[1] / sum(size_dist.values()) > 0.75
        assert size_dist[3] == 0  # easy에는 3개 동시 X

    def test_hard_has_more_multispawns(self):
        # hard: (0.55, 0.30, 0.15) — 다중 spawn 다수
        sp = Spawner(difficulty=DIFFICULTY_HARD, seed=2026)
        size_dist = Counter()
        for _ in range(2000):
            objs = sp.force_spawn()
            size_dist[len(objs)] += 1
        # 다중(2~3) spawn이 30% 이상
        multi = size_dist[2] + size_dist[3]
        assert multi / sum(size_dist.values()) > 0.30
