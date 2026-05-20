"""
judge.py - 가위바위보 진화 승패 판정 로직
==========================================

순수 함수 모듈. 카메라/UI/MediaPipe 의존성 없음.
W2 이후 코어 모듈로 리팩토링 시 그대로 이동 가능.

승패 매트릭스 (가로가 세로를 이김):
       가위  바위  보  총  불사조
가위    -    ❌    ✅   ❌    ✅
바위    ✅    -    ❌   ❌    ✅
보      ❌    ✅    -   ❌    ❌
총      ✅    ✅    ✅   -    ❌
불사조  ❌    ❌    ✅   ✅    -

Author: Stephen (gjkong)
Date: 2026-04-30
"""

# ============================================================
# 1. 손 모양 정의
# ============================================================
SHAPES = ("rock", "scissors", "paper", "gun", "phoenix")

# 각 손 모양이 이기는 손 모양들 (집합)
WINS_AGAINST = {
    "scissors": {"paper", "phoenix"},
    "rock":     {"scissors", "phoenix"},
    "paper":    {"rock"},
    "gun":      {"scissors", "rock", "paper"},
    "phoenix":  {"paper", "gun"},
}


# ============================================================
# 2. 승패 판정
# ============================================================
def judge(user_shape: str, ai_shape: str) -> str:
    """사용자 vs AI 승패 판정
    
    Args:
        user_shape: 사용자 손 모양 ("rock", "scissors", ...)
        ai_shape: AI 손 모양
    
    Returns:
        "user_win" | "ai_win" | "draw"
    
    Raises:
        ValueError: 알 수 없는 손 모양 입력 시
    """
    if user_shape not in SHAPES:
        raise ValueError(f"알 수 없는 사용자 손 모양: {user_shape}")
    if ai_shape not in SHAPES:
        raise ValueError(f"알 수 없는 AI 손 모양: {ai_shape}")
    
    if user_shape == ai_shape:
        return "draw"
    
    if ai_shape in WINS_AGAINST[user_shape]:
        return "user_win"
    else:
        return "ai_win"


def get_counters(shape: str) -> list:
    """주어진 손 모양을 이기는 손 모양 목록 반환
    
    AI 의사결정에 사용.
    
    Args:
        shape: 카운터를 찾을 대상 손 모양
    
    Returns:
        해당 손 모양을 이기는 손 모양 리스트
    
    Example:
        >>> get_counters("rock")
        ['paper', 'gun']  # 보, 총이 바위를 이김
    """
    if shape not in SHAPES:
        return []
    
    counters = [s for s in SHAPES if shape in WINS_AGAINST[s]]
    return counters


# ============================================================
# 3. 게임 상태 클래스 (3선 2승 진행 관리)
# ============================================================
class GameState:
    """3선 2승 게임 진행 상태 관리
    
    Attributes:
        user_score: 사용자 승수
        ai_score: AI 승수
        round_number: 현재 라운드 (1부터)
        history: [{"user": str, "ai": str, "result": str}, ...]
        max_score: 승리에 필요한 점수 (기본 2)
    """
    
    def __init__(self, max_score: int = 2):
        self.max_score = max_score
        self.reset()
    
    def reset(self):
        """게임 초기화"""
        self.user_score = 0
        self.ai_score = 0
        self.round_number = 1
        self.history = []
    
    def play_round(self, user_shape: str, ai_shape: str) -> dict:
        """한 라운드 진행 후 결과 기록
        
        Returns:
            {
                "round": int,
                "user": str,
                "ai": str,
                "result": str,  # "user_win" | "ai_win" | "draw"
                "user_score": int,
                "ai_score": int,
                "is_game_over": bool,
                "winner": str or None  # "user" | "ai" | None
            }
        """
        result = judge(user_shape, ai_shape)
        
        if result == "user_win":
            self.user_score += 1
        elif result == "ai_win":
            self.ai_score += 1
        # draw는 점수 변화 없음
        
        round_data = {
            "round": self.round_number,
            "user": user_shape,
            "ai": ai_shape,
            "result": result,
            "user_score": self.user_score,
            "ai_score": self.ai_score,
        }
        self.history.append(round_data)
        
        # 무승부가 아니면 라운드 진행
        if result != "draw":
            self.round_number += 1
        
        # 게임 종료 판정
        is_over = (self.user_score >= self.max_score or 
                   self.ai_score >= self.max_score)
        
        winner = None
        if is_over:
            winner = "user" if self.user_score >= self.max_score else "ai"
        
        round_data["is_game_over"] = is_over
        round_data["winner"] = winner
        
        return round_data
    
    def __repr__(self):
        return (f"GameState(user={self.user_score}, ai={self.ai_score}, "
                f"round={self.round_number}, history={len(self.history)})")


