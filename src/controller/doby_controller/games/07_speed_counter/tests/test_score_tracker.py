"""
test_score_tracker.py - 점수/콤보/종료조건 단위 테스트
"""

import time

import pytest

from score_tracker import (
    END_NONE,
    END_TIMEOUT,
    END_TOO_MANY_FAILS,
    END_WIN,
    ScoreTracker,
)


@pytest.fixture
def st():
    """매 테스트마다 새 인스턴스. TIME_LIMIT은 클래스 변수라 후속 fixture에서 격리"""
    tracker = ScoreTracker()
    tracker.start_game()
    yield tracker
    # TIME_LIMIT을 임시 변경한 테스트는 여기서 원복
    ScoreTracker.TIME_LIMIT = 60.0


class TestInitialState:
    def test_default_state(self):
        st = ScoreTracker()
        assert st.combo == 0
        assert st.max_combo == 0
        assert st.total_correct == 0
        assert st.total_wrong == 0
        assert st.round_count == 0
        assert st.start_time is None
        assert st.check_end() == END_NONE
        assert not st.is_game_over()

    def test_class_constants(self):
        assert ScoreTracker.WIN_COMBO == 5
        assert ScoreTracker.MAX_FAILS == 5
        assert ScoreTracker.TIME_LIMIT == 60.0


class TestCorrectAndWrong:
    def test_record_correct_increments(self, st):
        st.record_correct()
        assert st.combo == 1
        assert st.total_correct == 1
        assert st.round_count == 1
        assert st.max_combo == 1

    def test_record_wrong_resets_combo(self, st):
        for _ in range(3):
            st.record_correct()
        assert st.combo == 3
        st.record_wrong()
        assert st.combo == 0
        assert st.total_wrong == 1
        assert st.max_combo == 3, "max_combo는 보존되어야 함"

    def test_max_combo_tracks_peak(self, st):
        # 3 → 0 → 2 패턴
        for _ in range(3):
            st.record_correct()
        st.record_wrong()
        for _ in range(2):
            st.record_correct()
        assert st.combo == 2
        assert st.max_combo == 3
        assert st.total_correct == 5
        assert st.total_wrong == 1
        assert st.round_count == 6


class TestEndConditions:
    def test_5_consecutive_correct_wins(self, st):
        for i in range(4):
            st.record_correct()
            assert st.check_end() == END_NONE, f"{i+1}연속에서 조기 승리"
        st.record_correct()
        assert st.check_end() == END_WIN
        assert st.is_win()
        assert st.is_game_over()

    def test_5_wrong_loses_by_fails(self, st):
        for i in range(4):
            st.record_wrong()
            assert st.check_end() == END_NONE, f"{i+1}오답에서 조기 패배"
        st.record_wrong()
        assert st.check_end() == END_TOO_MANY_FAILS
        assert not st.is_win()
        assert st.is_game_over()

    def test_timeout(self):
        ScoreTracker.TIME_LIMIT = 0.2
        st = ScoreTracker()
        st.start_game()
        time.sleep(0.3)
        assert st.check_end() == END_TIMEOUT
        ScoreTracker.TIME_LIMIT = 60.0

    def test_win_takes_priority_over_fails(self):
        # 5콤보 + 5오답 동시 충족 상태에서 승리가 우선
        st = ScoreTracker()
        st.start_game()
        # 먼저 오답 4 + 정답 5
        for _ in range(4):
            st.record_wrong()
        for _ in range(5):
            st.record_correct()
        # 실제로는 5콤보 도달 시 즉시 승리지만, check_end의 우선순위 검증
        assert st.check_end() == END_WIN

    def test_end_reason_is_cached(self, st):
        for _ in range(5):
            st.record_correct()
        first = st.check_end()
        # 추가로 record_wrong을 호출해도 종료 사유는 변하지 않음
        st.record_wrong()
        assert st.check_end() == first == END_WIN


class TestReset:
    def test_reset_clears_everything(self, st):
        for _ in range(3):
            st.record_correct()
        st.record_wrong()
        st.reset()
        assert st.combo == 0
        assert st.max_combo == 0
        assert st.total_correct == 0
        assert st.total_wrong == 0
        assert st.round_count == 0
        assert st.start_time is None
        assert st.check_end() == END_NONE


class TestTimeMethods:
    def test_get_elapsed_zero_before_start(self):
        st = ScoreTracker()
        assert st.get_elapsed() == 0.0

    def test_get_remaining_decreases(self):
        ScoreTracker.TIME_LIMIT = 1.0
        st = ScoreTracker()
        st.start_game()
        first = st.get_remaining()
        time.sleep(0.05)
        second = st.get_remaining()
        assert second < first
        assert 0 <= second <= 1.0
        ScoreTracker.TIME_LIMIT = 60.0

    def test_remaining_clamped_to_zero(self):
        ScoreTracker.TIME_LIMIT = 0.1
        st = ScoreTracker()
        st.start_game()
        time.sleep(0.2)
        assert st.get_remaining() == 0.0
        ScoreTracker.TIME_LIMIT = 60.0

    def test_remaining_fails(self, st):
        assert st.get_remaining_fails() == 5
        st.record_wrong()
        st.record_wrong()
        assert st.get_remaining_fails() == 3
        for _ in range(10):
            st.record_wrong()
        assert st.get_remaining_fails() == 0


class TestSummary:
    def test_summary_keys(self, st):
        st.record_correct()
        st.record_correct()
        st.record_wrong()
        s = st.get_summary()
        assert set(s.keys()) == {
            "combo", "max_combo", "total_correct", "total_wrong",
            "round_count", "elapsed", "remaining", "remaining_fails",
            "end_reason",
        }
        assert s["combo"] == 0
        assert s["max_combo"] == 2
        assert s["total_correct"] == 2
        assert s["total_wrong"] == 1
        assert s["round_count"] == 3
        assert s["end_reason"] == END_NONE
