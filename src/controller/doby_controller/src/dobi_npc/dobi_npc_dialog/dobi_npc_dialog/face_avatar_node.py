#!/usr/bin/env python3
"""face_avatar — 노트북 풀스크린 얼굴 표현 GUI (애니메이션 v2).

Phase 2 W4-④. vicpinky LCD 없음 → 노트북 풀스크린.
+ §4 8 어휘 매핑 + §8 vicpinky_emotion 자산 재활용.

구독:
  /face_avatar/expression (std_msgs/String, 8 어휘 중 하나)
    basic | hello | happy | fun | interest | bored | sad | angry
  /rapport/event (RapportEvent) — abort_trigger 시 abort_expression으로 reset

자산: dobi_npc_dialog share/assets/vicpinky_emotion/emotion/*.gif 8개.

v2 변경 (이전 v1: 정적 1프레임 brightest 표시):
  PIL ImageSequence로 모든 프레임 추출 → max_frames_per_gif(기본 30)로 균등
  다운샘플링 → 화면 크기에 맞춰 미리 scale → pygame Surface 리스트로 캐시.
  GIF native frame duration(또는 fallback 33ms)으로 무한 loop 재생.

v2.1 추가 — start_at_brightest (기본 True):
  GIF 자산이 fade-in 검정으로 시작하므로 frame_index=0부터 재생하면
  표정 전환 시 1초 간 검정. 옵션 활성 시 GIF별 brightest frame index를
  미리 산출(PIL luminance 평균) → 표정 전환 시 그 인덱스부터 재생 →
  검정 깜빡임 없이 즉시 표정 visible. 그 이후는 자연 cycle.
  운영 정책상 abort 시 검정 1초가 차단 신호로 의도되면 false로 해제.

조작 (검증/디버깅):
  ESC, 창 닫기  → 종료
  1..8 키       → 표정 8 어휘 수동 전환
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Empty, String

from dobi_npc_msgs.msg import RapportEvent

# pygame 임포트 시 "Hello from the pygame community." 출력을 억제
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame  # noqa: E402
from PIL import Image, ImageSequence, ImageStat  # noqa: E402


# face_expression 8 어휘 (표시 순서 = 키 1~8)
EXPRESSIONS = ["basic", "hello", "happy", "fun", "interest", "bored", "sad", "angry"]


def _default_gif_dir() -> str:
    """gif_dir 기본값 결정 — env > package share > 빈 문자열.

    1. 환경변수 MOCA_GIF_DIR 우선 (배포/테스트 시 명시)
    2. dobi_npc_dialog share/assets/vicpinky_emotion/emotion
    3. 빈 문자열 → __init__ 의 isdir 체크에서 명확한 에러 메시지
    """
    env = os.environ.get('MOCA_GIF_DIR', '').strip()
    if env:
        return os.path.expanduser(env)
    try:
        candidate = (
            Path(get_package_share_directory('dobi_npc_dialog')) /
            'assets' / 'vicpinky_emotion' / 'emotion'
        )
        if candidate.is_dir():
            return str(candidate)
    except Exception:
        pass
    return ''


DEFAULT_GIF_DIR = _default_gif_dir()

# (Surface, duration_ms) 튜플의 리스트
FrameList = List[Tuple['pygame.Surface', int]]


class FaceAvatarNode(Node):
    """노트북 풀스크린 얼굴 표현 (애니메이션)."""

    def __init__(self):
        super().__init__('face_avatar_node')

        self.declare_parameter('gif_dir', DEFAULT_GIF_DIR)
        self.declare_parameter('fullscreen', True)
        self.declare_parameter('window_width', 1280)
        self.declare_parameter('window_height', 720)
        self.declare_parameter('initial_expression', 'basic')
        self.declare_parameter('topic', '/face_avatar/expression')
        # abort 시 표시할 표정. 빈 문자열이면 reset 안 함 (기존 표정 유지).
        self.declare_parameter('abort_expression', 'basic')
        self.declare_parameter('rapport_topic', '/rapport/event')
        # 디스플레이 점유 양보 (minigame 등). suspend 시 화면 검정 + 새 expression
        # 무시, resume 시 복귀. minigame이 같은 풀스크린을 점유할 때 사용.
        self.declare_parameter('suspend_topic', '/face_avatar/suspend')
        self.declare_parameter('resume_topic', '/face_avatar/resume')
        # abort 후 일정 시간 동안 새 expression 무시 (basic 유지). 0이면 비활성.
        # BT가 abort 후 빠르게 다음 사이클로 새 face publish하는 것을 차단해
        # "호객 차단" 시각 신호가 충분히 보이도록.
        self.declare_parameter('abort_dwell_sec', 2.0)
        # v2: 메모리 보호 위해 GIF당 최대 프레임 수 (균등 다운샘플링)
        # 30프레임 ≈ 1초 @ 30fps. 8 GIF * 30 frames = 240 frames 캐시.
        # 1920x1080 풀스크린 시 약 2GB, 800x600 윈도우 시 약 460MB.
        self.declare_parameter('max_frames_per_gif', 30)
        self.declare_parameter('fps_cap', 30)
        # v2.1: 표정 전환 시 brightest frame부터 시작 → fade-in 검정 회피.
        # false면 frame 0부터(GIF native intro 보존).
        self.declare_parameter('start_at_brightest', True)

        gif_dir = self.get_parameter('gif_dir').value
        fullscreen = bool(self.get_parameter('fullscreen').value)
        win_w = int(self.get_parameter('window_width').value)
        win_h = int(self.get_parameter('window_height').value)
        initial = self.get_parameter('initial_expression').value
        topic = self.get_parameter('topic').value
        self.abort_expression = self.get_parameter('abort_expression').value
        rapport_topic = self.get_parameter('rapport_topic').value
        suspend_topic = self.get_parameter('suspend_topic').value
        resume_topic = self.get_parameter('resume_topic').value
        self.abort_dwell_sec = float(self.get_parameter('abort_dwell_sec').value)
        self.max_frames = int(self.get_parameter('max_frames_per_gif').value)
        self.fps_cap = int(self.get_parameter('fps_cap').value)
        self.start_at_brightest = bool(
            self.get_parameter('start_at_brightest').value)

        if not os.path.isdir(gif_dir):
            raise FileNotFoundError(
                f"GIF 디렉토리 없음: {gif_dir}. "
                f"`gif_dir` 파라미터를 vicpinky_emotion/emotion 경로로 지정."
            )

        pygame.init()
        info = pygame.display.Info()
        sw, sh = info.current_w, info.current_h

        # set_mode 재호출 (resume 시) 위해 명시 flags / size 저장.
        # get_flags() 는 SDL internal high-bit flags 포함해서 set_mode 가 받으면
        # OverflowError. 명시 pygame public flag 만 보존.
        if fullscreen:
            try:
                self.screen = pygame.display.set_mode(
                    (sw, sh), pygame.FULLSCREEN)
                self._init_flags = pygame.FULLSCREEN
                self.get_logger().info(f"FULLSCREEN mode: {sw}x{sh}")
            except pygame.error as e:
                self.get_logger().warning(
                    f"FULLSCREEN 실패 ({e}) → NOFRAME fallback")
                self.screen = pygame.display.set_mode(
                    (sw, sh), pygame.NOFRAME)
                self._init_flags = pygame.NOFRAME
        else:
            self.screen = pygame.display.set_mode((win_w, win_h))
            self._init_flags = 0
            self.get_logger().info(f"WINDOWED mode: {win_w}x{win_h}")
        self._init_size = self.screen.get_size()

        pygame.display.set_caption('Dobi NPC face avatar')
        pygame.mouse.set_visible(False)

        # 모든 GIF의 모든 프레임을 미리 로드 + scale (애니메이션 v2)
        self.frames: dict = {}  # name -> FrameList
        self.brightest_idx: dict = {}  # name -> int (v2.1)
        for name in EXPRESSIONS:
            path = os.path.join(gif_dir, f"{name}.gif")
            if not os.path.isfile(path):
                self.get_logger().warning(f"GIF 누락 (skip): {path}")
                continue
            frame_list, brightest = self._load_gif_animation(path, name)
            if frame_list:
                self.frames[name] = frame_list
                self.brightest_idx[name] = brightest

        if not self.frames:
            raise RuntimeError(f"로드된 GIF 0개. gif_dir 확인: {gif_dir}")

        self.get_logger().info(
            f"loaded {len(self.frames)}/{len(EXPRESSIONS)} expressions, "
            f"screen={self.screen.get_size()}, fullscreen={fullscreen}, "
            f"max_frames_per_gif={self.max_frames}, fps_cap={self.fps_cap}, "
            f"start_at_brightest={self.start_at_brightest}"
        )

        self.current = initial if initial in self.frames else next(iter(self.frames))
        self._frame_index = self._start_index_for(self.current)
        self._frame_started_ms = pygame.time.get_ticks()
        # abort dwell — abort 후 이 시각(ms)까지 새 expression 무시
        self._dwell_until_ms = 0
        # 디스플레이 점유 양보 (minigame 등 외부 노드가 풀스크린 잡을 때)
        self._suspended = False

        self.sub = self.create_subscription(
            String, topic, self._on_expression, 10
        )
        self.rapport_sub = self.create_subscription(
            RapportEvent, rapport_topic, self._on_rapport, 10
        )
        self.suspend_sub = self.create_subscription(
            Empty, suspend_topic, self._on_suspend, 10
        )
        self.resume_sub = self.create_subscription(
            Empty, resume_topic, self._on_resume, 10
        )
        self.clock = pygame.time.Clock()

    def _fit_to_screen(self, surf: 'pygame.Surface') -> 'pygame.Surface':
        sw, sh = self.screen.get_size()
        iw, ih = surf.get_size()
        scale = min(sw / iw, sh / ih)
        return pygame.transform.smoothscale(
            surf, (max(1, int(iw * scale)), max(1, int(ih * scale)))
        )

    def _load_gif_animation(
        self, path: str, name: str,
    ) -> Tuple[FrameList, int]:
        """GIF의 모든 프레임 → 균등 다운샘플 → pygame Surface 리스트 + brightest idx.

        각 프레임의 native duration (Image.info['duration'] in ms)도 보존.
        다운샘플링 시 duration을 step배로 보정해 전체 재생 시간 유지.
        brightest idx: PIL luminance(L mode) 평균이 최대인 frame 인덱스.
        fade-in 검정 회피용 (start_at_brightest 옵션).
        """
        try:
            img = Image.open(path)
        except Exception as e:
            self.get_logger().warning(f"PIL.Image.open 실패 ({name}): {e}")
            return [], 0

        # 1단계: 모든 프레임 + duration 수집 (PIL)
        all_frames = []
        for frame in ImageSequence.Iterator(img):
            rgba = frame.convert('RGBA').copy()
            duration = int(rgba.info.get('duration', 33))  # ms, fallback 33ms
            if duration <= 0:
                duration = 33
            all_frames.append((rgba, duration))

        n_total = len(all_frames)
        if n_total == 0:
            self.get_logger().warning(f"GIF 프레임 0개: {name}")
            return [], 0

        # 2단계: 균등 다운샘플 (max_frames 초과 시)
        if n_total > self.max_frames:
            step = n_total / self.max_frames
            indices = [int(i * step) for i in range(self.max_frames)]
            sampled = [all_frames[i] for i in indices]
            # duration을 step배로 보정 (전체 재생 시간 유지)
            sampled = [(rgba, max(33, int(dur * step))) for rgba, dur in sampled]
            all_frames = sampled

        # 3단계: PIL → pygame Surface + 화면 크기 fit + brightness 측정
        result: FrameList = []
        brightest_idx = 0
        brightest_mean = -1.0
        for i, (rgba, duration) in enumerate(all_frames):
            try:
                mean_l = ImageStat.Stat(rgba.convert('L')).mean[0]
            except Exception:
                mean_l = 0.0
            if mean_l > brightest_mean:
                brightest_mean = mean_l
                brightest_idx = i
            surf = pygame.image.fromstring(
                rgba.tobytes(), rgba.size, rgba.mode)
            surf = self._fit_to_screen(surf.convert_alpha())
            result.append((surf, duration))

        total_ms = sum(d for _, d in result)
        self.get_logger().info(
            f"  {name}: {n_total} frames → {len(result)} sampled "
            f"({total_ms} ms total, brightest idx={brightest_idx} "
            f"mean={brightest_mean:.1f})"
        )
        return result, brightest_idx

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type != "abort_trigger":
            return
        # dwell timer 갱신 (매 abort_trigger 메시지마다 reset — sustained abort 동안 유지)
        if self.abort_dwell_sec > 0:
            self._dwell_until_ms = pygame.time.get_ticks() + int(
                self.abort_dwell_sec * 1000)
        if not self.abort_expression:
            return
        if self.abort_expression not in self.frames:
            self.get_logger().warning(
                f"abort_expression GIF 미로드: {self.abort_expression}")
            return
        if self.current != self.abort_expression:
            self.get_logger().info(
                f"abort_trigger ({msg.reason}) → face: "
                f"{self.current} -> {self.abort_expression} "
                f"(dwell {self.abort_dwell_sec:.1f}s)")
            self._switch_to(self.abort_expression)

    def _on_suspend(self, _msg: Empty):
        if self._suspended:
            return
        self._suspended = True
        self.get_logger().info("display suspended (외부 노드 풀스크린 점유)")
        # 즉시 검정 화면 — 다른 노드가 풀스크린을 그리기 전 시각 양보
        self.screen.fill((0, 0, 0))
        pygame.display.flip()

    def _on_resume(self, _msg: Empty):
        if not self._suspended:
            return
        self._suspended = False
        self.get_logger().info("display resumed")
        # X11 stacking 강제 raise — set_mode + toggle_fullscreen + wmctrl 시도.
        # 게임 cv2 풀스크린 윈도우가 닫힌 후 face_avatar 가 다른 윈도우 뒤에
        # 가려지는 현상 회피.
        # set_mode flags 는 __init__ 에서 저장한 명시 값 사용 (get_flags()
        # 는 SDL internal high-bit 포함 → OverflowError).
        try:
            self.screen = pygame.display.set_mode(
                self._init_size, self._init_flags)
        except pygame.error as e:
            self.get_logger().warning(f"set_mode 재호출 실패: {e}")
        except OverflowError as e:
            self.get_logger().warning(f"set_mode flags overflow: {e}")
        # 풀스크린 모드면 toggle x2 — X11 윈도우 강제 재배치 → raise.
        if self._init_flags & pygame.FULLSCREEN:
            try:
                pygame.display.toggle_fullscreen()
                pygame.display.toggle_fullscreen()
            except pygame.error as e:
                self.get_logger().warning(f"toggle_fullscreen 실패: {e}")
        # wmctrl fallback — apt 패키지가 있으면 윈도우 활성화. 없으면 silent.
        import subprocess
        try:
            subprocess.run(
                ['wmctrl', '-a', 'Dobi NPC face avatar'],
                check=False, timeout=2.0,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        # 즉시 1회 강제 렌더 — 자연 frame advance 까지 검정 안 머무름
        self._frame_started_ms = pygame.time.get_ticks()
        self._render()

    def _on_expression(self, msg: String):
        name = msg.data.strip().lower()
        if name not in EXPRESSIONS:
            self.get_logger().warning(f"unknown expression: '{msg.data}'")
            return
        if name not in self.frames:
            self.get_logger().warning(f"expression GIF 미로드: {name}")
            return
        # suspend 중이면 current 만 업데이트하고 화면은 그대로 (검정 유지).
        # resume 시 새 current 로 복귀.
        if self._suspended:
            if name != self.current:
                self.get_logger().info(
                    f"face (suspended): {self.current} -> {name} (defer render)")
                self.current = name
                self._frame_index = self._start_index_for(name)
            return
        # dwell time 중이면 abort_expression이 아닌 한 ignore
        # (abort_expression 자체는 허용 — sustained abort 중 BT가 우연히 같은
        # expression publish하는 케이스와 무관하게 현재 표정 유지)
        now_ms = pygame.time.get_ticks()
        if (now_ms < self._dwell_until_ms and
                name != self.abort_expression):
            remaining = (self._dwell_until_ms - now_ms) / 1000.0
            self.get_logger().info(
                f"abort dwell {remaining:.1f}s remaining → ignore '{name}'")
            return
        if name != self.current:
            self.get_logger().info(f"face: {self.current} -> {name}")
            self._switch_to(name)

    def _start_index_for(self, name: str) -> int:
        """start_at_brightest 옵션 따라 첫 프레임 인덱스 결정."""
        if self.start_at_brightest:
            return self.brightest_idx.get(name, 0)
        return 0

    def _switch_to(self, name: str):
        """expression 전환 + 시작 프레임 인덱스 reset."""
        self.current = name
        self._frame_index = self._start_index_for(name)
        self._frame_started_ms = pygame.time.get_ticks()

    def _advance_frame(self) -> bool:
        """현재 프레임의 duration 지났으면 다음으로. 변화 시 True."""
        frame_list = self.frames.get(self.current, [])
        if len(frame_list) <= 1:
            return False
        _, duration = frame_list[self._frame_index]
        elapsed = pygame.time.get_ticks() - self._frame_started_ms
        if elapsed >= duration:
            self._frame_index = (self._frame_index + 1) % len(frame_list)
            self._frame_started_ms = pygame.time.get_ticks()
            return True
        return False

    def _render(self):
        frame_list = self.frames.get(self.current, [])
        if not frame_list:
            return
        surf, _ = frame_list[self._frame_index]
        self.screen.fill((0, 0, 0))
        rect = surf.get_rect(center=self.screen.get_rect().center)
        self.screen.blit(surf, rect)
        pygame.display.flip()

    def run(self):
        running = True
        # 초기 1회 렌더 (실행 직후 검은 화면 방지)
        self._render()

        while running and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.0)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif pygame.K_1 <= event.key <= pygame.K_8:
                        idx = event.key - pygame.K_1
                        if idx < len(EXPRESSIONS):
                            wanted = EXPRESSIONS[idx]
                            if (wanted in self.frames and
                                    wanted != self.current):
                                self.get_logger().info(
                                    f"key {idx + 1}: {self.current} -> {wanted}")
                                self._switch_to(wanted)

            # 프레임 진행 또는 expression 전환 시 render. suspend 중에는
            # frame 진행 + render 둘 다 skip — 화면 검정 유지.
            if not self._suspended and self._advance_frame():
                self._render()

            self.clock.tick(self.fps_cap)

    def destroy_node(self):
        pygame.quit()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FaceAvatarNode()
    try:
        node.run()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
