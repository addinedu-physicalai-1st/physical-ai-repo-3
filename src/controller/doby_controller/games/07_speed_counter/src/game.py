"""
game.py - 스피드 카운터 (Speed Counter) 메인 게임
==================================================

W2 PlayWait - AI Vision 기반 매장 대기시간 게임
양손 손가락으로 1~10 만들기, 5연속 정답 시 승리

W1 (가위바위보 진화) 의 game.py 구조를 재활용하여 빠르게 구현.
변경 핵심:
- 손 모양 분류 → 양손 손가락 합산
- 라운드 기반 → 시간 기반 (가속 시스템)
- 3선 2승 → 5연속 정답

실행:
    cd ~/PlayWait
    python -m games.07_speed_counter.src.game

조작:
    [1/2/3]  난이도 선택 (쉬움/보통/어려움)
    [SPACE]  게임 시작
    [R]      재시작 (게임 종료 후)
    [Q/ESC]  종료
    [F]      전체 화면 토글
    [+/=]    화면 확대
    [-/_]    화면 축소
    [0]      기본 크기 리셋

Author: Stephen (gjkong)
Date: 2026-04-30 (W2 Step 4)
"""

import os
import sys
import cv2
import time
import signal
import atexit
import numpy as np
import mediapipe as mp
from enum import Enum

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from .hand_counter import (
        count_fingers_total, StabilityBuffer
    )
    from .question_gen import (
        QuestionGenerator, get_time_limit, get_speed_phase,
        DIFFICULTY_NORMAL, DIFFICULTIES
    )
    from .score_tracker import (
        ScoreTracker, END_NONE, END_WIN, END_TIMEOUT, END_TOO_MANY_FAILS
    )
    from .sound_manager import SoundManager
    from . import theme
    from . import ui_renderer as ui
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hand_counter import count_fingers_total, StabilityBuffer
    from question_gen import (
        QuestionGenerator, get_time_limit, get_speed_phase,
        DIFFICULTY_NORMAL, DIFFICULTIES
    )
    from score_tracker import (
        ScoreTracker, END_NONE, END_WIN, END_TIMEOUT, END_TOO_MANY_FAILS
    )
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
# 2. 게임 페이즈
# ============================================================
class GamePhase(Enum):
    DIFFICULTY_SELECT = "difficulty_select"
    READY = "ready"                  # 게임 시작 대기 (SPACE)
    QUESTION = "question"            # 출제 + 손 인식
    ROUND_RESULT = "round_result"    # 정답/오답 표시
    GAME_OVER = "game_over"          # 게임 종료


