#!/usr/bin/env python3
"""
mode_manager_node.py
vic_pinky 6상태 운영 모드 FSM + LaunchSupervisor.

6-state FSM (2026-05-19 확장 — follow + guiding 분리 운용, docs/moca_5state_fsm_spec.md SoT):
  idle      — 대기. 활성 mode stack 없음. 기본 상태. priority 99.
  serving   — 픽업 테이블 → 목표 테이블 배달 후 home 복귀. priority 1 (최상).
  patrol    — 5분 주기 전 테이블 순회 + 점유 감지. priority 3.
  guiding   — 카운터에서 결제 완료 고객을 빈 테이블로 인솔. priority 2.
  engaging  — 한산 시 모객 (cafe_funnel_v1.xml 6단계 BT). priority 5.
  follow    — 1인 reactive 추종 (person_tracking + approach_controller + LiDAR 거리). priority 4.

Legacy alias (M3 종료 2026-07-04 까지만 지원, WARN 로그 후 자동 변환):
  npc -> engaging

인터페이스:
  SRV /mode/request    (dobi_npc_msgs/SetMode)
       requested_mode + params(JSON) → success/current_mode/reason
  PUB /mode/state      (dobi_npc_msgs/ModeState, 1Hz)
       current_mode + entered_at + params + 가드 상태
  SUB /battery_state   (sensor_msgs/BatteryState)        — 배터리 가드
  SUB /rapport/event   (dobi_npc_msgs/RapportEvent)      — safety alarm 강제 idle
  SUB /operator/command (dobi_npc_msgs/OperatorCommand)  — stop_emergency / resume

가드 (idle 외 모드 거부):
  - 배터리 < battery_min (기본 0.20)          → reason="battery_low:<pct><<min>"
  - safety alarm (rapport abort_trigger 인지) → reason="safety_alarm_active"
  - 전이 진행 중                              → reason="transition_in_progress"
  - 알 수 없는 모드                            → reason="unknown_mode:<m>"
  - 잘못된 JSON params                        → reason="invalid_json_params:..."

priority enforce 책임은 moca_opserver 에 있음 (docs/moca_5state_fsm_spec.md §5).
mode_manager 는 priority 무관 모든 전이 허용 (운영자 수동 트리거 우선).
가드 발동 시 어느 상태에서든 idle 강제 전이.

B 단계 launch 제어:
  - subprocess.Popen("ros2 launch dobi_npc_bringup mode_<mode>.launch.py ...",
                     start_new_session=True)
  - kill: os.killpg(pgid, SIGTERM) → grace 후 SIGKILL
  - spawn 후 grace_spawn 동안 즉사 감지 → 실패 시 idle rollback
  - 비동기: service 응답 즉시(transition_started), 실 spawn/kill 은 백그라운드 thread
  - /mode/state 1Hz 가 transition 결과 반영

사용:
  ros2 run dobi_npc_bringup mode_manager
  ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \\
    "{requested_mode: 'serving', params: '{\"waypoint\": \"table_5\"}'}"
  ros2 topic echo /mode/state
"""

import json
import os
import shlex
import signal
import subprocess
import threading

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import BatteryState
from dobi_npc_msgs.msg import RapportEvent, ModeState, OperatorCommand
from dobi_npc_msgs.srv import SetMode


VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')

# M3 종료(2026-07-04) 후 제거 예정. WARN 로그 후 자동 변환.
# 2026-05-19 머지: follow 는 mode_guiding 과 분리 운용하므로 alias 에서 제거.
LEGACY_MODE_ALIAS = {
    'npc': 'engaging',
}


