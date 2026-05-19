"""
game.py - 가위바위보 진화 최종 게임 (UI + 사운드 통합)
========================================================

Step 5: 한글 UI + PinkLAB 디자인 + pygame 사운드 통합

Step 4 (game_logic_test.py) 의 게임 로직을 유지하면서:
- ui_renderer로 한글 UI 렌더링
- sound_manager로 효과음 재생
- theme.py로 디자인 일관성 유지

실행:
    cd PlayWait
    python -m games.06_rps_evolution.src.game

조작:
    [1/2/3]  난이도 선택 (쉬움/보통/어려움)
    [SPACE]  라운드 시작
    [R]      게임 재시작 (게임 종료 후)
    [Q/ESC]  종료

Author: Stephen (gjkong)
Date: 2026-04-30
"""

import os
import sys
import cv2
import time
import mediapipe as mp
from collections import deque, Counter
from enum import Enum

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from .judge import GameState, SHAPES
    from .ai_player import AIPlayer, DIFFICULTY_NORMAL
    from .sound_manager import SoundManager
    from . import theme
    from . import ui_renderer as ui
except ImportError:
    # 직접 실행 시: 현재 디렉토리를 sys.path에 추가
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from judge import GameState, SHAPES
    from ai_player import AIPlayer, DIFFICULTY_NORMAL
    from sound_manager import SoundManager
    import theme
    import ui_renderer as ui


# ============================================================
# 1. MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles


# ============================================================
# 2. 손 모양 분류 (Step 3에서 검증된 코드 재사용)
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


def is_finger_open(landmarks, tip_id, pip_id):
    return landmarks[tip_id].y < landmarks[pip_id].y


def is_thumb_open(landmarks, hand_label):
    tip_x = landmarks[THUMB_TIP].x
    ip_x = landmarks[THUMB_IP].x
    if hand_label == "Right":
        return tip_x < ip_x
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


# ============================================================
# 3. 안정화 버퍼
# ============================================================
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
# 4. 게임 페이즈
# ============================================================
class GamePhase(Enum):
    DIFFICULTY_SELECT = "difficulty_select"
    READY = "ready"
    COUNTDOWN = "countdown"
    DETECTING = "detecting"
    REVEAL = "reveal"
    ROUND_RESULT = "round_result"
    GAME_OVER = "game_over"


