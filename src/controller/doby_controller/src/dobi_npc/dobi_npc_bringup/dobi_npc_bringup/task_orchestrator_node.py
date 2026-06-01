#!/usr/bin/env python3
# flake8: noqa
"""ROS-only task orchestration for serving, guiding, completion, and patrol."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from dobi_npc_msgs.action import Serving
from dobi_npc_msgs.msg import GuidingState, ModeState, OpEvent, PatrolState, TableReport
from dobi_npc_msgs.srv import (
    GetTableStatus,
    RequestGuiding,
    SetMode,
    SetPatrolSchedule,
)


VALID_TABLES = ('T01', 'T02', 'T03', 'T04', 'T05')
DONE_SIGNALS = {
    'patrol': {'done', 'aborted'},
    'guiding': {'done', 'aborted'},
    'engaging': {'done', 'completed'},
}


@dataclass
class OrchestratorConfig:
    patrol_interval_minutes: float = 5.0
    patrol_enabled: bool = True
    business_hours: str = '09:00-22:00'
    battery_min: float = 0.20
    completion_dwell_serving: float = 3.0
    completion_dwell_patrol: float = 1.0
    completion_dwell_guiding: float = 5.0
    completion_dwell_engaging: float = 2.0
    setmode_timeout_sec: float = 2.0


def _in_business_hours(spec: str) -> bool:
    if not spec or spec.strip() in ('', '24h', '24/7', 'always'):
        return True
    try:
        start_raw, end_raw = spec.split('-', 1)
        start = tuple(int(v) for v in start_raw.strip().split(':', 1))
        end = tuple(int(v) for v in end_raw.strip().split(':', 1))
    except Exception:
        return True
    now = datetime.now()
    current = (now.hour, now.minute)
    return start <= current <= end


class TaskOrchestratorNode(Node):
    """Owns operational tasks but delegates final mode authority to mode_manager."""

    def __init__(self):
        super().__init__('task_orchestrator')

        self.declare_parameter('patrol_interval_minutes', 5.0)
        self.declare_parameter('patrol_enabled', True)
        self.declare_parameter('business_hours', '09:00-22:00')
        self.declare_parameter('battery_min', 0.20)
        self.declare_parameter('serving_action_timeout_sec', 600.0)

        self.config = OrchestratorConfig(
            patrol_interval_minutes=float(self.get_parameter('patrol_interval_minutes').value),
            patrol_enabled=bool(self.get_parameter('patrol_enabled').value),
            business_hours=str(self.get_parameter('business_hours').value),
            battery_min=float(self.get_parameter('battery_min').value),
        )

        self.current_mode = 'idle'
        self.mode_params: dict[str, Any] = {}
        self.battery_pct: float | None = None
        self.safety_ok = True
        self._idle_entered_at: float | None = time.time()
        self._pickup_in_progress = False
        self._current_serving_has_drink = False
        self._serving_progress_seen = False
        self._serving_done_started_at: float | None = None
        self._serving_state_seq = 0
        self._mode_done_started_at: dict[str, float | None] = {
            'patrol': None,
            'guiding': None,
            'engaging': None,
        }
        self._completion_running: set[str] = set()
        self._last_serving_state_json: dict[str, Any] = {}
        self._action_lock = threading.RLock()
        self._active_serving_action = False
        self._serving_action_timeout_sec = float(
            self.get_parameter('serving_action_timeout_sec').value)

        self._seen_event_ids: dict[str, float] = {}
        self._tables: dict[str, dict[str, Any]] = {
            tid: {
                'id': tid,
                'occupancy': 'unknown',
                'person_count': 0,
                'dishes_detected': False,
                'confidence': 0.0,
                'last_update': '',
            }
            for tid in VALID_TABLES
        }

        self._cb_group = ReentrantCallbackGroup()
        self._set_mode = self.create_client(SetMode, '/mode/request', callback_group=self._cb_group)
        self._pickup_ac = None  # TODO(single_arm): ActionClient(self, Pickup, 'pickup', ...)
        self._serve_ac = None  # TODO(single_arm): ActionClient(self, Serve, 'serve', ...)

        self.create_subscription(ModeState, '/mode/state', self._on_mode_state, 10)
        self.create_subscription(String, '/serving/state', self._on_serving_state, 10)
        self.create_subscription(PatrolState, '/patrol/state', self._on_patrol_state, 10)
        self.create_subscription(GuidingState, '/guiding/state', self._on_guiding_state, 10)
        self.create_subscription(TableReport, '/patrol/table_report', self._on_table_report, 10)
        self.create_subscription(BatteryState, '/battery_state', self._on_battery, 10)

        self._event_pub = self.create_publisher(OpEvent, '/doby/event', 10)

        self.create_service(RequestGuiding, '/task/request_guiding', self._on_request_guiding)
        self.create_service(GetTableStatus, '/task/get_table_status', self._on_get_table_status)
        self.create_service(SetPatrolSchedule, '/task/set_patrol_schedule', self._on_set_patrol_schedule)
        self._serving_action_server = ActionServer(
            self,
            Serving,
            '/serving/execute',
            execute_callback=self._execute_serving_action,
            goal_callback=self._on_serving_action_goal,
            cancel_callback=self._on_serving_action_cancel,
            callback_group=self._cb_group,
        )

        self.create_timer(1.0, self._tick)

        self.get_logger().info('task_orchestrator ready (ROS-only)')

    # ---------- service handlers ----------

    def _handle_serving_payload(self, payload: dict[str, Any],
                                trigger_source: str) -> dict[str, Any]:
        event_id = str(payload.get('event_id', '')).strip()
        target = str(payload.get('target_table', '')).strip()
        if event_id and self._event_seen(event_id):
            return {
                'success': False,
                'code': 'DUPLICATE_EVENT',
                'message': 'event_id already processed',
            }
        if target not in VALID_TABLES:
            return {
                'success': False,
                'code': 'INVALID_TABLE',
                'message': f'unknown table: {target}',
            }
        current = self.current_mode or 'idle'
        if current == 'serving':
            self._publish_event(trigger_source, 'pickup_ready', payload,
                                'rejected:SERVING_BUSY')
            return {
                'success': False,
                'code': 'SERVING_BUSY',
                'message': 'serving action already running',
                'mode_requested': False,
            }

        if current != 'idle':
            self._publish_event(trigger_source, 'pickup_ready', payload,
                                f'rejected:MODE_BUSY:{current}')
            return {
                'success': False,
                'code': 'MODE_BUSY',
                'message': f'current mode is {current}',
                'mode_requested': False,
            }

        result = self._start_serving(payload, trigger_source=trigger_source)
        if result.get('ok'):
            if event_id:
                self._event_mark(event_id)
            self._publish_event(trigger_source, 'pickup_ready', payload, 'accepted')
            return {
                'success': True,
                'code': 'OK',
                'message': result.get('message', ''),
                'mode_requested': bool(result.get('mode_requested', True)),
            }

        self._publish_event(trigger_source, 'pickup_ready', payload,
                            f'rejected:{result.get("code", "ERROR")}')
        return {
            'success': False,
            'code': result.get('code', 'ERROR'),
            'message': result.get('message', ''),
        }

    def _on_serving_action_goal(self, goal_request):
        del goal_request
        with self._action_lock:
            if self._active_serving_action:
                self.get_logger().warn(
                    '/serving/execute rejected: another serving action is active')
                return GoalResponse.REJECT
            self._active_serving_action = True
        return GoalResponse.ACCEPT

    def _on_serving_action_cancel(self, goal_handle):
        del goal_handle
        return CancelResponse.ACCEPT

    def _execute_serving_action(self, goal_handle):
        goal = goal_handle.request
        payload = {
            'event_id': goal.event_id.strip(),
            'drink_id': goal.drink_id,
            'order_id': goal.order_id,
            'target_table': goal.target_table.strip(),
            'via_pickup': bool(goal.via_pickup),
            'has_drink': bool(goal.has_drink),
        }
        result = Serving.Result()
        progress_seen = False
        final_state = ''
        try:
            start_state_seq = self._serving_state_seq
            start = self._handle_serving_payload(payload, trigger_source='action')
            if not bool(start.get('success')):
                result.success = False
                result.code = str(start.get('code', 'REJECTED'))
                result.message = str(start.get('message', 'serving request rejected'))
                result.final_state = ''
                goal_handle.abort()
                return result

            deadline = time.time() + self._serving_action_timeout_sec
            last_feedback_key = None
            while time.time() < deadline:
                if goal_handle.is_cancel_requested:
                    result.success = False
                    result.code = 'CANCELED'
                    result.message = 'serving action canceled'
                    result.final_state = final_state
                    goal_handle.canceled()
                    return result

                state_json = dict(self._last_serving_state_json)
                final_state = str(state_json.get('state', final_state or ''))
                if self.current_mode == 'serving' and final_state in (
                    'navigating', 'dwell', 'returning',
                ):
                    progress_seen = True

                feedback = Serving.Feedback()
                feedback.state = final_state
                feedback.current_table = str(state_json.get('current_table') or '')
                feedback.home_registered = bool(state_json.get('home_registered', False))
                feedback.message = str(start.get('message', ''))
                feedback_key = (
                    feedback.state,
                    feedback.current_table,
                    feedback.home_registered,
                    feedback.message,
                )
                if feedback_key != last_feedback_key:
                    goal_handle.publish_feedback(feedback)
                    last_feedback_key = feedback_key

                if progress_seen and self.current_mode == 'idle':
                    result.success = True
                    result.code = 'OK'
                    result.message = 'serving completed'
                    result.final_state = final_state or 'idle'
                    goal_handle.succeed()
                    return result

                if self._serving_failed_before_progress(
                    state_json, progress_seen, start_state_seq):
                    idle_result = self._request_mode(
                        'idle', {}, override_priority=True)
                    result.success = False
                    result.code = 'SERVING_NO_PROGRESS'
                    result.message = (
                        'serving dispatcher returned idle before navigation '
                        f'progress; idle_result={idle_result}')
                    result.final_state = final_state or 'idle'
                    goal_handle.abort()
                    return result

                time.sleep(0.2)

            result.success = False
            result.code = 'TIMEOUT'
            result.message = 'serving action timed out'
            result.final_state = final_state
            goal_handle.abort()
            return result
        finally:
            with self._action_lock:
                self._active_serving_action = False

    def _on_request_guiding(self, request, response):
        event_id = request.event_id.strip()
        if event_id and self._event_seen(event_id):
            response.success = False
            response.code = 'DUPLICATE_EVENT'
            response.message = 'event_id already processed'
            response.assigned_table = ''
            response.mode_requested = False
            return response
        if event_id:
            self._event_mark(event_id)

        assigned = self._assign_table(request.preferred_table.strip())
        payload = {
            'event_id': event_id,
            'customer_id': request.customer_id,
            'preferred_table': request.preferred_table,
            'party_size': int(request.party_size),
            'assigned_table': assigned,
        }
        if not assigned:
            self._publish_event('pos', 'guide_request', payload, 'rejected:no_empty_table')
            response.success = False
            response.code = 'NO_EMPTY_TABLE'
            response.message = 'all tables occupied'
            response.assigned_table = ''
            response.mode_requested = False
            return response

        result = self._request_mode(
            'guiding',
            {'target_table': assigned, 'customer_id': request.customer_id},
            override_priority=False,
        )
        response.success = bool(result.get('ok'))
        response.code = 'OK' if response.success else result.get('code', 'REJECTED')
        response.message = result.get('message', result.get('reason', ''))
        response.assigned_table = assigned
        response.mode_requested = response.success
        self._publish_event(
            'pos',
            'guide_request',
            payload,
            'accepted' if response.success else f'rejected:{response.code}',
        )
        return response

    def _on_get_table_status(self, request, response):
        table_id = request.table_id.strip()
        if table_id and table_id not in self._tables:
            response.success = False
            response.status_json = json.dumps({'error': f'unknown table: {table_id}'})
            return response
        response.success = True
        value: Any = self._tables[table_id] if table_id else list(self._tables.values())
        response.status_json = json.dumps(value, ensure_ascii=False)
        return response

    def _on_set_patrol_schedule(self, request, response):
        self.config.patrol_interval_minutes = float(request.interval_minutes)
        self.config.patrol_enabled = bool(request.enabled)
        self.config.business_hours = request.active_hours or ''
        response.success = True
        response.reason = ''
        self._publish_event('operator', 'patrol_schedule', {
            'interval_minutes': self.config.patrol_interval_minutes,
            'enabled': self.config.patrol_enabled,
            'active_hours': self.config.business_hours,
        }, 'accepted')
        return response

    # ---------- task flow ----------

    def _start_serving(self, payload: dict[str, Any], trigger_source: str) -> dict[str, Any]:
        self._current_serving_has_drink = bool(payload.get('has_drink', True))
        if bool(payload.get('via_pickup', True)):
            if self._pickup_in_progress:
                return {'ok': False, 'code': 'PICKUP_IN_PROGRESS', 'message': 'pickup action already running'}
            self._pickup_in_progress = True
            pickup_result: dict[str, Any] | None = None

            def on_pickup_done(ok: bool, msg: str) -> None:
                nonlocal pickup_result
                pickup_result = self._after_pickup(ok, msg, payload, trigger_source)

            self._send_pickup_goal(
                has_drink=self._current_serving_has_drink,
                done_cb=on_pickup_done,
            )
            if pickup_result is not None:
                return pickup_result
            return {'ok': True, 'message': 'pickup requested', 'mode_requested': False}

        return self._request_serving_mode(payload, trigger_source)

    def _after_pickup(self, success: bool, message: str, payload: dict[str, Any],
                      trigger_source: str) -> dict[str, Any]:
        self._pickup_in_progress = False
        if not success:
            self.get_logger().warn(f'pickup failed: {message}')
            self._publish_event(trigger_source, 'pickup_ready', payload, f'rejected:pickup:{message}')
            return {'ok': False, 'code': 'PICKUP_FAILED', 'message': message}
        result = self._request_serving_mode(payload, trigger_source)
        self._publish_event(
            trigger_source,
            'pickup_ready',
            payload,
            'accepted' if result.get('ok') else f'rejected:{result.get("code", "MODE_REJECTED")}',
        )
        return result

    def _request_serving_mode(self, payload: dict[str, Any], trigger_source: str) -> dict[str, Any]:
        del trigger_source
        return self._request_mode(
            'serving',
            {
                'waypoint': payload['target_table'],
                'via_pickup': bool(payload.get('via_pickup', True)),
                'has_drink': bool(payload.get('has_drink', True)),
                'drink_id': payload.get('drink_id', ''),
                'order_id': payload.get('order_id', ''),
            },
            override_priority=False,
        )

    # ---------- completion / patrol timers ----------

    def _tick(self) -> None:
        self._tick_completion()
        self._tick_idle_patrol()

    def _tick_completion(self) -> None:
        now = time.time()
        if self.current_mode == 'serving' and self._serving_done_started_at is not None:
            if now - self._serving_done_started_at >= self.config.completion_dwell_serving:
                self._serving_done_started_at = None
                if 'serving' not in self._completion_running:
                    self._completion_running.add('serving')
                    self._send_serve_then_idle()

        for mode in ('patrol', 'guiding', 'engaging'):
            started = self._mode_done_started_at[mode]
            if self.current_mode != mode:
                self._mode_done_started_at[mode] = None
                continue
            dwell = getattr(self.config, f'completion_dwell_{mode}')
            if started is not None and now - started >= dwell:
                self._mode_done_started_at[mode] = None
                self._request_idle_after_completion(mode, override_priority=False)

    def _tick_idle_patrol(self) -> None:
        if self.current_mode != 'idle' or self._idle_entered_at is None:
            return
        if not self.config.patrol_enabled or not _in_business_hours(self.config.business_hours):
            return
        if self.battery_pct is not None and self.battery_pct >= 0.0 and self.battery_pct < self.config.battery_min:
            return
        elapsed = time.time() - self._idle_entered_at
        if elapsed < self.config.patrol_interval_minutes * 60.0:
            return
        self._idle_entered_at = None
        result = self._request_mode('patrol', {'sweep_mode': 'all'}, override_priority=False)
        self._publish_event(
            'timer',
            'patrol_timer',
            {'idle_elapsed_sec': round(elapsed, 1), 'result': result},
            'accepted' if result.get('ok') else f'rejected:{result.get("code", "MODE_REJECTED")}',
        )

    # ---------- ROS callbacks ----------

    def _on_mode_state(self, msg: ModeState) -> None:
        previous = self.current_mode
        self.current_mode = msg.current_mode
        self.safety_ok = bool(msg.safety_ok)
        try:
            self.mode_params = json.loads(msg.params) if msg.params else {}
        except Exception:
            self.mode_params = {}
        if self.current_mode == 'idle':
            if previous != 'idle' or self._idle_entered_at is None:
                self._idle_entered_at = time.time()
            self._serving_progress_seen = False
            self._serving_done_started_at = None
            self._current_serving_has_drink = False
        else:
            self._idle_entered_at = None
        if self.current_mode == 'serving':
            self._current_serving_has_drink = bool(self.mode_params.get('has_drink', True))

    def _on_serving_state(self, msg: String) -> None:
        try:
            data = json.loads(msg.data) if msg.data else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {'value': data}
        self._last_serving_state_json = dict(data)
        self._serving_state_seq += 1
        state = str(data.get('state', ''))
        if self.current_mode != 'serving':
            self._serving_done_started_at = None
            return
        if state in ('navigating', 'dwell', 'returning'):
            self._serving_progress_seen = True
            self._serving_done_started_at = None
        elif state == 'idle' and self._serving_progress_seen:
            if self._serving_done_started_at is None:
                self._serving_done_started_at = time.time()

    def _serving_failed_before_progress(
        self,
        state_json: dict[str, Any],
        progress_seen: bool,
        start_state_seq: int,
    ) -> bool:
        if progress_seen or self._serving_state_seq <= start_state_seq:
            return False
        if self.current_mode != 'serving':
            return False
        if str(state_json.get('state', '')) != 'idle':
            return False
        if state_json.get('current_table'):
            return False
        queue = state_json.get('queue', [])
        return not queue

    def _on_patrol_state(self, msg: PatrolState) -> None:
        self._observe_mode_done('patrol', msg.current_state)

    def _on_guiding_state(self, msg: GuidingState) -> None:
        self._observe_mode_done('guiding', msg.current_state)

    def _observe_mode_done(self, mode: str, state: str) -> None:
        if self.current_mode != mode:
            self._mode_done_started_at[mode] = None
            return
        if state in DONE_SIGNALS[mode]:
            if self._mode_done_started_at[mode] is None:
                self._mode_done_started_at[mode] = time.time()
        else:
            self._mode_done_started_at[mode] = None

    def _on_table_report(self, msg: TableReport) -> None:
        if msg.table_id not in self._tables:
            return
        self._tables[msg.table_id].update({
            'occupancy': msg.occupancy,
            'person_count': int(msg.person_count),
            'dishes_detected': bool(msg.dishes_detected),
            'confidence': float(msg.confidence),
            'last_update': datetime.now().isoformat(timespec='seconds'),
        })

    def _on_battery(self, msg: BatteryState) -> None:
        self.battery_pct = float(msg.percentage)

    # ---------- temporarily disabled single_arm action helpers ----------

    def _send_pickup_goal(self, has_drink: bool, done_cb: Callable[[bool, str], None]) -> None:
        del has_drink
        self.get_logger().warn('pickup action is temporarily disabled; continuing without pickup')
        done_cb(True, 'pickup action disabled')

    def _send_serve_then_idle(self) -> None:
        self.get_logger().warn('serve action is temporarily disabled; returning idle directly')
        self._after_serve(True, 'serve action disabled')

    def _on_action_goal(self, future, done_cb: Callable[[bool, str], None], name: str) -> None:
        del future
        done_cb(False, f'{name}_action_disabled')

    def _on_action_result(self, future, done_cb: Callable[[bool, str], None], name: str) -> None:
        del future
        done_cb(False, f'{name}_action_disabled')

    def _after_serve(self, success: bool, message: str) -> None:
        self.get_logger().info(f'serve action done success={success} message={message}')
        self._completion_running.discard('serving')
        self._request_idle_after_completion('serving', override_priority=True)

    # ---------- mode / event helpers ----------

    def _request_mode(self, mode: str, params: dict[str, Any] | None = None, *, override_priority: bool) -> dict[str, Any]:
        if not self._set_mode.wait_for_service(timeout_sec=1.0):
            return {'ok': False, 'code': 'MODE_SERVICE_UNAVAILABLE', 'message': '/mode/request unavailable'}
        req = SetMode.Request()
        req.requested_mode = mode
        req.params = json.dumps(params or {}, ensure_ascii=False) if params else ''
        req.override_priority = bool(override_priority)
        future = self._set_mode.call_async(req)
        deadline = time.time() + self.config.setmode_timeout_sec
        while time.time() < deadline:
            if future.done():
                resp = future.result()
                return {
                    'ok': bool(resp.success),
                    'reason': resp.reason,
                    'current_mode_after': resp.current_mode,
                    'code': 'OK' if resp.success else resp.reason,
                    'message': resp.reason,
                }
            time.sleep(0.02)
        return {'ok': False, 'code': 'MODE_REQUEST_TIMEOUT', 'message': 'set mode request timed out'}

    def _request_idle_after_completion(self, completed_mode: str, *, override_priority: bool) -> None:
        result = self._request_mode('idle', {}, override_priority=override_priority)
        self._publish_event(
            'timer',
            'completion_idle',
            {'completed_mode': completed_mode, 'result': result},
            'accepted' if result.get('ok') else f'rejected:{result.get("code", "MODE_REJECTED")}',
        )

    def _publish_event(self, source: str, event_type: str, payload: dict[str, Any], outcome: str) -> None:
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
        self._event_pub.publish(msg)

    def _event_seen(self, event_id: str) -> bool:
        return event_id in self._seen_event_ids

    def _event_mark(self, event_id: str) -> None:
        self._seen_event_ids[event_id] = time.time()

    def _assign_table(self, preferred: str) -> str:
        if preferred in self._tables and self._tables[preferred]['occupancy'] in ('empty', 'unknown'):
            return preferred
        for status in ('empty', 'unknown'):
            for table_id, table in self._tables.items():
                if table['occupancy'] == status:
                    return table_id
        return ''


def main(args=None):
    rclpy.init(args=args)
    node = TaskOrchestratorNode()
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
