"""
test_slice_judge.py - 충돌 판정 + 콤보 점수 단위 테스트
"""

import pytest

from falling_object import FallingObject, KIND_BOMB
from slice_judge import (
    KIND_SCORES,
    SliceResult,
    combo_multiplier,
    judge_slice,
)


def make_obj(kind="americano", x=320, y=240, radius=36):
    """테스트용 정지 객체 생성"""
    return FallingObject(kind=kind, x=x, y=y, vx=0, vy=0, radius=radius)


class TestComboMultiplier:
    @pytest.mark.parametrize("n,expected", [
        (0, 1.0), (1, 1.0),
        (2, 1.5),
        (3, 2.0),
        (4, 3.0), (5, 3.0), (10, 3.0),
    ])
    def test_known_values(self, n, expected):
        assert combo_multiplier(n) == expected


class TestKindScores:
    def test_all_menu_kinds_have_score(self):
        for kind in ["americano", "latte", "cappuccino", "cake", "croissant"]:
            assert kind in KIND_SCORES
            assert KIND_SCORES[kind] > 0

    def test_bomb_has_no_score(self):
        assert KIND_BOMB not in KIND_SCORES

    def test_score_ordering(self):
        # 더 비싼 메뉴가 더 높은 점수
        assert KIND_SCORES["americano"] < KIND_SCORES["latte"]
        assert KIND_SCORES["latte"] < KIND_SCORES["cappuccino"]
        assert KIND_SCORES["cappuccino"] <= KIND_SCORES["cake"]


class TestJudgeNoSegment:
    def test_none_segment_returns_empty_result(self):
        objs = [make_obj()]
        r = judge_slice(None, objs)
        assert r.sliced_objects == []
        assert r.bomb_count == 0
        assert r.score_gained == 0
        # 객체는 손대지 않음
        assert objs[0].sliced is False


class TestSingleSlice:
    def test_segment_passes_through_object(self):
        # 객체 (320, 240) 반지름 36 — 가로 선분 (200, 240)→(440, 240)이 통과
        obj = make_obj("americano", x=320, y=240)
        seg = ((200, 240), (440, 240))
        r = judge_slice(seg, [obj])
        assert obj in r.sliced_objects
        assert obj.sliced is True
        assert r.score_gained == KIND_SCORES["americano"]
        assert r.multiplier == 1.0

    def test_segment_misses_object(self):
        obj = make_obj("americano", x=320, y=240, radius=36)
        # 객체 위로 100px 떨어진 선분 → 거리 100 > 반지름 36
        seg = ((200, 140), (440, 140))
        r = judge_slice(seg, [obj])
        assert r.sliced_objects == []
        assert obj.sliced is False
        assert r.score_gained == 0

    def test_segment_grazes_within_radius(self):
        # 거리가 정확히 반지름과 같으면 슬라이스 인정
        obj = make_obj("latte", x=320, y=240, radius=36)
        seg = ((200, 240 + 36), (440, 240 + 36))  # 위치적으로 정확히 36px 아래
        r = judge_slice(seg, [obj])
        assert obj in r.sliced_objects

    def test_already_sliced_object_skipped(self):
        obj = make_obj("americano")
        obj.sliced = True
        seg = ((200, 240), (440, 240))
        r = judge_slice(seg, [obj])
        assert r.sliced_objects == []
        assert r.score_gained == 0


class TestMultiSliceCombo:
    def test_two_objects_combo_multiplier(self):
        a = make_obj("americano", x=200, y=240)
        b = make_obj("latte", x=440, y=240)
        seg = ((100, 240), (540, 240))  # 두 객체 모두 통과
        r = judge_slice(seg, [a, b])
        assert len(r.sliced_objects) == 2
        assert r.multiplier == 1.5
        # base = 10 + 15 = 25, 25 * 1.5 = 37.5 → 38 (round)
        assert r.score_gained == 38

    def test_three_objects_combo(self):
        objs = [
            make_obj("americano", x=160, y=240),
            make_obj("latte", x=320, y=240),
            make_obj("cappuccino", x=480, y=240),
        ]
        seg = ((50, 240), (600, 240))
        r = judge_slice(seg, objs)
        assert len(r.sliced_objects) == 3
        assert r.multiplier == 2.0
        # base = 10 + 15 + 20 = 45, * 2 = 90
        assert r.score_gained == 90

    def test_four_objects_wonder_combo(self):
        objs = [make_obj("americano", x=80 + i * 130, y=240) for i in range(4)]
        seg = ((30, 240), (610, 240))
        r = judge_slice(seg, objs)
        assert len(r.sliced_objects) == 4
        assert r.multiplier == 3.0
        # base = 40, * 3 = 120
        assert r.score_gained == 120


class TestBombSlice:
    def test_single_bomb_no_score(self):
        bomb = make_obj(KIND_BOMB, x=320, y=240)
        seg = ((200, 240), (440, 240))
        r = judge_slice(seg, [bomb])
        assert r.bomb_count == 1
        assert r.score_gained == 0
        assert r.base_score == 0
        assert bomb.sliced is True

    def test_bomb_with_menu_no_combo_inflation(self):
        # 폭탄은 콤보 카운트에 포함되지 않음 (메뉴 1개로만 계산)
        menu = make_obj("latte", x=200, y=240)
        bomb = make_obj(KIND_BOMB, x=440, y=240)
        seg = ((100, 240), (540, 240))
        r = judge_slice(seg, [menu, bomb])
        assert r.bomb_count == 1
        # menu_count = 1 → multiplier 1.0
        assert r.multiplier == 1.0
        assert r.score_gained == KIND_SCORES["latte"]

    def test_bomb_plus_two_menu_uses_2x_combo(self):
        a = make_obj("americano", x=160, y=240)
        b = make_obj("latte", x=320, y=240)
        bomb = make_obj(KIND_BOMB, x=480, y=240)
        seg = ((50, 240), (600, 240))
        r = judge_slice(seg, [a, b, bomb])
        assert r.bomb_count == 1
        # menu_count = 2 → multiplier 1.5
        assert r.multiplier == 1.5
        # base = 10 + 15 = 25, * 1.5 = 37.5 → 38
        assert r.score_gained == 38


class TestImmunityToOrder:
    def test_object_order_does_not_affect_result(self):
        a = make_obj("americano", x=160, y=240)
        b = make_obj("latte", x=320, y=240)
        seg = ((50, 240), (600, 240))

        r1 = judge_slice(seg, [a, b])
        # 새 객체로 다시 (sliced 마킹 때문)
        a2 = make_obj("americano", x=160, y=240)
        b2 = make_obj("latte", x=320, y=240)
        r2 = judge_slice(seg, [b2, a2])

        assert r1.score_gained == r2.score_gained
        assert len(r1.sliced_objects) == len(r2.sliced_objects)
