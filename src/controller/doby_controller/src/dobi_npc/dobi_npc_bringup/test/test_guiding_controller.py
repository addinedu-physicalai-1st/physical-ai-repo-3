"""test_guiding_controller — FSM + lag 계산 + Nav2/persons mock 단위 테스트.

디자인 시나리오: docs/moca_guiding_design.md §9.1

전략 — patrol_scheduler 테스트와 동일:
  rclpy.init + 실 Node + act_nav MagicMock + parameter override.

실행:
  source install/setup.bash
  python3 -m pytest src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py -v
"""

import math
import time
from unittest.mock import MagicMock

import pytest
import rclpy
import yaml

from dobi_npc_msgs.msg import RapportEvent

from dobi_npc_bringup.guiding_controller_node import (
    FACE_BY_STATE,
    GuidingController,
    GUIDING_UTTER_PRIORITY_NORMAL,
    GUIDING_UTTER_PRIORITY_URGENT,
    State,
)


# ──────────────── fixtures ────────────────

SAMPLE_TABLES = {
    'home_pose': {
        'frame_id': 'map',
        'x': -36.887, 'y': 2.809, 'yaw': -1.5708,
    },
    'tables': [
        {'id': 'T01', 'pose': {'frame_id': 'map', 'x': -36.3, 'y': 0.5, 'yaw': 0.0},
         'approach_dist': 0.5},
        {'id': 'T02', 'pose': {'frame_id': 'map', 'x': -41.0, 'y': 0.2, 'yaw': 0.0},
         'approach_dist': 0.5},
    ],
}


@pytest.fixture(scope='module')
def rclpy_setup():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def tables_yaml(tmp_path):
    p = tmp_path / 'tables.yaml'
    p.write_text(yaml.safe_dump(SAMPLE_TABLES, allow_unicode=True))
    return str(p)


def _make_controller(
    tables_yaml_path: str,
    target_table: str = 'T01',
    customer_id: str = 'C-test',
) -> GuidingController:
    """parameter override + Nav2 mock 으로 controller 인스턴스화."""
    from rclpy.parameter import Parameter
    import json as _json

    params_json = _json.dumps({
        'target_table': target_table,
        'customer_id': customer_id,
    })

    g = GuidingController()
    g.set_parameters([
        Parameter('tables_yaml', Parameter.Type.STRING, tables_yaml_path),
        Parameter('params_json', Parameter.Type.STRING, params_json),
    ])
    # __init__ 가 이미 tables 와 params 를 빈 값으로 load 했음. 재실행.
    g._tables.clear()
    g._target_table_id = None
    g._customer_id = ''
    g._load_tables()
    g._parse_params()

    # Nav2 mock
    g.act_nav = MagicMock()
    g.act_nav.wait_for_server.return_value = True
    idle_send_future = MagicMock()
    idle_send_future.add_done_callback = MagicMock()
    g.act_nav.send_goal_async.return_value = idle_send_future

    # state INIT 으로 reset
    g._state = State.INIT
    g._customer_xy = None
    g._last_seen_at = None
    g._customer_in_sight = False
    g._robot_pose = None
    g._target_pose = None
    g._nav_goal_handle = None
    g._last_utter_at = {}
    return g


@pytest.fixture
def controller(rclpy_setup, tables_yaml):
    g = _make_controller(tables_yaml, target_table='T01')
    yield g
    g.destroy_node()


def _make_nav_result(status: int):
    fut = MagicMock()
    result = MagicMock()
    result.status = status
    fut.result.return_value = result
    return fut


# ──────────────── 1. 입력 검증 ────────────────

def test_load_tables_yaml(controller):
    """tables.yaml 의 T01/T02 + approach_dist 로드 확인."""
    assert set(controller._tables.keys()) == {'T01', 'T02'}
    assert controller._target_table_id == 'T01'
    assert controller._customer_id == 'C-test'


def test_invalid_target_table_goes_to_aborted(rclpy_setup, tables_yaml):
    """params 의 target_table 이 tables.yaml 에 없으면 ABORTED 진입."""
    g = _make_controller(tables_yaml, target_table='T99')
    # __init__ 안 LOCK_ON 전이 시 invalid check
    # Mock setup 이후 다시 transition (생성 시 _state=INIT 으로 reset 했으므로)
    # invalid 이면 _transition(ABORTED) — 코드의 __init__ 끝부분 분기
    if g._target_table_id and g._target_table_id in g._tables:
        g._transition(State.LOCK_ON)
    else:
        g._transition(State.ABORTED)
    assert g._state == State.ABORTED
    assert g._last_utter_text.startswith('어디 가셨어요')
    g.destroy_node()


