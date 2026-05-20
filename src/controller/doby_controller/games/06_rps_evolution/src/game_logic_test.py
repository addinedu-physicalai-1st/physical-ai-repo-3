"""
game_logic_test.py - 가위바위보 진화 게임 통합 테스트
=====================================================

Step 4: 카메라 + 손 인식 + 승패 판정 + AI 통합
- 화면 UI는 최소한 (Step 5에서 본격적으로 디자인)
- 콘솔 로그 + 화면 텍스트 오버레이만 사용
- 3선 2승 게임 진행

게임 진행:
1. 시작 시 난이도 선택 (1/2/3 키)
2. 'SPACE' 키로 라운드 시작 → 3-2-1 카운트다운
3. 카운트다운 후 1초간 손 모양 안정화 → 확정
4. AI 손 모양 공개 → 승패 판정
5. 2승 먼저 도달한 쪽 승리 → 'R' 키로 재시작

실행:
    cd PlayWait
    python -m games.06_rps_evolution.src.game_logic_test

종료: 'q' 또는 ESC

Author: Stephen (gjkong)
Date: 2026-04-30
"""

import cv2
import mediapipe as mp
import time
from collections import deque, Counter
from enum import Enum

from .judge import GameState, SHAPES
from .ai_player import AIPlayer, DIFFICULTIES, DIFFICULTY_NORMAL


# ============================================================
# 1. MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles


# ============================================================
# 2. 손 모양 분류 (Step 3에서 검증된 코드)
# ============================================================
THUMB_TIP, THUMB_IP = 4, 3
INDEX_TIP, INDEX_PIP = 8, 6
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18

HAND_SHAPES = {
    (0, 0, 0, 0, 0): "rock",
    (0, 1, 1, 0, 0): "scissors",
    (1, 1, 1, 1, 1): "paper",
    (1, 1, 0, 0, 0): "gun",
    (1, 1, 0, 0, 1): "phoenix",
}

SHAPE_DISPLAY = {
    "rock": "ROCK",
    "scissors": "SCISSORS",
    "paper": "PAPER",
    "gun": "GUN",
    "phoenix": "PHOENIX",
    "unknown": "???",
}


def is_finger_open(landmarks, tip_id, pip_id):
    return landmarks[tip_id].y < landmarks[pip_id].y


def is_thumb_open(landmarks, hand_label):
    tip_x = landmarks[THUMB_TIP].x
    ip_x = landmarks[THUMB_IP].x
    if hand_label == "Right":
        return tip_x < ip_x
    else:
        return tip_x > ip_x


def get_finger_states(landmarks, hand_label):
    return (
        int(is_thumb_open(landmarks, hand_label)),
        int(is_finger_open(landmarks, INDEX_TIP, INDEX_PIP)),
        int(is_finger_open(landmarks, MIDDLE_TIP, MIDDLE_PIP)),
        int(is_finger_open(landmarks, RING_TIP, RING_PIP)),
        int(is_finger_open(landmarks, PINKY_TIP, PINKY_PIP)),
    )


def classify_hand_shape(finger_states):
    return HAND_SHAPES.get(finger_states, "unknown")


class StabilityBuffer:
    def __init__(self, window_size=10, threshold=7):
        self.window_size = window_size
        self.threshold = threshold
        self.buffer = deque(maxlen=window_size)
        self.confirmed_shape = "unknown"
    
    def update(self, shape):
        self.buffer.append(shape)
        if len(self.buffer) < self.window_size:
            return self.confirmed_shape
        most_common, count = Counter(self.buffer).most_common(1)[0]
        if count >= self.threshold and most_common != "unknown":
            self.confirmed_shape = most_common
        return self.confirmed_shape
    
    def reset(self):
        self.buffer.clear()
        self.confirmed_shape = "unknown"


# ============================================================
# 3. 게임 상태 머신
# ============================================================
class GamePhase(Enum):
    """게임 페이즈"""
    DIFFICULTY_SELECT = "difficulty_select"  # 난이도 선택
    READY = "ready"                          # 라운드 시작 대기 (SPACE)
    COUNTDOWN = "countdown"                  # 3-2-1 카운트다운
    DETECTING = "detecting"                  # 손 모양 인식 중
    REVEAL = "reveal"                        # AI 손 공개
    ROUND_RESULT = "round_result"            # 라운드 결과 표시
    GAME_OVER = "game_over"                  # 게임 종료


