"""
score_tracker.py - 게임 상태 트래커
=====================================

순수 클래스 모듈. 카메라/UI/MediaPipe 의존성 없음.
콤보, 오답, 시간, 승패를 통합 관리.

승리 조건:
- 5연속 정답 도달 즉시 승리

패배 조건:
- 60초 경과 (시간 초과)
- 누적 오답 5회

Author: Stephen (gjkong)
Date: 2026-04-30 (W2 Step 3)
"""

import time


# ============================================================
# 1. 게임 종료 사유
# ============================================================
END_NONE = "none"           # 진행 중
END_WIN = "win"             # 5연속 정답
END_TIMEOUT = "timeout"     # 60초 경과
END_TOO_MANY_FAILS = "fails" # 오답 5회


# ============================================================
# 2. ScoreTracker 클래스
# ============================================================
class ScoreTracker:
    """게임 점수 + 진행 상태 통합 관리
    
    Attributes:
        combo: 현재 연속 정답 수
        max_combo: 게임 중 최고 콤보 (참고용)
        total_correct: 총 정답 수
        total_wrong: 총 오답 수
        round_count: 진행한 총 라운드 수
        start_time: 게임 시작 시간 (time.time())
    
    설정 (클래스 변수):
        WIN_COMBO: 승리에 필요한 연속 정답 수 (기본 5)
        MAX_FAILS: 최대 허용 오답 수 (기본 5)
        TIME_LIMIT: 전체 게임 제한 시간 초 (기본 60.0)
    """
    
    # 게임 설정 (조정 가능)
    WIN_COMBO = 5
    MAX_FAILS = 5
    TIME_LIMIT = 60.0
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """게임 초기화"""
        self.combo = 0
        self.max_combo = 0
        self.total_correct = 0
        self.total_wrong = 0
        self.round_count = 0
        self.start_time = None
        self._end_reason = END_NONE
    
    def start_game(self):
        """게임 시작 시간 기록"""
        self.start_time = time.time()
    
    # ----------------------------------------
    # 라운드 결과 처리
    # ----------------------------------------
    def record_correct(self):
        """정답 기록"""
        self.combo += 1
        self.total_correct += 1
        self.round_count += 1
        
        if self.combo > self.max_combo:
            self.max_combo = self.combo
    
    def record_wrong(self):
        """오답/시간초과 기록"""
        self.combo = 0  # 콤보 리셋
        self.total_wrong += 1
        self.round_count += 1
    
    # ----------------------------------------
    # 시간 관리
    # ----------------------------------------
    def get_elapsed(self) -> float:
        """게임 시작 후 경과 시간 (초)"""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time
    
    def get_remaining(self) -> float:
        """남은 게임 시간 (초)"""
        return max(0.0, self.TIME_LIMIT - self.get_elapsed())
    
    def get_remaining_fails(self) -> int:
        """남은 허용 오답 수"""
        return max(0, self.MAX_FAILS - self.total_wrong)
    
    # ----------------------------------------
    # 승패 판정
    # ----------------------------------------
    def check_end(self) -> str:
        """게임 종료 여부 + 사유 반환
        
        Returns:
            END_NONE: 진행 중
            END_WIN: 승리 (5연속 정답)
            END_TIMEOUT: 시간 초과
            END_TOO_MANY_FAILS: 오답 누적
        """
        if self._end_reason != END_NONE:
            return self._end_reason
        
        # 1) 승리 체크 (최우선)
        if self.combo >= self.WIN_COMBO:
            self._end_reason = END_WIN
            return END_WIN
        
        # 2) 시간 초과
        if self.start_time is not None and self.get_elapsed() >= self.TIME_LIMIT:
            self._end_reason = END_TIMEOUT
            return END_TIMEOUT
        
        # 3) 오답 누적
        if self.total_wrong >= self.MAX_FAILS:
            self._end_reason = END_TOO_MANY_FAILS
            return END_TOO_MANY_FAILS
        
        return END_NONE
    
    def is_game_over(self) -> bool:
        """게임 종료 여부 (간편 메서드)"""
        return self.check_end() != END_NONE
    
    def is_win(self) -> bool:
        """승리 여부"""
        return self.check_end() == END_WIN
    
    # ----------------------------------------
    # 요약 정보
    # ----------------------------------------
    def get_summary(self) -> dict:
        """게임 요약 정보 (UI/로깅용)"""
        return {
            "combo": self.combo,
            "max_combo": self.max_combo,
            "total_correct": self.total_correct,
            "total_wrong": self.total_wrong,
            "round_count": self.round_count,
            "elapsed": self.get_elapsed(),
            "remaining": self.get_remaining(),
            "remaining_fails": self.get_remaining_fails(),
            "end_reason": self.check_end(),
        }
    
    def __repr__(self):
        return (f"ScoreTracker(combo={self.combo}, "
                f"correct={self.total_correct}, wrong={self.total_wrong}, "
                f"elapsed={self.get_elapsed():.1f}s)")