def test_build_approach_pose_backward_offset(controller):
    """approach_dist=0.5, yaw=0 → x - 0.5*cos(0) = x - 0.5."""
    pose = controller._build_approach_pose('T01')
    assert pose is not None
    assert pose.pose.position.x == pytest.approx(-36.8, abs=0.01)
    assert pose.pose.position.y == pytest.approx(0.5, abs=0.01)


# ──────────────── 2. FSM transition ────────────────

def test_lock_on_no_customer_then_timeout(controller):
    """LOCK_ON 진입 후 customer_xy 없이 timeout 경과 → ABORTED."""
    controller._transition(State.LOCK_ON)
    assert controller._state == State.LOCK_ON
    # state_entered_at 을 과거로 옮겨 timeout 이미 경과 시뮬
    from rclpy.duration import Duration
    controller._state_entered_at = controller.get_clock().now() - Duration(seconds=20)
    controller._tick()
    assert controller._state == State.ABORTED


def test_lock_on_customer_detected_advances_to_moving(controller):
    """LOCK_ON 에서 customer_xy 검출되면 즉시 MOVING."""
    controller._transition(State.LOCK_ON)
    controller._customer_xy = (-36.0, 1.0)
    controller._tick()
    assert controller._state == State.MOVING


def test_moving_customer_lost_aborts(controller):
    """MOVING 중 customer_lost > 8s → ABORTED."""
    controller._state = State.MOVING
    controller._state_entered_at = controller.get_clock().now()
    # 마지막 본 시각을 9초 전으로
    from rclpy.duration import Duration
    controller._last_seen_at = controller.get_clock().now() - Duration(seconds=10)
    controller._tick()
    assert controller._state == State.ABORTED


def test_moving_lag_exceeds_max_transitions_to_waiting(controller):
    """MOVING + lag > 1.5m → WAITING."""
    controller._state = State.MOVING
    controller._state_entered_at = controller.get_clock().now()
    controller._last_seen_at = controller.get_clock().now()
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._target_pose = MagicMock()
    controller._target_pose.pose.position.x = 10.0
    controller._target_pose.pose.position.y = 0.0
    # customer 가 로봇 뒤 2m (lag = 2.0)
    controller._customer_xy = (-2.0, 0.0)
    controller._tick()
    assert controller._state == State.WAITING


def test_waiting_lag_recovers_resumes_moving(controller):
    """WAITING + lag < 1.0m → MOVING 재진입."""
    controller._state = State.WAITING
    controller._state_entered_at = controller.get_clock().now()
    controller._last_seen_at = controller.get_clock().now()
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._target_pose = MagicMock()
    controller._target_pose.pose.position.x = 10.0
    controller._target_pose.pose.position.y = 0.0
    # customer 가 거의 로봇 위치 (lag = 0.5)
    controller._customer_xy = (-0.5, 0.0)
    controller._tick()
    assert controller._state == State.MOVING


def test_arrived_dwell_advances_to_done(controller):
    """ARRIVED 진입 후 dwell 경과 → DONE."""
    controller._state = State.ARRIVED
    from rclpy.duration import Duration
    # arrival_dwell_sec=5.0 default — 6초 전 entered
    controller._state_entered_at = controller.get_clock().now() - Duration(seconds=6)
    controller._tick()
    assert controller._state == State.DONE


# ──────────────── 3. Nav2 callback ────────────────

def test_nav_succeeded_transitions_arrived(controller):
    """_on_nav_result(status=4) + state=MOVING → ARRIVED."""
    controller._state = State.MOVING
    controller._on_nav_result(_make_nav_result(status=4))
    assert controller._state == State.ARRIVED


def test_nav_aborted_transitions_aborted(controller):
    """_on_nav_result(status=6) + state=MOVING → ABORTED."""
    controller._state = State.MOVING
    controller._on_nav_result(_make_nav_result(status=6))
    assert controller._state == State.ABORTED


def test_nav_canceled_no_transition_during_waiting(controller):
    """_on_nav_result(status=5 CANCELED) — WAITING 진입 시 우리가 cancel, state 그대로."""
    controller._state = State.WAITING
    controller._on_nav_result(_make_nav_result(status=5))
    assert controller._state == State.WAITING


# ──────────────── 4. lag 계산 ────────────────

def test_compute_lag_positive_when_customer_behind(controller):
    """target=(10,0), robot=(0,0), customer=(-2,0) → lag=+2.0."""
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._target_pose = MagicMock()
    controller._target_pose.pose.position.x = 10.0
    controller._target_pose.pose.position.y = 0.0
    controller._customer_xy = (-2.0, 0.0)
    lag = controller._compute_lag()
    assert lag == pytest.approx(2.0, abs=0.01)


