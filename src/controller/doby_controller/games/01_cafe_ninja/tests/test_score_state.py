"""
test_score_state.py - 점수/생명/시간/종료조건 단위 테스트
"""

import time

import pytest

from falling_object import KIND_BOMB
from score_state import (
    END_LIVES_OUT,
    END_NONE,
    END_TIMEOUT,
    END_WIN,
    ScoreState,
    TARGET_SCORE,
)
from slice_judge import SliceResult


def make_result(score=0, sliced_count=0, bombs=0, multiplier=1.0):
    """테스트용 SliceResult 생성"""
    sliced = [object() for _ in range(sliced_count)]  # 더미
    return SliceResult(
        sliced_objects=sliced,
        bomb_count=bombs,
        base_score=score / multiplier if multiplier else 0,
        multiplier=multiplier,
        score_gained=score,
    )


@pytest.fixture
def state():
    s = ScoreState(difficulty="normal")
    s.start_game()
    yield s
    ScoreState.TIME_LIMIT = 60.0


class TestInitialState:
    def test_default_state(self):
        s = ScoreState()
        assert s.score == 0
        assert s.lives == ScoreState.START_LIVES
        assert s.bombs_hit == 0
        assert s.slices_total == 0
        assert s.max_combo == 0
        assert s.start_time is None
        assert s.check_end() == END_NONE
        assert not s.is_game_over()

    def test_target_set_by_difficulty(self):
        assert ScoreState("easy").target == TARGET_SCORE["easy"]
        assert ScoreState("normal").target == TARGET_SCORE["normal"]
        assert ScoreState("hard").target == TARGET_SCORE["hard"]

    def test_unknown_difficulty_raises(self):
        with pytest.raises(ValueError):
            ScoreState("insane")

    def test_target_ordering(self):
        assert TARGET_SCORE["easy"] < TARGET_SCORE["normal"] < TARGET_SCORE["hard"]


class TestApplySlice:
    def test_score_accumulates(self, state):
        state.apply_slice(make_result(score=10, sliced_count=1))
        assert state.score == 10
        state.apply_slice(make_result(score=15, sliced_count=1))
        assert state.score == 25
        assert state.slices_total == 2

    def test_bomb_decreases_lives(self, state):
        state.apply_slice(make_result(score=0, sliced_count=1, bombs=1))
        assert state.lives == ScoreState.START_LIVES - 1
        assert state.bombs_hit == 1

    def test_max_combo_tracks_peak(self, state):
        state.apply_slice(make_result(score=20, sliced_count=2, multiplier=1.5))
        assert state.max_combo == 2
        state.apply_slice(make_result(score=30, sliced_count=3, multiplier=2.0))
        assert state.max_combo == 3
        state.apply_slice(make_result(score=10, sliced_count=1))
        assert state.max_combo == 3, "max는 보존"

    def test_bomb_does_not_count_in_max_combo(self, state):
        # menu 2 + bomb 1 = total 3, but max_combo는 menu만 = 2
        state.apply_slice(make_result(score=25, sliced_count=3, bombs=1, multiplier=1.5))
        assert state.max_combo == 2

    def test_slices_total_excludes_bombs(self, state):
        state.apply_slice(make_result(score=10, sliced_count=2, bombs=1))
        assert state.slices_total == 1


class TestEndConditions:
    def test_target_score_wins(self, state):
        # normal target = 300
        state.apply_slice(make_result(score=300, sliced_count=1))
        assert state.check_end() == END_WIN
        assert state.is_win()

    def test_overshoot_target_still_wins(self, state):
        state.apply_slice(make_result(score=500, sliced_count=1))
        assert state.check_end() == END_WIN

    def test_lives_zero_loses(self, state):
        for _ in range(ScoreState.START_LIVES):
            state.apply_slice(make_result(sliced_count=1, bombs=1))
        assert state.lives == 0
        assert state.check_end() == END_LIVES_OUT
        assert not state.is_win()

    def test_timeout(self):
        ScoreState.TIME_LIMIT = 0.2
        s = ScoreState("normal")
        s.start_game()
        time.sleep(0.3)
        assert s.check_end() == END_TIMEOUT
        ScoreState.TIME_LIMIT = 60.0

    def test_win_takes_priority_over_lives_out(self, state):
        # 생명 0 + 점수 도달 동시 충족 → 승리 우선
        state.apply_slice(make_result(score=300, sliced_count=1, bombs=10))
        assert state.lives == 0
        assert state.check_end() == END_WIN

    def test_win_takes_priority_over_timeout(self):
        ScoreState.TIME_LIMIT = 0.2
        s = ScoreState("normal")
        s.start_game()
        time.sleep(0.3)
        # 시간이 다 흐른 후 점수 적용 — 승리 우선
        s.apply_slice(make_result(score=300, sliced_count=1))
        assert s.check_end() == END_WIN
        ScoreState.TIME_LIMIT = 60.0

    def test_end_reason_cached(self, state):
        for _ in range(ScoreState.START_LIVES):
            state.apply_slice(make_result(sliced_count=1, bombs=1))
        first = state.check_end()
        # 추가 점수 적용해도 종료 사유 안 바뀜
        state.apply_slice(make_result(score=500, sliced_count=1))
        assert state.check_end() == first == END_LIVES_OUT


class TestReset:
    def test_reset_clears_everything(self, state):
        state.apply_slice(make_result(score=100, sliced_count=2, multiplier=1.5))
        state.apply_slice(make_result(sliced_count=1, bombs=1))
        state.reset()
        assert state.score == 0
        assert state.lives == ScoreState.START_LIVES
        assert state.bombs_hit == 0
        assert state.slices_total == 0
        assert state.max_combo == 0
        assert state.start_time is None
        assert state.check_end() == END_NONE


class TestSummary:
    def test_summary_keys(self, state):
        state.apply_slice(make_result(score=50, sliced_count=2, multiplier=1.5))
        s = state.get_summary()
        assert set(s.keys()) == {
            "score", "target", "progress", "lives", "max_combo",
            "bombs_hit", "slices_total", "elapsed", "remaining",
            "end_reason",
        }
        assert s["score"] == 50
        assert s["target"] == TARGET_SCORE["normal"]
        assert s["progress"] == pytest.approx(50 / TARGET_SCORE["normal"])
        assert s["max_combo"] == 2
        assert s["end_reason"] == END_NONE


class TestTimeMethods:
    def test_get_elapsed_zero_before_start(self):
        s = ScoreState()
        assert s.get_elapsed() == 0.0

    def test_get_remaining_decreases(self):
        ScoreState.TIME_LIMIT = 1.0
        s = ScoreState()
        s.start_game()
        first = s.get_remaining()
        time.sleep(0.05)
        second = s.get_remaining()
        assert second < first
        assert 0.0 <= second <= 1.0
        ScoreState.TIME_LIMIT = 60.0