# ============================================================
# 3. 자체 테스트
# ============================================================
def _self_test():
    """다양한 시나리오 시뮬레이션"""
    print("=" * 50)
    print("score_tracker.py 자체 테스트")
    print("=" * 50)
    
    # 시나리오 1: 5연속 정답 → 승리
    print("\n[Test 1] 5연속 정답 시나리오")
    st = ScoreTracker()
    st.start_game()
    
    for i in range(5):
        st.record_correct()
        result = st.check_end()
        print(f"  R{i+1}: 정답 → 콤보 {st.combo}, "
              f"종료: {result}")
    
    if st.is_win():
        print(f"  ✅ 승리! 최고 콤보: {st.max_combo}")
    else:
        print(f"  ❌ 승리 판정 실패")
    
    # 시나리오 2: 오답 5회 → 패배
    print("\n[Test 2] 오답 5회 시나리오")
    st = ScoreTracker()
    st.start_game()
    
    for i in range(5):
        st.record_wrong()
        result = st.check_end()
        print(f"  R{i+1}: 오답 → 오답 {st.total_wrong}/{st.MAX_FAILS}, "
              f"종료: {result}")
    
    if st.check_end() == END_TOO_MANY_FAILS:
        print(f"  ✅ 오답 누적 패배 정상")
    else:
        print(f"  ❌ 오답 누적 판정 실패")
    
    # 시나리오 3: 정답/오답 혼합 (콤보 끊김)
    print("\n[Test 3] 정답/오답 혼합 (콤보 끊김)")
    st = ScoreTracker()
    st.start_game()
    
    sequence = [True, True, True, False, True, True]  # 3 → 0 → 2
    for i, correct in enumerate(sequence):
        if correct:
            st.record_correct()
        else:
            st.record_wrong()
        print(f"  R{i+1}: {'정답' if correct else '오답'} → "
              f"콤보 {st.combo}, max {st.max_combo}")
    
    print(f"  최종: 콤보 {st.combo}, 최고콤보 {st.max_combo}, "
          f"정답 {st.total_correct}, 오답 {st.total_wrong}")
    
    # 시나리오 4: 시간 초과 시뮬레이션
    print("\n[Test 4] 시간 초과 시뮬레이션 (TIME_LIMIT 임시 변경)")
    st = ScoreTracker()
    ScoreTracker.TIME_LIMIT = 0.5  # 임시 단축
    st.start_game()
    time.sleep(0.6)
    result = st.check_end()
    if result == END_TIMEOUT:
        print(f"  ✅ 시간 초과 정상 ({st.get_elapsed():.2f}s)")
    else:
        print(f"  ❌ 시간 초과 미감지: {result}")
    
    ScoreTracker.TIME_LIMIT = 60.0  # 원복
    
    # 시나리오 5: get_summary 검증
    print("\n[Test 5] get_summary() 검증")
    st = ScoreTracker()
    st.start_game()
    st.record_correct()
    st.record_correct()
    st.record_wrong()
    summary = st.get_summary()
    print(f"  요약: {summary}")
    
    print("\n✅ 모든 테스트 완료")


if __name__ == "__main__":
    _self_test()