class LaunchSupervisor:
    """모드별 ros2 launch 의 spawn/kill 관리.

    setsid 로 자식을 process group leader 로 띄움 → killpg(pgid, SIGTERM)
    으로 launch 가 띄운 모든 노드를 한 번에 종료. SIGTERM 후 grace 안에
    안 죽으면 SIGKILL 강제.

    스레드 안전 — 자체 lock. mode_manager 의 service callback 이 supervisor
    호출 전 lock 풀고, 호출 후 다시 mode_manager lock 획득하는 패턴.
    """

    GRACE_SPAWN_SEC = 1.5     # spawn 후 즉사 감지 grace
    GRACE_TERM_SEC = 3.0      # SIGTERM 후 SIGKILL 까지 대기

    def __init__(self, logger):
        self.logger = logger
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._mode: str | None = None  # 현재 spawn 한 모드 (idle 일 땐 None)

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def current_mode(self) -> str | None:
        with self._lock:
            return self._mode

    def kill(self) -> tuple[bool, str]:
        """현 stack 종료. 항상 (ok=True, reason) 반환 — 외부적으로 실패 없음."""
        with self._lock:
            proc = self._proc
            mode = self._mode
            self._proc = None
            self._mode = None

        if proc is None or proc.poll() is not None:
            return True, "no_running_stack"

        pid = proc.pid
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True, "already_gone"

        try:
            proc.wait(timeout=self.GRACE_TERM_SEC)
            self.logger.info(
                f'kill SIGTERM OK (mode={mode}, pgid={pid}, '
                f'rc={proc.returncode})')
            return True, "term"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            self.logger.warn(
                f'kill SIGKILL (mode={mode}, pgid={pid}, '
                f'SIGTERM 무응답 {self.GRACE_TERM_SEC}s)')
            return True, "kill"

    def spawn(self, mode: str, params_json: str) -> tuple[bool, str]:
        """모드별 launch spawn. (ok, reason) 반환.

        idle 모드는 launch 안 함 (no_stack 으로 ok 반환).
        spawn 후 GRACE_SPAWN_SEC 대기 — 자식이 즉시 종료되면 실패로 판단.
        """
        if mode == 'idle':
            with self._lock:
                self._proc = None
                self._mode = None
            return True, "idle_no_stack"

        launch_file = f'mode_{mode}.launch.py'
        cmd = ['ros2', 'launch', 'dobi_npc_bringup', launch_file]
        if params_json:
            # ros2 launch 는 인자에 공백 허용. shlex 로 감싸지 않고 그대로 전달.
            cmd.append(f'params_json:={params_json}')

        try:
            proc = subprocess.Popen(
                cmd, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as e:
            return False, f'ros2_launch_not_found:{e}'
        except Exception as e:
            return False, f'spawn_exception:{type(e).__name__}:{e}'

        # 즉사 감지 grace
        try:
            proc.wait(timeout=self.GRACE_SPAWN_SEC)
            rc = proc.returncode
            self.logger.warn(
                f'spawn 실패 (mode={mode}, 즉시 종료, rc={rc}, '
                f'cmd={shlex.join(cmd)})')
            return False, f'spawn_died_immediately:rc={rc}'
        except subprocess.TimeoutExpired:
            with self._lock:
                self._proc = proc
                self._mode = mode
            self.logger.info(
                f'spawn OK (mode={mode}, pgid={proc.pid}, '
                f'cmd={shlex.join(cmd)})')
            return True, "spawned"

    def shutdown(self) -> None:
        """노드 종료 시 잔존 stack 정리."""
        if self.is_running():
            self.kill()


class ModeManagerNode(Node):
    """4상태 FSM + 가드 + 비동기 LaunchSupervisor."""

    def __init__(self):
        super().__init__('mode_manager')

        self.declare_parameter('initial_mode', 'idle')
        self.declare_parameter('battery_min', 0.20)
        self.declare_parameter('state_publish_hz', 1.0)
        self.declare_parameter('safety_alarm_dwell_sec', 5.0)

        initial = self.get_parameter('initial_mode').value
        if initial not in VALID_MODES:
            self.get_logger().warn(
                f'initial_mode "{initial}" 잘못됨 → idle 사용')
            initial = 'idle'
        self.battery_min = float(self.get_parameter('battery_min').value)
        publish_hz = float(self.get_parameter('state_publish_hz').value)
        self.alarm_dwell_sec = float(
            self.get_parameter('safety_alarm_dwell_sec').value)

        self._lock = threading.Lock()
        self._current_mode = 'idle'   # 실제 현재 (supervisor 와 동기화)
        self._params = ''
        self._entered_at = self.get_clock().now().to_msg()
        self._last_reject_reason = ''
        self._busy = False             # 전이 진행 중 플래그

        # 가드 입력
        self._battery_pct = -1.0      # -1 = 미수신
        self._safety_alarm_until_ns = 0

        # supervisor
        self.supervisor = LaunchSupervisor(self.get_logger())

        # 입력 토픽 — 가드용
        self.sub_battery = self.create_subscription(
            BatteryState, '/battery_state', self._on_battery, 10)
        self.sub_rapport = self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)
        # 운영자 명령 — stop_emergency / resume (FSM spec §3.4)
        self.sub_op_cmd = self.create_subscription(
            OperatorCommand, '/operator/command', self._on_operator_cmd, 10)

        # 서비스
        self.srv = self.create_service(
            SetMode, '/mode/request', self._on_request)

        # 출력 토픽
        self.pub_state = self.create_publisher(ModeState, '/mode/state', 10)
        self.timer = self.create_timer(1.0 / publish_hz, self._publish_state)

        self.get_logger().info(
            f'mode_manager ready: initial={initial} '
            f'battery_min={self.battery_min} pub_hz={publish_hz}')

        # initial_mode != idle 이면 시동 시 자동 spawn (검증 편의)
        if initial != 'idle':
            self.get_logger().info(
                f'initial_mode={initial} → 자동 spawn 시도')
            threading.Thread(
                target=self._do_transition,
                args=('idle', initial, ''),
                daemon=True,
            ).start()
            with self._lock:
                self._busy = True

    # ---- 입력 콜백 -------------------------------------------------------

    def _on_battery(self, msg: BatteryState):
        import math
        pct = float(msg.percentage)
        # NaN은 미수신(-1.0)으로 처리 → _battery_ok()에서 True 반환 (라이브 미연결 환경)
        self._battery_pct = pct if math.isfinite(pct) else -1.0

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type != 'abort_trigger':
            return
        now_ns = self.get_clock().now().nanoseconds
        self._safety_alarm_until_ns = now_ns + int(
            self.alarm_dwell_sec * 1e9)
        with self._lock:
            if self._current_mode == 'idle' or self._busy:
                # 이미 idle 이거나 다른 전이 진행 중 — 여기서 강제 전이 안 함
                return
            prev = self._current_mode
            self._busy = True

        self.get_logger().warn(
            f'safety alarm → 강제 idle 시도 (이전: {prev})')
        threading.Thread(
            target=self._do_transition,
            args=(prev, 'idle', ''),
            kwargs={'reject_reason': 'safety_alarm_forced_idle'},
            daemon=True,
        ).start()

    def _on_operator_cmd(self, msg: OperatorCommand):
        """운영자 명령 — stop_emergency / resume (FSM spec §3.4).

        stop_emergency: 가드 무시하고 즉시 강제 idle + alarm dwell 시작.
                        operator 의도 우선이므로 _busy 라도 일단 대기 후 처리는 X
                        (기존 전이 끝나면 _busy 해제, 다음 publish 에서 idle 반영).
                        rapport abort 와 동일한 dwell 메커니즘 재사용.
        resume        : alarm dwell 즉시 해제 (다음 SetMode 통과).
        """
        ct = msg.command_type
        if ct == 'stop_emergency':
            now_ns = self.get_clock().now().nanoseconds
            self._safety_alarm_until_ns = now_ns + int(
                self.alarm_dwell_sec * 1e9)
            with self._lock:
                if self._current_mode == 'idle' or self._busy:
                    self.get_logger().warn(
                        'OperatorCommand stop_emergency 수신 — '
                        'idle 이거나 busy → dwell 만 설정')
                    return
                prev = self._current_mode
                self._busy = True

            self.get_logger().warn(
                f'OperatorCommand stop_emergency → 강제 idle (이전: {prev})')
            threading.Thread(
                target=self._do_transition,
                args=(prev, 'idle', ''),
                kwargs={'reject_reason': 'emergency_stop_forced_idle'},
                daemon=True,
            ).start()
        elif ct == 'resume':
            with self._lock:
                self._safety_alarm_until_ns = 0
                self._last_reject_reason = ''
            self.get_logger().info(
                'OperatorCommand resume → safety dwell 해제')
        # utter / express / skip_table 등은 mode_manager 가 처리 X (각 dispatcher 담당)

    # ---- 가드 평가 ------------------------------------------------------

    def _battery_ok(self) -> bool:
        if self._battery_pct < 0.0:
            return True   # 미수신은 안전 측 OK (라이브 미연결 환경)
        return self._battery_pct >= self.battery_min

    def _safety_ok(self) -> bool:
        if self._safety_alarm_until_ns == 0:
            return True
        return self.get_clock().now().nanoseconds >= self._safety_alarm_until_ns

    # ---- 서비스 핸들러 --------------------------------------------------

    def _on_request(self, request, response):
        req_mode = request.requested_mode
        req_params = request.params or ''

        # Legacy alias 자동 변환 (FSM spec §6.3, M3 종료 후 제거)
        if req_mode in LEGACY_MODE_ALIAS:
            new_name = LEGACY_MODE_ALIAS[req_mode]
            self.get_logger().warn(
                f'legacy mode "{req_mode}" -> "{new_name}" 자동 변환 '
                f'(deprecation: M3 종료 2026-07-04 까지만 지원)')
            req_mode = new_name

        with self._lock:
            # 1. 다른 전이 진행 중 → reject
            if self._busy:
                response.success = False
                response.current_mode = self._current_mode
                response.reason = 'transition_in_progress'
                self._last_reject_reason = response.reason
                self.get_logger().warn(
                    f'reject [{req_mode}] → {response.reason}')
                return response

            # 2. 모드명 검증
            if req_mode not in VALID_MODES:
                response.success = False
                response.current_mode = self._current_mode
                response.reason = f'unknown_mode:{req_mode}'
                self._last_reject_reason = response.reason
                self.get_logger().warn(
                    f'reject [{req_mode}] → {response.reason}')
                return response

            # 3. params JSON 검증 (빈 문자열 OK)
            if req_params and req_params.strip():
                try:
                    json.loads(req_params)
                except json.JSONDecodeError as e:
                    response.success = False
                    response.current_mode = self._current_mode
                    response.reason = f'invalid_json_params:{e.msg}'
                    self._last_reject_reason = response.reason
                    self.get_logger().warn(
                        f'reject [{req_mode}] → {response.reason}')
                    return response

            # 4. 가드 — idle 외 전환은 가드 통과 필요
            if req_mode != 'idle':
                if not self._battery_ok():
                    response.success = False
                    response.current_mode = self._current_mode
                    response.reason = (
                        f'battery_low:{self._battery_pct:.2f}<'
                        f'{self.battery_min:.2f}')
                    self._last_reject_reason = response.reason
                    self.get_logger().warn(
                        f'reject [{req_mode}] → {response.reason}')
                    return response
                if not self._safety_ok():
                    response.success = False
                    response.current_mode = self._current_mode
                    response.reason = 'safety_alarm_active'
                    self._last_reject_reason = response.reason
                    self.get_logger().warn(
                        f'reject [{req_mode}] → {response.reason}')
                    return response

            # 5. 검증 통과 → 백그라운드 전이 시작
            prev_mode = self._current_mode
            self._busy = True

        threading.Thread(
            target=self._do_transition,
            args=(prev_mode, req_mode, req_params),
            daemon=True,
        ).start()

        # 6. 즉시 응답 — 실 spawn/kill 결과는 /mode/state 로 갱신
        response.success = True
        response.current_mode = req_mode
        response.reason = 'transition_started'
        self.get_logger().info(
            f'transition_started: {prev_mode} → {req_mode} '
            f'params=\'{req_params}\'')
        return response

    # ---- 비동기 전이 (별 thread) ---------------------------------------

    def _do_transition(self, prev_mode: str, new_mode: str, new_params: str,
                       reject_reason: str = ''):
        """별 thread 에서 supervisor.kill + spawn 수행. 결과를 lock 안에 반영.

        prev_mode / new_mode 는 mode_manager 가 lock 안에서 미리 결정한 값.
        본 메서드는 lock 외부에서 spawn/kill block 작업 진행.
        """
        # kill 옛 stack
        kill_ok, kill_reason = self.supervisor.kill()
        # spawn 새 stack
        spawn_ok, spawn_reason = self.supervisor.spawn(new_mode, new_params)

        with self._lock:
            self._busy = False
            now = self.get_clock().now().to_msg()
            if spawn_ok:
                self._current_mode = new_mode
                self._params = new_params
                self._entered_at = now
                # safety alarm 강제 idle 같이 reject_reason 주어진 경우 보존
                self._last_reject_reason = reject_reason
                final_msg = (
                    f'transition_done: {prev_mode} → {new_mode} '
                    f'(kill={kill_reason}, spawn={spawn_reason})')
            else:
                # spawn 실패 → idle 로 rollback (옛 모드 stack 은 이미 kill됨)
                self._current_mode = 'idle'
                self._params = ''
                self._entered_at = now
                self._last_reject_reason = (
                    f'spawn_failed:{spawn_reason}')
                final_msg = (
                    f'transition_failed: {prev_mode} → {new_mode} '
                    f'rollback idle (kill={kill_reason}, spawn={spawn_reason})')

        if spawn_ok:
            self.get_logger().info(final_msg)
        else:
            self.get_logger().warn(final_msg)

    # ---- 상태 publish --------------------------------------------------

    def _publish_state(self):
        with self._lock:
            msg = ModeState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.current_mode = self._current_mode
            msg.entered_at = self._entered_at
            msg.params = self._params
            msg.battery_ok = self._battery_ok()
            msg.safety_ok = self._safety_ok()
            msg.last_reject_reason = self._last_reject_reason
        self.pub_state.publish(msg)

    # ---- 종료 ----------------------------------------------------------

    def destroy_node(self):
        self.supervisor.shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ModeManagerNode()
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
