#!/usr/bin/env python3
"""
serving_dispatcher_node.py
mode_serving 메인 노드 — Nav2 NavigateToPose 단발 반복 + 큐 + dwell + home 복귀.

책임 (Phase S-A):
  - tables.yaml 로드 → 테이블 ID ↔ PoseStamped 매핑
  - 큐 (FIFO) 관리: 진입 시 params_json 의 waypoint + /serving/goto_table 토픽 append
  - Nav2 NavigateToPose action 호출 → 도착 → dwell N초 → home_pose 복귀 → idle 대기
  - /serving/state 1Hz 발행 (JSON)

S-B 후속 (큐 hook 자리만 비워둠):
  - /serving/empty_tables 중앙 서버 push
  - /serving/clear_queue 서비스
  - 우선순위 큐 (manual override)

mode_manager 와의 인터페이스:
  - launch param `params_json` 으로 첫 명령 (예: '{"waypoint": "T01"}')
  - 추가 명령은 /serving/goto_table 토픽 (mode 진입 후)
  - mode_manager 가 SIGTERM 던지면 active goal cancel + cleanup

안전:
  - cmd_vel 직접 발행 X — Nav2 가 발행 → Phase B pipeline (twist_mux + smoother +
    collision_monitor) 가 OS 레벨 차단/감속. dispatcher 무신경.
  - placeholder 좌표 (모두 0) 감지 시 nav 거부 + ERROR log (위험 회피).

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
from nav2_msgs.action import NavigateToPose


class State(str, Enum):
    IDLE = 'idle'
    NAVIGATING = 'navigating'
    DWELL = 'dwell'
    RETURNING = 'returning'


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

        self.tables_yaml = self.get_parameter('tables_yaml').value
        self.params_json = self.get_parameter('params_json').value
        self.dwell_sec = float(self.get_parameter('dwell_sec').value)
        self.return_home = bool(self.get_parameter('return_home_after_dwell').value)
        self.nav_action = self.get_parameter('nav_action_name').value
        self.nav_timeout = float(self.get_parameter('nav_timeout_sec').value)

        # tables.yaml 로드
        self.home_pose: PoseStamped | None = None
        self.tables: dict[str, dict] = {}  # id → {'pose': PoseStamped, 'meta': {...}}
        self._load_tables(self.tables_yaml)

        # 상태
        self.state: State = State.IDLE
        self.queue: deque[str] = deque()
        self.current_table: str | None = None
        self.dwell_start_ns: int | None = None
        self._goal_handle = None
        self._nav_started_ns: int | None = None

        # Action client
        self._ac = ActionClient(self, NavigateToPose, self.nav_action)

        # 토픽
        self.create_subscription(String, '/serving/goto_table', self._on_goto_table, 10)
        self._state_pub = self.create_publisher(String, '/serving/state', 10)

        # 서비스 — tables.yaml 라이브 갱신 (운영 UI 좌표 등록 후 호출).
        # 큐 + 진행 중 nav 보존, home_pose + tables 만 다시 로드.
        self.create_service(Trigger, '/serving/reload_tables', self._on_reload_tables)

        # 진입 시 첫 명령 (params_json 의 waypoint)
        first_table = self._parse_first_waypoint(self.params_json)
        if first_table:
            self.queue.append(first_table)
            self.get_logger().info(f'진입 첫 명령 큐 추가: {first_table}')

        # 메인 tick
        self.create_timer(0.2, self._tick)
        # 상태 1Hz
        self.create_timer(1.0, self._publish_state)

        self.get_logger().info(
            f'serving_dispatcher start — tables={list(self.tables.keys())} '
            f'dwell={self.dwell_sec}s return_home={self.return_home}')

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
                self._start_next_nav()
            return

        if self.state == State.NAVIGATING:
            # nav_timeout 체크
            if self._nav_started_ns is not None:
                elapsed = (self.get_clock().now().nanoseconds - self._nav_started_ns) / 1e9
                if elapsed > self.nav_timeout:
                    self.get_logger().warn(
                        f'nav timeout ({elapsed:.1f}s > {self.nav_timeout}s) — cancel')
                    self._cancel_active_goal()
            return

        if self.state == State.DWELL:
            elapsed = (self.get_clock().now().nanoseconds - self.dwell_start_ns) / 1e9
            if elapsed >= self.dwell_sec:
                self.get_logger().info(f'dwell {self.dwell_sec}s 종료 — 다음 액션')
                self._after_dwell()
            return

        if self.state == State.RETURNING:
            # nav_timeout 동일 체크
            if self._nav_started_ns is not None:
                elapsed = (self.get_clock().now().nanoseconds - self._nav_started_ns) / 1e9
                if elapsed > self.nav_timeout:
                    self.get_logger().warn(f'home 복귀 timeout — cancel')
                    self._cancel_active_goal()
            return

    def _after_dwell(self) -> None:
        # 큐에 남은 테이블 있으면 우선 진행, 없으면 home 복귀 (옵션)
        if self.queue:
            self._start_next_nav()
            return
        if self.return_home and self.home_pose is not None:
            self._start_home_return()
            return
        self.state = State.IDLE
        self.current_table = None
        self.get_logger().info('idle 진입 (큐 비었음, home 복귀 비활성)')

    # ───────── nav 시작 ─────────

    def _start_next_nav(self) -> None:
        tid = self.queue.popleft()
        entry = self.tables.get(tid)
        if not entry:
            self.get_logger().warn(f'큐의 {tid!r} 가 tables 에 없음 — skip')
            return
        if entry['placeholder']:
            self.get_logger().error(
                f'테이블 {tid!r} 좌표 placeholder(0,0,0) — nav 거부. '
                'tables.yaml 에 RViz 등록 좌표 갱신 필요.')
            return
        self.current_table = tid
        self._send_nav_goal(entry['pose'], context=f'table {tid}')
        self.state = State.NAVIGATING

    def _start_home_return(self) -> None:
        self.current_table = HOME_TABLE_ID
        self._send_nav_goal(self.home_pose, context='home')
        self.state = State.RETURNING

    def _send_nav_goal(self, pose: PoseStamped, context: str) -> None:
        # 매 호출 시 stamp 갱신 (Nav2 가 fresh stamp 선호)
        pose.header.stamp = self.get_clock().now().to_msg()

        if not self._ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().error(
                f'Nav2 action server 미응답 ({self.nav_action!r}) — {context} skip')
            self.state = State.IDLE
            self.current_table = None
            return

        goal = NavigateToPose.Goal()
        goal.pose = pose

        send_future = self._ac.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self._nav_started_ns = self.get_clock().now().nanoseconds
        self.get_logger().info(
            f'nav goal 전송: {context} → ({pose.pose.position.x:.2f}, '
            f'{pose.pose.position.y:.2f})')

    def _on_goal_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:
            self.get_logger().error(f'goal response 실패: {e}')
            self._on_nav_finished(success=False)
            return
        if not handle.accepted:
            self.get_logger().warn('nav goal rejected by Nav2')
            self._on_nav_finished(success=False)
            return
        self._goal_handle = handle
        result_future = handle.get_result_async()
        result_future.add_done_callback(self._on_goal_result)

    def _on_goal_result(self, future) -> None:
        self._goal_handle = None
        try:
            result = future.result()
            status = result.status
        except Exception as e:
            self.get_logger().error(f'goal result 실패: {e}')
            self._on_nav_finished(success=False)
            return
        # action_msgs/GoalStatus: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
        success = (status == 4)
        self.get_logger().info(
            f'nav 결과: status={status} (4=SUCCEEDED, 5=CANCELED, 6=ABORTED) '
            f'success={success}')
        self._on_nav_finished(success=success)

    def _on_nav_finished(self, success: bool) -> None:
        self._nav_started_ns = None
        if self.state == State.NAVIGATING:
            if success:
                self.state = State.DWELL
                self.dwell_start_ns = self.get_clock().now().nanoseconds
                self.get_logger().info(
                    f'테이블 {self.current_table} 도착 — dwell {self.dwell_sec}s 시작')
            else:
                # nav 실패 시 해당 테이블 drop + 다음 큐 또는 home
                self.get_logger().warn(
                    f'테이블 {self.current_table} nav 실패 — drop, 다음 액션')
                self._after_dwell()
        elif self.state == State.RETURNING:
            if success:
                self.get_logger().info('home 복귀 성공 — idle')
            else:
                self.get_logger().warn('home 복귀 실패 — idle 강제')
            self.state = State.IDLE
            self.current_table = None
        else:
            # 예상치 못한 state — 안전하게 idle
            self.state = State.IDLE
            self.current_table = None

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
            # 실패 — 이전 상태 복원 (안전)
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
