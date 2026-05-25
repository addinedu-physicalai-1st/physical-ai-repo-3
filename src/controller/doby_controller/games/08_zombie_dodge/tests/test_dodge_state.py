"""
test_dodge_state.py — 점수·생명·시간·종료 단위 테스트
==========================================================

검증:
- apply_dodges → 점수 가산
- apply_hits → 생명 감소
- 종료 사유 우선순위 (WIN > LIVES_OUT > TIMEOUT)
- end_reason 캐시 (계속 동일 결과)
- time_provider 주입
- 잘못된 입력 / 무시
"""

import pytest

from dodge_state import (
    DodgeState,
    END_LIVES_OUT,
    END_NONE,
    END_TIMEOUT,
    END_WIN,
    LIVES_PER_HIT,
    SCORE_PER_DODGE,
    START_LIVES,
    TARGET_SCORE,
    TIME_LIMIT,
)


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


# ============================================================
# 1. apply_dodges / apply_hits
# ============================================================
class TestApply:
    def test_dodges_add_score(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_dodges(3)
        assert st.score == 30
        assert st.dodged_total == 3

    def test_hits_decrease_lives(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_hits(2)
        assert st.lives == START_LIVES - 2
        assert st.hit_total == 2

    def test_lives_clamped_to_zero(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_hits(99)
        assert st.lives == 0

    def test_no_apply_after_end(self):
        st = DodgeState("easy", time_provider=FakeClock(0))
        st.start_game()
        # easy 목표 100 → 10마리로 달성
        st.apply_dodges(10)
        assert st.check_end() == END_WIN
        # 이후 적용은 무시
        st.apply_dodges(5)
        assert st.score == 100  # 그대로

    def test_zero_count_ignored(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_dodges(0)
        st.apply_hits(0)
        assert st.score == 0
        assert st.lives == START_LIVES


# ============================================================
# 2. 종료 사유 우선순위
# ============================================================
class TestEndConditions:
    def test_win_immediate(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        # normal target 200, dodge 20마리
        st.apply_dodges(20)
        assert st.check_end() == END_WIN

    def test_lives_out(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_hits(START_LIVES)
        assert st.check_end() == END_LIVES_OUT

    def test_timeout(self):
        clock = FakeClock(0)
        st = DodgeState("normal", time_provider=clock)
        st.start_game()
        clock.t = TIME_LIMIT + 1
        assert st.check_end() == END_TIMEOUT

    def test_no_end_before_start(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        assert st.check_end() == END_NONE

    def test_no_end_in_progress(self):
        clock = FakeClock(0)
        st = DodgeState("normal", time_provider=clock)
        st.start_game()
        st.apply_dodges(5)  # 50점, 목표 200
        clock.t = 30  # 30초
        assert st.check_end() == END_NONE

    def test_win_priority_over_lives_out(self):
        # 같은 순간 점수 달성 + 생명 0 → WIN
        st = DodgeState("easy", time_provider=FakeClock(0))
        st.start_game()
        st.apply_dodges(10)  # easy target 100 → WIN
        # WIN으로 lock 됨, 이후 hits는 무시
        st.apply_hits(99)
        assert st.check_end() == END_WIN

    def test_win_priority_at_timeout(self):
        clock = FakeClock(0)
        st = DodgeState("easy", time_provider=clock)
        st.start_game()
        clock.t = TIME_LIMIT  # 시간 만료
        # 그러나 점수가 목표 달성
        st.apply_dodges(10)  # easy 100
        assert st.check_end() == END_WIN

    def test_end_reason_cached(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_hits(START_LIVES)
        first = st.check_end()
        assert first == END_LIVES_OUT
        for _ in range(5):
            assert st.check_end() == first


# ============================================================
# 3. 시간
# ============================================================
class TestTime:
    def test_elapsed_zero_before_start(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        assert st.get_elapsed() == 0.0

    def test_remaining_clamped(self):
        clock = FakeClock(0)
        st = DodgeState("normal", time_provider=clock)
        st.start_game()
        clock.t = TIME_LIMIT + 10
        assert st.get_remaining() == 0.0

    def test_remaining_decreasing(self):
        clock = FakeClock(0)
        st = DodgeState("normal", time_provider=clock)
        st.start_game()
        assert st.get_remaining() == pytest.approx(TIME_LIMIT)
        clock.t = 20
        assert st.get_remaining() == pytest.approx(TIME_LIMIT - 20)


# ============================================================
# 4. 난이도 / API
# ============================================================
class TestDifficulty:
    def test_target_scores_monotonic(self):
        assert (TARGET_SCORE["easy"]
                < TARGET_SCORE["normal"]
                < TARGET_SCORE["hard"])

    def test_invalid_difficulty(self):
        with pytest.raises(ValueError):
            DodgeState("god_tier", time_provider=FakeClock(0))

    def test_summary_keys(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        s = st.get_summary()
        for k in ("difficulty", "score", "target", "progress",
                  "lives", "max_lives", "dodged_total", "hit_total",
                  "elapsed", "remaining", "end_reason"):
            assert k in s

    def test_reset_clears_state(self):
        st = DodgeState("normal", time_provider=FakeClock(0))
        st.start_game()
        st.apply_dodges(3)
        st.apply_hits(1)
        st.reset()
        assert st.score == 0
        assert st.lives == START_LIVES
        assert st.start_time is None
        assert st.check_end() == END_NONE


# ============================================================
# 5. 상수
# ============================================================
class TestConstants:
    def test_score_per_dodge(self):
        assert SCORE_PER_DODGE == 10

    def test_start_lives(self):
        assert START_LIVES == 3

    def test_time_limit(self):
        assert TIME_LIMIT == 60.0
