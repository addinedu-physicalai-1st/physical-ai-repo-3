"""
question_gen.py - 숫자 출제 + 가속 시간 계산
==============================================

순수 함수 모듈. 카메라/UI/MediaPipe 의존성 없음.
W1 의 judge.py 와 마찬가지로 단위 테스트 친화적.

기능:
- 1~10 범위 랜덤 숫자 출제
- 직전 숫자 회피 (같은 숫자 연속 X)
- 콤보 + 난이도 기반 제한 시간 계산

Author: Stephen (gjkong)
Date: 2026-04-30 (W2 Step 3)
"""

import random


# ============================================================
# 1. 상수 정의
# ============================================================
MIN_NUMBER = 1
MAX_NUMBER = 10

DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"
DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)


# ============================================================
# 2. 난이도별 기본 시간 (초)
# ============================================================
# 콤보 0~2 (워밍업), 3~4 (가속 시작), 5+ (최고 속도)
TIME_TABLE = {
    DIFFICULTY_EASY: {
        "warmup": 4.0,
        "accelerated": 3.5,
        "fast": 3.0,
    },
    DIFFICULTY_NORMAL: {
        "warmup": 3.0,
        "accelerated": 2.5,
        "fast": 2.0,
    },
    DIFFICULTY_HARD: {
        "warmup": 2.0,
        "accelerated": 1.7,
        "fast": 1.4,
    },
}


# ============================================================
# 3. 출제 함수
# ============================================================
class QuestionGenerator:
    """1~10 숫자 출제기
    
    Attributes:
        last_number: 직전 출제 숫자 (회피용)
        history: 출제 이력 [int, int, ...]
    """
    
    def __init__(self, seed: int = None):
        # 인스턴스별 RNG (전역 random 오염 방지 + 시드 재현성 보장)
        self._rng = random.Random(seed)
        self.last_number = None
        self.history = []

    def reset(self):
        """출제 이력 초기화 (RNG 상태는 보존)"""
        self.last_number = None
        self.history = []

    def next_question(self) -> int:
        """다음 출제 숫자 생성 (직전 숫자 회피)

        Returns:
            1~10 사이의 숫자 (직전 숫자와 다른 값)
        """
        candidates = list(range(MIN_NUMBER, MAX_NUMBER + 1))

        # 직전 숫자 제외 (첫 출제 제외)
        if self.last_number is not None:
            candidates = [n for n in candidates if n != self.last_number]

        chosen = self._rng.choice(candidates)
        self.last_number = chosen
        self.history.append(chosen)
        return chosen


# ============================================================
# 4. 가속 시간 계산
# ============================================================
def get_time_limit(combo: int, difficulty: str) -> float:
    """콤보와 난이도에 따른 제한 시간 계산
    
    Args:
        combo: 현재 연속 정답 수 (0 이상)
        difficulty: "easy" | "normal" | "hard"
    
    Returns:
        제한 시간 (초)
    
    Raises:
        ValueError: 알 수 없는 난이도
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"알 수 없는 난이도: {difficulty}")
    
    table = TIME_TABLE[difficulty]
    
    if combo < 3:
        return table["warmup"]
    elif combo < 5:
        return table["accelerated"]
    else:
        return table["fast"]


def get_speed_phase(combo: int) -> str:
    """현재 콤보의 속도 단계 (UI 표시용)
    
    Returns:
        "warmup" | "accelerated" | "fast"
    """
    if combo < 3:
        return "warmup"
    elif combo < 5:
        return "accelerated"
    else:
        return "fast"


# ============================================================
# 5. 자체 테스트
# ============================================================
def _self_test():
    """단위 테스트"""
    print("=" * 50)
    print("question_gen.py 자체 테스트")
    print("=" * 50)
    
    # 1. 출제 테스트
    print("\n[Test 1] 1~10 출제 + 직전 숫자 회피")
    qg = QuestionGenerator(seed=42)
    questions = [qg.next_question() for _ in range(20)]
    print(f"  출제 결과: {questions}")
    
    # 직전 숫자 회피 검증
    has_consecutive = any(questions[i] == questions[i+1] 
                           for i in range(len(questions)-1))
    if has_consecutive:
        print("  ❌ 직전 숫자 회피 실패")
    else:
        print("  ✅ 직전 숫자 회피 정상")
    
    # 범위 검증
    if all(1 <= q <= 10 for q in questions):
        print("  ✅ 범위 (1~10) 정상")
    else:
        print("  ❌ 범위 벗어남")
    
    # 2. 시간 계산 테스트
    print("\n[Test 2] 가속 시간 계산")
    print(f"\n  {'콤보':<6}{'Easy':<8}{'Normal':<8}{'Hard':<8}")
    print(f"  {'-'*30}")
    for combo in [0, 2, 3, 4, 5, 7, 10]:
        e = get_time_limit(combo, "easy")
        n = get_time_limit(combo, "normal")
        h = get_time_limit(combo, "hard")
        phase = get_speed_phase(combo)
        print(f"  {combo:<6}{e:<8.1f}{n:<8.1f}{h:<8.1f} ({phase})")
    
    # 3. 분포 테스트 (1000회 출제 시 각 숫자 빈도)
    print("\n[Test 3] 분포 균형 (10000회 출제)")
    from collections import Counter
    qg = QuestionGenerator(seed=123)
    big_sample = [qg.next_question() for _ in range(10000)]
    counter = Counter(big_sample)
    avg = 10000 / 10  # 균등 분포 시 1000
    
    for n in range(1, 11):
        count = counter[n]
        diff_pct = (count - avg) / avg * 100
        bar = "█" * (count // 50)
        print(f"  {n:2}: {count:5} ({diff_pct:+.1f}%) {bar}")
    
    print("\n✅ 모든 테스트 완료")


if __name__ == "__main__":
    _self_test()
