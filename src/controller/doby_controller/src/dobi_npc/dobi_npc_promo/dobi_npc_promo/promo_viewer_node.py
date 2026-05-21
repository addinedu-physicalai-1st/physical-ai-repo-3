"""promo_viewer_node - engaging mode promo HTML kiosk viewer.

mode_engaging 진입 시 별도 launch 로 spawn 되어 google-chrome kiosk 풀스크린으로
assets/promo/promo.html 표시. BT funnel stage 에 따라 단일 디스플레이를 시간 분할.

=== BT funnel stage 별 디스플레이 분할 (cafe_funnel_v1.xml 기준) ===
  stage1 IdleScan / stage2 Approach  -> promo        (dialog/request 미발행)
  stage3 IceBreak                    -> face_avatar  (/dialog/request)
  stage4 Minigame                    -> minigame     (/minigame/start)
  stage5 Offer / stage6 LeadIn       -> face_avatar  (/dialog/request)
  cycle 끝 -> IdleScan 복귀          -> promo        (watchdog idle 감지)

=== 디스플레이 z-order 조율 ===
단일 디스플레이를 promo chrome / face_avatar / minigame_runner 가 시간 분할.
promo_viewer 는 promo chrome 의 spawn/kill 뿐 아니라 face_avatar 의 suspend/
resume 토픽도 제어해 z-order 를 명시 조율한다 (face_avatar resume 은 wmctrl
raise 포함 - minigame_runner 와 동일 인터페이스):
  - promo 표시 (PHASE_PROMO)  -> promo chrome spawn + /face_avatar/suspend
  - promo 숨김 (PHASE_DIALOG) -> promo chrome kill  + /face_avatar/resume
  - minigame (PHASE_MINIGAME) -> promo chrome kill  (face_avatar 는 minigame_runner 위임)

=== 전환 메커니즘 ===
  - /dialog/request  수신 -> PHASE_DIALOG (face_avatar), watchdog 갱신
  - /minigame/start  수신 -> PHASE_MINIGAME (minigame), watchdog 정지
  - /minigame/result 수신 -> PHASE_DIALOG (offer/leadin watchdog 재가동)
  - watchdog: PHASE_DIALOG 에서 idle_resume_sec 무활동 -> PHASE_PROMO
  IdleScan/Approach 는 토픽을 발행하지 않으므로 '무활동' 으로 간접 감지.

토픽:
  구독 - /dialog/request (String) / /minigame/start (String)
         /minigame/result (MinigameResult) / /promo/suspend /promo/resume (Empty)
  발행 - /face_avatar/suspend /face_avatar/resume (Empty)

파라미터:
  - browser_cmd        (str,   default 'google-chrome')
  - promo_html_path    (str,   default ''  -> assets/promo/promo.html 자동 추정)
  - kiosk              (bool,  default True)
  - respawn_delay_sec  (float, default 0.5)
  - idle_resume_sec    (float, default 8.0)  dialog 무활동 -> promo 복귀 임계
  - chrome_user_data_dir (str, default '/tmp/moca_promo_chrome')

기존 코드 0 변경 정책 정합 - 본 노드는 신규 패키지에 단독 신설.
"""
import os
import signal
import subprocess
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import Empty, String

try:
    from dobi_npc_msgs.msg import MinigameResult
    _HAS_MINIGAME_RESULT = True
except ImportError:
    _HAS_MINIGAME_RESULT = False

try:
    from dobi_npc_msgs.msg import UtterRequest
    _HAS_UTTER_REQUEST = True
except ImportError:
    _HAS_UTTER_REQUEST = False


# promo 단계 진입 시 1회 발화할 요약 홍보 멘트 (기본값).
_DEFAULT_PROMO_UTTER = (
    '로봇 카페 모카에 오신 것을 환영합니다. '
    '토스트 세트와 피자 세트, 그리고 다양한 음료를 준비했습니다. '
    '지금 오픈 이벤트가 진행 중입니다. '
    '미니게임에서 도비를 이기면 음료 할인 혜택을 드립니다. '
    '도비와 함께 즐거운 시간 보내세요.'
)