# ============================================================
# 5. 메인 게임 클래스
# ============================================================
class RPSEvolutionGame:
    """가위바위보 진화 - UI/사운드 통합 버전"""
    
    def __init__(self):
        # 카메라 & MediaPipe
        self.cap = None
        self.hands = None

        # 게임 상태
        self.stability = StabilityBuffer(window_size=10, threshold=7)
        self.game_state = GameState(max_score=2)
        self.ai_player = AIPlayer(difficulty=DIFFICULTY_NORMAL)
        self.phase = GamePhase.DIFFICULTY_SELECT
        self.phase_start_time = 0

        # === ROS 통합 — 자동화 / 결과 출력 옵션 (rps_node 가 설정) ===
        # auto_play=True 면 키 입력 없이 DIFFICULTY_SELECT/READY 자동 진행.
        # auto_play_difficulty 가 지정되면 해당 난이도, 없으면 normal.
        # auto_play_ready_delay 만큼 READY 페이즈에서 대기 후 COUNTDOWN 자동.
        # result_json_path 가 지정되면 GAME_OVER 진입 시 결과 JSON 저장.
        # auto_exit_sec 가 지정되면 GAME_OVER 진입 N 초 후 메인 루프 break.
        self.auto_play = False
        self.auto_play_difficulty = None
        self.auto_play_ready_delay = 1.5
        self.result_json_path = None
        self.auto_exit_sec = None
        self.game_started_at = None
        self.game_over_at = None
        
        # 라운드 데이터
        self.user_shape = None
        self.ai_shape = None
        self.round_result = None
        
        # 사운드 (사운드 폴더 경로 자동 계산)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sounds_dir = os.path.join(
            os.path.dirname(current_dir), "assets", "sounds"
        )
        self.sound = SoundManager(sounds_dir)
        
        # FPS
        self.prev_time = time.time()
        self.fps = 0.0
        
        # 카운트다운 사운드 트리거 (각 숫자 한 번만)
        self.countdown_played = set()
        
        # ★ 화면 크기 / 전체 화면 상태
        self.window_name = "PlayWait - RPS Evolution"
        self.display_scale = theme.DISPLAY_SCALE  # 기본 1.5
        self.is_fullscreen = False

        # 카메라 인덱스 (moca 통합용 — `--camera-index` 로 override).
        # PlayWait 단독 실행 시 0 (내장). moca minigame_runner 가 노트북 외장
        # 카메라 3 (RPC-20F) 인덱스를 전달.
        self.camera_index = 0
    
    # ----------------------------------------
    # 초기화
    # ----------------------------------------
    def setup(self):
        # self.camera_index (기본 0) — moca 통합 시 --camera-index 로 외장 캠
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print("❌ 카메라를 열 수 없습니다.")
            print("\n🔧 해결 방법:")
            print("   1. 다른 프로그램이 카메라를 사용 중인지 확인")
            print("      (Zoom, Teams, OBS, 브라우저 등)")
            print("   2. 이전 게임 프로세스가 남아있을 수 있음:")
            print("      $ pkill -f 'games.06_rps_evolution'")
            print("      $ sudo fuser -k /dev/video0")
            print("   3. 외장 카메라라면 카메라 인덱스를 1, 2로 변경")
            print("   4. USB 카메라 재연결 또는 시스템 재부팅")
            self.cap = None  # 명시적으로 None 처리
            return False
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, theme.SCREEN_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, theme.SCREEN_HEIGHT)
        
        # 카메라가 실제로 읽히는지 검증
        ret, _ = self.cap.read()
        if not ret:
            print("❌ 카메라는 열렸지만 프레임을 읽을 수 없습니다.")
            self.cap.release()
            self.cap = None
            return False
        
        self.hands = mp_hands.Hands(
            model_complexity=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
            max_num_hands=1,
        )
        
        # ★ 윈도우 미리 생성 (resize/fullscreen 가능하게)
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        self._apply_window_size()
        # 외부 호출자가 init 전 is_fullscreen=True 설정 시 풀스크린 적용
        if self.is_fullscreen:
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN)

        return True
    
    # ----------------------------------------
    # 페이즈 전환
    # ----------------------------------------
    def change_phase(self, new_phase: GamePhase):
        prev_phase = self.phase
        self.phase = new_phase
        self.phase_start_time = time.time()
        if new_phase == GamePhase.COUNTDOWN:
            self.countdown_played.clear()
        # 첫 라운드 진입 시각 (DIFFICULTY_SELECT → READY)
        if (prev_phase == GamePhase.DIFFICULTY_SELECT
                and new_phase == GamePhase.READY
                and self.game_started_at is None):
            self.game_started_at = time.time()
        # GAME_OVER 진입 시 결과 저장 + auto-exit 타이머 시작
        if (new_phase == GamePhase.GAME_OVER
                and prev_phase != GamePhase.GAME_OVER):
            self.game_over_at = time.time()
            self._save_result_json(completed=True)

    def _save_result_json(self, completed: bool):
        """결과를 JSON 파일로 저장 (외부 ROS 통합용)."""
        if not self.result_json_path:
            return
        import json
        gs = self.game_state
        ties = sum(1 for h in gs.history if h.get("result") == "draw")
        duration = 0.0
        if self.game_started_at is not None:
            duration = time.time() - self.game_started_at
        payload = {
            "customer_wins": int(gs.user_score),
            "robot_wins": int(gs.ai_score),
            "ties": int(ties),
            "rounds_played": int(len(gs.history)),
            "completed": bool(completed),
            "duration_sec": float(duration),
        }
        try:
            with open(self.result_json_path, "w") as f:
                json.dump(payload, f)
            print(f"💾 결과 저장: {self.result_json_path} {payload}")
        except Exception as e:
            print(f"⚠️  결과 저장 실패: {e}")

    def get_phase_elapsed(self) -> float:
        return time.time() - self.phase_start_time
    
    # ----------------------------------------
    # 키 입력
    # ----------------------------------------
    def handle_key(self, key: int) -> bool:
        if key == ord('q') or key == 27:
            return False
        
        # ★ 화면 크기 조절 (모든 페이즈에서 동작)
        if key == ord('f') or key == ord('F'):
            self._toggle_fullscreen()
            return True
        elif key in (ord('+'), ord('=')):
            self.display_scale = min(3.0, self.display_scale + 0.25)
            self._apply_window_size()
            print(f"🔍 화면 크기: {self.display_scale:.2f}x")
            return True
        elif key in (ord('-'), ord('_')):
            self.display_scale = max(0.5, self.display_scale - 0.25)
            self._apply_window_size()
            print(f"🔍 화면 크기: {self.display_scale:.2f}x")
            return True
        elif key == ord('0'):
            self.display_scale = theme.DISPLAY_SCALE
            self.is_fullscreen = False
            self._apply_window_size()
            print(f"🔍 화면 크기 리셋: {self.display_scale:.2f}x")
            return True
        
        # 페이즈별 키 처리
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            if key in (ord('1'), ord('2'), ord('3')):
                difficulty = {ord('1'): "easy", ord('2'): "normal", 
                              ord('3'): "hard"}[key]
                self.ai_player = AIPlayer(difficulty=difficulty)
                self.sound.play("click")
                print(f"🤖 난이도: {theme.DIFFICULTY_KOREAN[difficulty]}")
                self.change_phase(GamePhase.READY)
        
        elif self.phase == GamePhase.READY:
            if key == ord(' '):
                self.sound.play("click")
                print(f"\n--- 라운드 {self.game_state.round_number} 시작 ---")
                self.change_phase(GamePhase.COUNTDOWN)
        
        elif self.phase == GamePhase.GAME_OVER:
            if key in (ord('r'), ord('R')):
                self.game_state.reset()
                self.ai_player.reset()
                self.stability.reset()
                self.sound.play("click")
                print("\n🔄 게임 재시작!")
                self.change_phase(GamePhase.DIFFICULTY_SELECT)
        
        return True
    
    # ----------------------------------------
    # 화면 크기 관리
    # ----------------------------------------
    def _toggle_fullscreen(self):
        """전체 화면 토글"""
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN
            )
            print("🖥️  전체 화면 ON")
        else:
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_NORMAL
            )
            self._apply_window_size()
            print("🖥️  전체 화면 OFF")
    
    def _apply_window_size(self):
        """현재 display_scale에 맞춰 창 크기 적용"""
        if self.is_fullscreen:
            return
        w = int(theme.SCREEN_WIDTH * self.display_scale)
        h = int(theme.SCREEN_HEIGHT * self.display_scale)
        cv2.resizeWindow(self.window_name, w, h)
    
    # ----------------------------------------
    # 페이즈별 로직
    # ----------------------------------------
    def update_phase(self, current_shape: str):
        elapsed = self.get_phase_elapsed()

        # 자동화 — 외부 호출자가 키 입력 없이 흐름 자동 진행
        if self.auto_play:
            if self.phase == GamePhase.DIFFICULTY_SELECT:
                diff = self.auto_play_difficulty or "normal"
                self.ai_player = AIPlayer(difficulty=diff)
                print(f"🤖 [auto_play] 난이도: {diff}")
                self.change_phase(GamePhase.READY)
                return
            if (self.phase == GamePhase.READY
                    and elapsed >= self.auto_play_ready_delay):
                print(f"\n--- [auto_play] 라운드 "
                      f"{self.game_state.round_number} 시작 ---")
                self.change_phase(GamePhase.COUNTDOWN)
                return

        if self.phase == GamePhase.COUNTDOWN:
            count = max(1, int(theme.TIMING_COUNTDOWN - elapsed) + 1)
            # countdown 사운드는 자체로 3-2-1 카운트 포함 (4초). 첫 진입 시 1번만
            # 재생하고 그 후 trigger 무시 — 매 숫자마다 trigger 시 overlap 발생.
            if not self.countdown_played and count <= 3:
                self.countdown_played.add("started")
                self.sound.play("countdown")

            if elapsed >= theme.TIMING_COUNTDOWN:
                self.stability.reset()
                self.change_phase(GamePhase.DETECTING)
        
        elif self.phase == GamePhase.DETECTING:
            confirmed = self.stability.update(current_shape)
            if elapsed >= theme.TIMING_DETECTION:
                if confirmed != "unknown":
                    self.user_shape = confirmed
                    self.ai_shape = self.ai_player.choose_shape()
                    self.sound.play("reveal")
                    print(f"  👤 나: {theme.SHAPE_KOREAN_FULL[self.user_shape]}")
                    print(f"  🤖 Doby: {theme.SHAPE_KOREAN_FULL[self.ai_shape]}")
                    self.change_phase(GamePhase.REVEAL)
                else:
                    print("  ⚠️  손 모양 인식 실패. 다시 시도.")
                    self.change_phase(GamePhase.COUNTDOWN)
        
        elif self.phase == GamePhase.REVEAL:
            if elapsed >= theme.TIMING_REVEAL:
                round_data = self.game_state.play_round(
                    self.user_shape, self.ai_shape
                )
                self.round_result = round_data
                self.ai_player.record_user_shape(self.user_shape)
                
                # 결과 사운드
                result_sound = {
                    "user_win": "win",
                    "ai_win": "lose",
                    "draw": "click"
                }.get(round_data["result"], "click")
                self.sound.play(result_sound)
                
                # 콘솔 결과
                result_emoji = {
                    "user_win": "🎉 승리!",
                    "ai_win": "😢 패배",
                    "draw": "🤝 무승부"
                }
                print(f"  → {result_emoji[round_data['result']]} "
                      f"(점수 {round_data['user_score']}:{round_data['ai_score']})")
                
                self.change_phase(GamePhase.ROUND_RESULT)
        
        elif self.phase == GamePhase.ROUND_RESULT:
            if elapsed >= theme.TIMING_ROUND_RESULT:
                if self.round_result["is_game_over"]:
                    winner = self.round_result["winner"]
                    if winner == "user":
                        self.sound.play("victory")
                        print(f"\n{'='*40}")
                        print("🏆 게임 우승! 쿠폰 발급!")
                        print(f"{'='*40}")
                    else:
                        self.sound.play("lose")
                        print(f"\n{'='*40}")
                        print("😢 게임 패배. 다시 도전하세요!")
                        print(f"{'='*40}")
                    self.change_phase(GamePhase.GAME_OVER)
                else:
                    self.change_phase(GamePhase.READY)
    
    # ----------------------------------------
    # 렌더링 (페이즈별 UI 합성)
    # ----------------------------------------
    def render(self, frame, current_shape: str, hand_detected: bool):
        # 텍스트 큐 초기화 (배치 렌더링 시작)
        ui.begin_frame()
        
        # 1. DIFFICULTY_SELECT - 난이도 선택 화면
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            ui.draw_difficulty_select(frame)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)  # 텍스트 큐 비우고 한 번에 렌더링
            return frame
        
        # 2. 공통: 점수 바 + AI 영역
        ui.draw_score_bar(
            frame,
            self.game_state.user_score,
            self.game_state.ai_score,
            self.game_state.max_score,
            self.ai_player.difficulty,
            self.game_state.round_number,
        )
        
        # AI 영역 (REVEAL 페이즈와 ROUND_RESULT에서만 손 공개)
        is_revealed = self.phase in (GamePhase.REVEAL, GamePhase.ROUND_RESULT)
        ui.draw_ai_area(frame, self.ai_shape, is_revealed)
        
        # 3. 페이즈별 메시지/효과
        if self.phase == GamePhase.READY:
            ui.draw_message_bar(frame, "스페이스를 눌러 라운드 시작",
                                 theme.PINKLAB_PINK)
            ui.draw_user_indicator(frame, current_shape, hand_detected)
        
        elif self.phase == GamePhase.COUNTDOWN:
            elapsed = self.get_phase_elapsed()
            count = max(1, int(theme.TIMING_COUNTDOWN - elapsed) + 1)
            count = min(3, count)
            ui.draw_message_bar(frame, "준비!", theme.COLOR_DRAW)
            ui.draw_countdown(frame, count)
        
        elif self.phase == GamePhase.DETECTING:
            ui.draw_message_bar(frame, "손 모양을 보여주세요!",
                                 theme.COLOR_WIN)
            ui.draw_user_indicator(frame, current_shape, hand_detected)
        
        elif self.phase == GamePhase.REVEAL:
            ui.draw_message_bar(frame, "결과 확인 중...",
                                 theme.COLOR_DRAW)
            ui.draw_user_indicator(frame, self.user_shape, True)
        
        elif self.phase == GamePhase.ROUND_RESULT:
            ui.draw_round_result(
                frame,
                self.round_result["result"],
                self.user_shape,
                self.ai_shape,
            )
        
        elif self.phase == GamePhase.GAME_OVER:
            ui.draw_game_over(frame, self.round_result["winner"])
        
        # 4. 공통: FPS
        ui.draw_fps(frame, self.fps)
        
        # ★ 모든 텍스트를 한 번에 렌더링 (성능 핵심)
        ui.flush_text(frame)
        
        return frame
    
    # ----------------------------------------
    # 메인 루프
    # ----------------------------------------
    def run(self):
        if not self.setup():
            return
        
        print("\n" + "=" * 50)
        print("🎮 PlayWait - 가위바위보 진화 (RPS Evolution)")
        print("=" * 50)
        print("\n[게임 조작]")
        print("  [1] 쉬움  [2] 보통  [3] 어려움 - 난이도 선택")
        print("  [SPACE] - 라운드 시작")
        print("  [R] - 재시작 (게임 종료 후)")
        print("  [Q/ESC] - 종료")
        print("\n[화면 조작]")
        print("  [F] - 전체 화면 토글")
        print("  [+/=] - 화면 크기 키우기")
        print("  [-/_] - 화면 크기 줄이기")
        print("  [0] - 기본 크기로 리셋")
        print()
        
        try:
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
                
                # 손 분류
                current_shape = "unknown"
                hand_detected = False
                
                if results.multi_hand_landmarks:
                    hand_landmarks = results.multi_hand_landmarks[0]
                    handedness = results.multi_handedness[0]
                    
                    raw_label = handedness.classification[0].label
                    hand_label = "Right" if raw_label == "Left" else "Left"
                    
                    # 일부 페이즈에서만 손 그리기
                    if self.phase in (GamePhase.READY, GamePhase.COUNTDOWN,
                                       GamePhase.DETECTING):
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
                
                # FPS
                curr_time = time.time()
                elapsed = curr_time - self.prev_time
                if elapsed > 0:
                    self.fps = 1.0 / elapsed
                self.prev_time = curr_time
                
                # UI 합성
                frame = self.render(frame, current_shape, hand_detected)
                
                # ★ 화면 크기 적용
                if self.is_fullscreen:
                    # 전체 화면: 그대로 표시 (Window가 알아서 stretching)
                    cv2.imshow(self.window_name, frame)
                else:
                    # 일반 모드: display_scale 만큼 확대
                    if self.display_scale != 1.0:
                        display_frame = cv2.resize(
                            frame,
                            (int(theme.SCREEN_WIDTH * self.display_scale),
                             int(theme.SCREEN_HEIGHT * self.display_scale)),
                            interpolation=cv2.INTER_LINEAR
                        )
                    else:
                        display_frame = frame
                    cv2.imshow(self.window_name, display_frame)
                
                key = cv2.waitKey(1) & 0xFF
                if not self.handle_key(key):
                    break

                # auto-exit (ROS 통합) — GAME_OVER 후 N초 경과 시 자동 종료
                if (self.auto_exit_sec is not None
                        and self.phase == GamePhase.GAME_OVER
                        and self.game_over_at is not None
                        and time.time() - self.game_over_at >= self.auto_exit_sec):
                    print(f"⏰ auto-exit ({self.auto_exit_sec:.1f}s) → 종료")
                    break

        except KeyboardInterrupt:
            print("\n⚠️  사용자가 Ctrl+C로 중단")
        except Exception as e:
            print(f"\n❌ 게임 중 오류 발생: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ★ 어떤 경우에도 반드시 cleanup 실행
            self.cleanup()
    
    # ----------------------------------------
    # 안전 종료 (cleanup)
    # ----------------------------------------
    def cleanup(self):
        """모든 리소스 안전하게 해제 (멱등성 보장)"""
        print("\n🧹 리소스 정리 중...")
        
        # 카메라 해제
        if self.cap is not None:
            try:
                if self.cap.isOpened():
                    self.cap.release()
                    print("   ✓ 카메라 해제")
            except Exception as e:
                print(f"   ⚠️  카메라 해제 오류: {e}")
            finally:
                self.cap = None
        
        # MediaPipe 해제
        if self.hands is not None:
            try:
                self.hands.close()
                print("   ✓ MediaPipe 해제")
            except Exception as e:
                print(f"   ⚠️  MediaPipe 해제 오류: {e}")
            finally:
                self.hands = None
        
        # 사운드 해제
        if self.sound is not None:
            try:
                self.sound.cleanup()
                print("   ✓ 사운드 해제")
            except Exception as e:
                print(f"   ⚠️  사운드 해제 오류: {e}")
        
        # OpenCV 윈도우 정리
        try:
            cv2.destroyAllWindows()
            # waitKey 호출로 윈도우 종료 이벤트 처리
            for _ in range(4):
                cv2.waitKey(1)
            print("   ✓ 윈도우 닫음")
        except Exception as e:
            print(f"   ⚠️  윈도우 종료 오류: {e}")
        
        print("✅ 게임 종료 완료")


# ============================================================
# 6. 진입점 (시그널 핸들러 + atexit 등록)
# ============================================================
import signal
import atexit

# 전역 게임 인스턴스 (시그널 핸들러에서 접근용)
_game_instance = None


def _signal_handler(signum, frame):
    """SIGINT(Ctrl+C), SIGTERM 처리"""
    print(f"\n⚠️  시그널 수신: {signal.Signals(signum).name}")
    if _game_instance is not None:
        _game_instance.cleanup()
    import sys
    sys.exit(0)


def _atexit_cleanup():
    """인터프리터 종료 시 마지막 안전장치"""
    if _game_instance is not None:
        _game_instance.cleanup()


def main():
    global _game_instance
    import argparse

    parser = argparse.ArgumentParser(description="RPS Evolution game")
    parser.add_argument(
        "--auto-play", action="store_true",
        help="키 입력 없이 자동 진행 (ROS 통합 시).")
    parser.add_argument(
        "--difficulty", default=None,
        choices=["easy", "normal", "hard"],
        help="auto-play 시 난이도 (기본 normal).")
    parser.add_argument(
        "--result-json", default=None,
        help="GAME_OVER 진입 시 결과 JSON 저장 경로.")
    parser.add_argument(
        "--auto-exit", type=float, default=None,
        help="GAME_OVER N 초 후 자동 종료 (초).")
    parser.add_argument(
        "--ready-delay", type=float, default=1.5,
        help="auto-play READY 페이즈 대기 시간 (기본 1.5초).")
    parser.add_argument(
        "--fullscreen", action="store_true",
        help="cv2 윈도우 풀스크린 (호객 시연용).")
    parser.add_argument(
        "--camera-index", type=int, default=0,
        help="cv2.VideoCapture 인덱스 (기본 0=내장. moca 외장 캠은 2 등).")
    args = parser.parse_args()

    # 시그널 핸들러 등록 (Ctrl+C, kill)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # atexit 훅 등록 (정상 종료 시)
    atexit.register(_atexit_cleanup)

    # 게임 실행
    _game_instance = RPSEvolutionGame()
    _game_instance.auto_play = args.auto_play
    _game_instance.auto_play_difficulty = args.difficulty
    _game_instance.auto_play_ready_delay = args.ready_delay
    _game_instance.result_json_path = args.result_json
    _game_instance.auto_exit_sec = args.auto_exit
    _game_instance.is_fullscreen = bool(args.fullscreen)
    _game_instance.camera_index = int(args.camera_index)

    try:
        _game_instance.run()
    finally:
        _game_instance = None


if __name__ == "__main__":
    main()
