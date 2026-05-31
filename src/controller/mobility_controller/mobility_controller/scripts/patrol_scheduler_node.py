#!/usr/bin/env python3
"""patrol_scheduler_node — 순회(patrol) 모드 mobility orchestrator.

설계 SoT: docs/moca_patrol_design.md §2.

책임:
  - tables.yaml 의 sweep_order 를 순회하면서 각 테이블에 Nav2 NavigateToPose 송신
  - 도착 후 dwell N초 → table_occupancy_detector 에 ScanTable.srv 호출
  - TableReport 발행 + /patrol/state (1Hz) 발행
  - 사이클 종료 시 home_pose 복귀 후 DONE 상태 유지 (self-terminate X,
    task_orchestrator 가 /patrol/state="done" 관찰 후 SetMode('idle') 호출 → mode_manager SIGTERM)
  - /rapport/event abort_trigger 시 ABORTED 전이 + active Nav2 cancel

9-state FSM:
  INIT → NEXT ⇄ (MOVING → DWELL → SCAN → REPORT) → RETURNING → DONE
                                                    ↘ ABORTED

usage:
  ros2 run mobility_controller patrol_scheduler --ros-args -p tables_yaml:=/path
"""

import json
import math
import os
from enum import Enum
from typing import Optional

import rclpy
import yaml
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose

from dobi_npc_msgs.msg import PatrolState, RapportEvent, TableReport
from dobi_npc_msgs.srv import ScanTable


class State(str, Enum):
    INIT = 'init'
    NEXT = 'next'
    MOVING = 'moving'
    DWELL = 'dwell'
    SCAN = 'scan'
    REPORT = 'report'
    RETURNING = 'returning'
    DONE = 'done'
    ABORTED = 'aborted'


