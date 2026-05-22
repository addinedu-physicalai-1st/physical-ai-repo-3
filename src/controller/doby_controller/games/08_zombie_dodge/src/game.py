"""
game.py — W7 좀비 피하기 (Zombie Dodge)
=========================================

PlayWait W7 — 위에서 떨어지는 좀비를 몸으로 피하는 액션 게임. 할로윈 시즌.
60초 / 생명 3 / 목표 점수 달성 시 승리.

기술 스택
---------
- MediaPipe Pose (33 landmark, model_complexity=1)
- body_tracker.compute_dodge_box: Pose → 회피 박스 AABB (순수)
- zombie + zombie_spawner: 낙하 객체 + 난이도별 spawn (순수)
- dodge_judge.evaluate_frame: AABB-원 충돌 + 통과 판정 (순수)
- dodge_state: 점수·생명·시간·종료 (순수, time_provider 주입 가능)

W3·W4·W5·W6 인프라 재활용
--------------------------
- theme.py        (PinkLAB + W7 좀비 토큰)
- ui_renderer.py  (한글 PIL + 친근 도형 헬퍼 + 좀비 도형 + 회피 박스 시각화)
- sound_manager.py
- 안전 종료 4중 방어

핵심 설계 결정 (이전 학습 모두 적용)
------------------------------------
- **lazy import 0건** (W4 트러블 #16)
- **모듈명 prefix**: zombie_*, dodge_* (W5 트러블 #17)
- 실시간 시뮬레이션 (W3 카페닌자 패턴) — 라운드 X
- Pose 못 잡힐 때도 게임 진행 (passes는 카운트, 충돌은 skip)

실행
----
    cd ~/PlayWait
    .venv/bin/python -m games.08_zombie_dodge.src.game

조작
----
    [1/2/3]  난이도 / [SPACE] 시작 / [R] 재시작 / [Q/ESC] 종료
    [F]      전체 화면 / [+/-/0] 화면 크기

Author: Stephen (gjkong)
Date: 2026-05-12 (W7 Step 5)
"""

import atexit
import os
import signal
import sys
import time
from enum import Enum

import cv2
import mediapipe as mp

# ============================================================
# 모듈 import — 파일 상단 dual try/except 한 곳 (W4 트러블 #16)
# ============================================================
try:
    from .body_tracker import compute_person_mask
    from .zombie import Zombie, make_zombie
    from .zombie_spawner import (
        DIFFICULTIES,
        DIFFICULTY_EASY,
        DIFFICULTY_HARD,
        DIFFICULTY_NORMAL,
        Spawner,
    )
    from .dodge_judge import evaluate_frame
    from .dodge_state import (
        DodgeState,
        END_LIVES_OUT,
        END_NONE,
        END_TIMEOUT,
        END_WIN,
    )
    from .sound_manager import SoundManager
    from . import theme
    from . import ui_renderer as ui
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from body_tracker import compute_person_mask
    from zombie import Zombie, make_zombie
    from zombie_spawner import (
        DIFFICULTIES,
        DIFFICULTY_EASY,
        DIFFICULTY_HARD,
        DIFFICULTY_NORMAL,
        Spawner,
    )
    from dodge_judge import evaluate_frame
    from dodge_state import (
        DodgeState,
        END_LIVES_OUT,
        END_NONE,
        END_TIMEOUT,
        END_WIN,
    )
    from sound_manager import SoundManager
    import theme
    import ui_renderer as ui


# ============================================================
# MediaPipe Pose + core/vision/person_mask 호환
# ============================================================
mp_pose = mp.solutions.pose

# core import (직접 실행 모드에서도 동작하도록 PlayWait root sys.path 추가)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PLAYWAIT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _PLAYWAIT_ROOT not in sys.path:
    sys.path.insert(0, _PLAYWAIT_ROOT)

from core.vision.person_mask import PersonMaskDetector  # noqa: E402


# ============================================================
# 페이즈 (W3 패턴 — 실시간 시뮬레이션)
# ============================================================
class GamePhase(Enum):
    DIFFICULTY_SELECT = "difficulty_select"
    READY = "ready"
    PLAYING = "playing"
    GAME_OVER = "game_over"


# 충돌 임박 임계 (좀비 상단이 박스 상단에서 이 거리 이내면 warning 박스 색)
WARNING_DISTANCE_PX = 100