def _find_workspace_root() -> str:
    """CLAUDE.md 컨벤션 - SCRIPT_DIR 기반 워크스페이스 추정."""
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(12):
        if os.path.isdir(os.path.join(here, 'src')) and (
            os.path.isfile(os.path.join(here, 'moca.repos'))
            or os.path.isfile(os.path.join(here, 'CLAUDE.md'))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return ''


PHASE_PROMO = 'promo'        # promo chrome 풀스크린 (IdleScan/Approach)
PHASE_DIALOG = 'dialog'      # face_avatar 단계 (IceBreak/Offer/LeadIn)
PHASE_MINIGAME = 'minigame'  # minigame_runner 단계
PHASE_MANUAL = 'manual'      # 수동 /promo/suspend 로 내려간 상태


class PromoViewerNode(Node):

    def __init__(self):
        super().__init__('promo_viewer')

        self.declare_parameter('browser_cmd', 'google-chrome')
        self.declare_parameter('promo_html_path', '')
        self.declare_parameter('kiosk', True)
        self.declare_parameter('respawn_delay_sec', 0.5)
        self.declare_parameter('idle_resume_sec', 8.0)
        self.declare_parameter('chrome_user_data_dir', '/tmp/moca_promo_chrome')
        # promo 단계 진입 시 1회 발화할 홍보 멘트 (빈 문자열이면 발화 비활성)
        self.declare_parameter('promo_utter_text', _DEFAULT_PROMO_UTTER)
        self.declare_parameter('promo_voice', '')   # '' -> tts_node default
        self.declare_parameter('promo_rate', '')
        self.declare_parameter('promo_pitch', '')

        self.browser_cmd = str(self.get_parameter('browser_cmd').value)
        html_param = str(self.get_parameter('promo_html_path').value)
        self.kiosk = bool(self.get_parameter('kiosk').value)
        self.respawn_delay = float(self.get_parameter('respawn_delay_sec').value)
        self.idle_resume_sec = float(self.get_parameter('idle_resume_sec').value)
        self.user_data_dir = str(
            self.get_parameter('chrome_user_data_dir').value)
        self.promo_utter_text = str(
            self.get_parameter('promo_utter_text').value)
        self.promo_voice = str(self.get_parameter('promo_voice').value)
        self.promo_rate = str(self.get_parameter('promo_rate').value)
        self.promo_pitch = str(self.get_parameter('promo_pitch').value)

        if html_param:
            self.promo_html = os.path.abspath(html_param)
        else:
            ws = _find_workspace_root()
            self.promo_html = os.path.join(ws, 'assets', 'promo', 'promo.html')

        if not os.path.isfile(self.promo_html):
            self.get_logger().error(
                f'promo.html 파일 없음: {self.promo_html}')
        else:
            self.get_logger().info(f'promo.html: {self.promo_html}')

        self._proc: Optional[subprocess.Popen] = None
        self._phase = PHASE_PROMO
        self._last_dialog_t = 0.0

        # face_avatar 디스플레이 양보 제어 publisher
        self.pub_face_suspend = self.create_publisher(
            Empty, '/face_avatar/suspend', 10)
        self.pub_face_resume = self.create_publisher(
            Empty, '/face_avatar/resume', 10)
        # promo 단계 홍보 멘트 발화 — tts_node 직접 (/dialog/utter).
        # tts_node 는 새 utter 수신 시 interrupt(현 재생 즉시 중단)하므로
        # IceBreak 의 face 멘트가 도착하면 promo 멘트가 자동 중단됨 (겹침 방지).
        self.pub_utter = None
        if _HAS_UTTER_REQUEST:
            self.pub_utter = self.create_publisher(
                UtterRequest, '/dialog/utter', 10)
        elif self.promo_utter_text:
            self.get_logger().warn(
                'UtterRequest import 실패 — promo 멘트 발화 비활성')

        self.create_subscription(
            String, '/dialog/request', self._on_dialog_request, 10)
        self.create_subscription(
            String, '/minigame/start', self._on_mg_start, 10)
        if _HAS_MINIGAME_RESULT:
            self.create_subscription(
                MinigameResult, '/minigame/result', self._on_mg_result, 10)
        else:
            self.get_logger().warn(
                'dobi_npc_msgs/MinigameResult import 실패 - '
                '/minigame/result 구독 생략')
        self.create_subscription(Empty, '/promo/suspend', self._on_suspend, 10)
        self.create_subscription(Empty, '/promo/resume', self._on_resume, 10)

        self.create_timer(1.0, self._watchdog_tick)

        # 초기 — engaging 진입 시 IdleScan 부터이므로 promo 표시
        self.get_logger().info(
            f'promo_viewer 시작 - idle_resume_sec={self.idle_resume_sec}')
        self._enter_promo('초기 시작')

    # ───── face_avatar 디스플레이 양보 ─────

    def _face_suspend(self):
        self.pub_face_suspend.publish(Empty())

    def _face_resume(self):
        self.pub_face_resume.publish(Empty())

    # ───── promo 홍보 멘트 발화 ─────

    def _publish_promo_utter(self):
        """promo 단계 진입 시 홍보 멘트 1회 발화 (tts_node 직접)."""
        if not self.pub_utter or not self.promo_utter_text:
            return
        msg = UtterRequest()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.text = self.promo_utter_text
        msg.voice = self.promo_voice
        msg.rate = self.promo_rate
        msg.pitch = self.promo_pitch
        msg.face_expression = ''   # promo 단계 — face 변경 없음
        msg.persona_id = 'promo'
        msg.stage_id = 'promo'
        msg.source = 'npc'
        msg.priority = 30
        msg.preempt = False
        self.pub_utter.publish(msg)
        self.get_logger().info('promo 멘트 발화 요청')

    # ───── chrome subprocess 제어 ─────

    def _spawn(self):
        if self._proc and self._proc.poll() is None:
            return
        if not os.path.isfile(self.promo_html):
            self.get_logger().error(
                f'spawn 실패 - html 없음: {self.promo_html}')
            return
        url = f'file://{self.promo_html}'
        args = [self.browser_cmd]
        args.extend([
            f'--user-data-dir={self.user_data_dir}',
            '--noerrdialogs',
            '--disable-infobars',
            '--no-first-run',
            '--disable-session-crashed-bubble',
            '--disable-features=TranslateUI',
        ])
        if self.kiosk:
            # --kiosk + positional URL = 완전 전체화면.
            # --app=URL 은 앱 윈도우(작은 창)라 --kiosk 와 충돌 → 전체화면 실패.
            args.extend(['--kiosk', '--start-fullscreen', url])
        else:
            args.append(f'--app={url}')
        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.get_logger().info(f'promo spawn pid={self._proc.pid}')
        except FileNotFoundError:
            self.get_logger().error(
                f'browser 명령 없음: {self.browser_cmd}')
            self._proc = None

    def _kill(self):
        if not self._proc:
            return
        proc = self._proc
        self._proc = None
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=2.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            except Exception as e:
                self.get_logger().warn(f'_kill SIGTERM 예외: {e}')
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        # chrome 멀티프로세스 — 메인이 SIGTERM 에 죽어도 renderer/gpu 자식이
        # 별 그룹으로 남을 수 있어 user-data-dir 패턴으로 잔재 확실히 정리.
        try:
            subprocess.run(
                ['pkill', '-9', '-f', f'user-data-dir={self.user_data_dir}'],
                timeout=3,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        self.get_logger().info('promo kill')

    def _is_visible(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ───── phase 전환 ─────

    def _enter_promo(self, reason: str):
        """promo chrome 표시 + face_avatar 양보(suspend) + 홍보 멘트 1회 발화."""
        self._phase = PHASE_PROMO
        if not self._is_visible():
            time.sleep(self.respawn_delay)
            self._spawn()
        self._face_suspend()
        self._publish_promo_utter()
        self.get_logger().info(f'-> promo 단계 ({reason})')

    def _enter_dialog(self, reason: str):
        """promo chrome 숨김 + face_avatar 복귀(resume + raise)."""
        self._phase = PHASE_DIALOG
        self._kill()
        self._face_resume()
        self.get_logger().info(f'-> face_avatar 단계 ({reason})')

    def _enter_minigame(self, reason: str):
        """promo chrome 숨김. face_avatar 는 minigame_runner 가 제어."""
        self._phase = PHASE_MINIGAME
        self._kill()
        self.get_logger().info(f'-> minigame 단계 ({reason})')

    # ───── stage 토픽 콜백 ─────

    def _on_dialog_request(self, msg):
        # IceBreak / Offer / LeadIn 진입 — face_avatar 단계
        self._last_dialog_t = time.monotonic()
        if self._phase == PHASE_MINIGAME:
            # minigame 중 dialog 가 와도 minigame 우선 유지
            return
        if self._phase != PHASE_DIALOG:
            self._enter_dialog(f'dialog: {msg.data}')

    def _on_mg_start(self, msg):
        # Minigame 진입
        self._enter_minigame(f'start: {msg.data}')

    def _on_mg_result(self, msg):
        # minigame 종료 — 이후 Offer/LeadIn(face_avatar) 가 남아있으므로
        # dialog 단계로 두고 watchdog 재가동
        self._last_dialog_t = time.monotonic()
        gid = getattr(msg, 'game_id', '?')
        self._enter_dialog(f'minigame 종료: {gid}')

    def _on_suspend(self, _msg):
        # 수동 override — promo 내림
        self._phase = PHASE_MANUAL
        self._kill()
        self.get_logger().info('suspended (수동)')

    def _on_resume(self, _msg):
        # 수동 override — promo 올림
        self._enter_promo('수동 resume')

    # ───── idle 복귀 watchdog ─────

    def _watchdog_tick(self):
        # dialog 단계에서 idle_resume_sec 동안 새 dialog/request 가 없으면
        # cafe_funnel 이 LeadIn 을 끝내고 IdleScan 으로 복귀한 것으로 간주.
        if self._phase != PHASE_DIALOG:
            return
        idle = time.monotonic() - self._last_dialog_t
        if idle >= self.idle_resume_sec:
            self._enter_promo(f'IdleScan 복귀, dialog 무활동 {idle:.1f}s')

    def shutdown(self):
        self._kill()


def main(args=None):
    rclpy.init(args=args)
    node = PromoViewerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