# ============================================================
# 3. 메인 게임 클래스
# ============================================================
class SpeedCounterGame:
    """스피드 카운터 메인 게임"""
    
    def __init__(self):
        # 카메라 & MediaPipe
        self.cap = None
        self.hands = None

        # 게임 상태
        self.score = ScoreTracker()
        self.qgen = QuestionGenerator()
        self.stability = StabilityBuffer(window_size=5, threshold=4)
        self.phase = GamePhase.DIFFICULTY_SELECT
        self.phase_start_time = 0.0

        # === ROS 통합 — 자동화 / 결과 출력 옵션 (minigame_runner 가 설정) ===
        self.auto_play = False
        self.auto_play_difficulty = None
        self.auto_play_ready_delay = 3.0
        self.result_json_path = None
        self.auto_exit_sec = None
        self.game_started_at = None
        self.game_over_at = None
        
        # 라운드 데이터
        self.difficulty = DIFFICULTY_NORMAL
        self.current_question = None       # 현재 출제 숫자
        self.current_time_limit = 3.0      # 현재 라운드 제한 시간
        self.last_user_total = None        # 마지막 사용자 합계
        self.last_round_correct = None     # 마지막 라운드 정답 여부
        
        # 사운드
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sounds_dir = os.path.join(
            os.path.dirname(current_dir), "assets", "sounds"
        )
        self.sound = SoundManager(sounds_dir)
        
        # FPS
        self.prev_time = time.time()
        self.fps = 0.0
        
        # 화면 크기
        self.window_name = "PlayWait - Speed Counter"
        self.display_scale = theme.DISPLAY_SCALE
        self.is_fullscreen = False

        # 카메라 인덱스 (moca 통합용 — `--camera-index` 로 override).
        self.camera_index = 0

    # ----------------------------------------
    # 초기화
    # ----------------------------------------
    def setup(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            print("❌ 카메라를 열 수 없습니다.")
            print("\n🔧 해결:")
            print("   sudo fuser -k /dev/video0")
            self.cap = None
            return False
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, theme.SCREEN_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, theme.SCREEN_HEIGHT)
        
        ret, _ = self.cap.read()
        if not ret:
            print("❌ 카메라 프레임을 읽을 수 없습니다.")
            self.cap.release()
            self.cap = None
            return False
        
        self.hands = mp_hands.Hands(
            model_complexity=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
            max_num_hands=2,  # ★ W2: 두 손
        )
        
        # WINDOW_KEEPRATIO — fullscreen 시 cv2 가 frame aspect 자동 유지 + letterbox.
        # (stretch 가 default 라 가로/세로 비율 다른 화면에서 frame 늘어남)
        cv2.namedWindow(self.window_name,
                         cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        self._apply_window_size()
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
        """결과를 JSON 파일로 저장 (외부 ROS 통합용).

        END_WIN → customer_wins=1, 그 외(timeout/too_many_fails/none) →
        robot_wins=1. ties 는 사용 안 함 (speed_counter 무승부 없음).
        """
        if not self.result_json_path:
            return
        import json
        end = self.score.check_end()
        customer_won = (end == END_WIN)
        summary = self.score.get_summary() or {}
        rounds_played = int(
            summary.get("round_count",
                        summary.get("total_correct", 0)
                        + summary.get("total_wrong", 0)))
        duration = 0.0
        if self.game_started_at is not None:
            duration = time.time() - self.game_started_at
        payload = {
            "customer_wins": 1 if customer_won else 0,
            "robot_wins": 0 if customer_won else 1,
            "ties": 0,
            "rounds_played": rounds_played,
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
    # 새 라운드 시작
    # ----------------------------------------
    def start_new_round(self):
        """다음 출제 + 시간 결정"""
        self.current_question = self.qgen.next_question()
        self.current_time_limit = get_time_limit(
            self.score.combo, self.difficulty
        )
        self.stability.reset()
        self.last_user_total = None
        self.change_phase(GamePhase.QUESTION)
        
        phase_name = get_speed_phase(self.score.combo)
        print(f"\n[R{self.score.round_count + 1}] 숫자: {self.current_question}, "
              f"시간: {self.current_time_limit:.1f}s ({phase_name})")
    
    # ----------------------------------------
    # 키 입력
    # ----------------------------------------
    def handle_key(self, key: int) -> bool:
        if key == ord('q') or key == 27:
            return False
        
        # 화면 크기 조절 (모든 페이즈)
        if key in (ord('f'), ord('F')):
            self._toggle_fullscreen()
            return True
        elif key in (ord('+'), ord('=')):
            self.display_scale = min(3.0, self.display_scale + 0.25)
            self._apply_window_size()
            print(f"🔍 화면: {self.display_scale:.2f}x")
            return True
        elif key in (ord('-'), ord('_')):
            self.display_scale = max(0.5, self.display_scale - 0.25)
            self._apply_window_size()
            print(f"🔍 화면: {self.display_scale:.2f}x")
            return True
        elif key == ord('0'):
            self.display_scale = theme.DISPLAY_SCALE
            self.is_fullscreen = False
            self._apply_window_size()
            return True
        
        # 페이즈별 키
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            if key in (ord('1'), ord('2'), ord('3')):
                diff_map = {ord('1'): "easy", ord('2'): "normal", 
                            ord('3'): "hard"}
                self.difficulty = diff_map[key]
                self.sound.play("click")
                print(f"🎮 난이도: {theme.DIFFICULTY_KOREAN[self.difficulty]}")
                self.change_phase(GamePhase.READY)
        
        elif self.phase == GamePhase.READY:
            if key == ord(' '):
                self.sound.play("click")
                self.score.start_game()
                print(f"\n=== 게임 시작 ===")
                self.start_new_round()
        
        elif self.phase == GamePhase.GAME_OVER:
            if key in (ord('r'), ord('R')):
                self.score.reset()
                self.qgen.reset()
                self.stability.reset()
                self.sound.play("click")
                print("\n🔄 게임 재시작")
                self.change_phase(GamePhase.DIFFICULTY_SELECT)
        
        return True
    
    # ----------------------------------------
    # 화면 크기 관리
    # ----------------------------------------
    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            cv2.setWindowProperty(self.window_name,
                                   cv2.WND_PROP_FULLSCREEN,
                                   cv2.WINDOW_FULLSCREEN)
            print("🖥️  전체 화면 ON")
        else:
            cv2.setWindowProperty(self.window_name,
                                   cv2.WND_PROP_FULLSCREEN,
                                   cv2.WINDOW_NORMAL)
            self._apply_window_size()
            print("🖥️  전체 화면 OFF")
    
    def _apply_window_size(self):
        if self.is_fullscreen:
            return
        w = int(theme.SCREEN_WIDTH * self.display_scale)
        h = int(theme.SCREEN_HEIGHT * self.display_scale)
        cv2.resizeWindow(self.window_name, w, h)
    
    # ----------------------------------------
    # 페이즈별 로직
    # ----------------------------------------
    def update_phase(self, count_result):
        """페이즈별 게임 로직 업데이트

        Args:
            count_result: count_fingers_total() 결과 dict
        """
        elapsed = self.get_phase_elapsed()

        # 자동화 — 외부 호출자가 키 입력 없이 흐름 자동 진행
        if self.auto_play:
            if self.phase == GamePhase.DIFFICULTY_SELECT:
                self.difficulty = self.auto_play_difficulty or "normal"
                print(f"🎮 [auto_play] 난이도: {self.difficulty}")
                self.change_phase(GamePhase.READY)
                return
            if (self.phase == GamePhase.READY
                    and elapsed >= self.auto_play_ready_delay):
                self.score.start_game()
                print("\n=== [auto_play] 게임 시작 ===")
                self.start_new_round()
                return

        if self.phase == GamePhase.QUESTION:
            # 안정화 버퍼 업데이트
            current_total = count_result["total"]
            confirmed = self.stability.update(current_total)
            self.last_user_total = confirmed
            
            # 시간 초과 체크
            if elapsed >= self.current_time_limit:
                # 정답 여부 판정
                is_correct = (confirmed == self.current_question)
                self.last_round_correct = is_correct
                
                if is_correct:
                    self.score.record_correct()
                    self.sound.play("win")
                    print(f"  ✅ 정답! ({self.current_question} = {confirmed}) "
                          f"콤보 {self.score.combo}")
                else:
                    self.score.record_wrong()
                    self.sound.play("lose")
                    user_str = str(confirmed) if confirmed is not None else "인식실패"
                    print(f"  ❌ 오답! 정답 {self.current_question}, "
                          f"당신 {user_str} | 오답 {self.score.total_wrong}/5")
                
                self.change_phase(GamePhase.ROUND_RESULT)
        
        elif self.phase == GamePhase.ROUND_RESULT:
            # 1.5초 결과 표시 후 다음 진행
            if elapsed >= 1.5:
                # 게임 종료 체크
                end = self.score.check_end()
                if end != END_NONE:
                    if end == END_WIN:
                        self.sound.play("victory")
                        print(f"\n{'='*40}")
                        print(f"🏆 우승! 5연속 정답 달성!")
                        print(f"{'='*40}")
                    elif end == END_TIMEOUT:
                        self.sound.play("lose")
                        print(f"\n{'='*40}")
                        print(f"⏰ 시간 초과")
                        print(f"{'='*40}")
                    elif end == END_TOO_MANY_FAILS:
                        self.sound.play("lose")
                        print(f"\n{'='*40}")
                        print(f"💔 오답 5회 누적")
                        print(f"{'='*40}")
                    
                    summary = self.score.get_summary()
                    print(f"   최고 콤보: {summary['max_combo']}, "
                          f"정답 {summary['total_correct']}, "
                          f"오답 {summary['total_wrong']}")
                    
                    self.change_phase(GamePhase.GAME_OVER)
                else:
                    # 다음 라운드
                    self.start_new_round()
    
    # ----------------------------------------
    # 렌더링
    # ----------------------------------------
    def render(self, frame, count_result):
        ui.begin_frame()
        
        # 1. 난이도 선택
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            ui.draw_speed_difficulty_select(frame)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)
            return frame
        
        # 2. 공통: 점수바
        ui.draw_speed_score_bar(
            frame,
            combo=self.score.combo,
            win_combo=ScoreTracker.WIN_COMBO,
            fails=self.score.total_wrong,
            max_fails=ScoreTracker.MAX_FAILS,
            remaining_time=self.score.get_remaining(),
        )
        
        # 3. 페이즈별
        if self.phase == GamePhase.READY:
            cx = theme.SCREEN_WIDTH // 2
            cy = theme.SCREEN_HEIGHT // 2
            
            ui.draw_text_korean(frame, "준비되셨나요?", (cx, cy - 60),
                                  theme.FONT_SIZE_LARGE, theme.COLOR_WHITE,
                                  anchor="mm")
            ui.draw_text_korean(frame, "양손을 카메라에 보여주세요",
                                  (cx, cy - 10),
                                  theme.FONT_SIZE_NORMAL,
                                  theme.COLOR_GRAY_LIGHT, anchor="mm")
            ui.draw_text_korean(frame, "[SPACE] 게임 시작", (cx, cy + 50),
                                  theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK,
                                  anchor="mm")
            ui.draw_text_korean(frame, "5연속 정답이 목표!", (cx, cy + 110),
                                  theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW,
                                  anchor="mm")
        
        elif self.phase == GamePhase.QUESTION:
            # 출제 숫자 (큰 표시)
            ui.draw_question_number(frame, self.current_question)
            
            # 타이머 바
            elapsed = self.get_phase_elapsed()
            remaining = max(0.0, self.current_time_limit - elapsed)
            ui.draw_timer_bar(frame, remaining, self.current_time_limit)
            
            # 사용자 손가락 표시
            ui.draw_user_count_indicator(
                frame,
                count_result["total"],
                self.current_question,
                count_result["left"],
                count_result["right"],
            )
        
        elif self.phase == GamePhase.ROUND_RESULT:
            ui.draw_round_feedback(
                frame,
                self.last_round_correct,
                self.current_question,
                self.last_user_total,
            )
        
        elif self.phase == GamePhase.GAME_OVER:
            end = self.score.check_end()
            ui.draw_speed_game_over(
                frame,
                win=(end == END_WIN),
                end_reason=end,
                max_combo=self.score.max_combo,
                total_correct=self.score.total_correct,
                total_wrong=self.score.total_wrong,
            )
        
        # 4. FPS
        ui.draw_fps(frame, self.fps)
        ui.flush_text(frame)
        
        return frame
    
    # ----------------------------------------
    # 메인 루프
    # ----------------------------------------
    def run(self):
        if not self.setup():
            return
        
        print("\n" + "=" * 50)
        print("🎮 PlayWait W2 - 스피드 카운터 (Speed Counter)")
        print("=" * 50)
        print("\n[게임 조작]")
        print("  [1/2/3] 난이도 선택")
        print("  [SPACE] 게임 시작")
        print("  [R] 재시작 (게임 종료 후)")
        print("  [Q/ESC] 종료")
        print("\n[화면 조작]")
        print("  [F] 전체 화면 / [+] 확대 / [-] 축소 / [0] 리셋")
        print()
        
        try:
            while self.cap.isOpened():
                success, frame = self.cap.read()
                if not success:
                    continue
                
                frame = cv2.flip(frame, 1)
                
                # MediaPipe
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = self.hands.process(rgb)
                rgb.flags.writeable = True
                
                # 양손 손가락 합산
                count_result = count_fingers_total(results)
                
                # 손 랜드마크 그리기 (QUESTION 페이즈에서만)
                if (self.phase == GamePhase.QUESTION 
                        and results.multi_hand_landmarks):
                    for hl in results.multi_hand_landmarks:
                        mp_drawing.draw_landmarks(
                            frame, hl, mp_hands.HAND_CONNECTIONS,
                            mp_drawing_styles.get_default_hand_landmarks_style(),
                            mp_drawing_styles.get_default_hand_connections_style(),
                        )
                
                # 페이즈 업데이트
                self.update_phase(count_result)
                
                # FPS
                curr = time.time()
                elapsed = curr - self.prev_time
                if elapsed > 0:
                    self.fps = 1.0 / elapsed
                self.prev_time = curr
                
                # UI
                frame = self.render(frame, count_result)
                
                # 화면 표시
                if self.is_fullscreen:
                    # WINDOW_KEEPRATIO + WND_PROP_FULLSCREEN → cv2 자동 letterbox
                    cv2.imshow(self.window_name, frame)
                else:
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
            print(f"\n❌ 오류: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    # ----------------------------------------
    # 안전 종료
    # ----------------------------------------
    def cleanup(self):
        """모든 리소스 안전하게 해제"""
        print("\n🧹 리소스 정리 중...")
        
        if self.cap is not None:
            try:
                if self.cap.isOpened():
                    self.cap.release()
                    print("   ✓ 카메라 해제")
            except Exception:
                pass
            finally:
                self.cap = None
        
        if self.hands is not None:
            try:
                self.hands.close()
                print("   ✓ MediaPipe 해제")
            except Exception:
                pass
            finally:
                self.hands = None
        
        if self.sound is not None:
            try:
                self.sound.cleanup()
                print("   ✓ 사운드 해제")
            except Exception:
                pass
        
        try:
            cv2.destroyAllWindows()
            for _ in range(4):
                cv2.waitKey(1)
            print("   ✓ 윈도우 닫음")
        except Exception:
            pass
        
        print("✅ 게임 종료 완료")


# ============================================================
# 4. 시그널 핸들러 + atexit
# ============================================================
_game_instance = None


def _signal_handler(signum, frame):
    print(f"\n⚠️  시그널: {signal.Signals(signum).name}")
    if _game_instance is not None:
        _game_instance.cleanup()
    sys.exit(0)


def _atexit_cleanup():
    if _game_instance is not None:
        _game_instance.cleanup()


def main():
    global _game_instance
    import argparse

    parser = argparse.ArgumentParser(description="Speed Counter game")
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
        "--ready-delay", type=float, default=3.0,
        help="auto-play READY 페이즈 대기 시간 (기본 3.0초 — 게임 설명 보일 시간).")
    parser.add_argument(
        "--fullscreen", action="store_true",
        help="cv2 윈도우 풀스크린 (호객 시연용).")
    parser.add_argument(
        "--camera-index", type=int, default=0,
        help="cv2.VideoCapture 인덱스 (기본 0=내장. moca 외장 캠은 2 등).")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(_atexit_cleanup)

    _game_instance = SpeedCounterGame()
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
