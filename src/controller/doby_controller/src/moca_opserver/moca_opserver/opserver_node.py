#!/usr/bin/env python3
"""opserver_node.py — moca_opserver 메인 노드.

API 사양: docs/moca_opserver_api_spec.md §1, §4 (ROS 인터페이스 매트릭스).
FSM 사양: docs/moca_5state_fsm_spec.md.

책임:
  1. ROS 구독 (8): /mode/state, /serving/state, /patrol/state,
                    /patrol/table_report, /guiding/state, /battery_state,
                    /odom, /rapport/event
  2. ROS 발행 (4): /opserver/event, /operator/command,
                    /serving/goto_table, /utter/request
  3. SetMode 클라이언트 (orchestrator 가 호출)
  4. FastAPI :8800 (REST + WebSocket) — uvicorn 별 thread
  5. priority gating (orchestrator)
  6. 이벤트 큐 (idempotent)
  7. 테이블 점유 캐시 (table_registry)
  8. 서빙/주문/안내 큐
  9. patrol 5분 idle 타이머 (M2 본격 구현)

사용:
  ros2 launch moca_opserver opserver.launch.py
  ros2 run moca_opserver opserver_node
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node

from std_msgs.msg import String
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from dobi_npc_msgs.msg import (
    ModeState, PatrolState, TableReport, GuidingState,
    OpEvent, OperatorCommand, RapportEvent, UtterRequest,
)

from single_arm_controller_interfaces.action import Pickup, Serve

from .completion_watcher import CompletionWatcher
from .idle_patrol_timer import IdlePatrolTimer
from .mode_orchestrator import ModeOrchestrator, VALID_MODES
from .rest_api import build_fastapi_app
from .ws_hub import WsHub, now_iso


log = logging.getLogger(__name__)


# ---------- 설정 모델 ----------

@dataclass
class OpServerConfig:
    """opserver_config.yaml + ROS parameter 로 주입."""
    host: str = '0.0.0.0'
    port: int = 8800
    patrol_interval_minutes: float = 5.0
    patrol_enabled: bool = True
    patrol_retrigger_cooldown_sec: float = 30.0  # 0 = 즉시 재트리거 가능 (테스트용)
    business_hours: str = '09:00-22:00'
    battery_min: float = 0.20
    alarm_dwell_sec: float = 5.0
    setmode_timeout_sec: float = 2.0
    robot_offline_threshold_sec: float = 3.0
    completion_dwell_serving: float = 3.0
    completion_dwell_patrol: float = 1.0
    completion_dwell_guiding: float = 5.0
    completion_dwell_engaging: float = 2.0

    def snapshot(self) -> dict:
        return asdict(self)


# ---------- 메인 노드 ----------

class OpServerNode(Node):
    """moca_opserver ROS 노드 + FastAPI 임베드."""

    def __init__(self):
        super().__init__('moca_opserver')

        # 시작 시각
        self._started_at = time.time()

        # 파라미터 (config 매핑)
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8800)
        self.declare_parameter('patrol_interval_minutes', 5.0)
        self.declare_parameter('patrol_enabled', True)
        self.declare_parameter('business_hours', '09:00-22:00')
        self.declare_parameter('battery_min', 0.20)
        self.declare_parameter('alarm_dwell_sec', 5.0)

        self.config = OpServerConfig(
            host=str(self.get_parameter('host').value),
            port=int(self.get_parameter('port').value),
            patrol_interval_minutes=float(
                self.get_parameter('patrol_interval_minutes').value),
            patrol_enabled=bool(self.get_parameter('patrol_enabled').value),
            business_hours=str(self.get_parameter('business_hours').value),
            battery_min=float(self.get_parameter('battery_min').value),
            alarm_dwell_sec=float(self.get_parameter('alarm_dwell_sec').value),
        )

        # ROS 상태 캐시 (FastAPI thread 가 read-only 접근, 락 불필요한 단순 dict)
        self.current_mode: str = 'idle'
        self.mode_entered_at: str = ''
        self.mode_params: str = ''
        self.last_reject_reason: str = ''
        self.battery_pct: float | None = None
        self.battery_voltage: float = 0.0
        self.safety_ok: bool = True
        self.robot_online: bool = False
        # 테스트 전용 — _on_mode_state 의 safety_ok 덮어쓰기 차단 (MOCA_TEST_MODE)
        self._test_safety_locked: bool = False
        # 테스트 전용 — /serving/state 콜백의 completion_watcher 신호 차단
        # (inject_completion='serving' 시 실 dispatcher 의 'navigating' 신호로 dwell reset 회피)
        self._test_completion_locked: bool = False
        self._last_mode_state_ts: float = 0.0
        self._robot_pose: dict | None = None
        # AMCL pose (map frame) 받은 적 있나? True 면 /odom 은 무시 (Nav2 사용 시 표준).
        # False (AMCL 없음) 면 /odom 좌표 그대로 사용 (odom frame, 시작 0 기준).
        self._has_amcl_pose: bool = False
        self._serving_state_json: dict = {}
        self._patrol_state: dict = {}
        self._guiding_state: dict = {}
        self._last_patrol_completed_at: str = ''

        # pickup action 비동기 진행 중 플래그 — drain/REST 재진입 차단
        self._pickup_in_progress: bool = False
        # 현재 serving 세션의 음료 여부 — CompletionWatcher 가 Serve goal 에 사용
        self._current_serving_has_drink: bool = False

        # 캐시 / 큐 (M1 in-memory, M3 sqlite 영속화 검토)
        self._tables: dict[str, dict] = {
            tid: {
                'id': tid, 'occupancy': 'unknown', 'person_count': 0,
                'dishes_detected': False, 'confidence': 0.0,
                'last_update': '', 'cumulative_serving_count': 0,
                'cumulative_occupied_detected': 0,
            } for tid in ('T01', 'T02', 'T03', 'T04', 'T05')
        }
        self._serving_queue: deque = deque()
        self._order_queue: deque = deque()
        self._guiding_queue: deque = deque()
        self._events: deque = deque(maxlen=500)
        self._seen_event_ids: dict[str, float] = {}
        self._event_ttl_sec = 3600.0
        self._alarms_acked: set[str] = set()

        # FastAPI / WS
        self.ws_hub = WsHub()
        self._fastapi_loop: asyncio.AbstractEventLoop | None = None

        # ROS 구독
        self.create_subscription(
            ModeState, '/mode/state', self._on_mode_state, 10)
        self.create_subscription(
            String, '/serving/state', self._on_serving_state, 10)
        self.create_subscription(
            PatrolState, '/patrol/state', self._on_patrol_state, 10)
        self.create_subscription(
            TableReport, '/patrol/table_report', self._on_table_report, 10)
        self.create_subscription(
            GuidingState, '/guiding/state', self._on_guiding_state, 10)
        self.create_subscription(
            BatteryState, '/battery_state', self._on_battery, 10)
        self.create_subscription(
            Odometry, '/odom', self._on_odom, 10)
        # AMCL pose — map frame (Nav2 사용 시). floorplan affine 이 map 기준이라
        # /odom (odom frame, spawn 시 0,0) 보다 정확. 받으면 _on_odom 무시.
        self.create_subscription(
            PoseWithCovarianceStamped, '/amcl_pose', self._on_amcl_pose, 10)
        self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)

        # ROS 발행
        self.pub_op_event = self.create_publisher(
            OpEvent, '/opserver/event', 10)
        self.pub_op_cmd = self.create_publisher(
            OperatorCommand, '/operator/command', 10)
        self.pub_serving_goto = self.create_publisher(
            String, '/serving/goto_table', 10)
        self.pub_utter = self.create_publisher(
            UtterRequest, '/utter/request', 10)
        # /rapport/event publisher — 테스트 (inject_rapport_abort) 및 향후 운영자
        # 강제 abort UI 용. 운영 모드에서는 OpServer 가 abort 트리거 발행 X (감정 노드 책임).
        self.pub_rapport = self.create_publisher(
            RapportEvent, '/rapport/event', 10)

        # SetMode 클라이언트 (orchestrator 가 보유)
        self.orchestrator = ModeOrchestrator(self)
        self.orchestrator.SETMODE_TIMEOUT_SEC = self.config.setmode_timeout_sec

        # single_arm_controller Serve / Pickup action clients
        self._arm_cb_group = ReentrantCallbackGroup()
        self._arm_ac = ActionClient(
            self, Serve, 'serve',
            callback_group=self._arm_cb_group,
        )
        self._pickup_ac = ActionClient(
            self, Pickup, 'pickup',
            callback_group=self._arm_cb_group,
        )

        # 자동 idle 복귀 + 5분 idle patrol 타이머
        self.completion_watcher = CompletionWatcher(self)
        self.idle_patrol_timer = IdlePatrolTimer(self)

        # robot online 체크 + completion_watcher/idle_patrol_timer tick
        self.create_timer(0.5, self._tick_robot_online)
        # /odom 다운샘플 broadcast 1Hz timer
        self.create_timer(1.0, self._broadcast_robot_pose)
        # CompletionWatcher + IdlePatrolTimer tick (1Hz)
        self.create_timer(1.0, self._tick_completion_and_patrol)

        # FastAPI 임베드 (별 thread)
        self.app = build_fastapi_app(self)
        self._uvicorn_thread = threading.Thread(
            target=self._run_uvicorn, daemon=True, name='uvicorn')
        self._uvicorn_thread.start()

        self.get_logger().info(
            f'moca_opserver ready: http://{self.config.host}:{self.config.port}'
            f' (battery_min={self.config.battery_min}, '
            f'patrol_interval={self.config.patrol_interval_minutes}min)')

    # ---------- FastAPI / uvicorn ----------

    def _run_uvicorn(self):
        import uvicorn
        # uvicorn 이 자체 이벤트루프를 생성하므로 직접 잡기 어렵다.
        # event loop 캡처: 별 task 로 등록하기 위해 lifespan="off" + loop="asyncio"
        config = uvicorn.Config(
            self.app, host=self.config.host, port=self.config.port,
            log_level='info', loop='asyncio')
        server = uvicorn.Server(config)
        # uvicorn 의 main loop 를 캡처 — server.serve() 가 만든 loop 가
        # asyncio.get_event_loop() 로 잡힌다 (별 thread 안에서).
        try:
            asyncio.new_event_loop().run_until_complete(self._serve_with_loop(server))
        except Exception as e:
            self.get_logger().error(f'uvicorn server crashed: {e}')

    async def _serve_with_loop(self, server) -> None:
        self._fastapi_loop = asyncio.get_event_loop()
        await server.serve()

    def ws_broadcast(self, msg_type: str, data: dict[str, Any]) -> None:
        """ROS 콜백(별 thread)에서 WS broadcast 호출."""
        if self._fastapi_loop is None:
            return
        self.ws_hub.broadcast_threadsafe(self._fastapi_loop, msg_type, data)

    # ---------- serving 진입 (pickup 선행 or 즉시) ----------

    def start_serving_with_pickup(
        self,
        waypoint: str,
        via_pickup: bool,
        trigger_source: str,
        has_drink: bool = True,
        override_priority: bool = False,
    ) -> dict:
        """via_pickup=True 이면 Pickup action 완료 후 SetMode('serving').
        via_pickup=False 이면 즉시 SetMode('serving').
        항상 즉시 반환 (pickup 경로는 비동기 콜백).

        has_drink: Pickup/Serve goal 에 전달되는 음료 여부 플래그.

        반환:
          via_pickup=False → orchestrator.request_mode_change() 결과 그대로
          via_pickup=True  → {'ok': True, 'pickup_requested': True}
                             (실패 시 {'ok': False, 'code': ..., 'message': ...})
        """
        params = {'waypoint': waypoint, 'via_pickup': via_pickup, 'has_drink': has_drink}
        self._current_serving_has_drink = has_drink

        if not via_pickup:
            return self.orchestrator.request_mode_change(
                target_mode='serving',
                params=params,
                trigger_source=trigger_source,
                override_priority=override_priority,
            )

        if self._pickup_in_progress:
            self.get_logger().warn('[pickup] 이미 pickup 진행 중 — 중복 요청 무시')
            return {'ok': False, 'code': 'PICKUP_IN_PROGRESS',
                    'message': 'pickup action already running'}

        self._pickup_in_progress = True
        self.get_logger().info(
            f'[pickup] Pickup action 요청 → 완료 후 SetMode(serving) '
            f'waypoint={waypoint} has_drink={has_drink}')

        def _after_pickup(success: bool, msg: str) -> None:
            self._pickup_in_progress = False
            if not success:
                self.get_logger().warn(
                    f'[pickup] 실패 ({msg}) — SetMode(serving) 취소')
                return
            self.get_logger().info(
                f'[pickup] 완료 — SetMode(serving) 요청 waypoint={waypoint}')
            self.orchestrator.request_mode_change(
                target_mode='serving',
                params=params,
                trigger_source=trigger_source,
                override_priority=override_priority,
            )

        self.send_arm_pickup_goal(_after_pickup, has_drink=has_drink)
        return {'ok': True, 'pickup_requested': True}

    # ---------- single_arm_controller Serve action ----------

    def send_arm_serve_goal(self, done_cb, has_drink: bool | None = None) -> None:
        """Serve action goal 전송. 서버 미가동 시 done_cb(False, 'server_unavailable') 즉시 호출.

        CompletionWatcher 가 serving 완료 후 호출. node 계약의 일부.
        Args:
            done_cb: (success: bool, message: str) -> None
            has_drink: None 이면 _current_serving_has_drink 사용.
        """
        if not self._arm_ac.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn(
                '[arm] action server not available — skipping, going idle')
            done_cb(False, 'server_unavailable')
            return

        goal = Serve.Goal()
        goal.has_drink = self._current_serving_has_drink if has_drink is None else has_drink
        self.get_logger().info(f'[arm] Serve goal has_drink={goal.has_drink}')

        send_future = self._arm_ac.send_goal_async(
            goal,
            feedback_callback=self._on_arm_feedback,
        )
        send_future.add_done_callback(
            lambda f: self._on_arm_goal_accepted(f, done_cb))

    def _on_arm_feedback(self, feedback_msg) -> None:
        self.get_logger().info(
            f'[arm] feedback: {feedback_msg.feedback.status}')

    def _on_arm_goal_accepted(self, future, done_cb) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn('[arm] goal rejected')
            done_cb(False, 'goal_rejected')
            return
        self.get_logger().info('[arm] goal accepted, waiting for result...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda f: self._on_arm_result(f, done_cb))

    def _on_arm_result(self, future, done_cb) -> None:
        result = future.result().result
        self.get_logger().info(
            f'[arm] result: success={result.success} message="{result.message}"')
        done_cb(result.success, result.message)

    # ---------- single_arm_controller Pickup action ----------

    def send_arm_pickup_goal(self, done_cb, has_drink: bool = True) -> None:
        """Pickup action goal 전송. 서버 미가동 시 done_cb(False, 'server_unavailable') 즉시 호출.

        Args:
            done_cb: (success: bool, message: str) -> None
            has_drink: Pickup.Goal.has_drink 에 전달.
        """
        if not self._pickup_ac.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn(
                '[pickup] action server not available')
            done_cb(False, 'server_unavailable')
            return

        goal = Pickup.Goal()
        goal.has_drink = has_drink
        self.get_logger().info(f'[pickup] Pickup goal has_drink={goal.has_drink}')

        send_future = self._pickup_ac.send_goal_async(
            goal,
            feedback_callback=self._on_pickup_feedback,
        )
        send_future.add_done_callback(
            lambda f: self._on_pickup_goal_accepted(f, done_cb))

    def _on_pickup_feedback(self, feedback_msg) -> None:
        self.get_logger().info(
            f'[pickup] feedback: {feedback_msg.feedback.status}')

    def _on_pickup_goal_accepted(self, future, done_cb) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn('[pickup] goal rejected')
            done_cb(False, 'goal_rejected')
            return
        self.get_logger().info('[pickup] goal accepted, waiting for result...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda f: self._on_pickup_result(f, done_cb))

    def _on_pickup_result(self, future, done_cb) -> None:
        result = future.result().result
        self.get_logger().info(
            f'[pickup] result: success={result.success} message="{result.message}"')
        done_cb(result.success, result.message)

    # ---------- ROS 콜백 ----------

    def _on_mode_state(self, msg: ModeState):
        self.current_mode = msg.current_mode
        self.mode_entered_at = self._stamp_to_iso(msg.entered_at)
        self.mode_params = msg.params  # snapshot 호환 위해 ROS msg 원본 string 보존
        # WS broadcast 는 parsed dict (M3 dashboard + 시나리오 테스트 가 dict 기대)
        params_dict: dict = {}
        if msg.params:
            try:
                parsed = json.loads(msg.params)
                if isinstance(parsed, dict):
                    params_dict = parsed
            except (ValueError, TypeError):
                pass
        self.last_reject_reason = msg.last_reject_reason
        if not self._test_safety_locked:
            self.safety_ok = bool(msg.safety_ok)
        self._last_mode_state_ts = time.time()
        # has_drink 복구 — 재시작/외부 SetMode 경로에서도 일관성 유지
        if msg.current_mode == 'serving':
            self._current_serving_has_drink = bool(params_dict.get('has_drink', True))
        elif msg.current_mode == 'idle':
            self._current_serving_has_drink = False
        # IdlePatrolTimer 신호
        self.idle_patrol_timer.on_mode_state(msg.current_mode)
        self.ws_broadcast('mode_state', {
            'current': msg.current_mode,
            'entered_at': self.mode_entered_at,
            'params': params_dict,
            'battery_ok': bool(msg.battery_ok),
            'safety_ok': bool(msg.safety_ok),
            'last_reject_reason': msg.last_reject_reason,
        })

    def _on_serving_state(self, msg: String):
        try:
            self._serving_state_json = json.loads(msg.data) if msg.data else {}
        except Exception:
            self._serving_state_json = {'raw': msg.data}
        # CompletionWatcher 신호 — serving_dispatcher 의 JSON.state 가 "idle" 이면 dwell 시작
        # _test_completion_locked 활성 시 신호 차단 (테스트 inject 와 충돌 회피)
        if not self._test_completion_locked:
            state_val = ''
            if isinstance(self._serving_state_json, dict):
                state_val = str(self._serving_state_json.get('state', ''))
            self.completion_watcher.on_serving_state(state_val)
        self.ws_broadcast('serving_progress', self._serving_state_json)

    def _on_patrol_state(self, msg: PatrolState):
        self._patrol_state = {
            'state': msg.current_state,
            'current_table': msg.current_table,
            'tables_visited': int(msg.tables_visited),
            'tables_total': int(msg.tables_total),
            'progress': float(msg.progress),
        }
        if msg.current_state == 'done':
            self._last_patrol_completed_at = now_iso()
        # CompletionWatcher 신호 — "done"/"aborted" 시 dwell 시작
        self.completion_watcher.on_patrol_state(msg.current_state)
        self.ws_broadcast('patrol_progress', self._patrol_state)

    def _on_table_report(self, msg: TableReport):
        if msg.table_id in self._tables:
            t = self._tables[msg.table_id]
            t['occupancy'] = msg.occupancy
            t['person_count'] = int(msg.person_count)
            t['dishes_detected'] = bool(msg.dishes_detected)
            t['confidence'] = float(msg.confidence)
            t['last_update'] = now_iso()
            if msg.occupancy == 'occupied':
                t['cumulative_occupied_detected'] += 1
            self.ws_broadcast('table_update', dict(t))

    def _on_guiding_state(self, msg: GuidingState):
        self._guiding_state = {
            'state': msg.current_state,
            'target_table': msg.target_table,
            'customer_id': msg.customer_id,
            'distance_to_target': float(msg.distance_to_target),
            'distance_to_customer': float(msg.distance_to_customer),
            'customer_in_sight': bool(msg.customer_in_sight),
        }
        # CompletionWatcher 신호 — "done"/"aborted" 시 dwell 시작
        self.completion_watcher.on_guiding_state(msg.current_state)
        self.ws_broadcast('guiding_progress', self._guiding_state)

    def _on_battery(self, msg: BatteryState):
        self.battery_pct = float(msg.percentage)
        self.battery_voltage = float(msg.voltage)
        # 5Hz → 1Hz 다운샘플은 timer 가 처리하지 않고, 단순히 모든 콜백마다 broadcast
        # 하지 않음 — 클라이언트 부하 회피 위해 변화 임계만 push (M3: 본격 다운샘플)
        self.ws_broadcast('battery', {
            'percentage': self.battery_pct,
            'voltage': self.battery_voltage,
        })

    def _on_odom(self, msg: Odometry):
        # 20Hz 들어오므로 캐시만 갱신, broadcast 는 1Hz timer 에서.
        # AMCL pose 가 한 번이라도 왔으면 odom 무시 (map frame 우선).
        if self._has_amcl_pose:
            return
        q = msg.pose.pose.orientation
        # yaw extraction from quaternion (no tf import to keep deps light)
        import math
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        self._robot_pose = {
            'x': float(msg.pose.pose.position.x),
            'y': float(msg.pose.pose.position.y),
            'yaw': yaw,
            'frame': 'odom',
        }

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped):
        # AMCL pose 는 map frame robot 좌표. floorplan affine 이 map 기준이라 우선.
        q = msg.pose.pose.orientation
        import math
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        self._robot_pose = {
            'x': float(msg.pose.pose.position.x),
            'y': float(msg.pose.pose.position.y),
            'yaw': yaw,
            'frame': 'map',
        }
        self._has_amcl_pose = True

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type == 'abort_trigger':
            self._append_event('warn', 'rapport',
                               f'abort_trigger weight={msg.weight:.2f}',
                               'safety')
            self.ws_broadcast('alarm', {
                'code': 'rapport_abort',
                'value': float(msg.weight),
                'severity': 'high',
            })

    # ---------- timer ----------

    def _tick_robot_online(self):
        elapsed = time.time() - self._last_mode_state_ts
        was = self.robot_online
        self.robot_online = (self._last_mode_state_ts > 0 and
                              elapsed < self.config.robot_offline_threshold_sec)
        if was != self.robot_online:
            self.get_logger().warn(
                f'robot_online -> {self.robot_online} (last_seen={elapsed:.1f}s)')
            self.ws_broadcast('alarm', {
                'code': 'robot_online_changed',
                'value': self.robot_online,
                'severity': 'low' if self.robot_online else 'high',
            })

    def _tick_completion_and_patrol(self):
        """1Hz tick — CompletionWatcher dwell 만료 + IdlePatrolTimer 5분 dwell 검사
        + idle 진입 후 serving_queue 자동 drain (G3 큐잉 정책 완결)."""
        try:
            self.completion_watcher.tick()
        except Exception as e:
            self.get_logger().error(f'completion_watcher.tick error: {e}')
        try:
            self._drain_serving_queue()
        except Exception as e:
            self.get_logger().error(f'serving_queue drain error: {e}')
        try:
            self.idle_patrol_timer.tick()
        except Exception as e:
            self.get_logger().error(f'idle_patrol_timer.tick error: {e}')

    def _drain_serving_queue(self) -> None:
        """idle 진입 + serving_queue 비어있지 않으면 첫 entry 로 serving 시작.

        guiding_design §10 G3 정책 — guiding 중 pickup 은 큐잉 → guiding 완료
        + idle 진입 + 본 tick 이 첫 entry 로 serving 자동 시작.
        via_pickup=True 이면 start_serving_with_pickup 이 pickup 먼저 수행.
        """
        if self.current_mode != 'idle':
            return
        if self._pickup_in_progress:
            return
        if not self._serving_queue:
            return
        # IdlePatrolTimer 의 cooldown 과 동일 — patrol 자동 트리거 직후엔 미동작
        entry = self._serving_queue[0]
        target = entry.get('target_table') or entry.get('waypoint')
        if not target:
            # 잘못된 entry — 폐기
            self._serving_queue.popleft()
            return
        via_pickup = bool(entry.get('via_pickup', True))
        has_drink = bool(entry.get('has_drink', True))
        result = self.start_serving_with_pickup(
            waypoint=target,
            via_pickup=via_pickup,
            trigger_source='queue_drain',
            has_drink=has_drink,
            override_priority=False,
        )
        if result.get('ok'):
            self._serving_queue.popleft()
            self.get_logger().info(
                f'serving queue drain: idle → serving target={target} '
                f'(remaining queue={len(self._serving_queue)})')
            try:
                self.publish_op_event(
                    source='timer', event_type='serving_queue_drain',
                    payload={'target_table': target, 'remaining': len(self._serving_queue)},
                    outcome='accepted')
            except Exception:
                pass

    def _broadcast_robot_pose(self):
        if self._robot_pose is not None:
            self.ws_broadcast('robot_pose', self._robot_pose)

    # ---------- 헬퍼: 시간 ----------

    def uptime_sec(self) -> float:
        return time.time() - self._started_at

    @staticmethod
    def _stamp_to_iso(stamp) -> str:
        if stamp is None:
            return ''
        try:
            sec = int(stamp.sec) + int(stamp.nanosec) / 1e9
            from datetime import datetime, timezone
            return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat(
                timespec='milliseconds').replace('+00:00', 'Z')
        except Exception:
            return ''

    # ---------- event_queue (idempotency) ----------

    def event_seen(self, event_id: str) -> bool:
        now = time.time()
        # 간단한 GC
        if len(self._seen_event_ids) > 1024:
            self._seen_event_ids = {
                k: v for k, v in self._seen_event_ids.items()
                if now - v < self._event_ttl_sec
            }
        return event_id in self._seen_event_ids

    def event_mark(self, event_id: str) -> None:
        self._seen_event_ids[event_id] = time.time()

    # ---------- 큐 ----------

    def order_queue_register(self, payload: dict) -> int:
        self._order_queue.append(payload)
        return len(self._order_queue)

    def serving_queue_register(self, payload: dict) -> int:
        self._serving_queue.append(payload)
        return len(self._serving_queue)

    def serving_queue_size(self) -> int:
        return len(self._serving_queue)

    def assign_table_for_guide(self, preferred: str | None) -> str | None:
        """빈 테이블 할당. M1: preferred 우선, 없으면 점유 무관 첫 번째 테이블."""
        if preferred and preferred in self._tables:
            t = self._tables[preferred]
            if t['occupancy'] in ('empty', 'unknown'):
                return preferred
        # 빈 테이블 검색
        for tid, t in self._tables.items():
            if t['occupancy'] == 'empty':
                return tid
        # M1: empty 가 없으면 unknown 도 허용 (patrol 미실행 환경)
        for tid, t in self._tables.items():
            if t['occupancy'] == 'unknown':
                return tid
        return None

    # ---------- 발행 헬퍼 ----------

    def publish_op_event(self, source: str, event_type: str,
                         payload: dict, outcome: str) -> None:
        msg = OpEvent()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id = str(payload.get('event_id', '') or '')
        msg.source = source
        msg.event_type = event_type
        try:
            msg.payload = json.dumps(payload, ensure_ascii=False)
        except Exception:
            msg.payload = str(payload)
        msg.outcome = outcome
        self.pub_op_event.publish(msg)
        # 이벤트 로그에도 기록
        level = 'warn' if outcome.startswith('rejected') else 'info'
        self._append_event(level, source, f'{event_type}: {outcome}', event_type)

    def publish_operator_command(self, command_type: str,
                                  payload: dict) -> None:
        msg = OperatorCommand()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.command_type = command_type
        try:
            msg.payload = json.dumps(payload, ensure_ascii=False) if payload else ''
        except Exception:
            msg.payload = str(payload)
        self.pub_op_cmd.publish(msg)
        # utter 는 별도로 UtterRequest 도 발행
        if command_type == 'utter':
            self._publish_utter(payload)

    def publish_serving_goto_table(self, table_id: str) -> None:
        msg = String()
        msg.data = table_id
        self.pub_serving_goto.publish(msg)

    def _publish_utter(self, payload: dict) -> None:
        msg = UtterRequest()
        msg.header.stamp = self.get_clock().now().to_msg()
        # UtterRequest 필드는 기존 구조 (text/priority/intent 등) — 안전하게 text 만
        text = str(payload.get('text', ''))
        if hasattr(msg, 'text'):
            msg.text = text
        if hasattr(msg, 'priority'):
            msg.priority = 10   # 운영자 우선순위
        self.pub_utter.publish(msg)

    # ---------- event log ----------

    def _append_event(self, level: str, source: str, msg: str,
                       category: str) -> None:
        ev = {
            'ts': now_iso(),
            'level': level,
            'source': source,
            'msg': msg,
            'category': category,
        }
        self._events.append(ev)
        self.ws_broadcast('event_log', ev)

    def ack_alarm(self, alarm_code: str) -> None:
        self._alarms_acked.add(alarm_code)

    # ---------- snapshot ----------

    def get_status_snapshot(self) -> dict:
        return {
            'uptime_sec': max(0.0, time.time() - self._started_at),
            'environment': {
                'ros_domain_id': os.environ.get('ROS_DOMAIN_ID', ''),
                'localhost_only': os.environ.get('ROS_LOCALHOST_ONLY', '0'),
                'hint': os.environ.get('MOCA_DOMAIN_HINT', ''),
            },
            'mode': {
                'current': self.current_mode,
                'entered_at': self.mode_entered_at,
                'params': self.mode_params,
                'battery_ok': self._battery_ok(),
                'safety_ok': self.safety_ok,
                'last_reject_reason': self.last_reject_reason,
            },
            'battery': {
                'percentage': self.battery_pct,
                'voltage': self.battery_voltage,
            },
            'robot_online': self.robot_online,
            'queue': {
                'serving': list(self._serving_queue),
                'guiding': list(self._guiding_queue),
                'order': list(self._order_queue),
            },
            'tables': list(self._tables.values()),
            'config': self.config.snapshot(),
            'serving_state': self._serving_state_json,
            'patrol_state': self._patrol_state,
            'guiding_state': self._guiding_state,
        }

    def get_tables_snapshot(self) -> list:
        return list(self._tables.values())

    def get_events_snapshot(self) -> list:
        return list(self._events)

    def last_patrol_completed_at(self) -> str:
        return self._last_patrol_completed_at

    def _battery_ok(self) -> bool:
        if self.battery_pct is None or self.battery_pct < 0:
            return True
        return self.battery_pct >= self.config.battery_min

    # ---------- config 갱신 ----------

    def update_config(self, updates: dict) -> list[str]:
        keys: list[str] = []
        for k, v in updates.items():
            if v is None:
                continue
            if hasattr(self.config, k):
                setattr(self.config, k, v)
                keys.append(k)
        return keys


def main(args=None):
    rclpy.init(args=args)
    node = OpServerNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
