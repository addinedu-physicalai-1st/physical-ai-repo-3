"""
score_state.py — 점수·생명·시간·종료조건 통합 관리
====================================================

W2의 ScoreTracker와 비슷하지만 W3 카페 닌자는 다음 점이 다름:
- 콤보가 아닌 누적 점수
- 생명(라이프) 시스템 추가 (폭탄 = 생명 -1)
- 목표 점수 도달 시 즉시 승리
- 60초 경과 시 점수 미달이면 패배

순수 클래스 (vision/UI/MediaPipe 의존성 없음).

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 4)
"""

import time


# ============================================================
# 1. 종료 사유
# ============================================================
END_NONE = "none"
END_WIN = "win"               # 목표 점수 달성
END_LIVES_OUT = "lives_out"   # 폭탄 N회로 생명 소진
END_TIMEOUT = "timeout"       # 60초 경과 후 점수 미달


# ============================================================
# 2. 난이도별 목표 점수
# ============================================================
TARGET_SCORE = {
    "easy": 200,
    "normal": 300,
    "hard": 450,
}


# ============================================================
# 3. ScoreState 클래스
# ============================================================
class ScoreState:
    """게임 진행 상태

    Attributes:
        score: 누적 점수
        max_combo: 한 슬라이스 최대 동시 베기 수 (UI/통계용)
        lives: 남은 생명 (시작 3, 폭탄 1회당 -1)
        bombs_hit: 누적 폭탄 베기 수
        slices_total: 총 슬라이스 횟수 (메뉴 베기 횟수)
        start_time: 게임 시작 시각

    클래스 변수 (조정 가능):
        START_LIVES: 시작 생명 (기본 3)
        TIME_LIMIT: 게임 시간 (초, 기본 60)
    """

    START_LIVES = 3
    TIME_LIMIT = 60.0

    def __init__(self, difficulty: str = "normal"):
        if difficulty not in TARGET_SCORE:
            raise ValueError(f"알 수 없는 난이도: {difficulty}")
        self.difficulty = difficulty
        self.target = TARGET_SCORE[difficulty]
        self.reset()

    def reset(self):
        self.score = 0
        self.max_combo = 0
        self.lives = self.START_LIVES
        self.bombs_hit = 0
        self.slices_total = 0
        self.start_time = None
        self._end_reason = END_NONE

    def start_game(self):
        self.start_time = time.time()

    # ------------------------------------------------------------
    # 슬라이스 결과 적용
    # ------------------------------------------------------------
    def apply_slice(self, result):
        """slice_judge.judge_slice() 결과를 상태에 반영

        Args:
            result: SliceResult
        """
        # 점수
        self.score += result.score_gained

        # 폭탄 → 생명 차감
        if result.bomb_count > 0:
            self.lives = max(0, self.lives - result.bomb_count)
            self.bombs_hit += result.bomb_count

        # 통계
        menu_count = len(result.sliced_objects) - result.bomb_count
        self.slices_total += menu_count
        if menu_count > self.max_combo:
            self.max_combo = menu_count

    # ------------------------------------------------------------
    # 시간
    # ------------------------------------------------------------
    def get_elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def get_remaining(self) -> float:
        return max(0.0, self.TIME_LIMIT - self.get_elapsed())

    # ------------------------------------------------------------
    # 종료 판정
    # ------------------------------------------------------------
    def check_end(self) -> str:
        """게임 종료 사유 반환

        우선순위:
            1) 목표 점수 도달 → 승리 (즉시)
            2) 생명 0 → 패배
            3) 시간 초과 → 패배 (점수 미달)
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
            # 시간 초과 시점에 다시 한 번 점수 체크 (동시 충족 시 승리 우선)
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

    # ------------------------------------------------------------
    # UI/로깅
    # ------------------------------------------------------------
    def get_summary(self) -> dict:
        return {
            "score": self.score,
            "target": self.target,
            "progress": (self.score / self.target) if self.target else 0.0,
            "lives": self.lives,
            "max_combo": self.max_combo,
            "bombs_hit": self.bombs_hit,
            "slices_total": self.slices_total,
            "elapsed": self.get_elapsed(),
            "remaining": self.get_remaining(),
            "end_reason": self.check_end(),
        }

    def __repr__(self):
        return (f"ScoreState(score={self.score}/{self.target}, "
                f"lives={self.lives}, "
                f"elapsed={self.get_elapsed():.1f}s)")
