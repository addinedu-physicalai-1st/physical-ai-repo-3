"""
dodge_state.py — W7 점수 + 생명 + 시간 + 종료 사유
======================================================

W3 score_state 패턴 + W5/W7 prefix 적용.
- 회피(pass) 시 점수 +10
- 충돌 시 생명 -1
- 종료:
    1) score >= target → WIN (즉시)
    2) lives <= 0 → LIVES_OUT
    3) 60초 경과 → WIN(점수 충족) 또는 TIMEOUT

time 의존부는 time_provider 콜백으로 주입 가능 → 단위 테스트 시간 제어.

Author: Stephen (gjkong)
Date: 2026-05-12 (W7 Step 4)
"""

import time


# ============================================================
# 1. 종료 사유
# ============================================================
END_NONE = "none"
END_WIN = "win"
END_LIVES_OUT = "lives_out"
END_TIMEOUT = "timeout"


# ============================================================
# 2. 난이도별 목표 점수
# ============================================================
TARGET_SCORE = {
    "easy":   100,
    "normal": 200,
    "hard":   350,
}

# 회피 점수 / 충돌 생명 감소
SCORE_PER_DODGE = 10
LIVES_PER_HIT = 1

START_LIVES = 3
TIME_LIMIT = 60.0


# ============================================================
# 3. DodgeState
# ============================================================
class DodgeState:
    """W7 라운드 상태 (1 게임 = 1 라운드 = 60초).

    Attributes:
        difficulty
        target: 목표 점수
        score: 누적 점수
        lives: 남은 생명
        dodged_total: 통과시킨 좀비 수
        hit_total: 충돌 수
        start_time: epoch 시작 (start_game 호출 시점)
        _end_reason: cache
    """

    START_LIVES = START_LIVES
    TIME_LIMIT = TIME_LIMIT

    def __init__(self, difficulty: str = "normal", time_provider=None):
        if difficulty not in TARGET_SCORE:
            raise ValueError(f"알 수 없는 난이도: {difficulty}")
        self.difficulty = difficulty
        self.target = TARGET_SCORE[difficulty]
        self._now = time_provider if time_provider is not None else time.time
        self.reset()

    def reset(self):
        self.score = 0
        self.lives = self.START_LIVES
        self.dodged_total = 0
        self.hit_total = 0
        self.start_time = None
        self._end_reason = END_NONE

    def start_game(self):
        self.start_time = self._now()

    # ----------------------------------------
    # 이벤트 적용
    # ----------------------------------------
    def apply_dodges(self, n: int):
        """좀비 n마리 회피 — 점수 가산."""
        if n <= 0:
            return
        if self._end_reason != END_NONE:
            return
        self.score += n * SCORE_PER_DODGE
        self.dodged_total += n

    def apply_hits(self, n: int):
        """좀비 n마리에게 부딪힘 — 생명 감소."""
        if n <= 0:
            return
        if self._end_reason != END_NONE:
            return
        self.lives = max(0, self.lives - n * LIVES_PER_HIT)
        self.hit_total += n

    # ----------------------------------------
    # 시간
    # ----------------------------------------
    def get_elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return self._now() - self.start_time

    def get_remaining(self) -> float:
        return max(0.0, self.TIME_LIMIT - self.get_elapsed())

    # ----------------------------------------
    # 종료
    # ----------------------------------------
    def check_end(self) -> str:
        """종료 사유.

        우선순위:
            1) score ≥ target → WIN (즉시)
            2) lives ≤ 0 → LIVES_OUT
            3) 시간 초과 → WIN(점수 충족) 또는 TIMEOUT
        """
        if self._end_reason != END_NONE:
            return self._end_reason

        if self.score >= self.target:
            self._end_reason = END_WIN
            return END_WIN

        if self.lives <= 0:
            self._end_reason = END_LIVES_OUT
            return END_LIVES_OUT

        if self.start_time is not None and self.get_elapsed() >= self.TIME_LIMIT:
            if self.score >= self.target:
                self._end_reason = END_WIN
                return END_WIN
            self._end_reason = END_TIMEOUT
            return END_TIMEOUT

        return END_NONE

    def is_game_over(self) -> bool:
        return self.check_end() != END_NONE

    def is_win(self) -> bool:
        return self.check_end() == END_WIN

    # ----------------------------------------
    # UI / 로깅
    # ----------------------------------------
    def get_summary(self) -> dict:
        return {
            "difficulty":   self.difficulty,
            "score":        self.score,
            "target":       self.target,
            "progress":     (self.score / self.target) if self.target else 0.0,
            "lives":        self.lives,
            "max_lives":    self.START_LIVES,
            "dodged_total": self.dodged_total,
            "hit_total":    self.hit_total,
            "elapsed":      self.get_elapsed(),
            "remaining":    self.get_remaining(),
            "end_reason":   self.check_end(),
        }

    def __repr__(self):
        return (
            f"DodgeState(score={self.score}/{self.target}, "
            f"lives={self.lives}, end={self.check_end()})"
        )
