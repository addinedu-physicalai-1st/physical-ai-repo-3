"""
game.py - 카페 닌자 (Cafe Ninja) 메인 게임
============================================

W3 PlayWait - AI Vision 기반 매장 대기시간 게임
검지 끝으로 떨어지는 메뉴 아이템을 베는 액션 게임.

W1+W2 인프라(theme, ui_renderer, sound_manager) 100% 재활용.
W3 신규: finger_tracker / falling_object / spawner / slice_judge / score_state

실행:
    cd ~/PlayWait
    python -m games.01_cafe_ninja.src.game

조작:
    [1/2/3]  난이도 선택 (쉬움/보통/어려움)
    [SPACE]  게임 시작
    [R]      재시작 (게임 종료 후)
    [Q/ESC]  종료
    [F]      전체 화면 토글
    [+/=]    화면 확대 / [-/_] 축소 / [0] 리셋

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 5)
"""

import atexit
import os
import signal
import sys
import time
from enum import Enum

import cv2
import mediapipe as mp

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from .finger_tracker import FingerTrail, get_hand_bbox, get_index_tip_pixel
    from .falling_object import FallingObject, KIND_KUNAI
    from .spawner import (
        DIFFICULTIES, DIFFICULTY_EASY, DIFFICULTY_HARD,
        DIFFICULTY_NORMAL, Spawner,
    )
    from .slice_judge import judge_slice
    from .score_state import (
        END_LIVES_OUT, END_NONE, END_TIMEOUT, END_WIN, ScoreState,
    )
    from .sound_manager import SoundManager
    from .cafe_ninja_sprite import (
        NinjaSprite, STATE_ATTACK, STATE_IDLE, STATE_THROW, load_background,
    )
    from .ninja_silhouette import NinjaSilhouette
    from . import theme
    from . import ui_renderer as ui
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from finger_tracker import FingerTrail, get_hand_bbox, get_index_tip_pixel
    from falling_object import FallingObject, KIND_KUNAI
    from spawner import (
        DIFFICULTIES, DIFFICULTY_EASY, DIFFICULTY_HARD,
        DIFFICULTY_NORMAL, Spawner,
    )
    from slice_judge import judge_slice
    from score_state import (
        END_LIVES_OUT, END_NONE, END_TIMEOUT, END_WIN, ScoreState,
    )
    from sound_manager import SoundManager
    from cafe_ninja_sprite import (
        NinjaSprite, STATE_ATTACK, STATE_IDLE, STATE_THROW, load_background,
    )
    from ninja_silhouette import NinjaSilhouette
    import theme
    import ui_renderer as ui


# ============================================================
# MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils


# ============================================================
# 게임 페이즈
# ============================================================
class GamePhase(Enum):
    DIFFICULTY_SELECT = "difficulty_select"
    READY = "ready"
    PLAYING = "playing"
    GAME_OVER = "game_over"


# ============================================================
# 슬라이스 효과 (한 프레임 흰 원 + 콤보 팝업)
# ============================================================
class SliceFlash:
    """베기 직후 한 프레임 효과 — 위치/배수/점수 + 잔여 표시 시간"""
    __slots__ = ("pos", "multiplier", "gained", "expires_at",
                 "objects_to_flash")

    def __init__(self, pos, multiplier, gained, objects, duration=0.4):
        self.pos = pos
        self.multiplier = multiplier
        self.gained = gained
        self.expires_at = time.time() + duration
        self.objects_to_flash = list(objects)

    def is_alive(self) -> bool:
        return time.time() < self.expires_at


