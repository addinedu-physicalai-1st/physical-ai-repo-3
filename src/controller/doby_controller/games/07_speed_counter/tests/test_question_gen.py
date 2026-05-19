"""
test_question_gen.py - 출제기 + 가속 시간 단위 테스트
"""

from collections import Counter

import pytest

from question_gen import (
    DIFFICULTIES,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    MAX_NUMBER,
    MIN_NUMBER,
    QuestionGenerator,
    TIME_TABLE,
    get_speed_phase,
    get_time_limit,
)


class TestQuestionGenerator:
    def test_range_within_1_to_10(self):
        qg = QuestionGenerator(seed=42)
        for _ in range(200):
            n = qg.next_question()
            assert MIN_NUMBER <= n <= MAX_NUMBER

    def test_no_consecutive_duplicates(self):
        qg = QuestionGenerator(seed=42)
        nums = [qg.next_question() for _ in range(500)]
        for a, b in zip(nums, nums[1:]):
            assert a != b, f"직전 숫자 회피 실패: {a} → {b}"

    def test_history_grows(self):
        qg = QuestionGenerator(seed=1)
        assert qg.history == []
        for i in range(1, 6):
            qg.next_question()
            assert len(qg.history) == i

    def test_reset_clears_history_and_last(self):
        qg = QuestionGenerator(seed=1)
        for _ in range(5):
            qg.next_question()
        qg.reset()
        assert qg.history == []
        assert qg.last_number is None
        first_after_reset = qg.next_question()
        assert MIN_NUMBER <= first_after_reset <= MAX_NUMBER

    def test_distribution_roughly_uniform(self):
        # 직전 회피로 인해 완전 균등은 아니지만 ±20% 이내여야 함
        qg = QuestionGenerator(seed=2026)
        N = 10000
        sample = [qg.next_question() for _ in range(N)]
        counter = Counter(sample)
        expected = N / 10
        for n in range(1, 11):
            ratio = counter[n] / expected
            assert 0.8 <= ratio <= 1.2, (
                f"숫자 {n} 분포 편향: {counter[n]} / 기대 {expected:.0f} (비율 {ratio:.2f})"
            )

    def test_seed_reproducibility(self):
        a = QuestionGenerator(seed=777)
        b = QuestionGenerator(seed=777)
        for _ in range(50):
            assert a.next_question() == b.next_question()


class TestGetTimeLimit:
    @pytest.mark.parametrize("combo,phase", [
        (0, "warmup"), (1, "warmup"), (2, "warmup"),
        (3, "accelerated"), (4, "accelerated"),
        (5, "fast"), (7, "fast"), (100, "fast"),
    ])
    def test_phase_boundaries(self, combo, phase):
        assert get_speed_phase(combo) == phase

    @pytest.mark.parametrize("difficulty", DIFFICULTIES)
    def test_time_limit_decreases_with_combo(self, difficulty):
        warmup = get_time_limit(0, difficulty)
        accel = get_time_limit(3, difficulty)
        fast = get_time_limit(5, difficulty)
        assert warmup > accel > fast, (
            f"{difficulty}: 콤보 증가 시 시간 단축 안 됨 ({warmup}/{accel}/{fast})"
        )

    @pytest.mark.parametrize("difficulty,expected", [
        (DIFFICULTY_EASY, (4.0, 3.5, 3.0)),
        (DIFFICULTY_NORMAL, (3.0, 2.5, 2.0)),
        (DIFFICULTY_HARD, (2.0, 1.7, 1.4)),
    ])
    def test_exact_time_table_values(self, difficulty, expected):
        assert get_time_limit(0, difficulty) == expected[0]
        assert get_time_limit(3, difficulty) == expected[1]
        assert get_time_limit(5, difficulty) == expected[2]

    def test_unknown_difficulty_raises(self):
        with pytest.raises(ValueError):
            get_time_limit(0, "insane")

    def test_easy_is_slowest_hard_is_fastest(self):
        # 같은 콤보에서 난이도별 시간 비교
        for combo in [0, 3, 5, 10]:
            e = get_time_limit(combo, DIFFICULTY_EASY)
            n = get_time_limit(combo, DIFFICULTY_NORMAL)
            h = get_time_limit(combo, DIFFICULTY_HARD)
            assert e > n > h, f"콤보 {combo}: easy({e}) > normal({n}) > hard({h}) 위반"

    def test_table_consistency(self):
        # TIME_TABLE의 모든 키가 DIFFICULTIES에 있고, 각 dict가 3 phase 보유
        assert set(TIME_TABLE.keys()) == set(DIFFICULTIES)
        for diff, phases in TIME_TABLE.items():
            assert set(phases.keys()) == {"warmup", "accelerated", "fast"}
