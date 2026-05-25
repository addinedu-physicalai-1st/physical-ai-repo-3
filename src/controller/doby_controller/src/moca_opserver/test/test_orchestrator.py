"""test_orchestrator.py — ModeOrchestrator priority gating + 가드 단위 테스트.

API spec 매트릭스: docs/moca_opserver_api_spec.md §8.1
FSM 우선순위: docs/moca_5state_fsm_spec.md §3.3

실행:
  colcon test --packages-select moca_opserver
  colcon test-result --verbose

또는 직접 (워크스페이스 루트에서):
  source install/setup.bash
  python3 -m pytest src/moca_opserver/test/test_orchestrator.py -v

테스트 전략:
  - ROS 노드 없이 ModeOrchestrator 만 단위 검증
  - FakeNode 가 ModeOrchestrator 가 접근하는 속성/메서드 stub
  - SetMode 클라이언트는 MagicMock — wait_for_service / call_async / future.result 패치
"""

from unittest.mock import MagicMock

import pytest

from moca_opserver.mode_orchestrator import (
    ModeOrchestrator, PRIORITY, VALID_MODES,
)


# ---------- 테스트용 stub ----------

class FakeConfig:
    """ModeOrchestrator 가 self.node.config.battery_min 만 접근."""
    def __init__(self, battery_min: float = 0.20):
        self.battery_min = battery_min


class FakeNode:
    """ModeOrchestrator 가 필요로 하는 최소 인터페이스만."""

    def __init__(self, current_mode: str = 'idle',
                 battery_pct: float | None = 0.85,
                 safety_ok: bool = True,
                 robot_online: bool = True,
                 battery_min: float = 0.20):
        self.current_mode = current_mode
        self.battery_pct = battery_pct
        self.safety_ok = safety_ok
        self.robot_online = robot_online
        self.config = FakeConfig(battery_min=battery_min)
        # SetMode client mock — ModeOrchestrator __init__ 의 create_client 호출 흡수
        self._mock_client = MagicMock()

    def create_client(self, srv_type, srv_name):
        return self._mock_client


def _make_setmode_response(success: bool = True,
                             current_mode_after: str = '',
                             reason: str = 'transition_started'):
    """mode_manager 의 SetMode 응답 형태 mock."""
    resp = MagicMock()
    resp.success = success
    resp.current_mode = current_mode_after
    resp.reason = reason
    return resp


def _setup_orchestrator(
    current_mode: str = 'idle',
    battery_pct: float | None = 0.85,
    safety_ok: bool = True,
    robot_online: bool = True,
    battery_min: float = 0.20,
    setmode_success: bool = True,
    setmode_reason: str = 'transition_started',
):
    """ModeOrchestrator + FakeNode 페어 생성 + SetMode mock 주입."""
    node = FakeNode(
        current_mode=current_mode, battery_pct=battery_pct,
        safety_ok=safety_ok, robot_online=robot_online,
        battery_min=battery_min)
    orch = ModeOrchestrator(node)
    # 즉시 done 상태의 future mock
    future = MagicMock()
    future.done.return_value = True
    future.result.return_value = _make_setmode_response(
        success=setmode_success, reason=setmode_reason)
    orch.cli_set_mode.wait_for_service = MagicMock(return_value=True)
    orch.cli_set_mode.call_async = MagicMock(return_value=future)
    return orch, node


# ---------- 1. priority gating 5×4 매트릭스 ----------

# (current, target, expected_ok, expected_code_if_reject)
# self-loop 4종 제외 — orchestrator 가 거부하지만 별도 테스트로 검증
PRIORITY_MATRIX = [
    # current=idle 에서 모든 모드 진입 허용 (priority 무관)
    ('idle', 'serving',  True,  None),
    ('idle', 'patrol',   True,  None),
    ('idle', 'guiding',  True,  None),
    ('idle', 'engaging', True,  None),

    # current=serving 에서 idle 외 모든 진입 거부 (priority 1 최상)
    ('serving', 'idle',     True,  None),
    ('serving', 'patrol',   False, 'BUSY'),
    ('serving', 'guiding',  False, 'BUSY'),
    ('serving', 'engaging', False, 'BUSY'),

    # current=patrol(3) 에서 serving(1)/guiding(2) preempt, engaging(5) 거부
    ('patrol', 'idle',     True,  None),
    ('patrol', 'serving',  True,  None),
    ('patrol', 'guiding',  True,  None),
    ('patrol', 'engaging', False, 'BUSY'),

    # current=guiding(2) 에서 serving(1) preempt, patrol/engaging 거부
    ('guiding', 'idle',     True,  None),
    ('guiding', 'serving',  True,  None),
    ('guiding', 'patrol',   False, 'BUSY'),
    ('guiding', 'engaging', False, 'BUSY'),

    # current=engaging(5) 에서 serving/patrol/guiding 모두 preempt 허용
    ('engaging', 'idle',     True,  None),
    ('engaging', 'serving',  True,  None),
    ('engaging', 'patrol',   True,  None),
    ('engaging', 'guiding',  True,  None),
]


