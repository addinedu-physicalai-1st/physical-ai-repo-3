#!/usr/bin/env python3
"""minigame_runner_node — 미니게임 dispatcher (Phase 3+).

PlayWait 기반 다중 게임을 game_id 별로 dispatch 하는 wrapper:
  - rps           → moca/games/06_rps_evolution/src/game.py
  - speed_counter → moca/games/07_speed_counter/src/game.py
  - cafe_ninja    → moca/games/01_cafe_ninja/src/game.py

흐름:
  1) /minigame/start (std_msgs/String, game_id) 수신 → registry lookup
  2) /face_avatar/suspend publish → settle 대기 (디스플레이 양보)
  3) subprocess: python3 <game_script> --auto-play --difficulty <diff>
                                       --auto-exit N --ready-delay D
                                       --result-json <tmp>
                                       --camera-index <N>
  4) subprocess wait (timeout). SIGTERM/SIGKILL fallback.
  5) JSON 결과 → MinigameResult publish (game_id 보존)
  6) /face_avatar/resume publish → IDLE 복귀

카메라 분리 (2026-05-06): 게임은 카메라 3 (노트북 외장 RPC-20F, 기본
인덱스 2) 를 사용. GEVA 는 카메라 1 (노트북 내장, 인덱스 0) 을 그대로
점유 → 게임 중에도 GEVA 가동 → Salichs 2014 abort_trigger 학술 정합 유지.
그래서 /geva/suspend|resume 흐름은 폐기.

JSON 형식 (game.py._save_result_json 공통):
  {"customer_wins": int, "robot_wins": int, "ties": int,
   "rounds_played": int, "completed": bool, "duration_sec": float}

각 게임이 mediapipe + opencv + pygame(사운드) 사용 — 시스템 의존
(CLAUDE.md §7 mediapipe 0.10.14 user pip + python3-opencv apt + python3-pygame apt).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Empty, String

from dobi_npc_msgs.msg import MinigameResult


def _find_workspace_root() -> str:
    """현재 파일 위치 기반 워크스페이스 루트 추정 (clone 위치 무관).

    src/ 와 marker 파일(moca.repos 또는 CLAUDE.md) 을 가진 부모 디렉토리 검색.
    symlink-install 시 __file__ 이 src/ 트리. 일반 install 시 install/ 트리.
    """
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(here, 'src')) and (
            os.path.isfile(os.path.join(here, 'moca.repos')) or
            os.path.isfile(os.path.join(here, 'CLAUDE.md'))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return ''


def _games_root() -> str:
    """게임 디렉토리 root — env > workspace 추정 > 빈 문자열.

    1. 환경변수 MOCA_GAMES_DIR 우선 (배포/테스트 시 명시)
    2. 워크스페이스 추정 후 games/
    3. 빈 문자열 → registry 의 경로는 빈 경로가 되어 launch 가 명시 안 하면 즉시 에러
    """
    env = os.environ.get('MOCA_GAMES_DIR', '').strip()
    if env:
        return os.path.expanduser(env)
    ws = _find_workspace_root()
    if ws:
        return os.path.join(ws, 'games')
    return ''


_GAMES = _games_root()

# 게임 ID → game.py 경로. 새 게임 추가 시 한 곳에서만 등록.
# launch 의 game_registry 파라미터로 override 가능 (운영자 패널/테스트 환경).
DEFAULT_GAME_REGISTRY: Dict[str, str] = {
    "rps":           os.path.join(_GAMES, '06_rps_evolution', 'src', 'game.py') if _GAMES else '',
    "speed_counter": os.path.join(_GAMES, '07_speed_counter', 'src', 'game.py') if _GAMES else '',
    "cafe_ninja":    os.path.join(_GAMES, '01_cafe_ninja',     'src', 'game.py') if _GAMES else '',
}

# 게임별 default. minigame_runner 가 게임 subprocess 띄우기 전 자체 pygame
# 풀스크린 으로 5초 카운트다운 + 룰 텍스트 표시 (explain 섹션). 그 후 게임은
# ready_delay 짧게 시작 → GAME_OVER 후 auto_exit 까지 결과 화면 표시 후 종료.
#
# auto_exit_sec=5.0 통일 — funnel 다음 단계(minigame_win/lose phrase) 자연 진행.
# 주의: rps victory.wav 10.21초가 5초 후 잘림. 짧은 wav 로 교체하거나
# 후속에 result-based 분기 (win 시만 길게) 검토.
DEFAULT_GAME_PARAMS: Dict[str, dict] = {
    "rps": {
        "auto_exit_sec": 5.0,
        "ready_delay_sec": 0.5,
        "explain": {
            "title": "가위바위보",
            "rules": [
                "카운트가 끝나면 가위 / 바위 / 보!",
                "3판 2선승. 이기면 추천 메뉴 안내!",
            ],
            "countdown_sec": 5.0,
        },
    },
    "speed_counter": {
        "auto_exit_sec": 5.0,
        "ready_delay_sec": 0.5,
        "explain": {
            "title": "스피드 카운터",
            "rules": [
                "양손 손가락 합으로 화면 숫자를 만들기!",
                "5번 연속 정답이면 우승.",
            ],
            "countdown_sec": 5.0,
        },
    },
    "cafe_ninja": {
        "auto_exit_sec": 5.0,
        "ready_delay_sec": 0.5,
        "explain": {
            "title": "카페 닌자",
            "rules": [
                "검지 손가락으로 떨어지는 메뉴 베기!",
                "폭탄은 피하세요.",
            ],
            "countdown_sec": 5.0,
        },
    },
}


def _find_korean_font():
    """시스템 한국어 폰트 경로 탐색. 미발견 시 None."""
    os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    import pygame
    if not pygame.font.get_init():
        pygame.font.init()
    candidates = [
        "NanumSquareRound", "NanumGothic", "Nanum Gothic",
        "Noto Sans CJK KR", "NotoSansCJKkr", "NotoSansCJK",
        "Malgun Gothic",
    ]
    for name in candidates:
        path = pygame.font.match_font(name)
        if path:
            return path
    return None


class MinigameRunnerNode(Node):
    def __init__(self):
        super().__init__('minigame_runner')

        self.declare_parameter('python_executable', 'python3')
        self.declare_parameter('difficulty', 'normal')
        self.declare_parameter('game_timeout_sec', 120.0)
        self.declare_parameter('result_dir', '/tmp')
        self.declare_parameter('start_topic', '/minigame/start')
        self.declare_parameter('result_topic', '/minigame/result')
        self.declare_parameter('face_suspend_topic', '/face_avatar/suspend')
        self.declare_parameter('face_resume_topic', '/face_avatar/resume')
        self.declare_parameter('suspend_settle_sec', 0.4)
        # 카메라 3 (노트북 외장 RPC-20F) 인덱스. GEVA 는 카메라 1 (내장, 0)
        # 그대로 점유. 외장 USB UVC 캠은 보통 /dev/video2 → 2 기본. 환경마다
        # 다르면 launch param 으로 override.
        self.declare_parameter('game_camera_index', 2)

        self._python = self.get_parameter('python_executable').value
        self._difficulty = self.get_parameter('difficulty').value
        self._timeout = float(self.get_parameter('game_timeout_sec').value)
        self._result_dir = self.get_parameter('result_dir').value
        self._suspend_settle = float(
            self.get_parameter('suspend_settle_sec').value)
        self._game_camera_index = int(
            self.get_parameter('game_camera_index').value)

        for gid, path in DEFAULT_GAME_REGISTRY.items():
            if not os.path.isfile(path):
                self.get_logger().warning(
                    f"game '{gid}' script 미발견 (시동 시점): {path}")

        self.pub_result = self.create_publisher(
            MinigameResult, self.get_parameter('result_topic').value, 10)
        self.pub_face_suspend = self.create_publisher(
            Empty, self.get_parameter('face_suspend_topic').value, 10)
        self.pub_face_resume = self.create_publisher(
            Empty, self.get_parameter('face_resume_topic').value, 10)

        # /minigame/start 토픽: String (game_id). 빈 문자열이면 "rps" 기본.
        self.sub_start = self.create_subscription(
            String, self.get_parameter('start_topic').value,
            self._on_start, 10)

        self._running = False
        self._game_thread: Optional[threading.Thread] = None

        registered = ", ".join(sorted(DEFAULT_GAME_REGISTRY.keys()))
        self.get_logger().info(
            f"minigame_runner ready (subprocess wrapper)\n"
            f"  registered games: {registered}\n"
            f"  difficulty={self._difficulty} timeout={self._timeout}s\n"
            f"  game_camera_index={self._game_camera_index} "
            f"(GEVA 카메라 1 분리 — /geva/suspend|resume 폐기)")

    def _on_start(self, msg: String):
        if self._running:
            self.get_logger().warning("게임 중복 시작 무시 (이미 진행중)")
            return
        game_id = msg.data.strip() or "rps"
        if game_id not in DEFAULT_GAME_REGISTRY:
            self.get_logger().error(
                f"unknown game_id: '{game_id}' "
                f"(registered: {sorted(DEFAULT_GAME_REGISTRY.keys())})")
            self._publish_failure_result(game_id=game_id)
            return
        script = DEFAULT_GAME_REGISTRY[game_id]
        if not os.path.isfile(script):
            self.get_logger().error(
                f"game '{game_id}' script 미발견: {script}")
            self._publish_failure_result(game_id=game_id)
            return
        self._running = True
        self._game_thread = threading.Thread(
            target=self._run_game_subprocess,
            args=(game_id, script),
            daemon=True)
        self._game_thread.start()

    def _run_game_subprocess(self, game_id: str, script: str):
        params = DEFAULT_GAME_PARAMS.get(game_id, {})
        auto_exit = float(params.get("auto_exit_sec", 4.0))
        ready_delay = float(params.get("ready_delay_sec", 0.5))
        explain = params.get("explain", {})

        result_path = Path(self._result_dir) / (
            f"minigame_{game_id}_{int(time.time())}_{os.getpid()}.json")
        cmd = [
            self._python, script,
            "--auto-play",
            "--difficulty", self._difficulty,
            "--auto-exit", str(auto_exit),
            "--ready-delay", str(ready_delay),
            "--result-json", str(result_path),
            "--fullscreen",
            "--camera-index", str(self._game_camera_index),
        ]
        t_start = time.monotonic()
        proc = None
        try:
            self.get_logger().info(
                f"[{game_id}] suspend face_avatar (디스플레이 양보)")
            self.pub_face_suspend.publish(Empty())
            time.sleep(self._suspend_settle)

            # 게임 시작 전 설명 + 5초 카운트다운 (pygame 풀스크린)
            if explain:
                proceed = self._show_explain_countdown(game_id, explain)
                if not proceed:
                    self.get_logger().warning(
                        f"[{game_id}] 카운트다운 중 사용자 ESC → 게임 미시작")
                    self._publish_failure_result(game_id, t_start)
                    return

            self.get_logger().info(
                f"[{game_id}] subprocess: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd)
            try:
                proc.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                self.get_logger().error(
                    f"[{game_id}] timeout {self._timeout}s — SIGTERM")
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)

            rc = proc.returncode if proc is not None else -1
            self.get_logger().info(f"[{game_id}] returncode={rc}")
            self._publish_result_from_json(
                game_id, result_path, t_start, rc)
        except Exception as e:
            self.get_logger().error(f"[{game_id}] subprocess 예외: {e}")
            self._publish_failure_result(game_id, t_start)
        finally:
            try:
                if result_path.exists():
                    result_path.unlink()
            except Exception:
                pass
            self.pub_face_resume.publish(Empty())
            self._running = False

    def _show_explain_countdown(self, game_id: str, explain: dict) -> bool:
        """게임 시작 전 설명 + 카운트다운 (pygame 풀스크린).

        ESC/QUIT 수신 시 False 반환 (게임 미시작). 정상 완료 시 True.
        face_avatar/geva 는 이미 suspend 상태로 호출됨.
        """
        os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
        import pygame

        title = explain.get("title", game_id)
        rules = explain.get("rules", [])
        countdown_sec = float(explain.get("countdown_sec", 5.0))

        pygame.init()
        try:
            info = pygame.display.Info()
            sw, sh = info.current_w, info.current_h
            try:
                screen = pygame.display.set_mode(
                    (sw, sh), pygame.FULLSCREEN)
            except pygame.error as e:
                self.get_logger().warning(
                    f"[{game_id}] FULLSCREEN 실패 ({e}) → NOFRAME fallback")
                screen = pygame.display.set_mode(
                    (sw, sh), pygame.NOFRAME)
            pygame.display.set_caption(f'Dobi minigame: {title}')
            pygame.mouse.set_visible(False)

            font_path = _find_korean_font()
            if font_path:
                font_lg = pygame.font.Font(font_path, int(sh * 0.30))
                font_md = pygame.font.Font(font_path, int(sh * 0.07))
                font_sm = pygame.font.Font(font_path, int(sh * 0.045))
            else:
                font_lg = pygame.font.SysFont(None, int(sh * 0.32))
                font_md = pygame.font.SysFont(None, int(sh * 0.08))
                font_sm = pygame.font.SysFont(None, int(sh * 0.05))

            clock = pygame.time.Clock()
            end_t = time.monotonic() + countdown_sec

            self.get_logger().info(
                f"[{game_id}] explain countdown — "
                f"title='{title}' rules={len(rules)} sec={countdown_sec}")

            while time.monotonic() < end_t:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        return False
                    if (ev.type == pygame.KEYDOWN
                            and ev.key == pygame.K_ESCAPE):
                        return False

                screen.fill((0, 0, 0))

                # title
                t_surf = font_md.render(title, True, (200, 220, 255))
                screen.blit(t_surf, t_surf.get_rect(
                    center=(sw // 2, int(sh * 0.14))))

                # rules (각 줄 중앙 정렬)
                line_y = int(sh * 0.28)
                for line in rules:
                    r_surf = font_sm.render(line, True, (220, 220, 220))
                    screen.blit(r_surf, r_surf.get_rect(
                        center=(sw // 2, line_y)))
                    line_y += int(font_sm.get_linesize() * 1.4)

                # countdown number (5 → 1)
                remaining = end_t - time.monotonic()
                n = max(1, int(remaining) + 1)
                if n > countdown_sec:
                    n = int(countdown_sec)
                c_surf = font_lg.render(
                    str(n), True, (255, 200, 100))
                screen.blit(c_surf, c_surf.get_rect(
                    center=(sw // 2, int(sh * 0.72))))

                pygame.display.flip()
                clock.tick(30)
            return True
        finally:
            # display subsystem 명시 종료 → 그 후 전체 quit. SDL2 가 X11
            # 윈도우 destroy 비동기인 케이스 대비.
            try:
                pygame.display.quit()
            except Exception:
                pass
            try:
                pygame.quit()
            except Exception:
                pass
            # X11 잔존 윈도우 강제 close (pygame.quit 후에도 잔존 — face_avatar
            # 위에 stacking → face_avatar 안 보이는 원인).
            try:
                subprocess.run(
                    ['wmctrl', '-c', f'Dobi minigame: {title}'],
                    check=False, timeout=2.0,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _publish_result_from_json(
            self, game_id: str, path: Path,
            t_start: float, returncode: int):
        msg = MinigameResult()
        msg.game_id = game_id
        msg.header.stamp = self.get_clock().now().to_msg()
        if not path.exists():
            self.get_logger().error(
                f"[{game_id}] result JSON 없음: {path} "
                f"(returncode={returncode})")
            msg.completed = False
            msg.duration_sec = float(time.monotonic() - t_start)
            self.pub_result.publish(msg)
            return
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            self.get_logger().error(f"[{game_id}] JSON 파싱 실패: {e}")
            msg.completed = False
            msg.duration_sec = float(time.monotonic() - t_start)
            self.pub_result.publish(msg)
            return
        msg.customer_wins = int(data.get("customer_wins", 0))
        msg.robot_wins = int(data.get("robot_wins", 0))
        msg.ties = int(data.get("ties", 0))
        msg.rounds_played = int(data.get("rounds_played", 0))
        msg.completed = bool(data.get("completed", False))
        msg.duration_sec = float(
            data.get("duration_sec", time.monotonic() - t_start))
        decided = msg.customer_wins + msg.robot_wins
        msg.customer_win_rate = (
            float(msg.customer_wins) / decided if decided > 0 else 0.0)
        self.pub_result.publish(msg)
        self.get_logger().info(
            f"[{game_id}] result: customer={msg.customer_wins} "
            f"robot={msg.robot_wins} ties={msg.ties} "
            f"win_rate={msg.customer_win_rate:.2f} "
            f"completed={msg.completed} dur={msg.duration_sec:.1f}s")

    def _publish_failure_result(
            self, game_id: str = "unknown",
            t_start: Optional[float] = None):
        msg = MinigameResult()
        msg.game_id = game_id
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.completed = False
        if t_start is not None:
            msg.duration_sec = float(time.monotonic() - t_start)
        self.pub_result.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = MinigameRunnerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
