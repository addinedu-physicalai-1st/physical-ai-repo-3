#!/usr/bin/env python3
"""guiding_controller_node — 동행 안내(guiding) 모드 supervised controller.

설계 SoT: docs/moca_guiding_design.md §2.

책임:
  - target_table + customer_id JSON params 파싱 + 검증
  - 7-state FSM: INIT → LOCK_ON → MOVING ⇄ WAITING → ARRIVED → DONE (+ ABORTED)
  - 카운터 앞에서 customer person bbox lock-on (10s timeout)
  - Nav2 NavigateToPose 로 target_table 진행 + 카메라로 customer 추적
  - customer lag > 1.5m → WAITING (Nav2 cancel + "천천히 따라오세요" 발화)
  - customer lag < 1.0m → MOVING 재개 (Nav2 재송신)
  - customer 시야 8s 무검출 → ABORTED ("어디 가셨어요" 발화)
  - 도착 후 5s dwell → DONE (OpServer SetMode('idle') 대기, patrol 과 동일 패턴)

follow_controller 와 알고리즘 정반대 (follow=주인 추적 reactive, guiding=로봇 앞장 supervised).
코드 재사용 < 30% — 별도 신규 노드 (디자인 §1).

usage:
  ros2 run dobi_npc_bringup guiding_controller --ros-args \\
    -p tables_yaml:=/path -p params_json:='{"target_table":"T02","customer_id":"C-001"}'
"""

import json
import math
import os
from enum import Enum
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav2_msgs.action import NavigateToPose
from vision_msgs.msg import Detection2DArray

from dobi_npc_msgs.msg import GuidingState, RapportEvent, UtterRequest


class State(str, Enum):
    INIT = 'init'
    LOCK_ON = 'lock_on'
    MOVING = 'moving'
    WAITING = 'waiting'
    ARRIVED = 'arrived'
    DONE = 'done'
    ABORTED = 'aborted'


# 디자인 §5.3 → CLAUDE.md §4.2 face 8 어휘 매핑
# (CLAUDE.md 자산 우선 — emotion/*.gif: basic/hello/happy/fun/interest/bored/sad/angry)
FACE_BY_STATE = {
    State.INIT:    'basic',
    State.LOCK_ON: 'basic',
    State.MOVING:  'happy',
    State.WAITING: 'interest',   # confused → interest (호기심 / 주의 환기)
    State.ARRIVED: 'happy',
    State.DONE:    'happy',
    State.ABORTED: 'sad',
}

# UtterRequest.priority — 낮을수록 우선 (UtterRequest.msg 정책)
#   0=safety / 10=operator / 20=serving / 25=guiding(본 모드) / 30=npc / 255=lowest
GUIDING_UTTER_PRIORITY_NORMAL = 25
GUIDING_UTTER_PRIORITY_URGENT = 15   # ABORTED 같은 긴급 발화 (operator 다음)