@pytest.mark.parametrize("current,target,expected_ok,expected_code",
                          PRIORITY_MATRIX)
def test_priority_gating(current, target, expected_ok, expected_code):
    """5×4=20 priority 매트릭스 — override 없이 자동 트리거 경로."""
    orch, _ = _setup_orchestrator(current_mode=current)
    result = orch.request_mode_change(
        target_mode=target, params={}, trigger_source='test')
    assert result['ok'] == expected_ok, (
        f'priority[{current}={PRIORITY[current]}] -> '
        f'[{target}={PRIORITY[target]}] 기대={expected_ok} 실제={result}')
    if not expected_ok:
        assert result.get('code') == expected_code


def test_priority_self_loop_rejected():
    """current == target 같은 모드 재요청은 priority 동등 → BUSY (mode_manager 가 큐 append 처리)."""
    orch, _ = _setup_orchestrator(current_mode='serving')
    result = orch.request_mode_change('serving', params={}, trigger_source='test')
    assert result['ok'] is False
    assert result['code'] == 'BUSY'


# ---------- 2. override_priority=True ----------

@pytest.mark.parametrize("current,target", [
    ('serving', 'patrol'),
    ('serving', 'engaging'),
    ('guiding', 'patrol'),
    ('patrol', 'engaging'),
])
def test_override_priority_allows_lower(current, target):
    """운영자 명시 override_priority=True → priority 룰 무시 (수동 의도 우선)."""
    orch, _ = _setup_orchestrator(current_mode=current)
    result = orch.request_mode_change(
        target_mode=target, params={}, trigger_source='operator',
        override_priority=True)
    assert result['ok'] is True
    assert result.get('reason') == 'transition_started'


# ---------- 3. 사전 가드 ----------

def test_battery_low_rejects_active_mode():
    """배터리 < battery_min 일 때 idle 외 모드 거부."""
    orch, _ = _setup_orchestrator(
        current_mode='idle', battery_pct=0.15, battery_min=0.20)
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is False
    assert result['code'] == 'BATTERY_LOW'
    assert '0.15' in result['message']


def test_battery_low_allows_idle():
    """배터리 부족이어도 idle 진입은 허용 (활동 모드 종료 경로)."""
    orch, _ = _setup_orchestrator(
        current_mode='serving', battery_pct=0.15, battery_min=0.20)
    result = orch.request_mode_change('idle', params={})
    assert result['ok'] is True


def test_battery_unknown_allows_active_mode():
    """배터리 미수신(-1 또는 None) 은 안전 측 OK (라이브 미연결 환경)."""
    orch, _ = _setup_orchestrator(current_mode='idle', battery_pct=None)
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is True


def test_safety_alarm_rejects_active_mode():
    """safety alarm dwell 동안 idle 외 모드 거부."""
    orch, _ = _setup_orchestrator(current_mode='idle', safety_ok=False)
    result = orch.request_mode_change('patrol', params={})
    assert result['ok'] is False
    assert result['code'] == 'SAFETY_ALARM'


def test_safety_alarm_allows_idle():
    """safety alarm 중에도 idle 진입은 허용."""
    orch, _ = _setup_orchestrator(current_mode='engaging', safety_ok=False)
    result = orch.request_mode_change('idle', params={})
    assert result['ok'] is True


# ---------- 4. 입력 검증 ----------