def test_compute_lag_negative_when_customer_ahead(controller):
    """target=(10,0), robot=(0,0), customer=(5,0) → lag=-5.0 (앞섬)."""
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._target_pose = MagicMock()
    controller._target_pose.pose.position.x = 10.0
    controller._target_pose.pose.position.y = 0.0
    controller._customer_xy = (5.0, 0.0)
    lag = controller._compute_lag()
    assert lag == pytest.approx(-5.0, abs=0.01)


def test_compute_lag_zero_without_data(controller):
    """robot 또는 target 미수신 → lag=0."""
    controller._robot_pose = None
    controller._target_pose = None
    controller._customer_xy = (1.0, 1.0)
    assert controller._compute_lag() == 0.0


# ──────────────── 5. rapport abort ────────────────

def test_rapport_abort_triggers_aborted(controller):
    """rapport abort_trigger → ABORTED + Nav2 cancel."""
    controller._state = State.MOVING
    msg = RapportEvent()
    msg.event_type = 'abort_trigger'
    msg.weight = -0.7
    controller._on_rapport(msg)
    assert controller._state == State.ABORTED


def test_rapport_non_abort_event_ignored(controller):
    """abort 외 이벤트는 무시."""
    controller._state = State.MOVING
    msg = RapportEvent()
    msg.event_type = 'engagement_up'
    controller._on_rapport(msg)
    assert controller._state == State.MOVING


def test_rapport_abort_during_done_ignored(controller):
    """DONE/ABORTED/INIT 상태에서는 abort 무시."""
    for ignore in (State.DONE, State.ABORTED, State.INIT):
        controller._state = ignore
        msg = RapportEvent()
        msg.event_type = 'abort_trigger'
        controller._on_rapport(msg)
        assert controller._state == ignore


# ──────────────── 6. utter (UtterRequest 발행) ────────────────

def test_utter_publishes_with_face_expression(controller):
    """_utter 발행 시 face_expression 이 state 매핑값으로 채워짐."""
    published = []
    controller.pub_utter.publish = lambda msg: published.append(msg)
    controller._state = State.MOVING
    controller._utter('테스트 발화', priority=GUIDING_UTTER_PRIORITY_NORMAL)
    assert len(published) == 1
    msg = published[0]
    assert msg.text == '테스트 발화'
    assert msg.face_expression == 'happy'   # MOVING → happy
    assert msg.source == 'guiding'
    assert msg.priority == GUIDING_UTTER_PRIORITY_NORMAL
    assert msg.preempt is False


def test_utter_cooldown_blocks_repeat(controller):
    """utter_cooldown_sec 안 같은 텍스트 재발행 차단."""
    published = []
    controller.pub_utter.publish = lambda msg: published.append(msg)
    controller._state = State.MOVING
    controller._utter('반복 발화', priority=GUIDING_UTTER_PRIORITY_NORMAL)
    controller._utter('반복 발화', priority=GUIDING_UTTER_PRIORITY_NORMAL)
    assert len(published) == 1


def test_utter_face_by_state_mapping():
    """FACE_BY_STATE 매핑 — CLAUDE.md §4.2 8 어휘 (basic/happy/interest/sad)."""
    # 디자인 §5.3 매핑 → CLAUDE.md 8 어휘 정합
    assert FACE_BY_STATE[State.LOCK_ON] == 'basic'
    assert FACE_BY_STATE[State.MOVING] == 'happy'
    assert FACE_BY_STATE[State.WAITING] == 'interest'
    assert FACE_BY_STATE[State.ARRIVED] == 'happy'
    assert FACE_BY_STATE[State.ABORTED] == 'sad'


# ──────────────── 7. 거리 계산 헬퍼 ────────────────

def test_distance_to_customer(controller):
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._customer_xy = (3.0, 4.0)
    assert controller._distance_to_customer() == pytest.approx(5.0, abs=0.01)


def test_distance_to_customer_unknown_when_no_data(controller):
    controller._robot_pose = None
    controller._customer_xy = None
    assert controller._distance_to_customer() == -1.0


def test_distance_to_target(controller):
    controller._robot_pose = (0.0, 0.0, 0.0)
    controller._target_pose = MagicMock()
    controller._target_pose.pose.position.x = 6.0
    controller._target_pose.pose.position.y = 8.0
    assert controller._distance_to_target() == pytest.approx(10.0, abs=0.01)


# ──────────────── 8. State enum sanity ────────────────

def test_state_enum_values_match_spec():
    """디자인 §2.3 7-state FSM."""
    expected = {'init', 'lock_on', 'moving', 'waiting', 'arrived', 'done', 'aborted'}
    assert {s.value for s in State} == expected
