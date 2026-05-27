#!/usr/bin/env python3
"""
serving_dispatcher_node.py
mode_serving 메인 노드 — opennav_docking 정밀 주차 + 큐 + dwell + home 복귀.

책임:
  - tables.yaml 로드 → 테이블 ID ↔ PoseStamped 매핑
  - 큐 (FIFO) 관리: 진입 시 params_json 의 waypoint + /serving/goto_table 토픽 append
  - 정밀 주차 (enable_docking=true, 기본):
      DockRobot(use_dock_id=false, dock_pose=tables.yaml pose, navigate_to_staging_pose=true)
      → docking_server 가 staging 이동 + 정밀 접근(odom 서보) 한 액션으로 처리
      → dwell N초 → UndockRobot(staging 복귀) → 다음 큐 또는 home 복귀
  - 레거시 (enable_docking=false): NavigateToPose 단발 (도킹 없이 pose 정차)
  - home 복귀는 항상 NavigateToPose (home = staging, 도킹 안 함)
  - /serving/state 1Hz 발행 (JSON)

mode_manager 와의 인터페이스:
  - launch param `params_json` 으로 첫 명령 (예: '{"waypoint": "T01"}')
  - 추가 명령은 /serving/goto_table 토픽 (mode 진입 후)
  - mode_manager 가 SIGTERM 던지면 active goal cancel + cleanup

안전:
  - cmd_vel 직접 발행 X — Nav2/docking_server 가 발행 → cmd_vel_nav → smoother →
    /bt/cmd_vel → twist_mux(80) → collision_monitor/e_stop 파이프라인. dispatcher 무신경.
  - placeholder 좌표 (모두 0) 감지 시 nav/dock 거부 + ERROR log (위험 회피).
  - dock/undock 타임아웃은 docking_server 가 소유 (max_staging_time / dock_approach_timeout /
    max_undocking_time). dispatcher 의 dock_timeout_sec 은 서버가 결과를 영영 안 줄 때만
    발동하는 last-resort 안전망 (이중 cancel 회피).

자세한 명세: docs/cafe_npc_serving_mode.md
"""

import json
import math
import os
from collections import deque
from enum import Enum

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
import yaml

from std_msgs.msg import String
from std_srvs.srv import Trigger
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose, DockRobot, UndockRobot


class State(str, Enum):
    IDLE = 'idle'
    DOCKING = 'docking'        # DockRobot 진행 (staging 이동 + 정밀 접근)
    NAVIGATING = 'navigating'  # 레거시 NavigateToPose (enable_docking=false)
    DWELL = 'dwell'
    UNDOCKING = 'undocking'    # UndockRobot 진행 (staging 복귀)
    RETURNING = 'returning'    # home 복귀 NavigateToPose


HOME_TABLE_ID = '__home__'  # 큐 sentinel — home 복귀 명령