def test_invalid_mode_rejected():
    """VALID_MODES 에 없는 모드명 거부."""
    orch, _ = _setup_orchestrator(current_mode='idle')
    result = orch.request_mode_change('foobar', params={})
    assert result['ok'] is False
    assert result['code'] == 'INVALID_MODE'


def test_legacy_mode_alias_not_translated_in_orchestrator():
    """legacy alias (npc/follow) 는 mode_manager 가 처리.
    orchestrator 는 VALID_MODES 만 허용 — npc/follow 도 INVALID_MODE 거부.
    """
    orch, _ = _setup_orchestrator(current_mode='idle')
    for legacy in ('npc', 'follow'):
        result = orch.request_mode_change(legacy, params={})
        assert result['ok'] is False
        assert result['code'] == 'INVALID_MODE'


# ---------- 5. 로봇 오프라인 ----------

def test_robot_offline_rejects_active_mode():
    """/mode/state 미수신 시 idle 외 모드 거부."""
    orch, _ = _setup_orchestrator(current_mode='idle', robot_online=False)
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is False
    assert result['code'] == 'ROBOT_OFFLINE'


def test_robot_offline_allows_idle():
    """오프라인이어도 idle 요청은 허용 (cleanup 경로)."""
    orch, _ = _setup_orchestrator(current_mode='engaging', robot_online=False)
    result = orch.request_mode_change('idle', params={})
    assert result['ok'] is True


# ---------- 6. SetMode 결과 변환 ----------

def test_setmode_failure_propagated():
    """mode_manager 가 success=False 응답 시 orchestrator 도 ok=False."""
    orch, _ = _setup_orchestrator(
        current_mode='idle', setmode_success=False,
        setmode_reason='transition_in_progress')
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is False
    assert result['reason'] == 'transition_in_progress'


def test_setmode_service_unavailable():
    """wait_for_service 가 False → INTERNAL_ERROR."""
    orch, _ = _setup_orchestrator(current_mode='idle')
    orch.cli_set_mode.wait_for_service = MagicMock(return_value=False)
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is False
    assert result['code'] == 'INTERNAL_ERROR'
    assert 'unavailable' in result['message']


def test_setmode_timeout():
    """future 가 timeout 내 done 안 됨 → INTERNAL_ERROR setmode timeout."""
    orch, _ = _setup_orchestrator(current_mode='idle')
    # done() 영원히 False
    stuck_future = MagicMock()
    stuck_future.done.return_value = False
    orch.cli_set_mode.call_async = MagicMock(return_value=stuck_future)
    orch.SETMODE_TIMEOUT_SEC = 0.1   # 빠른 테스트
    result = orch.request_mode_change('serving', params={'waypoint': 'T01'})
    assert result['ok'] is False
    assert result['code'] == 'INTERNAL_ERROR'
    assert 'timeout' in result['message']


def test_preempted_flag_correctness():
    """선점 케이스 — current=patrol → target=serving 성공 시 preempted=True."""
    orch, _ = _setup_orchestrator(current_mode='patrol')
    result = orch.request_mode_change(
        target_mode='serving', params={'waypoint': 'T03'})
    assert result['ok'] is True
    assert result['preempted'] is True
    assert result['current_mode_before'] == 'patrol'


def test_preempted_flag_idle_origin():
    """current=idle → target=serving 은 preempted=False (선점 아님)."""
    orch, _ = _setup_orchestrator(current_mode='idle')
    result = orch.request_mode_change(
        target_mode='serving', params={'waypoint': 'T03'})
    assert result['ok'] is True
    assert result['preempted'] is False


def test_preempted_flag_to_idle():
    """current=engaging → target=idle 은 preempted=False (cleanup)."""
    orch, _ = _setup_orchestrator(current_mode='engaging')
    result = orch.request_mode_change(target_mode='idle', params={})
    assert result['ok'] is True
    assert result['preempted'] is False


# ---------- 7. PRIORITY 상수 자체 sanity ----------

def test_priority_constants_match_spec():
    """FSM spec §3.3 / API spec §5.1 — 5종 모드 + 숫자 정확성."""
    assert PRIORITY == {
        'serving': 1, 'guiding': 2, 'patrol': 3, 'engaging': 5, 'idle': 99,
    }
    assert set(VALID_MODES) == {
        'idle', 'serving', 'patrol', 'guiding', 'engaging',
    }