# ============================================================
# 4. 메인 게임 클래스
# ============================================================
class RPSEvolutionGame:
    """가위바위보 진화 게임 메인 클래스"""
    
    def __init__(self):
        self.cap = None
        self.hands = None
        self.stability = StabilityBuffer(window_size=10, threshold=7)
        
        # 게임 상태
        self.game_state = GameState(max_score=2)
        self.ai_player = AIPlayer(difficulty=DIFFICULTY_NORMAL)
        self.phase = GamePhase.DIFFICULTY_SELECT
        
        # 페이즈 타이머
        self.phase_start_time = 0
        
        # 라운드 데이터
        self.user_shape = None
        self.ai_shape = None
        self.round_result = None
        
        # FPS 측정
        self.prev_time = time.time()
        self.fps = 0.0
    
    # ----------------------------------------
    # 카메라 & MediaPipe 초기화
    # ----------------------------------------
    def setup(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("❌ 카메라를 열 수 없습니다.")
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.hands = mp_hands.Hands(
            model_complexity=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
            max_num_hands=1,
        )
        return True
    
    # ----------------------------------------
    # 페이즈 전환
    # ----------------------------------------
    def change_phase(self, new_phase: GamePhase):
        self.phase = new_phase
        self.phase_start_time = time.time()
    
    def get_phase_elapsed(self) -> float:
        return time.time() - self.phase_start_time
    
    # ----------------------------------------
    # 키 입력 처리
    # ----------------------------------------
    def handle_key(self, key: int) -> bool:
        """키 입력 처리. False 반환 시 종료"""
        if key == ord('q') or key == 27:  # q or ESC
            return False
        
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            if key == ord('1'):
                self.ai_player = AIPlayer(difficulty="easy")
                print(f"🤖 난이도: EASY")
                self.change_phase(GamePhase.READY)
            elif key == ord('2'):
                self.ai_player = AIPlayer(difficulty="normal")
                print(f"🤖 난이도: NORMAL")
                self.change_phase(GamePhase.READY)
            elif key == ord('3'):
                self.ai_player = AIPlayer(difficulty="hard")
                print(f"🤖 난이도: HARD")
                self.change_phase(GamePhase.READY)
        
        elif self.phase == GamePhase.READY:
            if key == ord(' '):  # SPACE
                print(f"\n--- 라운드 {self.game_state.round_number} 시작 ---")
                self.change_phase(GamePhase.COUNTDOWN)
        
        elif self.phase == GamePhase.GAME_OVER:
            if key == ord('r') or key == ord('R'):
                self.game_state.reset()
                self.ai_player.reset()
                self.stability.reset()
                print("\n🔄 게임 재시작!")
                self.change_phase(GamePhase.READY)
        
        return True
    
    # ----------------------------------------
    # 페이즈별 업데이트 로직
    # ----------------------------------------
    def update_phase(self, current_shape: str):
        elapsed = self.get_phase_elapsed()
        
        if self.phase == GamePhase.COUNTDOWN:
            # 3초 카운트다운
            if elapsed >= 3.0:
                self.stability.reset()
                self.change_phase(GamePhase.DETECTING)
        
        elif self.phase == GamePhase.DETECTING:
            # 1.5초 동안 손 모양 안정화 시도
            confirmed = self.stability.update(current_shape)
            
            if elapsed >= 1.5:
                if confirmed != "unknown":
                    self.user_shape = confirmed
                    self.ai_shape = self.ai_player.choose_shape()
                    print(f"  👤 사용자: {SHAPE_DISPLAY[self.user_shape]}")
                    print(f"  🤖 AI:     {SHAPE_DISPLAY[self.ai_shape]}")
                    self.change_phase(GamePhase.REVEAL)
                else:
                    # 인식 실패 → 재시도
                    print("  ⚠️  손 모양 인식 실패. 다시 시도합니다.")
                    self.change_phase(GamePhase.COUNTDOWN)
        
        elif self.phase == GamePhase.REVEAL:
            # 0.8초 후 결과 판정
            if elapsed >= 0.8:
                round_data = self.game_state.play_round(
                    self.user_shape, self.ai_shape
                )
                self.round_result = round_data
                self.ai_player.record_user_shape(self.user_shape)
                
                # 결과 출력
                result_emoji = {
                    "user_win": "🎉 승리!",
                    "ai_win": "😢 패배",
                    "draw": "🤝 무승부"
                }
                print(f"  → {result_emoji[round_data['result']]} "
                      f"(점수 {round_data['user_score']}:{round_data['ai_score']})")
                
                self.change_phase(GamePhase.ROUND_RESULT)
        
        elif self.phase == GamePhase.ROUND_RESULT:
            # 2초 후 다음 라운드 또는 게임 종료
            if elapsed >= 2.0:
                if self.round_result["is_game_over"]:
                    winner = self.round_result["winner"]
                    print(f"\n{'='*40}")
                    if winner == "user":
                        print("🏆 게임 우승! 쿠폰 발급!")
                    else:
                        print("😢 게임 패배. 다시 도전하세요!")
                    print(f"{'='*40}")
                    self.change_phase(GamePhase.GAME_OVER)
                else:
                    self.change_phase(GamePhase.READY)
    
    # ----------------------------------------
    # UI 렌더링
    # ----------------------------------------
    def render(self, frame, current_shape: str, hand_detected: bool):
        h, w, _ = frame.shape
        
        # 상단 정보 패널 (반투명)
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 90), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        
        # 점수
        score_text = f"USER {self.game_state.user_score} : {self.game_state.ai_score} AI"
        cv2.putText(frame, score_text, (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        
        # 난이도
        cv2.putText(frame, f"Difficulty: {self.ai_player.difficulty.upper()}",
                    (w - 350, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        cv2.putText(frame, f"Round: {self.game_state.round_number}",
                    (w - 350, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        
        # 페이즈별 중앙 메시지
        center_x, center_y = w // 2, h // 2
        
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            self._draw_text_center(frame, "Choose Difficulty", center_y - 100, 1.5, (255, 255, 0))
            self._draw_text_center(frame, "[1] EASY", center_y - 40, 1.0, (100, 255, 100))
            self._draw_text_center(frame, "[2] NORMAL", center_y, 1.0, (255, 200, 0))
            self._draw_text_center(frame, "[3] HARD", center_y + 40, 1.0, (255, 100, 100))
        
        elif self.phase == GamePhase.READY:
            self._draw_text_center(frame, "Press SPACE to start round", center_y, 1.2, (0, 255, 255))
            self._draw_text_center(frame, f"Best of {self.game_state.max_score * 2 - 1}",
                                    center_y + 60, 0.8, (200, 200, 200))
        
        elif self.phase == GamePhase.COUNTDOWN:
            elapsed = self.get_phase_elapsed()
            count = max(1, 3 - int(elapsed))
            self._draw_text_center(frame, str(count), center_y, 5.0, (0, 0, 255))
            self._draw_text_center(frame, "Get Ready!", center_y - 200, 1.5, (255, 255, 255))
        
        elif self.phase == GamePhase.DETECTING:
            self._draw_text_center(frame, "SHOW YOUR HAND!", center_y - 200, 1.5, (0, 255, 0))
            shape_color = (0, 255, 255) if current_shape != "unknown" else (100, 100, 100)
            self._draw_text_center(frame, f"Detecting: {SHAPE_DISPLAY[current_shape]}",
                                    h - 60, 1.0, shape_color)
        
        elif self.phase == GamePhase.REVEAL:
            self._draw_text_center(frame, "AI:", center_y - 100, 1.2, (255, 100, 100))
            self._draw_text_center(frame, SHAPE_DISPLAY[self.ai_shape],
                                    center_y - 30, 2.5, (255, 100, 100))
            self._draw_text_center(frame, "VS", center_y + 50, 1.5, (255, 255, 255))
            self._draw_text_center(frame, f"YOU: {SHAPE_DISPLAY[self.user_shape]}",
                                    h - 60, 1.2, (100, 255, 255))
        
        elif self.phase == GamePhase.ROUND_RESULT:
            result_msg = {
                "user_win": ("YOU WIN!", (0, 255, 0)),
                "ai_win": ("AI WINS", (0, 0, 255)),
                "draw": ("DRAW", (0, 255, 255)),
            }
            msg, color = result_msg[self.round_result["result"]]
            self._draw_text_center(frame, msg, center_y, 3.0, color)
            
            self._draw_text_center(frame,
                f"You: {SHAPE_DISPLAY[self.user_shape]}  vs  AI: {SHAPE_DISPLAY[self.ai_shape]}",
                center_y + 100, 0.9, (255, 255, 255))
        
        elif self.phase == GamePhase.GAME_OVER:
            winner = self.round_result["winner"]
            if winner == "user":
                self._draw_text_center(frame, "VICTORY!", center_y - 50, 3.5, (0, 255, 0))
                self._draw_text_center(frame, "You earned a coupon!", center_y + 30, 1.2, (0, 255, 255))
            else:
                self._draw_text_center(frame, "GAME OVER", center_y - 50, 3.0, (0, 0, 255))
                self._draw_text_center(frame, "Try again!", center_y + 30, 1.2, (200, 200, 200))
            self._draw_text_center(frame, "Press R to restart", center_y + 100, 0.9, (200, 200, 200))
        
        # 하단: FPS + 종료 안내
        cv2.putText(frame, f"FPS: {self.fps:.0f} | 'q'/ESC to quit",
                    (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        
        return frame
    
    def _draw_text_center(self, frame, text, y, scale, color):
        h, w, _ = frame.shape
        font = cv2.FONT_HERSHEY_SIMPLEX
        thickness = max(2, int(scale * 2))
        text_size = cv2.getTextSize(text, font, scale, thickness)[0]
        x = (w - text_size[0]) // 2
        # 그림자 효과
        cv2.putText(frame, text, (x + 2, y + 2), font, scale, (0, 0, 0), thickness + 2)
        cv2.putText(frame, text, (x, y), font, scale, color, thickness)
    
    # ----------------------------------------
    # 메인 루프
    # ----------------------------------------
    def run(self):
        if not self.setup():
            return
        
        print("\n" + "=" * 50)
        print("🎮 PlayWait - 가위바위보 진화 (RPS Evolution)")
        print("=" * 50)
        print("\n[1] EASY  [2] NORMAL  [3] HARD - 난이도 선택")
        print("[SPACE] - 라운드 시작")
        print("[R] - 게임 재시작 (게임 종료 후)")
        print("[Q/ESC] - 종료\n")
        
        while self.cap.isOpened():
            success, frame = self.cap.read()
            if not success:
                continue
            
            frame = cv2.flip(frame, 1)
            
            # MediaPipe 처리
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False
            results = self.hands.process(rgb_frame)
            rgb_frame.flags.writeable = True
            
            # 손 감지 + 분류
            current_shape = "unknown"
            hand_detected = False
            
            if results.multi_hand_landmarks:
                hand_landmarks = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0]
                
                raw_label = handedness.classification[0].label
                hand_label = "Right" if raw_label == "Left" else "Left"
                
                # 랜드마크 그리기 (가벼운 스타일)
                mp_drawing.draw_landmarks(
                    frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                    mp_drawing_styles.get_default_hand_landmarks_style(),
                    mp_drawing_styles.get_default_hand_connections_style(),
                )
                
                landmarks = hand_landmarks.landmark
                finger_states = get_finger_states(landmarks, hand_label)
                current_shape = classify_hand_shape(finger_states)
                hand_detected = True
            
            # 페이즈 업데이트
            self.update_phase(current_shape)
            
            # FPS 계산
            curr_time = time.time()
            elapsed = curr_time - self.prev_time
            if elapsed > 0:
                self.fps = 1.0 / elapsed
            self.prev_time = curr_time
            
            # UI 렌더링
            frame = self.render(frame, current_shape, hand_detected)
            
            cv2.imshow("PlayWait - RPS Evolution (Step 4)", frame)
            
            # 키 입력
            key = cv2.waitKey(1) & 0xFF
            if not self.handle_key(key):
                break
        
        # 정리
        self.cap.release()
        if self.hands:
            self.hands.close()
        cv2.destroyAllWindows()
        print("\n✅ 게임 종료")


# ============================================================
# 5. 진입점
# ============================================================
def main():
    game = RPSEvolutionGame()
    game.run()


if __name__ == "__main__":
    main()