# ============================================================
# 4. 자체 테스트 (이 파일을 직접 실행하면 동작)
# ============================================================
def _self_test():
    """단위 테스트: 모든 매트릭스 검증"""
    print("=" * 50)
    print("judge.py 자체 테스트")
    print("=" * 50)
    
    # 1. 기본 승패 매트릭스 검증
    test_cases = [
        # (user, ai, expected)
        ("scissors", "paper", "user_win"),    # 가위 > 보
        ("scissors", "rock", "ai_win"),       # 가위 < 바위
        ("scissors", "phoenix", "user_win"),  # 가위 > 불사조
        ("rock", "scissors", "user_win"),     # 바위 > 가위
        ("rock", "paper", "ai_win"),          # 바위 < 보
        ("rock", "phoenix", "user_win"),      # 바위 > 불사조
        ("paper", "rock", "user_win"),        # 보 > 바위
        ("paper", "gun", "ai_win"),           # 보 < 총
        ("paper", "phoenix", "ai_win"),       # 보 < 불사조
        ("gun", "scissors", "user_win"),      # 총 > 가위
        ("gun", "rock", "user_win"),          # 총 > 바위
        ("gun", "paper", "user_win"),         # 총 > 보
        ("gun", "phoenix", "ai_win"),         # 총 < 불사조
        ("phoenix", "paper", "user_win"),     # 불사조 > 보
        ("phoenix", "gun", "user_win"),       # 불사조 > 총
        ("rock", "rock", "draw"),             # 동점
    ]
    
    print("\n[Test 1] 승패 매트릭스 검증")
    passed = 0
    for user, ai, expected in test_cases:
        actual = judge(user, ai)
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            passed += 1
        print(f"  {status} {user:10} vs {ai:10} → {actual:10} (예상: {expected})")
    print(f"\n  결과: {passed}/{len(test_cases)} 통과")
    
    # 2. 카운터 검증
    print("\n[Test 2] get_counters() 검증")
    print(f"  rock의 카운터: {get_counters('rock')}")       # paper, gun
    print(f"  paper의 카운터: {get_counters('paper')}")     # scissors, gun, phoenix
    print(f"  gun의 카운터: {get_counters('gun')}")         # phoenix
    print(f"  phoenix의 카운터: {get_counters('phoenix')}") # scissors, rock
    
    # 3. GameState 진행 시나리오
    print("\n[Test 3] GameState 진행 시나리오 (3선 2승)")
    game = GameState(max_score=2)
    
    scenarios = [
        ("rock", "scissors"),   # 사용자 1승
        ("paper", "rock"),      # 사용자 2승 → 게임 종료
    ]
    
    for user, ai in scenarios:
        result = game.play_round(user, ai)
        print(f"  R{result['round']-1 if result['result']!='draw' else result['round']}: "
              f"{user} vs {ai} → {result['result']} "
              f"(점수 {result['user_score']}:{result['ai_score']})")
        if result["is_game_over"]:
            print(f"  🏆 게임 종료! 우승자: {result['winner']}")
            break
    
    print("\n✅ 모든 테스트 완료")


if __name__ == "__main__":
    _self_test()
