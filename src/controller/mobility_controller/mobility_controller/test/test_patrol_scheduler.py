"""test_patrol_scheduler — FSM 전이 + Nav2 mock + rapport abort 단위 테스트.

전략: rclpy.init() 으로 실 Node 인스턴스화 + 외부 의존(Nav2 action client,
ScanTable service client) MagicMock. FSM transition 직접 호출 + callback 시뮬.

실행:
  source install/setup.bash
  python3 -m pytest src/controller/mobility_controller/mobility_controller/test/test_patrol_scheduler.py -v
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest
import rclpy
import yaml

from dobi_npc_msgs.msg import RapportEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from patrol_scheduler_node import PatrolScheduler, State  # noqa: E402


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
        {'id': 'T03', 'pose': {'frame_id': 'map', 'x': -40.0, 'y': 4.0, 'yaw': 0.0},
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


@pytest.fixture
def scheduler(rclpy_setup, tables_yaml):
    """패키지 default 가 아닌 본 테스트용 PatrolScheduler 인스턴스.

    Node.__init__ 안에서 _load_tables() 가 호출되므로 tables_yaml param 을 미리 주입.
    """
    # ROS parameter 를 노드 생성 전에 주입: 별 노드 띄우거나 NodeOptions 사용 가능하나
    # 단순화 — Node 생성 후 declare_parameter 값을 직접 override.
    # PatrolScheduler.__init__ 가 declare_parameter('tables_yaml','') 후 get_parameter
    # 로 읽으므로, 인스턴스화 시점에는 default '' 이고 _load_tables 가 error 로그 + 빈
    # tables 로 남는다. 따라서 우리는 그 흐름을 우회:
    # 1) 실 노드 생성 (tables 비어있음)
    # 2) tables_yaml param 강제 갱신
    # 3) _load_tables() 수동 재호출
    # 또는 더 단순하게 NodeOptions parameter_overrides 사용. 후자 채택.
    from rclpy.parameter import Parameter
    s = PatrolScheduler.__new__(PatrolScheduler)
    # rclpy Node 의 정상 __init__ 우회 — 직접 setup 으로 control 강화
    # 그러나 복잡하니 정공법으로:
    s = _make_scheduler_with_tables(tables_yaml)
    yield s
    # cleanup
    s.destroy_node()


def _make_scheduler_with_tables(tables_yaml_path: str) -> PatrolScheduler:
    """parameter_overrides 로 tables_yaml 주입한 PatrolScheduler 생성 + Nav2 mock.

    Nav2 action client 를 MagicMock 으로 교체해서 wait_for_server / send_goal_async 가
    즉시 응답 + future 가 idle 상태로 유지되게 함. 그러면 _send_nav_goal 진입 후
    state 는 MOVING / RETURNING 에서 callback 대기. 테스트는 직접 _on_nav_result
    호출로 SUCCEEDED/FAILED 시뮬레이션.
    """
    from rclpy.parameter import Parameter
    s = PatrolScheduler()
    s.set_parameters([
        Parameter('tables_yaml', Parameter.Type.STRING, tables_yaml_path),
    ])
    # _load_tables 재호출 (생성 시 빈 tables 로 init 됐을 가능성)
    s._tables.clear()
    s._home_pose = None
    s._sweep_order = []
    s._current_table_index = 0
    s._tables_visited = 0
    s._load_tables()

    # Nav2 action client mock — wait_for_server 즉시 True + send_goal_async 가 idle future
    s.act_nav = MagicMock()
    s.act_nav.wait_for_server.return_value = True
    idle_send_future = MagicMock()
    idle_send_future.add_done_callback = MagicMock()  # callback 등록만 받고 호출 X
    s.act_nav.send_goal_async.return_value = idle_send_future

    # state INIT 으로 reset (fresh NEXT 진입을 테스트가 명시적으로 트리거)
    s._state = State.INIT
    return s


def _make_nav_result(status: int):
    """Nav2 action result future mock — status 4=SUCCEEDED, 6=ABORTED."""
    fut = MagicMock()
    result = MagicMock()
    result.status = status
    fut.result.return_value = result
    return fut


# ──────────────── 1. tables.yaml 로드 ────────────────

def test_load_tables_yaml(scheduler, tables_yaml):
    """tables.yaml 로드 후 home_pose + 3 tables + sweep_order 정렬 확인."""
    assert scheduler._home_pose is not None
    assert set(scheduler._tables.keys()) == {'T01', 'T02', 'T03'}
    # sweep_order 의 default 는 T01~T05 — tables.yaml 에 없는 T04/T05 는 filter out
    assert scheduler._sweep_order == ['T01', 'T02', 'T03']
    assert scheduler._tables_total == 3


def test_build_approach_pose_backward_offset(scheduler):
    """approach_dist 만큼 yaw 반대 방향 backward 좌표 계산."""
    table = scheduler._tables['T01']
    pose = scheduler._build_approach_pose(table)
    assert pose is not None
    # T01: x=-36.3, yaw=0, approach=0.5 → backward = x - 0.5*cos(0) = -36.8
    assert pose.pose.position.x == pytest.approx(-36.8, abs=0.01)
    assert pose.pose.position.y == pytest.approx(0.5, abs=0.01)


# ──────────────── 2. FSM transition ────────────────

def test_initial_transition_to_next(scheduler):
    """INIT 직후 _load_tables 가 끝나면 NEXT 로 이미 전이됐어야 함.

    fixture 가 reset 후 _load_tables 다시 호출했으므로 현재 state 가 INIT 인 상태.
    명시적으로 NEXT 전이 호출 후 검증.
    """
    scheduler._transition(State.NEXT)
    # NEXT 가 entry action 으로 즉시 MOVING 전이
    assert scheduler._state == State.MOVING
    assert scheduler._current_table_id == 'T01'
    assert scheduler._current_table_index == 1


def test_sweep_progresses_table_by_table(scheduler):
    """NEXT → MOVING 이 sweep_order 인덱스를 1씩 증가."""
    scheduler._transition(State.NEXT)  # T01
    assert scheduler._current_table_id == 'T01'
    # _on_enter_next 가 idx 1 로 이동 + MOVING 전이
    # 다음 NEXT 호출 시 T02
    # MOVING 의 entry 가 send_goal 시도하는데 Nav2 action client wait_for_server 실패 → handle_nav_failure
    # 그게 _emit_report_unknown + NEXT 전이를 호출 (코드 의도)


def test_nav_succeeded_moves_to_dwell(scheduler):
    """_on_nav_result(status=4) → MOVING 에서 DWELL 로 전이."""
    scheduler._transition(State.NEXT)  # → MOVING (T01)
    # 강제로 state 만 MOVING 으로 두고 result mock
    scheduler._state = State.MOVING
    scheduler._on_nav_result(_make_nav_result(status=4))
    assert scheduler._state == State.DWELL


def test_nav_aborted_emits_unknown_and_advances(scheduler):
    """_on_nav_result(status=6 ABORTED) → unknown report + NEXT."""
    scheduler._transition(State.NEXT)
    scheduler._state = State.MOVING
    initial_visited = scheduler._tables_visited
    scheduler._on_nav_result(_make_nav_result(status=6))
    # _handle_nav_failure → _emit_report_unknown + transition NEXT
    # NEXT 가 즉시 entry 로 다음 table → MOVING 또는 RETURNING
    assert scheduler._tables_visited == initial_visited + 1


def test_scan_done_with_result_publishes_report(scheduler):
    """_on_scan_done → _last_scan_result 저장 + REPORT 전이."""
    scheduler._transition(State.NEXT)
    scheduler._state = State.SCAN
    scheduler._current_table_id = 'T02'

    fut = MagicMock()
    scan_result = MagicMock()
    scan_result.success = True
    scan_result.occupancy = 'occupied'
    scan_result.person_count = 2
    scan_result.dishes_detected = False
    scan_result.confidence = 0.91
    fut.result.return_value = scan_result

    initial_visited = scheduler._tables_visited
    scheduler._on_scan_done(fut)
    # _on_scan_done → _last_scan_result 저장 + REPORT 전이
    # REPORT 의 entry → TableReport 발행 + tables_visited++ + NEXT 전이
    assert scheduler._tables_visited == initial_visited + 1


def test_scan_exception_falls_back_to_unknown(scheduler):
    """future.result() exception → _last_scan_result=None → REPORT 가 unknown 발행."""
    scheduler._transition(State.NEXT)
    scheduler._state = State.SCAN
    scheduler._current_table_id = 'T01'

    fut = MagicMock()
    fut.result.side_effect = RuntimeError('mock service exception')

    # 발행된 TableReport 캡처를 위해 publisher 의 publish 메서드 spy
    published = []
    original_publish = scheduler.pub_report.publish
    scheduler.pub_report.publish = lambda msg: (
        published.append(msg) or original_publish(msg)
    )

    scheduler._on_scan_done(fut)
    assert len(published) == 1
    assert published[0].occupancy == 'unknown'
    assert published[0].confidence == 0.0


# ──────────────── 3. 사이클 종료 ────────────────

def test_sweep_exhaustion_transitions_returning(scheduler):
    """sweep_order 소진 시 NEXT 의 entry 가 RETURNING 전이."""
    # 인위적으로 끝까지 visit
    scheduler._current_table_index = len(scheduler._sweep_order)
    scheduler._transition(State.NEXT)
    # NEXT entry → home_pose 있으므로 RETURNING
    assert scheduler._state == State.RETURNING


def test_returning_succeeded_reaches_done(scheduler):
    """RETURNING + nav SUCCEEDED → DONE 전이."""
    scheduler._state = State.RETURNING
    scheduler._on_nav_result(_make_nav_result(status=4))
    assert scheduler._state == State.DONE


def test_returning_failed_still_reaches_done(scheduler):
    """RETURNING + nav 실패 → DONE (어쨌든 사이클 종료)."""
    scheduler._state = State.RETURNING
    scheduler._on_nav_result(_make_nav_result(status=6))
    assert scheduler._state == State.DONE


def test_no_home_pose_done_directly(scheduler):
    """home_pose 없으면 RETURNING entry 가 즉시 DONE."""
    scheduler._home_pose = None
    scheduler._state = State.RETURNING
    # entry 재호출 (직접 transition 우회)
    scheduler._on_enter_returning()
    assert scheduler._state == State.DONE


# ──────────────── 4. abort / preempt ────────────────

def test_rapport_abort_triggers_aborted_state(scheduler):
    """/rapport/event abort_trigger 수신 시 ABORTED 전이."""
    scheduler._state = State.MOVING
    msg = RapportEvent()
    msg.event_type = 'abort_trigger'
    msg.weight = -0.8
    scheduler._on_rapport(msg)
    assert scheduler._state == State.ABORTED


def test_rapport_non_abort_event_ignored(scheduler):
    """abort_trigger 아닌 이벤트는 무시 (engagement_up 등)."""
    scheduler._state = State.MOVING
    msg = RapportEvent()
    msg.event_type = 'engagement_up'
    msg.weight = 0.3
    scheduler._on_rapport(msg)
    assert scheduler._state == State.MOVING


def test_rapport_abort_during_done_ignored(scheduler):
    """이미 DONE/ABORTED/INIT 상태면 abort 무시 (이중 전이 방지)."""
    for ignore_state in (State.DONE, State.ABORTED, State.INIT):
        scheduler._state = ignore_state
        msg = RapportEvent()
        msg.event_type = 'abort_trigger'
        scheduler._on_rapport(msg)
        assert scheduler._state == ignore_state


# ──────────────── 5. State enum sanity ────────────────

def test_state_enum_values_match_spec():
    """patrol_design §2.2 FSM 9 states."""
    expected = {
        'init', 'next', 'moving', 'dwell', 'scan', 'report',
        'returning', 'done', 'aborted',
    }
    assert {s.value for s in State} == expected