class PatrolScheduler(Node):
    """5-state FSM 의 patrol 모드 dispatcher."""

    def __init__(self):
        super().__init__('patrol_scheduler')

        # ---- 파라미터 (디자인 §2.1.1) ----
        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter(
            'sweep_order', ['T01', 'T02', 'T03', 'T04', 'T05'])
        self.declare_parameter('dwell_per_table_sec', 2.0)
        self.declare_parameter('arrival_timeout_sec', 30.0)
        self.declare_parameter('inter_table_timeout_sec', 60.0)
        self.declare_parameter('return_home_after_cycle', True)
        self.declare_parameter('report_to_orchestrator', True)
        self.declare_parameter('scan_service_name', '/table_occupancy/scan')
        self.declare_parameter('nav_action_name', '/navigate_to_pose')

        # ---- 내부 상태 ----
        self._state: State = State.INIT
        self._current_table_id: Optional[str] = None
        self._current_table_index = 0
        self._tables_visited = 0
        self._tables_total = 0
        self._started_at = self.get_clock().now()
        self._state_entered_at = self.get_clock().now()
        self._sweep_order: list[str] = []
        self._last_scan_result = None

        # Nav2 핸들 (active goal 추적)
        self._nav_goal_handle = None
        self._nav_result_future = None

        # ---- tables.yaml 로드 ----
        self._tables: dict[str, dict] = {}
        self._home_pose: Optional[PoseStamped] = None
        self._load_tables()

        # ---- ROS 인터페이스 ----
        self.pub_state = self.create_publisher(
            PatrolState, '/patrol/state', 10)
        self.pub_report = self.create_publisher(
            TableReport, '/patrol/table_report', 10)
        self.sub_rapport = self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)

        self.act_nav = ActionClient(
            self, NavigateToPose,
            self.get_parameter('nav_action_name').value)
        self.cli_scan = self.create_client(
            ScanTable, self.get_parameter('scan_service_name').value)

        # 1Hz state publish + 20Hz FSM tick (dwell/timeout 체크)
        self.create_timer(1.0, self._publish_state)
        self.create_timer(0.05, self._tick)

        self.get_logger().info(
            f'patrol_scheduler ready: sweep={self._sweep_order} '
            f'dwell={self.get_parameter("dwell_per_table_sec").value}s '
            f'arrival_timeout={self.get_parameter("arrival_timeout_sec").value}s')

        # INIT 의 entry action (tables 로드 완료) 직후 NEXT 로 전이
        self._transition(State.NEXT)

    # ─────────── tables.yaml ───────────

    def _load_tables(self) -> None:
        path = self.get_parameter('tables_yaml').value
        if not path or not os.path.isfile(path):
            self.get_logger().error(
                f'tables_yaml 파일 없음: {path!r} — patrol 진행 불가')
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
            self._home_pose = self._dict_to_pose(home)

        # tables
        for entry in data.get('tables', []):
            tid = entry.get('id')
            pose_d = entry.get('pose', {})
            if not tid or not pose_d:
                continue
            self._tables[tid] = {
                'id': tid,
                'pose_dict': pose_d,
                'approach_dist': float(entry.get('approach_dist', 0.5)),
                'description': entry.get('description', ''),
            }

        # sweep_order — params_json 우선 (task_orchestrator 가 priority_only 시 override)
        params_raw = self.get_parameter('params_json').value
        sweep_from_params: Optional[list[str]] = None
        sweep_mode = 'all'
        if params_raw:
            try:
                d = json.loads(params_raw)
                sweep_mode = d.get('sweep_mode', 'all')
                # 명시적 sweep_order override 도 지원 (M3 priority_only)
                if isinstance(d.get('sweep_order'), list):
                    sweep_from_params = [str(x) for x in d['sweep_order']]
            except json.JSONDecodeError as e:
                self.get_logger().warn(
                    f'params_json 파싱 실패: {e} — sweep_order param 사용')

        if sweep_from_params:
            self._sweep_order = sweep_from_params
        else:
            # ParameterValue 가 list 또는 tuple 반환 가능
            self._sweep_order = list(self.get_parameter('sweep_order').value)

        # tables.yaml 에 없는 ID 제거
        self._sweep_order = [
            tid for tid in self._sweep_order if tid in self._tables
        ]
        self._tables_total = len(self._sweep_order)

        self.get_logger().info(
            f'tables loaded: {sorted(self._tables.keys())} '
            f'home_pose={"OK" if self._home_pose else "MISSING"} '
            f'sweep_mode={sweep_mode} sweep={self._sweep_order}')

    def _dict_to_pose(self, d: dict) -> Optional[PoseStamped]:
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

    def _build_approach_pose(self, table: dict) -> Optional[PoseStamped]:
        """테이블 면에서 approach_dist 만큼 뒤에 정차할 PoseStamped."""
        pose_d = table['pose_dict']
        try:
            x = float(pose_d.get('x', 0.0))
            y = float(pose_d.get('y', 0.0))
            yaw = float(pose_d.get('yaw', 0.0))
        except (TypeError, ValueError):
            return None
        approach = float(table.get('approach_dist', 0.5))
        ps = PoseStamped()
        ps.header.frame_id = pose_d.get('frame_id', 'map')
        ps.header.stamp = self.get_clock().now().to_msg()
        # 테이블 yaw 방향(=정면) 반대 방향 backward
        ps.pose.position.x = x - approach * math.cos(yaw)
        ps.pose.position.y = y - approach * math.sin(yaw)
        ps.pose.orientation.z = math.sin(yaw / 2.0)
        ps.pose.orientation.w = math.cos(yaw / 2.0)
        return ps

    # ─────────── FSM ───────────

    def _transition(self, new_state: State) -> None:
        if new_state == self._state:
            return
        prev = self._state
        self._state = new_state
        self._state_entered_at = self.get_clock().now()
        self.get_logger().info(f'state: {prev.value} → {new_state.value}')

        # entry actions
        if new_state == State.NEXT:
            self._on_enter_next()
        elif new_state == State.MOVING:
            self._on_enter_moving()
        elif new_state == State.SCAN:
            self._on_enter_scan()
        elif new_state == State.REPORT:
            self._on_enter_report()
        elif new_state == State.RETURNING:
            self._on_enter_returning()
        elif new_state == State.DONE:
            self._on_enter_done()
        elif new_state == State.ABORTED:
            self._on_enter_aborted()
        # DWELL 은 _tick 에서 elapsed 만 체크

    def _on_enter_next(self) -> None:
        if self._current_table_index >= len(self._sweep_order):
            # sweep 소진
            if self.get_parameter('return_home_after_cycle').value and \
                    self._home_pose is not None:
                self._transition(State.RETURNING)
            else:
                self._transition(State.DONE)
            return
        self._current_table_id = self._sweep_order[self._current_table_index]
        self._current_table_index += 1
        self._transition(State.MOVING)

    def _on_enter_moving(self) -> None:
        table = self._tables.get(self._current_table_id)
        if table is None:
            self.get_logger().warn(
                f'unknown table {self._current_table_id} — skip')
            self._emit_report_unknown(error='unknown_table')
            self._transition(State.NEXT)
            return
        pose = self._build_approach_pose(table)
        if pose is None:
            self.get_logger().warn(
                f'invalid pose for {self._current_table_id} — skip')
            self._emit_report_unknown(error='invalid_pose')
            self._transition(State.NEXT)
            return
        self._send_nav_goal(pose, context=f'table {self._current_table_id}')

    def _on_enter_scan(self) -> None:
        if not self.cli_scan.wait_for_service(timeout_sec=2.0):
            self.get_logger().warn(
                'scan service unavailable — emit unknown + NEXT')
            self._last_scan_result = None
            self._transition(State.REPORT)
            return
        req = ScanTable.Request()
        req.table_id = self._current_table_id or ''
        future = self.cli_scan.call_async(req)
        future.add_done_callback(self._on_scan_done)

    def _on_scan_done(self, future) -> None:
        try:
            self._last_scan_result = future.result()
        except Exception as e:
            self.get_logger().warn(f'scan future error: {e}')
            self._last_scan_result = None
        # ROS callback thread 에서 transition 호출 — rclpy 가 직렬화 보장
        self._transition(State.REPORT)

    def _on_enter_report(self) -> None:
        msg = TableReport()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.table_id = self._current_table_id or ''
        r = self._last_scan_result
        if r is not None and getattr(r, 'success', False):
            msg.occupancy = r.occupancy
            msg.person_count = int(r.person_count)
            msg.dishes_detected = bool(r.dishes_detected)
            msg.confidence = float(r.confidence)
        else:
            msg.occupancy = 'unknown'
            msg.person_count = 0
            msg.dishes_detected = False
            msg.confidence = 0.0
        self.pub_report.publish(msg)
        self._tables_visited += 1
        self.get_logger().info(
            f'TableReport {msg.table_id} occupancy={msg.occupancy} '
            f'person={msg.person_count} conf={msg.confidence:.2f}')
        self._last_scan_result = None
        self._transition(State.NEXT)

    def _on_enter_returning(self) -> None:
        if self._home_pose is None:
            self.get_logger().warn('home_pose 없음 — DONE 직행')
            self._transition(State.DONE)
            return
        self._send_nav_goal(self._home_pose, context='home')

    def _on_enter_done(self) -> None:
        self.get_logger().info(
            f'patrol cycle DONE — visited={self._tables_visited}/{self._tables_total}. '
            f'task_orchestrator SetMode("idle") 대기.')
        # self-terminate X — /patrol/state="done" 계속 publish 하면서
        # task_orchestrator 가 SetMode('idle') 호출 → mode_manager SIGTERM

    def _on_enter_aborted(self) -> None:
        self.get_logger().warn(
            f'patrol ABORTED at table_index={self._current_table_index}/{self._tables_total}')
        self._cancel_nav()
        # DONE 과 동일하게 task_orchestrator 가 /patrol/state="aborted" 관찰 후 idle 전이

    # ─────────── Nav2 ───────────

    def _send_nav_goal(self, pose: PoseStamped, context: str) -> None:
        if not self.act_nav.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn(
                f'Nav2 action server 미응답 — {context} skip')
            if self._state == State.MOVING:
                self._emit_report_unknown(error='nav_server_unavailable')
                self._transition(State.NEXT)
            elif self._state == State.RETURNING:
                self._transition(State.DONE)
            return
        goal = NavigateToPose.Goal()
        goal.pose = pose
        self.get_logger().info(
            f'Nav2 send_goal {context}: '
            f'({pose.pose.position.x:.2f}, {pose.pose.position.y:.2f})')
        send_future = self.act_nav.send_goal_async(goal)
        send_future.add_done_callback(self._on_nav_accepted)

    def _on_nav_accepted(self, future) -> None:
        try:
            gh = future.result()
        except Exception as e:
            self.get_logger().warn(f'send_goal future error: {e}')
            self._handle_nav_failure()
            return
        if not gh.accepted:
            self.get_logger().warn('Nav2 goal rejected')
            self._handle_nav_failure()
            return
        self._nav_goal_handle = gh
        self._nav_result_future = gh.get_result_async()
        self._nav_result_future.add_done_callback(self._on_nav_result)

    def _on_nav_result(self, future) -> None:
        try:
            result = future.result()
            status = int(result.status)
        except Exception as e:
            self.get_logger().warn(f'get_result future error: {e}')
            status = 0
        # action_msgs/GoalStatus: SUCCEEDED=4, CANCELED=5, ABORTED=6
        self._nav_goal_handle = None
        if status == 4:
            if self._state == State.MOVING:
                self._transition(State.DWELL)
            elif self._state == State.RETURNING:
                self._transition(State.DONE)
        else:
            self.get_logger().warn(f'Nav2 result status={status}')
            self._handle_nav_failure()

    def _handle_nav_failure(self) -> None:
        if self._state == State.MOVING:
            self._emit_report_unknown(error='nav_failed')
            self._transition(State.NEXT)
        elif self._state == State.RETURNING:
            self._transition(State.DONE)

    def _cancel_nav(self) -> None:
        if self._nav_goal_handle is not None:
            try:
                self._nav_goal_handle.cancel_goal_async()
            except Exception as e:
                self.get_logger().warn(f'cancel_goal_async failed: {e}')
            self._nav_goal_handle = None

    # ─────────── 보조 ───────────

    def _emit_report_unknown(self, error: str = '') -> None:
        msg = TableReport()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.table_id = self._current_table_id or ''
        msg.occupancy = 'unknown'
        msg.person_count = 0
        msg.dishes_detected = False
        msg.confidence = 0.0
        self.pub_report.publish(msg)
        self._tables_visited += 1
        self.get_logger().info(
            f'TableReport {msg.table_id} occupancy=unknown reason={error}')

    def _on_rapport(self, msg: RapportEvent) -> None:
        if msg.event_type != 'abort_trigger':
            return
        if self._state in (State.DONE, State.ABORTED, State.INIT):
            return
        self.get_logger().warn(
            f'rapport abort_trigger weight={msg.weight:.2f} → ABORTED')
        self._transition(State.ABORTED)

    # ─────────── 타이머 ───────────

    def _tick(self) -> None:
        """20Hz FSM tick — dwell/timeout 만 체크 (Nav2/Scan 은 콜백 진행)."""
        now = self.get_clock().now()
        elapsed = (now - self._state_entered_at).nanoseconds / 1e9

        if self._state == State.DWELL:
            if elapsed >= float(
                    self.get_parameter('dwell_per_table_sec').value):
                self._transition(State.SCAN)

        elif self._state == State.MOVING:
            if elapsed >= float(
                    self.get_parameter('arrival_timeout_sec').value):
                self.get_logger().warn(
                    f'Nav2 timeout {self._current_table_id} '
                    f'(elapsed={elapsed:.1f}s) — cancel + skip')
                self._cancel_nav()
                self._emit_report_unknown(error='nav_timeout')
                self._transition(State.NEXT)

        elif self._state == State.SCAN:
            # scan 가드 — service 가 hang 한 경우 (5초 후 fallback)
            if elapsed >= 5.0 and self._last_scan_result is None:
                self.get_logger().warn(
                    'scan service hung 5s — REPORT unknown')
                self._transition(State.REPORT)

    def _publish_state(self) -> None:
        msg = PatrolState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.current_state = self._state.value
        msg.current_table = self._current_table_id or ''
        msg.tables_visited = self._tables_visited
        msg.tables_total = self._tables_total
        msg.progress = (
            self._tables_visited / self._tables_total
            if self._tables_total > 0 else 0.0
        )
        msg.started_at = self._started_at.to_msg()
        self.pub_state.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PatrolScheduler()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node._cancel_nav()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