class ServingDispatcher(Node):
    def __init__(self):
        super().__init__('serving_dispatcher')

        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter('dwell_sec', 5.0)
        self.declare_parameter('return_home_after_dwell', True)
        self.declare_parameter('nav_action_name', 'navigate_to_pose')
        self.declare_parameter('nav_timeout_sec', 60.0)
        # 정밀 주차 (opennav_docking)
        self.declare_parameter('enable_docking', True)
        self.declare_parameter('dock_type', 'cafe_table')
        self.declare_parameter('dock_action_name', 'dock_robot')
        self.declare_parameter('undock_action_name', 'undock_robot')
        self.declare_parameter('max_staging_time_sec', 60.0)      # 서버 staging 이동 타임아웃 (goal 필드)
        self.declare_parameter('max_undocking_time_sec', 30.0)    # 서버 undock 타임아웃 (goal 필드)
        self.declare_parameter('dock_timeout_sec', 180.0)         # dispatcher last-resort 안전망

        self.tables_yaml = self.get_parameter('tables_yaml').value
        self.params_json = self.get_parameter('params_json').value
        self.dwell_sec = float(self.get_parameter('dwell_sec').value)
        self.return_home = bool(self.get_parameter('return_home_after_dwell').value)
        self.nav_action = self.get_parameter('nav_action_name').value
        self.nav_timeout = float(self.get_parameter('nav_timeout_sec').value)
        self.enable_docking = bool(self.get_parameter('enable_docking').value)
        self.dock_type = self.get_parameter('dock_type').value
        self.dock_action = self.get_parameter('dock_action_name').value
        self.undock_action = self.get_parameter('undock_action_name').value
        self.max_staging_time = float(self.get_parameter('max_staging_time_sec').value)
        self.max_undocking_time = float(self.get_parameter('max_undocking_time_sec').value)
        self.dock_timeout = float(self.get_parameter('dock_timeout_sec').value)

        # tables.yaml 로드
        self.home_pose: PoseStamped | None = None
        self.tables: dict[str, dict] = {}  # id → {'pose': PoseStamped, 'meta': {...}}
        self._load_tables(self.tables_yaml)

        # 상태
        self.state: State = State.IDLE
        self.queue: deque[str] = deque()
        self.current_table: str | None = None
        self.dwell_start_ns: int | None = None
        self._goal_handle = None          # 현재 활성 goal (nav/dock/undock 통합 — 동시 1개만)
        self._action_started_ns: int | None = None

        # Action clients
        self._nav_ac = ActionClient(self, NavigateToPose, self.nav_action)
        self._dock_ac = ActionClient(self, DockRobot, self.dock_action)
        self._undock_ac = ActionClient(self, UndockRobot, self.undock_action)

        # 토픽
        self.create_subscription(String, '/serving/goto_table', self._on_goto_table, 10)
        self._state_pub = self.create_publisher(String, '/serving/state', 10)

        # 서비스 — tables.yaml 라이브 갱신 (운영 UI 좌표 등록 후 호출).
        self.create_service(Trigger, '/serving/reload_tables', self._on_reload_tables)

        # 진입 시 첫 명령 (params_json 의 waypoint)
        first_table = self._parse_first_waypoint(self.params_json)
        if first_table:
            self.queue.append(first_table)
            self.get_logger().info(f'진입 첫 명령 큐 추가: {first_table}')

        # 메인 tick + 상태 1Hz
        self.create_timer(0.2, self._tick)
        self.create_timer(1.0, self._publish_state)

        self.get_logger().info(
            f'serving_dispatcher start — tables={list(self.tables.keys())} '
            f'dwell={self.dwell_sec}s return_home={self.return_home} '
            f'docking={self.enable_docking}(type={self.dock_type!r})')

    # ───────── tables.yaml 로드 ─────────

    def _load_tables(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            self.get_logger().error(f'tables_yaml 파일 없음: {path!r}')
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.get_logger().error(f'tables_yaml 파싱 실패: {e}')
            return

        # home_pose
        home = data.get('home_pose')
        if home:
            ps = self._dict_to_pose(home)
            if ps and not self._is_placeholder(home):
                self.home_pose = ps
            else:
                self.get_logger().warn(
                    'home_pose 가 placeholder(0,0,0) 또는 누락 — 자동 복귀 비활성. '
                    'tables.yaml 에 RViz 등록 좌표 갱신 필요.')

        # tables
        for entry in data.get('tables', []):
            tid = entry.get('id')
            pose_d = entry.get('pose', {})
            if not tid or not pose_d:
                continue
            ps = self._dict_to_pose(pose_d)
            if not ps:
                continue
            self.tables[tid] = {
                'pose': ps,
                'placeholder': self._is_placeholder(pose_d),
                'description': entry.get('description', ''),
                'approach_dist': float(entry.get('approach_dist', 0.0)),
            }

    def _dict_to_pose(self, d: dict) -> PoseStamped | None:
        try:
            ps = PoseStamped()
            ps.header.frame_id = d.get('frame_id', 'map')
            ps.pose.position.x = float(d.get('x', 0.0))
            ps.pose.position.y = float(d.get('y', 0.0))
            ps.pose.position.z = 0.0
            yaw = float(d.get('yaw', 0.0))
            ps.pose.orientation.z = math.sin(yaw / 2.0)
            ps.pose.orientation.w = math.cos(yaw / 2.0)
            return ps
        except (TypeError, ValueError) as e:
            self.get_logger().warn(f'pose 파싱 실패: {e}')
            return None

    @staticmethod
    def _is_placeholder(d: dict) -> bool:
        return (float(d.get('x', 0.0)) == 0.0 and
                float(d.get('y', 0.0)) == 0.0 and
                float(d.get('yaw', 0.0)) == 0.0)

    # ───────── 진입 params_json 파싱 ─────────

    def _parse_first_waypoint(self, raw: str) -> str | None:
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warn(f'params_json 파싱 실패: {raw!r}')
            return None
        wp = obj.get('waypoint') if isinstance(obj, dict) else None
        if not wp:
            return None
        if wp not in self.tables:
            self.get_logger().warn(
                f'진입 waypoint {wp!r} 가 tables.yaml 에 없음 — 무시')
            return None
        return wp

    # ───────── /serving/goto_table 구독 ─────────

    def _on_goto_table(self, msg: String) -> None:
        tid = msg.data.strip()
        if not tid:
            return
        if tid not in self.tables:
            self.get_logger().warn(
                f'/serving/goto_table {tid!r} — tables.yaml 에 없음, 무시. '
                f'가용: {sorted(self.tables.keys())}')
            return
        self.queue.append(tid)
        self.get_logger().info(
            f'/serving/goto_table {tid!r} 큐 추가 (대기={len(self.queue)}, state={self.state.value})')

    # ───────── 메인 tick (5Hz) ─────────

    def _tick(self) -> None:
        if self.state == State.IDLE:
            if self.queue:
                self._start_next()
            return

        # 액션 진행 상태들 — last-resort 타임아웃 안전망
        if self.state in (State.DOCKING, State.UNDOCKING):
            self._check_timeout(self.dock_timeout)
            return

        if self.state in (State.NAVIGATING, State.RETURNING):
            self._check_timeout(self.nav_timeout)
            return

        if self.state == State.DWELL:
            elapsed = (self.get_clock().now().nanoseconds - self.dwell_start_ns) / 1e9
            if elapsed >= self.dwell_sec:
                self.get_logger().info(f'dwell {self.dwell_sec}s 종료 — 다음 액션')
                self._on_dwell_done()
            return

    def _check_timeout(self, limit: float) -> None:
        if self._action_started_ns is None:
            return
        elapsed = (self.get_clock().now().nanoseconds - self._action_started_ns) / 1e9
        if elapsed > limit:
            self.get_logger().warn(
                f'{self.state.value} 액션 타임아웃 ({elapsed:.1f}s > {limit}s) — cancel')
            self._cancel_active_goal()

    # ───────── 다음 테이블 시작 (도킹 or 레거시 nav) ─────────

    def _start_next(self) -> None:
        tid = self.queue.popleft()
        entry = self.tables.get(tid)
        if not entry:
            self.get_logger().warn(f'큐의 {tid!r} 가 tables 에 없음 — skip')
            return
        if entry['placeholder']:
            self.get_logger().error(
                f'테이블 {tid!r} 좌표 placeholder(0,0,0) — 거부. '
                'tables.yaml 에 RViz 등록 좌표 갱신 필요.')
            return
        self.current_table = tid
        if self.enable_docking:
            self._send_dock_goal(entry['pose'], tid)
        else:
            self._send_nav_goal(entry['pose'], context=f'table {tid}', state=State.NAVIGATING)

    # ───────── DockRobot ─────────

    def _send_dock_goal(self, pose: PoseStamped, tid: str) -> None:
        if not self._dock_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().error(
                f'docking_server 미응답 ({self.dock_action!r}) — table {tid} skip')
            self._reset_idle()
            return
        pose.header.stamp = self.get_clock().now().to_msg()
        goal = DockRobot.Goal()
        goal.use_dock_id = False
        goal.dock_pose = pose
        goal.dock_type = self.dock_type
        goal.navigate_to_staging_pose = True
        goal.max_staging_time = self.max_staging_time

        self.state = State.DOCKING
        self._action_started_ns = self.get_clock().now().nanoseconds
        send_future = self._dock_ac.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self.get_logger().info(
            f'dock goal 전송: table {tid} → dock_pose=({pose.pose.position.x:.2f}, '
            f'{pose.pose.position.y:.2f}) type={self.dock_type!r}')

    # ───────── UndockRobot ─────────

    def _start_undock(self) -> None:
        if not self._undock_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn(
                f'undock action 미응답 ({self.undock_action!r}) — undock skip, 다음 진행')
            self._proceed_next()
            return
        goal = UndockRobot.Goal()
        goal.dock_type = self.dock_type
        goal.max_undocking_time = self.max_undocking_time

        self.state = State.UNDOCKING
        self._action_started_ns = self.get_clock().now().nanoseconds
        send_future = self._undock_ac.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self.get_logger().info(f'undock goal 전송 (type={self.dock_type!r})')

    # ───────── NavigateToPose (레거시 table / home 복귀) ─────────

    def _start_home_return(self) -> None:
        self.current_table = HOME_TABLE_ID
        self._send_nav_goal(self.home_pose, context='home', state=State.RETURNING)

    def _send_nav_goal(self, pose: PoseStamped, context: str, state: State) -> None:
        pose.header.stamp = self.get_clock().now().to_msg()
        if not self._nav_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().error(
                f'Nav2 action server 미응답 ({self.nav_action!r}) — {context} skip')
            self._reset_idle()
            return
        goal = NavigateToPose.Goal()
        goal.pose = pose

        self.state = state
        self._action_started_ns = self.get_clock().now().nanoseconds
        send_future = self._nav_ac.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self.get_logger().info(
            f'nav goal 전송: {context} → ({pose.pose.position.x:.2f}, '
            f'{pose.pose.position.y:.2f})')

    # ───────── 공통 goal response / result 콜백 ─────────

    def _on_goal_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:
            self.get_logger().error(f'goal response 실패: {e}')
            self._on_action_finished(success=False)
            return
        if not handle.accepted:
            self.get_logger().warn(f'goal rejected ({self.state.value})')
            self._on_action_finished(success=False)
            return
        self._goal_handle = handle
        result_future = handle.get_result_async()
        result_future.add_done_callback(self._on_goal_result)

    def _on_goal_result(self, future) -> None:
        self._goal_handle = None
        try:
            wrapper = future.result()
            status = wrapper.status
            result = wrapper.result
        except Exception as e:
            self.get_logger().error(f'goal result 실패: {e}')
            self._on_action_finished(success=False)
            return
        # action_msgs/GoalStatus: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
        # Dock/Undock 결과엔 success 필드도 있음 — 둘 다 참이어야 성공.
        succeeded = (status == 4)
        if hasattr(result, 'success'):
            succeeded = succeeded and bool(result.success)
        err = getattr(result, 'error_code', None)
        self.get_logger().info(
            f'{self.state.value} 결과: status={status} '
            f'success={succeeded}' + (f' error_code={err}' if err else ''))
        self._on_action_finished(success=succeeded)

    def _on_action_finished(self, success: bool) -> None:
        self._action_started_ns = None
        st = self.state

        if st == State.DOCKING:
            if success:
                self._enter_dwell()
            else:
                # 도킹 실패 — undock 안 함(도킹 안 됨). drop 후 다음 진행.
                self.get_logger().warn(f'테이블 {self.current_table} 도킹 실패 — drop, 다음 진행')
                self._proceed_next()

        elif st == State.NAVIGATING:  # 레거시 (도킹 비활성)
            if success:
                self._enter_dwell()
            else:
                self.get_logger().warn(f'테이블 {self.current_table} nav 실패 — drop, 다음 진행')
                self._proceed_next()

        elif st == State.UNDOCKING:
            if not success:
                self.get_logger().warn('undock 실패 — 다음 진행 (Nav2 가 현 위치에서 replan)')
            self._proceed_next()

        elif st == State.RETURNING:
            if success:
                self.get_logger().info('home 복귀 성공 — idle')
            else:
                self.get_logger().warn('home 복귀 실패 — idle 강제')
            self._reset_idle()

        else:
            self._reset_idle()

    # ───────── dwell / 다음 전이 ─────────

    def _enter_dwell(self) -> None:
        self.state = State.DWELL
        self.dwell_start_ns = self.get_clock().now().nanoseconds
        self.get_logger().info(
            f'테이블 {self.current_table} 도착 — dwell {self.dwell_sec}s 시작')

    def _on_dwell_done(self) -> None:
        # 도킹 모드면 먼저 undock(staging 복귀) 후 다음 진행. 레거시면 바로 다음.
        if self.enable_docking and self.current_table not in (None, HOME_TABLE_ID):
            self._start_undock()
            return
        self._proceed_next()

    def _proceed_next(self) -> None:
        if self.queue:
            self._start_next()
            return
        if self.return_home and self.home_pose is not None:
            self._start_home_return()
            return
        self._reset_idle()
        self.get_logger().info('idle 진입 (큐 비었음)')

    def _reset_idle(self) -> None:
        self.state = State.IDLE
        self.current_table = None
        self._action_started_ns = None

    # ───────── cancel ─────────

    def _cancel_active_goal(self) -> None:
        if self._goal_handle is None:
            return
        try:
            self._goal_handle.cancel_goal_async()
            self.get_logger().info('active goal cancel 요청')
        except Exception as e:
            self.get_logger().warn(f'cancel 실패: {e}')

    # ───────── /serving/reload_tables 서비스 ─────────

    def _on_reload_tables(self, request, response):
        prev_home = self.home_pose
        prev_tables = dict(self.tables)
        self.home_pose = None
        self.tables = {}
        self._load_tables(self.tables_yaml)
        loaded = sorted(self.tables.keys())
        response.success = bool(loaded)
        if response.success:
            response.message = (
                f'tables.yaml reloaded — tables={loaded}, '
                f'home={"OK" if self.home_pose else "placeholder"}')
            self.get_logger().info(response.message)
        else:
            self.home_pose = prev_home
            self.tables = prev_tables
            response.message = 'reload 실패 — 이전 상태 복원'
            self.get_logger().error(response.message)
        return response

    # ───────── 상태 발행 ─────────

    def _publish_state(self) -> None:
        msg = String()
        msg.data = json.dumps({
            'state': self.state.value,
            'current_table': self.current_table,
            'queue': list(self.queue),
            'dwell_sec': self.dwell_sec,
            'return_home': self.return_home,
            'enable_docking': self.enable_docking,
            'home_registered': self.home_pose is not None,
        }, ensure_ascii=False)
        self._state_pub.publish(msg)

    # ───────── shutdown ─────────

    def on_shutdown(self) -> None:
        self._cancel_active_goal()


def main(args=None):
    rclpy.init(args=args)
    node = ServingDispatcher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.on_shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
