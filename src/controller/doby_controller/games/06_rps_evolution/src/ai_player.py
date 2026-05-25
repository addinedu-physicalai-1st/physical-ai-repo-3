"""
ai_player.py - AI 의사결정 모듈
================================

3단계 난이도 AI 플레이어.
judge.py 외 외부 의존성 없음 (random, collections만 사용).

난이도별 전략:
- Easy: 완전 랜덤 (사용자 70% 승률 목표)
- Normal: 70% 랜덤 + 30% 사용자 직전 손 카운터 (사용자 50% 승률)
- Hard: 사용자 패턴 분석 + 강력한 손 모양 선호 (사용자 30% 승률)

Author: Stephen (gjkong)
Date: 2026-04-30
"""

import random
from collections import Counter

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from .judge import SHAPES, get_counters
except ImportError:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from judge import SHAPES, get_counters


# ============================================================
# 1. 난이도 상수
# ============================================================
DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"

DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)


# ============================================================
# 2. AI 플레이어 클래스
# ============================================================
class AIPlayer:
    """3단계 난이도 AI 플레이어
    
    Attributes:
        difficulty: "easy" | "normal" | "hard"
        history: 사용자가 낸 손 모양 기록 [str, str, ...]
    """
    
    def __init__(self, difficulty: str = DIFFICULTY_NORMAL, seed: int = None):
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"알 수 없는 난이도: {difficulty}. "
                             f"가능한 값: {DIFFICULTIES}")
        
        self.difficulty = difficulty
        self.history = []  # 사용자가 낸 손 기록
        
        # 테스트용 시드 고정 (None이면 랜덤)
        if seed is not None:
            random.seed(seed)
    
    def reset(self):
        """게임 초기화 (history 비우기)"""
        self.history = []
    
    def record_user_shape(self, user_shape: str):
        """사용자가 낸 손 모양 기록 (게임 라운드 종료 후 호출)"""
        if user_shape in SHAPES:
            self.history.append(user_shape)
    
    def choose_shape(self) -> str:
        """현재 난이도에 따라 AI 손 모양 결정
        
        Returns:
            손 모양 이름 ("rock", "scissors", ...)
        """
        if self.difficulty == DIFFICULTY_EASY:
            return self._choose_easy()
        elif self.difficulty == DIFFICULTY_NORMAL:
            return self._choose_normal()
        elif self.difficulty == DIFFICULTY_HARD:
            return self._choose_hard()
        else:
            return random.choice(SHAPES)
    
    # ----------------------------------------
    # 난이도별 전략
    # ----------------------------------------
    def _choose_easy(self) -> str:
        """Easy: 완전 랜덤"""
        return random.choice(SHAPES)
    
    def _choose_normal(self) -> str:
        """Normal: 70% 랜덤 + 30% 직전 사용자 손 카운터"""
        # 첫 라운드 또는 30% 확률 미만이면 랜덤
        if not self.history or random.random() >= 0.3:
            return random.choice(SHAPES)
        
        # 사용자 직전 손의 카운터 중 랜덤 선택
        last_user = self.history[-1]
        counters = get_counters(last_user)
        if counters:
            return random.choice(counters)
        return random.choice(SHAPES)
    
    def _choose_hard(self) -> str:
        """Hard: 최근 5라운드 패턴 분석 + '총' 선호 (10% 가산)"""
        # 데이터가 충분하지 않으면 Normal과 동일
        if len(self.history) < 3:
            return self._choose_normal()
        
        recent = self.history[-5:]
        
        # 사용자가 가장 자주 낸 손 모양의 카운터 우선
        most_common_shape = Counter(recent).most_common(1)[0][0]
        counters = get_counters(most_common_shape)
        
        if counters:
            # 70% 확률로 분석 결과 사용
            if random.random() < 0.7:
                # "총"이 카운터에 포함되어 있으면 우선 (Hard 특성)
                if "gun" in counters and random.random() < 0.4:
                    return "gun"
                return random.choice(counters)
        
        # 30% 확률로 변칙 (예측 회피)
        return random.choice(SHAPES)


# ============================================================
# 3. 자체 테스트
# ============================================================
def _self_test():
    """AI 동작 시뮬레이션 (1000라운드 통계)"""
    print("=" * 50)
    print("ai_player.py 자체 테스트")
    print("=" * 50)
    
    # 시뮬레이션: 사용자가 "rock"만 1000번 내는 경우
    # 각 난이도 AI의 카운터 비율 확인
    print("\n[Test 1] 사용자가 'rock' 만 내는 경우 1000라운드")
    print("기대: Easy=무관심, Normal=약간 카운터, Hard=강하게 카운터")
    
    for difficulty in DIFFICULTIES:
        ai = AIPlayer(difficulty=difficulty, seed=42)
        ai_shapes = []
        
        for _ in range(1000):
            ai_choice = ai.choose_shape()
            ai_shapes.append(ai_choice)
            ai.record_user_shape("rock")  # 사용자는 항상 rock
        
        counter = Counter(ai_shapes)
        # rock의 카운터: paper, gun
        counter_rate = (counter.get("paper", 0) + counter.get("gun", 0)) / 1000 * 100
        
        print(f"\n  [{difficulty.upper():6}] 분포:")
        for shape in SHAPES:
            count = counter.get(shape, 0)
            bar = "█" * (count // 20)
            print(f"    {shape:10} {count:4} ({count/10:.1f}%) {bar}")
        print(f"    👉 rock 카운터(paper+gun) 비율: {counter_rate:.1f}%")
    
    # 2. AI vs 랜덤 사용자 시뮬레이션 (사용자 승률 측정)
    print("\n[Test 2] AI vs 랜덤 사용자 1000게임 (사용자 승률)")
    print("기대: Easy → ~50%, Normal → ~45%, Hard → ~40%")
    
    from .judge import judge
    
    for difficulty in DIFFICULTIES:
        ai = AIPlayer(difficulty=difficulty, seed=123)
        random.seed(456)  # 사용자 랜덤도 고정
        
        user_wins, ai_wins, draws = 0, 0, 0
        for _ in range(1000):
            user_shape = random.choice(SHAPES)
            ai_shape = ai.choose_shape()
            result = judge(user_shape, ai_shape)
            
            if result == "user_win":
                user_wins += 1
            elif result == "ai_win":
                ai_wins += 1
            else:
                draws += 1
            
            ai.record_user_shape(user_shape)
        
        total_decisive = user_wins + ai_wins
        win_rate = user_wins / total_decisive * 100 if total_decisive else 0
        
        print(f"\n  [{difficulty.upper():6}] "
              f"사용자 {user_wins} | AI {ai_wins} | 무승부 {draws}")
        print(f"          무승부 제외 사용자 승률: {win_rate:.1f}%")
    
    print("\n✅ 모든 테스트 완료")


if __name__ == "__main__":
    _self_test()
