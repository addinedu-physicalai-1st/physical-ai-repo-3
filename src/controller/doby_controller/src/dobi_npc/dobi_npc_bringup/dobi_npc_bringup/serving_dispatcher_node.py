#!/usr/bin/env python3
"""
serving_dispatcher_node.py
mode_serving 메인 노드 — Nav2 단발 NavigateToPose + 다중경유 NavigateThroughPoses.

책임:
  - tables.yaml 로드 → 테이블 ID ↔ PoseStamped 매핑 (기존 단일 주행 경로, 하위호환)
  - waypoints_yaml (mapv6) 로드 → W## 웨이포인트 + routes(테이블별 outbound/return)
  - 큐 (FIFO) 관리: 진입 시 params_json 의 waypoint + /serving/goto_table 토픽 append
  - 명령 해석:
      "T02"        → routes[T02].outbound 를 NavigateThroughPoses 로 주행 → 마지막 WP 정차
      "T02:return" → routes[T02].return  을 NavigateThroughPoses 로 주행 → 마지막 WP 정차
      (routes 에 없는 ID → 기존 tables.yaml 단일 NavigateToPose + dwell + home 복귀)
  - /serving/state 1Hz 발행 (JSON)

경로(route) 흐름 (연동 테스트):
  - outbound/return 모두 "웨이포인트 시퀀스를 자율로 주행 → 마지막 WP 에서 정지".
  - 마지막 구간(테이블 접근 / 대기장소 복귀)과 관제서버 통신은 teleop + 수동 명령 (이번 스코프 밖).
  - 따라서 route 흐름은 dwell / 자동 home 복귀를 쓰지 않고 도착 즉시 idle.

mode_manager 와의 인터페이스:
  - launch param `params_json` 으로 첫 명령 (예: '{"waypoint": "T02"}')
  - 추가 명령은 /serving/goto_table 토픽 (mode 진입 후, 예: "T02:return")
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

from builtin_interfaces.msg import Time as TimeMsg, Duration as DurationMsg
from std_msgs.msg import String
from std_srvs.srv import Trigger
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose, NavigateThroughPoses, BackUp, Spin
from nav2_msgs.srv import ClearEntireCostmap
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener


class State(str, Enum):
    IDLE = 'idle'
    NAVIGATING = 'navigating'   # 단일 NavigateToPose (table 경로)
    ROUTING = 'routing'         # 다중경유 NavigateThroughPoses (route 경로)
    RECOVERING = 'recovering'   # 경로 실패 후 backup 리커버리 중
    FINALIZING = 'finalizing'   # route 경유 후 마지막 도착점 NavigateToPose (xy 근접)
    SPINNING = 'spinning'       # 마지막 도착점 yaw 정밀 정렬 (Spin 제자리 회전)
    DWELL = 'dwell'
    RETURNING = 'returning'


HOME_TABLE_ID = '__home__'  # 큐 sentinel — home 복귀 명령


class ServingDispatcher(Node):
    def __init__(self):
        super().__init__('serving_dispatcher')

        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('waypoints_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter('dwell_sec', 5.0)
        self.declare_parameter('return_home_after_dwell', True)
        self.declare_parameter('nav_action_name', 'navigate_to_pose')
        self.declare_parameter('ntp_action_name', 'navigate_through_poses')
        self.declare_parameter('nav_timeout_sec', 60.0)
        self.declare_parameter('route_timeout_sec', 180.0)
        self.declare_parameter('recovery_enabled', True)
        self.declare_parameter('recovery_backup_dist', 0.4)
        self.declare_parameter('recovery_backup_speed', 0.1)
        self.declare_parameter('route_max_retries', 1)
        self.declare_parameter('route_final_navigate_to_pose', True)
        self.declare_parameter('route_final_spin_align', True)

        self.tables_yaml = self.get_parameter('tables_yaml').value
        self.waypoints_yaml = self.get_parameter('waypoints_yaml').value
        self.params_json = self.get_parameter('params_json').value
        self.dwell_sec = float(self.get_parameter('dwell_sec').value)
        self.return_home = bool(self.get_parameter('return_home_after_dwell').value)
        self.nav_action = self.get_parameter('nav_action_name').value
        self.ntp_action = self.get_parameter('ntp_action_name').value
        self.nav_timeout = float(self.get_parameter('nav_timeout_sec').value)
        self.route_timeout = float(self.get_parameter('route_timeout_sec').value)
        self.recovery_enabled = bool(self.get_parameter('recovery_enabled').value)
        self.backup_dist = float(self.get_parameter('recovery_backup_dist').value)
        self.backup_speed = float(self.get_parameter('recovery_backup_speed').value)
        self.route_max_retries = int(self.get_parameter('route_max_retries').value)
        self.route_final_n2p = bool(self.get_parameter('route_final_navigate_to_pose').value)
        self.route_final_spin = bool(self.get_parameter('route_final_spin_align').value)

        # 설정 로드
        self.home_pose: PoseStamped | None = None
        self.tables: dict[str, dict] = {}      # id → {'pose': PoseStamped, ...}
        self.waypoints: dict[str, dict] = {}   # W## → {'pose': PoseStamped, 'placeholder': bool}
        self.routes: dict[str, dict] = {}      # T## → {'outbound': [W..], 'return': [W..]}
        self.home_poses: dict[str, PoseStamped] = {}  # home: 섹션 named pose (route 에서 ID 로 참조 가능)
        self._load_tables(self.tables_yaml)
        self._load_waypoints(self.waypoints_yaml)

        # 상태
        self.state: State = State.IDLE
        self.queue: deque[str] = deque()
        self.current_table: str | None = None
        self.dwell_start_ns: int | None = None
        self._goal_handle = None
        self._nav_started_ns: int | None = None

        # Action client (단일 + 다중경유 + backup 리커버리)
        self._ac = ActionClient(self, NavigateToPose, self.nav_action)
        self._ntp_ac = ActionClient(self, NavigateThroughPoses, self.ntp_action)
        self._backup_ac = ActionClient(self, BackUp, 'backup')
        self._spin_ac = ActionClient(self, Spin, 'spin')
        # 현재 로봇 yaw 조회용 TF (map→base_footprint) — 마지막 도착점 Spin 정렬 각 계산
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        # 코스트맵 clear 서비스 (리커버리 시 best-effort)
        self._clear_global_cli = self.create_client(
            ClearEntireCostmap, '/global_costmap/clear_entirely_global_costmap')
        self._clear_local_cli = self.create_client(
            ClearEntireCostmap, '/local_costmap/clear_entirely_local_costmap')
        # 리커버리 재시도 상태
        self._cur_route: tuple | None = None   # (route_id, leg, poses)
        self._route_retries = 0
        self._route_final_pose: PoseStamped | None = None  # route 마지막 도착점 (정밀 정렬용)

        # 토픽
        self.create_subscription(String, '/serving/goto_table', self._on_goto_table, 10)
        self._state_pub = self.create_publisher(String, '/serving/state', 10)

        # 서비스 — 설정 라이브 갱신 (운영 UI 좌표 등록 후 호출).
        self.create_service(Trigger, '/serving/reload_tables', self._on_reload_tables)

        # 진입 시 첫 명령 (params_json 의 waypoint)
        first_cmd = self._parse_first_waypoint(self.params_json)
        if first_cmd:
            self.queue.append(first_cmd)
            self.get_logger().info(f'진입 첫 명령 큐 추가: {first_cmd}')

        # 메인 tick + 상태 1Hz
        self.create_timer(0.2, self._tick)
        self.create_timer(1.0, self._publish_state)

        self.get_logger().info(
            f'serving_dispatcher start — tables={list(self.tables.keys())} '
            f'routes={list(self.routes.keys())} waypoints={len(self.waypoints)} '
            f'dwell={self.dwell_sec}s return_home={self.return_home}')

    # ───────── tables.yaml 로드 (단일 주행 경로, 하위호환) ─────────

    def _load_tables(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            if path:
                self.get_logger().warn(f'tables_yaml 파일 없음: {path!r}')
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

    # ───────── waypoints_yaml 로드 (mapv6 웨이포인트 + routes) ─────────

    def _load_waypoints(self, path: str) -> None:
        if not path:
            return
        if not os.path.isfile(path):
            self.get_logger().warn(
                f'waypoints_yaml 파일 없음: {path!r} — 경로(route) 추종 비활성')
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.get_logger().error(f'waypoints_yaml 파싱 실패: {e}')
            return

        # waypoints: W## → pose
        for wid, d in (data.get('waypoints') or {}).items():
            if not isinstance(d, dict):
                continue
            ps = self._dict_to_pose(d)
            if ps:
                self.waypoints[wid] = {
                    'pose': ps, 'placeholder': self._is_placeholder(d)}

        # home (mapv6) — named pose. route 시퀀스에서 ID 로 참조 가능 (예: return [..., HOME]).
        # 첫 항목은 table 자동 복귀용 home_pose fallback 으로도 설정.
        for hid, d in (data.get('home') or {}).items():
            if not isinstance(d, dict) or self._is_placeholder(d):
                continue
            ps = self._dict_to_pose(d)
            if not ps:
                continue
            self.home_poses[hid] = ps
            if self.home_pose is None:
                self.home_pose = ps

        # routes: T## → {'outbound': [..], 'return': [..]}
        for rid, legs in (data.get('routes') or {}).items():
            if not isinstance(legs, dict):
                continue
            self.routes[rid] = {
                'outbound': list(legs.get('outbound') or []),
                'return': list(legs.get('return') or []),
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

    # ───────── 명령 파싱 ─────────

    def _parse_route_command(self, cmd: str) -> tuple[str | None, str | None]:
        """'T02' → ('T02','outbound'); 'T02:return' → ('T02','return').
        leg 미지정 = outbound. 알 수 없는 leg = (None, None).
        """
        cmd = cmd.strip()
        if ':' in cmd:
            base, _, leg = cmd.partition(':')
            base = base.strip()
            leg = leg.strip().lower()
            if leg in ('return', 'ret', 'back', 'home'):
                return base, 'return'
            if leg in ('outbound', 'out', 'fwd', 'forward', 'go'):
                return base, 'outbound'
            return None, None
        return cmd, 'outbound'

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
        base, _leg = self._parse_route_command(wp)
        if base in self.routes or wp in self.tables:
            return wp
        self.get_logger().warn(
            f'진입 waypoint {wp!r} 가 routes/tables 에 없음 — 무시')
        return None

    # ───────── /serving/goto_table 구독 ─────────

    def _on_goto_table(self, msg: String) -> None:
        cmd = msg.data.strip()
        if not cmd:
            return
        base, leg = self._parse_route_command(cmd)
        if base in self.routes:
            self.queue.append(cmd)
            self.get_logger().info(
                f'/serving/goto_table {cmd!r} (route {base}:{leg}) 큐 추가 '
                f'(대기={len(self.queue)}, state={self.state.value})')
            return
        if cmd in self.tables:
            self.queue.append(cmd)
            self.get_logger().info(
                f'/serving/goto_table {cmd!r} (table) 큐 추가 '
                f'(대기={len(self.queue)}, state={self.state.value})')
            return
        self.get_logger().warn(
            f'/serving/goto_table {cmd!r} — routes/tables 어디에도 없음, 무시. '
            f'routes={sorted(self.routes.keys())} tables={sorted(self.tables.keys())}')

    # ───────── 메인 tick (5Hz) ─────────

    def _tick(self) -> None:
        if self.state == State.IDLE:
            if self.queue:
                self._start_next_nav()
            return

        if self.state in (State.NAVIGATING, State.ROUTING, State.RETURNING, State.FINALIZING, State.SPINNING):
            if self._nav_started_ns is not None:
                elapsed = (self.get_clock().now().nanoseconds - self._nav_started_ns) / 1e9
                limit = self.route_timeout if self.state == State.ROUTING else self.nav_timeout
                if elapsed > limit:
                    self.get_logger().warn(
                        f'{self.state.value} timeout ({elapsed:.1f}s > {limit}s) — cancel')
                    self._cancel_active_goal()
            return

        if self.state == State.DWELL:
            elapsed = (self.get_clock().now().nanoseconds - self.dwell_start_ns) / 1e9
            if elapsed >= self.dwell_sec:
                self.get_logger().info(f'dwell {self.dwell_sec}s 종료 — 다음 액션')
                self._after_dwell()
            return

    def _after_dwell(self) -> None:
        # 큐에 남은 명령 있으면 우선 진행, 없으면 home 복귀 (옵션)
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
        cmd = self.queue.popleft()
        base, leg = self._parse_route_command(cmd)

        # route 경로 (다중경유) 우선
        if base in self.routes:
            self._start_route(base, leg)
            return

        # 기존 table 경로 (단일 NavigateToPose + dwell + home 복귀) — 하위호환
        entry = self.tables.get(cmd)
        if not entry:
            self.get_logger().warn(f'큐의 {cmd!r} 가 routes/tables 에 없음 — skip')
            return
        if entry['placeholder']:
            self.get_logger().error(
                f'테이블 {cmd!r} 좌표 placeholder(0,0,0) — nav 거부. '
                'tables.yaml 에 RViz 등록 좌표 갱신 필요.')
            return
        self.current_table = cmd
        self._send_nav_goal(entry['pose'], context=f'table {cmd}')
        self.state = State.NAVIGATING

    def _start_route(self, route_id: str, leg: str) -> None:
        route = self.routes.get(route_id, {})
        wp_ids = list(route.get(leg) or [])
        if not wp_ids:
            self.get_logger().warn(
                f'경로 {route_id}:{leg} 경유 웨이포인트 없음 — 자율 주행 생략 '
                f'(teleop 구간). idle 유지')
            self.state = State.IDLE
            self.current_table = None
            return

        poses, missing = [], []
        for wid in wp_ids:
            wp = self.waypoints.get(wid)
            if wp is not None and not wp['placeholder']:
                poses.append(wp['pose'])
            elif wid in self.home_poses:          # home: 섹션 이름(HOME 등)도 경유점으로 허용
                poses.append(self.home_poses[wid])
            else:
                missing.append(wid)
        if missing:
            self.get_logger().error(
                f'경로 {route_id}:{leg} 웨이포인트 누락/placeholder {missing} — 주행 거부. '
                f'가용 WP={sorted(self.waypoints.keys())}')
            self.state = State.IDLE
            self.current_table = None
            return

        self.current_table = f'{route_id}:{leg}'
        self._cur_route = (route_id, leg, poses)
        self._route_retries = 0
        self._route_final_pose = poses[-1]   # 마지막 도착점 — NTP 후 NavigateToPose 로 정밀 정렬
        self._send_through_poses(
            poses, context=f'{route_id}:{leg} [{" → ".join(wp_ids)}]')
        self.state = State.ROUTING

    def _start_home_return(self) -> None:
        self.current_table = HOME_TABLE_ID
        self._send_nav_goal(self.home_pose, context='home')
        self.state = State.RETURNING

    # ───────── 마지막 도착점 yaw 정밀 정렬 (Spin 제자리 회전) ─────────

    @staticmethod
    def _yaw_from_quat(q) -> float:
        return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                          1.0 - 2.0 * (q.y * q.y + q.z * q.z))

    def _current_robot_yaw(self) -> float | None:
        # map→base_footprint TF 에서 현재 heading. Time() = 최신 TF (시계 skew 회피).
        try:
            t = self._tf_buffer.lookup_transform('map', 'base_footprint', Time())
            return self._yaw_from_quat(t.transform.rotation)
        except Exception as e:
            self.get_logger().warn(f'[spin] map→base_footprint TF 조회 실패: {e}')
            return None

    def _start_final_spin(self) -> None:
        # 목표 yaw(절대) - 현재 yaw → 상대 회전각을 Spin 으로 제자리 정렬.
        target_yaw = self._yaw_from_quat(self._route_final_pose.pose.orientation)
        cur = self._current_robot_yaw()
        if cur is None:
            self.get_logger().warn('[spin] 현재 yaw 미상 — yaw 정렬 생략')
            self._finish_route()
            return
        rel = (target_yaw - cur + math.pi) % (2.0 * math.pi) - math.pi
        if abs(rel) < 0.02:   # ~1.1° 이내면 이미 정렬됨
            self.get_logger().info(
                f'[spin] 이미 정렬 (잔차 {math.degrees(abs(rel)):.1f}°) — 생략')
            self._finish_route()
            return
        if not self._spin_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn('[spin] spin action server 미응답 — yaw 정렬 생략')
            self._finish_route()
            return
        goal = Spin.Goal()
        goal.target_yaw = float(rel)
        goal.time_allowance = DurationMsg(sec=15)
        self.get_logger().info(
            f'[spin] yaw 정렬: 제자리 {math.degrees(rel):+.1f}° 회전 '
            f'(현재 {math.degrees(cur):.1f}° → 목표 {math.degrees(target_yaw):.1f}°)')
        sf = self._spin_ac.send_goal_async(goal)
        sf.add_done_callback(self._on_spin_response)
        self._nav_started_ns = self.get_clock().now().nanoseconds
        self.state = State.SPINNING

    def _on_spin_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:
            self.get_logger().warn(f'[spin] response 실패: {e}')
            self._finish_route()
            return
        if not handle.accepted:
            self.get_logger().warn('[spin] goal rejected — yaw 정렬 생략')
            self._finish_route()
            return
        self._goal_handle = handle
        handle.get_result_async().add_done_callback(self._on_spin_result)

    def _on_spin_result(self, future) -> None:
        self._goal_handle = None
        self._nav_started_ns = None
        try:
            status = future.result().status
            self.get_logger().info(f'[spin] 결과 status={status} (4=SUCCEEDED)')
        except Exception as e:
            self.get_logger().warn(f'[spin] result 실패: {e}')
        self._finish_route()

    def _finish_route(self) -> None:
        self.get_logger().info(
            f'경로 {self.current_table} 완료 — 마지막 웨이포인트 정밀 정차(yaw 정렬). '
            f'teleop 인계 대기 (idle)')
        self.state = State.IDLE
        self.current_table = None
        self._cur_route = None
        self._route_final_pose = None

    def _send_nav_goal(self, pose: PoseStamped, context: str) -> None:
        # stamp 0 = 최신 TF 사용 (sim/실물 시계 skew 의 extrapolation abort 회피)
        pose.header.stamp = TimeMsg()

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

    def _send_through_poses(self, poses: list[PoseStamped], context: str) -> None:
        # stamp 0 = 최신 TF 사용 (시계 skew extrapolation abort 회피)
        for p in poses:
            p.header.stamp = TimeMsg()

        if not self._ntp_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().error(
                f'Nav2 action server 미응답 ({self.ntp_action!r}) — route {context} skip')
            self.state = State.IDLE
            self.current_table = None
            return

        goal = NavigateThroughPoses.Goal()
        goal.poses = poses

        send_future = self._ntp_ac.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self._nav_started_ns = self.get_clock().now().nanoseconds
        self.get_logger().info(
            f'route goal 전송 ({len(poses)}개 경유): {context}')

    # ───────── goal 콜백 (단일/다중경유 공용 — GoalStatus 동일) ─────────

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
                self.get_logger().warn(
                    f'테이블 {self.current_table} nav 실패 — drop, 다음 액션')
                self._after_dwell()
        elif self.state == State.ROUTING:
            if success:
                if self.route_final_n2p and self._route_final_pose is not None:
                    self.get_logger().info(
                        f'경로 {self.current_table} 경유 완료 — 마지막 도착점 '
                        f'NavigateToPose 정밀 정렬')
                    self._send_nav_goal(
                        self._route_final_pose, context=f'{self.current_table} final')
                    self.state = State.FINALIZING
                else:
                    self.get_logger().info(
                        f'경로 {self.current_table} 완료 — 마지막 웨이포인트 정차. '
                        f'teleop 인계 대기 (idle)')
                    self.state = State.IDLE
                    self.current_table = None
                    self._cur_route = None
                    self._route_final_pose = None
            elif (self.recovery_enabled and self._cur_route is not None
                  and self._route_retries < self.route_max_retries):
                self._route_retries += 1
                self.get_logger().warn(
                    f'경로 {self.current_table} 실패 — 리커버리 '
                    f'{self._route_retries}/{self.route_max_retries} '
                    f'(backup {self.backup_dist}m + 코스트맵 clear 후 재시도)')
                self._start_recovery()
            else:
                self.get_logger().warn(
                    f'경로 {self.current_table} 실패 — 리커버리 소진/비활성, 포기 (idle)')
                self.state = State.IDLE
                self.current_table = None
                self._cur_route = None
                self._route_final_pose = None
        elif self.state == State.FINALIZING:
            # route 경유 후 NavigateToPose(xy 근접) 결과 → yaw 정밀 정렬(Spin) 단계로
            if success and self.route_final_spin and self._route_final_pose is not None:
                self._start_final_spin()
            else:
                if not success:
                    self.get_logger().warn(
                        f'경로 {self.current_table} 마지막 xy 정렬 실패 — yaw 정렬 생략')
                self._finish_route()
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

    # ───────── 리커버리 (backup + 코스트맵 clear + 경로 재시도) ─────────

    def _start_recovery(self) -> None:
        self.state = State.RECOVERING
        if not self._backup_ac.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn(
                '[recovery] backup action server 미응답 — 코스트맵 clear 후 바로 재시도')
            self._after_recovery()
            return
        goal = BackUp.Goal()
        goal.target.x = float(self.backup_dist)   # behavior 가 |x| 만큼 후진
        goal.speed = float(self.backup_speed)
        goal.time_allowance = DurationMsg(sec=15)
        self.get_logger().info(
            f'[recovery] backup {self.backup_dist}m @ {self.backup_speed}m/s 전송')
        sf = self._backup_ac.send_goal_async(goal)
        sf.add_done_callback(self._on_backup_response)

    def _on_backup_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:
            self.get_logger().warn(f'[recovery] backup response 실패: {e}')
            self._after_recovery()
            return
        if not handle.accepted:
            self.get_logger().warn('[recovery] backup rejected — 바로 재시도')
            self._after_recovery()
            return
        self._goal_handle = handle
        handle.get_result_async().add_done_callback(self._on_backup_result)

    def _on_backup_result(self, future) -> None:
        self._goal_handle = None
        try:
            status = future.result().status
            self.get_logger().info(
                f'[recovery] backup 결과 status={status} (4=SUCCEEDED)')
        except Exception as e:
            self.get_logger().warn(f'[recovery] backup result 실패: {e}')
        self._after_recovery()

    def _after_recovery(self) -> None:
        self._clear_costmaps()
        if self._cur_route is None:
            self.state = State.IDLE
            self.current_table = None
            return
        route_id, leg, poses = self._cur_route
        self.get_logger().info(
            f'[recovery] 코스트맵 clear + 경로 {route_id}:{leg} 재시도 '
            f'({self._route_retries}/{self.route_max_retries})')
        self.current_table = f'{route_id}:{leg}'
        self._send_through_poses(
            list(poses), context=f'{route_id}:{leg} (retry {self._route_retries})')
        self.state = State.ROUTING

    def _clear_costmaps(self) -> None:
        for cli in (self._clear_global_cli, self._clear_local_cli):
            try:
                if cli.service_is_ready():
                    cli.call_async(ClearEntireCostmap.Request())
            except Exception as e:
                self.get_logger().warn(f'[recovery] 코스트맵 clear 실패: {e}')

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
        prev = (self.home_pose, dict(self.home_poses), dict(self.tables),
                dict(self.waypoints), dict(self.routes))
        self.home_pose = None
        self.home_poses = {}
        self.tables = {}
        self.waypoints = {}
        self.routes = {}
        self._load_tables(self.tables_yaml)
        self._load_waypoints(self.waypoints_yaml)
        loaded = sorted(self.tables.keys())
        routes = sorted(self.routes.keys())
        response.success = bool(loaded or routes)
        if response.success:
            response.message = (
                f'reloaded — tables={loaded}, routes={routes}, '
                f'waypoints={len(self.waypoints)}, '
                f'home={"OK" if self.home_pose else "placeholder"}')
            self.get_logger().info(response.message)
        else:
            # 실패 — 이전 상태 복원 (안전)
            (self.home_pose, self.home_poses, self.tables, self.waypoints, self.routes) = prev
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
            'routes': sorted(self.routes.keys()),
            'waypoints': sorted(self.waypoints.keys()),
            'route_retries': self._route_retries,
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