class GuidingController(Node):
    """7-state FSM 로 guiding 모드 운용."""

    def __init__(self):
        super().__init__('guiding_controller')

        # ---- 파라미터 (디자인 §2.1.1) ----
        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter('persons_topic', '/robot_cam/persons')
        self.declare_parameter('lock_on_timeout_sec', 10.0)
        self.declare_parameter('lag_distance_max_m', 1.5)
        self.declare_parameter('lag_distance_min_m', 1.0)
        self.declare_parameter('customer_lost_timeout_sec', 8.0)
        self.declare_parameter('arrival_dwell_sec', 5.0)
        self.declare_parameter('utter_cooldown_sec', 5.0)
        self.declare_parameter('nav_overall_timeout_sec', 90.0)
        self.declare_parameter('nav_action_name', '/navigate_to_pose')

        # ---- 내부 상태 ----
        self._state: State = State.INIT
        self._state_entered_at = self.get_clock().now()
        self._started_at = self.get_clock().now()

        self._target_table_id: Optional[str] = None
        self._customer_id: str = ''
        self._target_pose: Optional[PoseStamped] = None

        # customer 추적
        self._customer_xy: Optional[Tuple[float, float]] = None
        self._last_seen_at: Optional[rclpy.time.Time] = None
        self._customer_in_sight = False
        self._image_w: int = 640    # ground projection 휴리스틱 (M2 placeholder)
        self._image_h: int = 480

        # 로봇 pose
        self._robot_pose: Optional[Tuple[float, float, float]] = None  # (x, y, yaw)

        # Nav2
        self._nav_goal_handle = None
        self._nav_result_future = None

        # utter 쿨다운 — text → 마지막 발행 Time
        self._last_utter_at: dict = {}
        self._last_utter_text = ''

        # ---- tables.yaml + params 파싱 ----
        self._tables: dict = {}
        self._load_tables()
        self._parse_params()
        if self._target_table_id is None or self._target_table_id not in self._tables:
            self.get_logger().error(
                f'invalid target_table={self._target_table_id!r} '
                f'in params — available: {sorted(self._tables.keys())}. '
                'Will publish state="aborted" and wait for SetMode("idle").')
            # ABORTED 상태에서 종료 — params/table 미검증
            self._target_table_id = self._target_table_id or ''

        # ---- ROS 인터페이스 ----
        self.pub_state = self.create_publisher(
            GuidingState, '/guiding/state', 10)
        self.pub_utter = self.create_publisher(
            UtterRequest, '/utter/request', 10)
        self.sub_persons = self.create_subscription(
            Detection2DArray,
            str(self.get_parameter('persons_topic').value),
            self._on_persons, 10)
        self.sub_odom = self.create_subscription(
            Odometry, '/odom', self._on_odom, 10)
        self.sub_rapport = self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)

        self.act_nav = ActionClient(
            self, NavigateToPose,
            str(self.get_parameter('nav_action_name').value))

        # 1Hz state publish + 20Hz FSM tick
        self.create_timer(1.0, self._publish_state)
        self.create_timer(0.05, self._tick)

        self.get_logger().info(
            f'guiding_controller ready: target_table={self._target_table_id!r} '
            f'customer_id={self._customer_id!r} '
            f'lag_max={self.get_parameter("lag_distance_max_m").value}m '
            f'lost_timeout={self.get_parameter("customer_lost_timeout_sec").value}s')

        # INIT entry — 정상 params 면 LOCK_ON, invalid 면 ABORTED
        if self._target_table_id and self._target_table_id in self._tables:
            self._transition(State.LOCK_ON)
        else:
            self._transition(State.ABORTED)

    # ─────────── tables.yaml / params ───────────

    def _load_tables(self) -> None:
        path = self.get_parameter('tables_yaml').value
        if not path or not os.path.isfile(path):
            self.get_logger().error(
                f'tables_yaml 파일 없음: {path!r} — guiding 진행 불가')
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.get_logger().error(f'tables_yaml 파싱 실패: {e}')
            return
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

    def _parse_params(self) -> None:
        raw = self.get_parameter('params_json').value
        if not raw:
            return
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            self.get_logger().error(f'params_json 파싱 실패: {e}')
            return
        if isinstance(d, dict):
            self._target_table_id = d.get('target_table') or None
            self._customer_id = str(d.get('customer_id', ''))

    def _build_approach_pose(self, table_id: str) -> Optional[PoseStamped]:
        """tables.yaml 의 pose + approach_dist → Nav2 goal 좌표."""
        t = self._tables.get(table_id)
        if t is None:
            return None
        pose_d = t['pose_dict']
        try:
            x = float(pose_d.get('x', 0.0))
            y = float(pose_d.get('y', 0.0))
            yaw = float(pose_d.get('yaw', 0.0))
        except (TypeError, ValueError):
            return None
        approach = float(t.get('approach_dist', 0.5))
        ps = PoseStamped()
        ps.header.frame_id = pose_d.get('frame_id', 'map')
        ps.header.stamp = self.get_clock().now().to_msg()
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

        if new_state == State.LOCK_ON:
            self._on_enter_lock_on()
        elif new_state == State.MOVING:
            self._on_enter_moving()
        elif new_state == State.WAITING:
            self._on_enter_waiting()
        elif new_state == State.ARRIVED:
            self._on_enter_arrived()
        elif new_state == State.DONE:
            self._on_enter_done()
        elif new_state == State.ABORTED:
            self._on_enter_aborted()

    def _on_enter_lock_on(self) -> None:
        self._utter('잠시만요, 안내해 드릴게요', priority=GUIDING_UTTER_PRIORITY_NORMAL)

    def _on_enter_moving(self) -> None:
        # WAITING 에서 재진입 시 active goal 이 cancel 상태 — 새 send_goal 필요
        self._utter('저를 따라오세요', priority=GUIDING_UTTER_PRIORITY_NORMAL)
        pose = self._build_approach_pose(self._target_table_id or '')
        if pose is None:
            self.get_logger().error(
                f'target_table {self._target_table_id} pose 무효 — ABORTED')
            self._transition(State.ABORTED)
            return
        self._target_pose = pose
        self._send_nav_goal(pose)

    def _on_enter_waiting(self) -> None:
        self._utter('천천히 따라오세요', priority=GUIDING_UTTER_PRIORITY_NORMAL)
        self._cancel_nav()

    def _on_enter_arrived(self) -> None:
        self._utter('여기서 편하게 즐기세요', priority=GUIDING_UTTER_PRIORITY_NORMAL)

    def _on_enter_done(self) -> None:
        self.get_logger().info(
            'guiding DONE — OpServer SetMode("idle") 대기')
        # patrol 과 동일 — self-terminate X, /guiding/state="done" 유지 publish

    def _on_enter_aborted(self) -> None:
        self._utter(
            '어디 가셨어요? 카운터로 다시 와주세요',
            priority=GUIDING_UTTER_PRIORITY_URGENT)
        self._cancel_nav()
        # patrol 과 동일 — OpServer 가 /guiding/state="aborted" 관찰 후 idle

    # ─────────── Nav2 ───────────

    def _send_nav_goal(self, pose: PoseStamped) -> None:
        if not self.act_nav.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn('Nav2 action server 미응답 — ABORTED')
            self._transition(State.ABORTED)
            return
        goal = NavigateToPose.Goal()
        goal.pose = pose
        self.get_logger().info(
            f'Nav2 send_goal target={self._target_table_id}: '
            f'({pose.pose.position.x:.2f}, {pose.pose.position.y:.2f})')
        send_future = self.act_nav.send_goal_async(goal)
        send_future.add_done_callback(self._on_nav_accepted)

    def _on_nav_accepted(self, future) -> None:
        try:
            gh = future.result()
        except Exception as e:
            self.get_logger().warn(f'nav send_goal future error: {e}')
            self._transition(State.ABORTED)
            return
        if not gh.accepted:
            self.get_logger().warn('Nav2 goal rejected — ABORTED')
            self._transition(State.ABORTED)
            return
        self._nav_goal_handle = gh
        self._nav_result_future = gh.get_result_async()
        self._nav_result_future.add_done_callback(self._on_nav_result)

    def _on_nav_result(self, future) -> None:
        try:
            result = future.result()
            status = int(result.status)
        except Exception as e:
            self.get_logger().warn(f'nav get_result error: {e}')
            status = 0
        self._nav_goal_handle = None
        # action_msgs/GoalStatus: SUCCEEDED=4, CANCELED=5, ABORTED=6
        if status == 4:
            if self._state == State.MOVING:
                self._transition(State.ARRIVED)
        elif status == 5:
            # WAITING 진입 시 우리가 cancel 한 경우 — 정상
            self.get_logger().info('Nav2 goal canceled (WAITING 진입)')
        else:
            if self._state == State.MOVING:
                self.get_logger().warn(f'Nav2 result status={status} — ABORTED')
                self._transition(State.ABORTED)

    def _cancel_nav(self) -> None:
        if self._nav_goal_handle is not None:
            try:
                self._nav_goal_handle.cancel_goal_async()
            except Exception as e:
                self.get_logger().warn(f'cancel_goal_async failed: {e}')
            self._nav_goal_handle = None

    # ─────────── customer / odom 콜백 ───────────

    def _on_persons(self, msg: Detection2DArray) -> None:
        """가장 큰 bbox = 가장 가까운 사람 = customer (M2 단순화, 디자인 §2.5).

        ID tracking 은 M3. 본 M2 구현은 매 프레임 최근접 bbox 로 갱신.
        """
        if not msg.detections:
            return
        # 가장 큰 bbox 선택 — follow_controller 패턴
        best = None
        best_area = 0.0
        for d in msg.detections:
            area = float(d.bbox.size_x) * float(d.bbox.size_y)
            if area > best_area:
                best_area = area
                best = d
        if best is None:
            return
        # ground projection (M2 placeholder, 디자인 §7.1)
        # 실제 카메라 외부보정 + bbox 하단 → 지면 ray projection 은 M3.
        # M2: 로봇 진행방향 (target 방향) 의 반대쪽 1m 가정 — lag 계산 동작은 함.
        xy = self._project_to_world_heuristic(best)
        if xy is None:
            return
        self._customer_xy = xy
        self._customer_in_sight = True
        self._last_seen_at = self.get_clock().now()

    def _project_to_world_heuristic(self, detection) -> Optional[Tuple[float, float]]:
        """M2 placeholder ground projection — 로봇 뒤 1m 가정.

        디자인 §7.1: 정확도 낮음. lag 계산이 의미 약함. customer_lost_timeout 만 신뢰.
        M3: TF + camera_info + bbox 하단 ray projection 으로 교체.
        """
        if self._robot_pose is None:
            return None
        rx, ry, yaw = self._robot_pose
        if self._target_pose is not None:
            # target 방향의 *반대쪽* 1m (손님이 로봇 뒤에 있다고 가정)
            tx = self._target_pose.pose.position.x
            ty = self._target_pose.pose.position.y
            dx, dy = tx - rx, ty - ry
            norm = math.hypot(dx, dy)
            if norm > 1e-3:
                ux, uy = dx / norm, dy / norm
                return (rx - 1.0 * ux, ry - 1.0 * uy)
        # target 없으면 로봇 yaw 반대 방향 1m
        return (rx - 1.0 * math.cos(yaw), ry - 1.0 * math.sin(yaw))

    def _on_odom(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        # yaw extraction from quaternion (no tf2 dep)
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        self._robot_pose = (
            float(msg.pose.pose.position.x),
            float(msg.pose.pose.position.y),
            yaw,
        )

    def _on_rapport(self, msg: RapportEvent) -> None:
        if msg.event_type != 'abort_trigger':
            return
        if self._state in (State.DONE, State.ABORTED, State.INIT):
            return
        self.get_logger().warn(
            f'rapport abort_trigger weight={msg.weight:.2f} → ABORTED')
        self._transition(State.ABORTED)

    # ─────────── 핵심 계산 ───────────

    def _compute_lag(self) -> float:
        """로봇 진행방향 기준 customer 뒤처짐 (양수=뒤, 음수=앞).

        direction = (target - robot).normalized()
        lag = -dot(customer - robot, direction)
        """
        if (self._robot_pose is None or self._customer_xy is None
                or self._target_pose is None):
            return 0.0
        rx, ry, _ = self._robot_pose
        tx = self._target_pose.pose.position.x
        ty = self._target_pose.pose.position.y
        norm = math.hypot(tx - rx, ty - ry)
        if norm < 1e-3:
            return 0.0
        dirx, diry = (tx - rx) / norm, (ty - ry) / norm
        cx, cy = self._customer_xy
        return -((cx - rx) * dirx + (cy - ry) * diry)

    def _distance_to_customer(self) -> float:
        if self._customer_xy is None or self._robot_pose is None:
            return -1.0
        rx, ry, _ = self._robot_pose
        cx, cy = self._customer_xy
        return float(math.hypot(cx - rx, cy - ry))

    def _distance_to_target(self) -> float:
        if self._target_pose is None or self._robot_pose is None:
            return -1.0
        rx, ry, _ = self._robot_pose
        tx = self._target_pose.pose.position.x
        ty = self._target_pose.pose.position.y
        return float(math.hypot(tx - rx, ty - ry))

    def _seconds_since_last_seen(self) -> float:
        if self._last_seen_at is None:
            return float('inf')
        now = self.get_clock().now()
        return (now - self._last_seen_at).nanoseconds / 1e9

    # ─────────── 발화 (UtterRequest) ───────────

    def _utter(self, text: str, priority: int) -> None:
        """UtterRequest 발행 + face_expression 동기 + 쿨다운."""
        cd = float(self.get_parameter('utter_cooldown_sec').value)
        now = self.get_clock().now()
        last = self._last_utter_at.get(text)
        if last is not None and (now - last).nanoseconds / 1e9 < cd:
            return
        msg = UtterRequest()
        msg.header.stamp = now.to_msg()
        msg.text = text
        msg.face_expression = FACE_BY_STATE.get(self._state, 'basic')
        msg.source = 'guiding'
        msg.priority = int(max(0, min(255, priority)))
        msg.preempt = False
        self.pub_utter.publish(msg)
        self._last_utter_at[text] = now
        self._last_utter_text = text
        self.get_logger().info(
            f'utter [{msg.face_expression}] prio={msg.priority}: {text}')

    # ─────────── 20Hz tick ───────────

    def _tick(self) -> None:
        now = self.get_clock().now()
        elapsed = (now - self._state_entered_at).nanoseconds / 1e9

        if self._state == State.LOCK_ON:
            if self._customer_xy is not None:
                self._transition(State.MOVING)
            elif elapsed > float(
                    self.get_parameter('lock_on_timeout_sec').value):
                self.get_logger().warn(
                    f'lock_on timeout {elapsed:.1f}s — ABORTED')
                self._transition(State.ABORTED)

        elif self._state == State.MOVING:
            # customer 시야 잃음 체크
            lost_for = self._seconds_since_last_seen()
            lost_timeout = float(
                self.get_parameter('customer_lost_timeout_sec').value)
            if lost_for > lost_timeout:
                self.get_logger().warn(
                    f'customer lost {lost_for:.1f}s > {lost_timeout:.1f}s — ABORTED')
                self._transition(State.ABORTED)
                return
            # lag 체크
            lag = self._compute_lag()
            if lag > float(self.get_parameter('lag_distance_max_m').value):
                self.get_logger().info(
                    f'lag={lag:.2f}m > max — WAITING')
                self._transition(State.WAITING)
            # 전체 nav timeout
            if elapsed > float(
                    self.get_parameter('nav_overall_timeout_sec').value):
                self.get_logger().warn(
                    f'nav overall timeout {elapsed:.1f}s — ABORTED')
                self._transition(State.ABORTED)

        elif self._state == State.WAITING:
            lost_for = self._seconds_since_last_seen()
            lost_timeout = float(
                self.get_parameter('customer_lost_timeout_sec').value)
            if lost_for > lost_timeout:
                self.get_logger().warn(
                    f'customer lost {lost_for:.1f}s > {lost_timeout:.1f}s in WAITING — ABORTED')
                self._transition(State.ABORTED)
                return
            lag = self._compute_lag()
            if lag < float(self.get_parameter('lag_distance_min_m').value):
                self.get_logger().info(
                    f'lag={lag:.2f}m < min — MOVING 재개')
                self._transition(State.MOVING)

        elif self._state == State.ARRIVED:
            if elapsed > float(self.get_parameter('arrival_dwell_sec').value):
                self._transition(State.DONE)

    # ─────────── 1Hz state publish ───────────

    def _publish_state(self) -> None:
        msg = GuidingState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.current_state = self._state.value
        msg.target_table = self._target_table_id or ''
        msg.customer_id = self._customer_id
        msg.customer_in_sight = self._customer_in_sight
        msg.distance_to_customer = self._distance_to_customer()
        msg.customer_lag_m = float(self._compute_lag())
        if self._last_seen_at is not None:
            msg.customer_last_seen = self._last_seen_at.to_msg()
        msg.distance_to_target = self._distance_to_target()
        msg.progress = 0.0   # M3: Nav2 feedback 활용
        msg.started_at = self._started_at.to_msg()
        msg.last_utter_text = self._last_utter_text
        self.pub_state.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = GuidingController()
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