# ============================================================
# 메인 게임 클래스
# ============================================================
class CafeNinjaGame:
    """카페 닌자 메인 게임"""

    def __init__(self):
        self.cap = None
        self.hands = None

        self.score = ScoreState(difficulty=DIFFICULTY_NORMAL)
        self.spawner = Spawner(difficulty=DIFFICULTY_NORMAL)
        self.trail = FingerTrail()
        self.objects = []  # 살아있는 FallingObject 리스트
        self.flashes = []  # 활성 SliceFlash 리스트

        self.phase = GamePhase.DIFFICULTY_SELECT
        self.difficulty = DIFFICULTY_NORMAL
        self.last_frame_time = time.time()

        # 사운드
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sounds_dir = os.path.join(
            os.path.dirname(current_dir), "assets", "sounds"
        )
        self.sound = SoundManager(sounds_dir)

        # 화면
        self.window_name = "PlayWait - Cafe Ninja"
        self.display_scale = theme.DISPLAY_SCALE
        self.is_fullscreen = False
        self.fps = 0.0
        self.prev_fps_time = time.time()

        # 폴리싱: 닌자 마스코트 + 배경 (실패해도 게임은 굴러가야 함)
        self.ninja_sprite = None
        self.background = None
        try:
            self.ninja_sprite = NinjaSprite(
                sprite_root=theme.NINJA_SPRITE_DIR,
                target_height=theme.MASCOT_HEIGHT,
                fps=theme.MASCOT_FPS,
            )
            print(f"🥷 닌자 마스코트 로드: {theme.NINJA_SPRITE_DIR}")
        except Exception as e:
            print(f"⚠️  마스코트 로드 실패 (무시하고 진행): {e}")
        try:
            self.background = load_background(
                theme.BACKGROUND_PATH,
                theme.SCREEN_WIDTH,
                theme.SCREEN_HEIGHT,
                brightness=theme.BACKGROUND_BRIGHTNESS,
                saturation=theme.BACKGROUND_SATURATION,
            )
            print(f"🏯 배경 로드: {theme.BACKGROUND_PATH}")
        except Exception as e:
            print(f"⚠️  배경 로드 실패 (무시하고 진행): {e}")

        # 폴리싱: 그림자 실루엣 (Selfie Seg + Face Detection)
        self.silhouette = NinjaSilhouette()
        if self.silhouette.available:
            print("🥷 Silhouette 활성 (Selfie Seg + Face Detection)")
        else:
            print("⚠️ Silhouette 비활성 — spotlight 폴백")

    # ----------------------------------------
    # 초기화
    # ----------------------------------------
    def setup(self):
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

        self.hands = mp_hands.Hands(
            model_complexity=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
            max_num_hands=1,  # W3은 한 손 (검지 한 개로 베기)
        )

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        self._apply_window_size()
        if self.is_fullscreen:
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN)
        return True

    # ----------------------------------------
    # 키 입력
    # ----------------------------------------
    def handle_key(self, key: int) -> bool:
        if key == ord('q') or key == 27:
            return False

        # 화면 크기 (모든 페이즈)
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

        # 페이즈별
        if self.phase == GamePhase.DIFFICULTY_SELECT:
            if key in (ord('1'), ord('2'), ord('3')):
                diff_map = {
                    ord('1'): DIFFICULTY_EASY,
                    ord('2'): DIFFICULTY_NORMAL,
                    ord('3'): DIFFICULTY_HARD,
                }
                self.difficulty = diff_map[key]
                self.score = ScoreState(difficulty=self.difficulty)
                self.spawner = Spawner(difficulty=self.difficulty)
                self.sound.play("click")
                print(f"🎮 난이도: {theme.DIFFICULTY_KOREAN[self.difficulty]} "
                      f"(목표 {self.score.target}점)")
                self.phase = GamePhase.READY

        elif self.phase == GamePhase.READY:
            if key == ord(' '):
                self.sound.play("click")
                self.score.start_game()
                self.last_frame_time = time.time()
                self.phase = GamePhase.PLAYING
                print(f"\n=== 게임 시작 (목표 {self.score.target}점) ===")

        elif self.phase == GamePhase.GAME_OVER:
            if key in (ord('r'), ord('R')):
                self.sound.play("click")
                self.score.reset()
                self.spawner.reset()
                self.trail.reset()
                self.objects.clear()
                self.flashes.clear()
                print("\n🔄 게임 재시작")
                self.phase = GamePhase.DIFFICULTY_SELECT

        return True

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
    # 게임 로직
    # ----------------------------------------
    def update_playing(self, dt: float, tip_px):
        """PLAYING 페이즈 1프레임 갱신"""
        # 1) 검지 트레일
        self.trail.update(tip_px)

        # 2) 새 객체 spawn
        new_objs = self.spawner.update(dt)
        self.objects.extend(new_objs)

        # 3) 객체 운동
        for obj in self.objects:
            obj.step()

        # 4) 슬라이스 판정 (트레일 속도가 임계 이상일 때만)
        if self.trail.is_slicing():
            seg = self.trail.get_segment()
            result = judge_slice(seg, self.objects)
            if result.sliced_objects:
                self.score.apply_slice(result)
                # 사운드: slice = swish 0.4초 효과음, explosion은 lose로 매핑
                if result.bomb_count > 0:
                    self.sound.play("lose")     # 폭탄 = lose 효과 (전용 explosion wav 미준비)
                if (len(result.sliced_objects) - result.bomb_count) > 0:
                    self.sound.play("slice")    # 베기 = swish.wav

                # 마스코트 상태 전이: kunai 슬라이스 or 3+ 콤보 → THROW, 그 외 → ATTACK
                if self.ninja_sprite is not None:
                    menu_count = len(result.sliced_objects) - result.bomb_count
                    has_kunai = any(
                        o.kind == KIND_KUNAI for o in result.sliced_objects
                    )
                    if has_kunai or menu_count >= 3:
                        self.ninja_sprite.set_state(STATE_THROW, duration=0.7)
                    elif menu_count >= 1:
                        self.ninja_sprite.set_state(STATE_ATTACK, duration=0.5)
                # 시각 효과
                flash_pos = (
                    int(sum(o.x for o in result.sliced_objects) / len(result.sliced_objects)),
                    int(sum(o.y for o in result.sliced_objects) / len(result.sliced_objects)),
                )
                self.flashes.append(SliceFlash(
                    pos=flash_pos,
                    multiplier=result.multiplier,
                    gained=result.score_gained,
                    objects=result.sliced_objects,
                ))
                # 콘솔 로그
                if result.bomb_count > 0:
                    print(f"  💥 폭탄! 생명 {self.score.lives}/{ScoreState.START_LIVES}")
                if result.score_gained > 0:
                    print(f"  ✨ +{result.score_gained}점 "
                          f"(콤보 ×{result.multiplier}) → 총 {self.score.score}점")

        # 5) 화면 밖 객체 + 베인 객체 제거
        self.objects = [
            o for o in self.objects
            if not o.is_off_screen(theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT)
            and not o.sliced
        ]

        # 6) 만료된 flash 제거
        self.flashes = [f for f in self.flashes if f.is_alive()]

        # 7) 종료 체크
        end = self.score.check_end()
        if end != END_NONE:
            if end == END_WIN:
                self.sound.play("victory")
                print(f"\n{'='*40}")
                print(f"🏆 우승! {self.score.score}점 / 목표 {self.score.target}점")
                print(f"{'='*40}")
            else:
                self.sound.play("lose")
                reason = "생명 소진" if end == END_LIVES_OUT else "시간 초과"
                print(f"\n{'='*40}")
                print(f"💔 {reason} ({self.score.score}/{self.score.target}점)")
                print(f"{'='*40}")
            summary = self.score.get_summary()
            print(f"   최고 콤보: {summary['max_combo']}, "
                  f"메뉴 {summary['slices_total']}회, 폭탄 {summary['bombs_hit']}회")
            self.phase = GamePhase.GAME_OVER

    # ----------------------------------------
    # 렌더링
    # ----------------------------------------
    def render(self, frame, tip_px, hand_bbox=None, person_mask=None, eye_points=None,
                nose_point=None, mouth_point=None):
        if eye_points is None:
            eye_points = []
        ui.begin_frame()

        # 폴리싱: silhouette 합성 (PLAYING + silhouette 활성 + 배경 로드 OK)
        # 폴백: silhouette 비활성이면 기존 배경 + spotlight 방식
        if (self.phase == GamePhase.PLAYING
                and getattr(self, "silhouette", None) is not None
                and self.silhouette.available
                and self.background is not None):
            ui.apply_silhouette(frame, person_mask, eye_points, hand_bbox, self.background,
                                 nose_point=nose_point, mouth_point=mouth_point)
        else:
            if self.background is not None:
                ui.draw_background(frame, self.background)
            if self.phase == GamePhase.PLAYING:
                ui.apply_hand_spotlight(frame, hand_bbox)

        if self.phase == GamePhase.DIFFICULTY_SELECT:
            ui.draw_ninja_difficulty_select(frame)
            ui.draw_ninja_mascot(frame, self.ninja_sprite)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)
            return frame

        if self.phase == GamePhase.READY:
            ui.draw_ninja_ready(frame)
            ui.draw_ninja_mascot(frame, self.ninja_sprite)
            ui.draw_fps(frame, self.fps)
            ui.flush_text(frame)
            return frame

        if self.phase == GamePhase.PLAYING:
            # 객체들 (도형, 즉시 렌더 — PIL 큐 안 거침)
            for obj in self.objects:
                ui.draw_falling_object(frame, obj)

            # 슬라이스 효과
            for flash in self.flashes:
                for obj in flash.objects_to_flash:
                    ui.draw_slice_flash(frame, obj)
                ui.draw_combo_popup(frame, flash.multiplier,
                                     flash.gained, flash.pos)

            # 검지 트레일
            ui.draw_finger_trail(frame, self.trail.get_trail(),
                                  self.trail.is_slicing())
            ui.draw_finger_tip(frame, tip_px, self.trail.is_slicing())

            # 마스코트 (HUD 그리기 직전 — HUD가 위에 와도 마스코트는 좌측 하단에 있어 충돌 X)
            ui.draw_ninja_mascot(frame, self.ninja_sprite)

            # HUD
            ui.draw_ninja_score_bar(
                frame,
                score=self.score.score,
                target=self.score.target,
                lives=self.score.lives,
                max_lives=ScoreState.START_LIVES,
                remaining_time=self.score.get_remaining(),
            )

        elif self.phase == GamePhase.GAME_OVER:
            end = self.score.check_end()
            ui.draw_ninja_game_over(
                frame,
                win=(end == END_WIN),
                end_reason=end,
                score=self.score.score,
                target=self.score.target,
                max_combo=self.score.max_combo,
                slices_total=self.score.slices_total,
                bombs_hit=self.score.bombs_hit,
            )
            ui.draw_ninja_mascot(frame, self.ninja_sprite)

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
        print("🥷 PlayWait W3 - 카페 닌자 (Cafe Ninja)")
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
                ok, frame = self.cap.read()
                if not ok:
                    continue

                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape

                # MediaPipe
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = self.hands.process(rgb)
                rgb.flags.writeable = True

                # 검지 끝 좌표 + 손 bbox (스포트라이트용)
                tip_px = None
                hand_bbox = None
                if results.multi_hand_landmarks:
                    hl = results.multi_hand_landmarks[0]
                    tip_px = get_index_tip_pixel(hl, w, h)
                    hand_bbox = get_hand_bbox(hl, w, h)

                # 닌자 복면 합성 (PLAYING 페이즈만 — 다른 페이즈는 안내문 노출 필요)
                if self.phase == GamePhase.PLAYING and self.silhouette.available:
                    sil_result = self.silhouette.process(frame)
                    person_mask = sil_result.person_mask
                    eye_points = sil_result.eye_points
                    nose_point = sil_result.nose_point
                    mouth_point = sil_result.mouth_point
                else:
                    person_mask = None
                    eye_points = []
                    nose_point = None
                    mouth_point = None

                # 게임 페이즈 갱신
                now = time.time()
                dt = now - self.last_frame_time
                self.last_frame_time = now

                if self.phase == GamePhase.PLAYING:
                    self.update_playing(dt, tip_px)
                else:
                    # PLAYING 외 페이즈에서도 트레일은 업데이트해서 깜빡임 방지
                    self.trail.update(tip_px)

                # 마스코트 애니메이션 진행
                if self.ninja_sprite is not None:
                    self.ninja_sprite.update()

                # FPS
                fps_dt = now - self.prev_fps_time
                if fps_dt > 0:
                    self.fps = 1.0 / fps_dt
                self.prev_fps_time = now

                # UI
                frame = self.render(frame, tip_px, hand_bbox, person_mask, eye_points,
                                     nose_point=nose_point, mouth_point=mouth_point)

                # 화면 표시
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
# 시그널 핸들러 + atexit
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
    parser = argparse.ArgumentParser(description="Cafe Ninja game")
    parser.add_argument("--auto-play", action="store_true")
    parser.add_argument("--difficulty", default=None,
                        choices=["easy", "normal", "hard"])
    parser.add_argument("--result-json", default=None)
    parser.add_argument("--auto-exit", type=float, default=None)
    parser.add_argument("--ready-delay", type=float, default=1.5)
    parser.add_argument("--fullscreen", action="store_true",
                        help="cv2 윈도우 풀스크린 (호객 시연용).")
    parser.add_argument("--camera-index", type=int, default=0)
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(_atexit_cleanup)

    _game_instance = CafeNinjaGame()
    _game_instance.is_fullscreen = bool(args.fullscreen)
    try:
        _game_instance.run()
    finally:
        _game_instance = None


if __name__ == "__main__":
    main()