# ============================================================
# 메인 게임
# ============================================================
class ZombieDodgeGame:

    def __init__(self):
        self.cap = None
        self.pose = None
        self.person_detector = None
        self.current_person = None  # PersonMask | None — 매 프레임 갱신

        self.difficulty = DIFFICULTY_NORMAL
        self.state = DodgeState(difficulty=self.difficulty)
        self.spawner = Spawner(
            difficulty=self.difficulty,
            frame_width=theme.SCREEN_WIDTH,
            frame_height=theme.SCREEN_HEIGHT,
        )
        self.zombies = []  # 살아있는 Zombie 리스트
        self.phase = GamePhase.DIFFICULTY_SELECT
        self.last_frame_time = time.time()

        current_dir = os.path.dirname(os.path.abspath(__file__))
        sounds_dir = os.path.join(
            os.path.dirname(current_dir), "assets", "sounds"
        )
        self.sound = SoundManager(sounds_dir)

        self.window_name = "PlayWait - Zombie Dodge"
        self.display_scale = theme.DISPLAY_SCALE
        self.is_fullscreen = False
        self.fps = 0.0
        self.prev_fps_time = time.time()

    # ----------------------------------------
    # 초기화
    # ----------------------------------------
    def setup(self) -> bool:
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("❌ 카메라를 열 수 없습니다.")
            print("   sudo fuser -k /dev/video0")
            self.cap = None
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, theme.SCREEN_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, theme.SCREEN_HEIGHT)
        ok, _ = self.cap.read()
        if not ok:
            print("❌ 카메라 프레임을 읽을 수 없습니다.")
            self.cap.release()
            self.cap = None
            return False

        self.pose = mp_pose.Pose(
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self.person_detector = PersonMaskDetector(model_selection=0)

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        self._apply_window_size()
        return True

    # ----------------------------------------
    # 키 입력
    # ----------------------------------------
    def handle_key(self, key: int) -> bool:
        if key == ord('q') or key == 27:
            return False

        if key in (ord('f'), ord('F')):
            self._toggle_fullscreen()
            return True
        if key in (ord('+'), ord('=')):
            self.display_scale = min(3.0, self.display_scale + 0.25)
            self._apply_window_size()
            print(f"🔍 화면: {self.display_scale:.2f}x")
            return True
        if key in (ord('-'), ord('_')):
            self.display_scale = max(0.5, self.display_scale - 0.25)
            self._apply_window_size()
            print(f"🔍 화면: {self.display_scale:.2f}x")
            return True
        if key == ord('0'):
            self.display_scale = theme.DISPLAY_SCALE
            self.is_fullscreen = False
            self._apply_window_size()
            return True

        if self.phase == GamePhase.DIFFICULTY_SELECT:
            if key in (ord('1'), ord('2'), ord('3')):
                diff_map = {
                    ord('1'): DIFFICULTY_EASY,
                    ord('2'): DIFFICULTY_NORMAL,
                    ord('3'): DIFFICULTY_HARD,
                }
                self.difficulty = diff_map[key]
                self.state = DodgeState(difficulty=self.difficulty)
                self.spawner = Spawner(
                    difficulty=self.difficulty,
                    frame_width=theme.SCREEN_WIDTH,
                    frame_height=theme.SCREEN_HEIGHT,
                )
                self.zombies.clear()
                self.sound.play("click")
                print(
                    f"🎮 난이도: {theme.DIFFICULTY_KOREAN[self.difficulty]} "
                    f"(목표 {self.state.target}점)"
                )
                self.phase = GamePhase.READY

        elif self.phase == GamePhase.READY:
            if key == ord(' '):
                self.sound.play("click")
                self.state.start_game()
                self.last_frame_time = time.time()
                self.phase = GamePhase.PLAYING
                print(f"\n=== 시작! 60초 안에 좀비 피하기 (목표 "
                      f"{self.state.target}점) ===")

        elif self.phase == GamePhase.GAME_OVER:
            if key in (ord('r'), ord('R')):
                self.sound.play("click")
                self.state.reset()
                self.spawner.reset()
                self.zombies.clear()
                print("\n🔄 게임 재시작")
                self.phase = GamePhase.DIFFICULTY_SELECT

        return True

    # ----------------------------------------
    # PLAYING 갱신
    # ----------------------------------------
    def update_playing(self, dt: float, person, frame_w, frame_h):
        # 1) PersonMask (호출 측에서 이미 계산해 전달)

        # 2) 새 좀비 spawn
        new_zs = self.spawner.update(dt)
        self.zombies.extend(new_zs)

        # 3) 좀비 운동
        for z in self.zombies:
            z.step()

        # 4) 판정 — 회피 임계는 frame 하단 (좀비가 화면 끝까지 떨어지면 pass)
        dodge_y_threshold = frame_h - 10
        result = evaluate_frame(self.zombies, person,
                                dodge_y_threshold=dodge_y_threshold)

        # 5) 점수 + 생명 적용
        if result.passes:
            self.state.apply_dodges(len(result.passes))
            self.sound.play(theme.ZOMBIE_DODGE_SOUND)
        if result.collisions:
            self.state.apply_hits(len(result.collisions))
            self.sound.play(theme.ZOMBIE_HIT_SOUND)
            print(f"  💥 부딪힘! 생명 {self.state.lives}/"
                  f"{self.state.START_LIVES}")

        # 6) 죽거나 통과한 좀비 + 화면 밖 제거
        self.zombies = [
            z for z in self.zombies
            if not z.dodged
            and not z.passed
            and not z.is_off_screen(frame_w, frame_h)
        ]

        # 7) 종료 체크
        end = self.state.check_end()
        if end != END_NONE:
            if end == END_WIN:
                self.sound.play(theme.ZOMBIE_VICTORY_SOUND)
                print(f"\n{'='*40}")
                print(f"🏆 생존! {self.state.score}/{self.state.target}점")
                print(f"{'='*40}")
            else:
                self.sound.play(theme.ZOMBIE_GAMEOVER_SOUND)
                reason = {
                    END_LIVES_OUT: "생명 소진",
                    END_TIMEOUT:   "시간 초과",
                }.get(end, "패배")
                print(f"\n{'='*40}")
                print(f"💔 {reason} ({self.state.score}/{self.state.target}점)")
                print(f"{'='*40}")
            self.phase = GamePhase.GAME_OVER

        return person

    # ----------------------------------------
    # 렌더
    # ----------------------------------------
    def render(self, frame, person):
        ui.begin_frame()

        if self.phase == GamePhase.DIFFICULTY_SELECT:
            ui.draw_dodge_difficulty_select(frame)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)
            return frame

        if self.phase == GamePhase.READY:
            ui.draw_dodge_ready(frame)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)
            return frame

        # HUD (PLAYING / GAME_OVER 공통)
        ui.draw_dodge_score_bar(
            frame,
            score=self.state.score,
            target=self.state.target,
            lives=self.state.lives,
            max_lives=self.state.START_LIVES,
            remaining=self.state.get_remaining(),
        )

        if self.phase == GamePhase.PLAYING:
            # 좀비 (즉시 렌더, PIL 큐 안 거침)
            for z in self.zombies:
                ui.draw_zombie(frame, z)

            # 사람 외곽선 (마스크 잘 잡혔을 때만)
            if person is not None:
                # 충돌 임박 여부 — 좀비 중 하나라도 person bbox 상단에서
                # WARNING_DISTANCE_PX 이내면 warning 색
                px1, py1, px2, py2 = person.bbox
                warning = any(
                    py1 - WARNING_DISTANCE_PX <= z.y <= py1
                    and px1 - z.radius <= z.x <= px2 + z.radius
                    for z in self.zombies
                )
                ui.draw_person_outline(frame, person, warning=warning)

        elif self.phase == GamePhase.GAME_OVER:
            ui.draw_dodge_game_over(
                frame,
                win=self.state.is_win(),
                summary=self.state.get_summary(),
            )

        ui.draw_fps(frame, self.fps)
        ui.flush_text(frame)
        return frame

    # ----------------------------------------
    # 화면 크기
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
    # 메인 루프
    # ----------------------------------------
    def run(self):
        if not self.setup():
            return

        print("\n" + "=" * 50)
        print("🧟 PlayWait W7 - 좀비 피하기 (Zombie Dodge)")
        print("=" * 50)
        print("\n[게임 조작]")
        print("  [1/2/3] 난이도 (쉬움/보통/어려움)")
        print("  [SPACE] 게임 시작")
        print("  [R]     재시작")
        print("  [Q/ESC] 종료")
        print("\n[화면 조작]")
        print("  [F] 전체 화면 / [+] 확대 / [-] 축소 / [0] 리셋")
        print()

        try:
            while self.cap.isOpened():
                ok, frame = self.cap.read()
                if not ok:
                    continue

                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape

                raw_mask = self.person_detector.process(frame)
                self.current_person = compute_person_mask(raw_mask)

                now = time.time()
                dt = now - self.last_frame_time
                self.last_frame_time = now

                if self.phase == GamePhase.PLAYING:
                    self.update_playing(dt, self.current_person, w, h)

                fps_dt = now - self.prev_fps_time
                if fps_dt > 0:
                    self.fps = 1.0 / fps_dt
                self.prev_fps_time = now

                frame = self.render(frame, self.current_person)

                if self.is_fullscreen:
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

        if self.pose is not None:
            try:
                self.pose.close()
                print("   ✓ Pose 해제")
            except Exception:
                pass
            finally:
                self.pose = None

        if self.person_detector is not None:
            try:
                self.person_detector.close()
                print("   ✓ PersonMaskDetector 해제")
            except Exception:
                pass
            finally:
                self.person_detector = None

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
# 시그널 + atexit
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

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(_atexit_cleanup)

    _game_instance = ZombieDodgeGame()
    try:
        _game_instance.run()
    finally:
        _game_instance = None


if __name__ == "__main__":
    main()
