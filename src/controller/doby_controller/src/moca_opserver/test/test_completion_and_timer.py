"""test_completion_and_timer — CompletionWatcher + IdlePatrolTimer 단위 테스트.

ROS Node 없이 FakeNode + mock orchestrator 로 검증.

실행:
  source install/setup.bash
  python3 -m pytest src/moca_opserver/test/test_completion_and_timer.py -v
"""

import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from moca_opserver.completion_watcher import CompletionWatcher
from moca_opserver.idle_patrol_timer import (
    IdlePatrolTimer, _in_business_hours, _parse_business_hours,
)


# ──────────────── FakeNode ────────────────

class _FakeConfig:
    """OpServerConfig 의 필요한 필드만."""
    completion_dwell_serving = 3.0
    completion_dwell_patrol = 1.0
    completion_dwell_guiding = 5.0
    completion_dwell_engaging = 2.0
    patrol_interval_minutes = 5.0
    patrol_enabled = True
    business_hours = ''
    battery_min = 0.20
    auto_return_after_serve = True


class _FakeLogger:
    def info(self, *_args): pass
    def warn(self, *_args): pass
    def warning(self, *_args): pass
    def debug(self, *_args): pass
    def error(self, *_args): pass


class _FakeNode:
    """CompletionWatcher / IdlePatrolTimer 가 접근하는 최소 인터페이스."""

    def __init__(self, current_mode: str = 'idle', battery_pct=None):
        self.current_mode = current_mode
        self.battery_pct = battery_pct
        self.config = _FakeConfig()
        self.orchestrator = MagicMock()
        self.orchestrator.request_mode_change = MagicMock(
            return_value={'ok': True, 'reason': 'transition_started'})
        self._logger = _FakeLogger()
        self.published_events = []

    def get_logger(self):
        return self._logger

    def publish_op_event(self, source, event_type, payload, outcome):
        self.published_events.append({
            'source': source, 'event_type': event_type,
            'payload': payload, 'outcome': outcome,
        })


# ──────────────── 1. business_hours 파싱 ────────────────

@pytest.mark.parametrize('spec,start,end', [
    ('09:00-22:00', (9, 0), (22, 0)),
    ('08:30-23:45', (8, 30), (23, 45)),
])
def test_business_hours_parse_valid(spec, start, end):
    assert _parse_business_hours(spec) == (start, end)


@pytest.mark.parametrize('spec', ['', '24h', '24/7', 'always'])
def test_business_hours_parse_open(spec):
    assert _parse_business_hours(spec) == (None, None)


@pytest.mark.parametrize('spec', ['garbage', '09:00', None])
def test_business_hours_parse_invalid_returns_none(spec):
    assert _parse_business_hours(spec) == (None, None)


def test_in_business_hours_24h():
    """빈 문자열 = 24시간 활성 → 항상 True."""
    assert _in_business_hours('') is True


def test_in_business_hours_within():
    """09:00-22:00 사이 시각 (예: 12:00)."""
    now = datetime(2026, 5, 16, 12, 0)
    assert _in_business_hours('09:00-22:00', now=now) is True


def test_in_business_hours_outside():
    """영업시간 밖 (예: 06:00)."""
    now = datetime(2026, 5, 16, 6, 0)
    assert _in_business_hours('09:00-22:00', now=now) is False


# ──────────────── 2. IdlePatrolTimer ────────────────

def test_idle_timer_starts_dwell_on_idle():
    node = _FakeNode(current_mode='idle')
    t = IdlePatrolTimer(node)
    t.on_mode_state('idle')
    # tick 안 했지만 dwell 시작은 됐어야 함
    assert t._last_idle_entered_at is not None


def test_idle_timer_resets_on_non_idle():
    node = _FakeNode(current_mode='idle')
    t = IdlePatrolTimer(node)
    t.on_mode_state('idle')
    assert t._last_idle_entered_at is not None
    # 다른 모드 진입 → dwell 리셋
    t.on_mode_state('serving')
    assert t._last_idle_entered_at is None


def test_idle_timer_tick_no_trigger_before_interval():
    """5분 미만 idle 에서는 tick 해도 트리거 안 함."""
    node = _FakeNode(current_mode='idle')
    t = IdlePatrolTimer(node)
    t.on_mode_state('idle')
    # interval 1분 = 60s 로 단축
    node.config.patrol_interval_minutes = 1.0
    # 30s elapsed 시뮬 — dwell 시작 시각을 30초 전으로
    t._last_idle_entered_at = time.time() - 30.0
    t.tick()
    node.orchestrator.request_mode_change.assert_not_called()


def test_idle_timer_tick_triggers_after_interval():
    """interval 경과 + idle 유지 시 SetMode('patrol') 호출."""
    node = _FakeNode(current_mode='idle')
    t = IdlePatrolTimer(node)
    t.on_mode_state('idle')
    node.config.patrol_interval_minutes = 0.05   # 3초
    # 4초 전 시작 시뮬
    t._last_idle_entered_at = time.time() - 4.0
    t.tick()
    node.orchestrator.request_mode_change.assert_called_once()
    call = node.orchestrator.request_mode_change.call_args
    assert call.kwargs.get('target_mode') == 'patrol' \
        or call.args[0] == 'patrol'
    # 트리거 후 dwell 리셋
    assert t._last_idle_entered_at is None


def test_idle_timer_blocked_when_disabled():
    """patrol_enabled=False → 트리거 안 함."""
    node = _FakeNode(current_mode='idle')
    node.config.patrol_enabled = False
    t = IdlePatrolTimer(node)
    t._last_idle_entered_at = time.time() - 1000.0
    t.tick()
    node.orchestrator.request_mode_change.assert_not_called()


def test_idle_timer_blocked_outside_business_hours():
    """영업시간 밖이면 트리거 안 함."""
    node = _FakeNode(current_mode='idle')
    # 영업시간을 매우 좁게 — 현재 시각과 안 겹치게 (00:00-00:01)
    node.config.business_hours = '00:00-00:01'
    # 본 테스트가 자정~00:01 사이 돌아갈 가능성 — 영업시간을 미래 1분으로
    now = datetime.now()
    # 절대 현재가 들어갈 수 없게 — 1년 뒤 23:59 같이 의미 없는 spec 만들기 어려움.
    # 단순화: 04:00-04:01 같이 일반적으로 안 걸리는 영업시간
    node.config.business_hours = '04:00-04:01'
    t = IdlePatrolTimer(node)
    t._last_idle_entered_at = time.time() - 1000.0
    # 04:00-04:01 사이 돌아갈 가능성도 있음 — 일단 _in_business_hours 직접 테스트로 대체
    # 가드는 트리거 조건이 4시 안일 때만 동작하므로 일반 시간엔 False 반환
    if _in_business_hours('04:00-04:01', now):
        pytest.skip('현재 시각이 04:00-04:01 사이 — 본 테스트 skip')
    t.tick()
    node.orchestrator.request_mode_change.assert_not_called()


def test_idle_timer_blocked_when_battery_low():
    """battery < battery_min → 트리거 안 함."""
    node = _FakeNode(current_mode='idle', battery_pct=0.15)
    node.config.battery_min = 0.20
    t = IdlePatrolTimer(node)
    t._last_idle_entered_at = time.time() - 1000.0
    t.tick()
    node.orchestrator.request_mode_change.assert_not_called()


def test_idle_timer_battery_unknown_allows():
    """battery_pct=None (미수신) → 안전 측 OK, 트리거 허용."""
    node = _FakeNode(current_mode='idle', battery_pct=None)
    node.config.patrol_interval_minutes = 0.05
    t = IdlePatrolTimer(node)
    t._last_idle_entered_at = time.time() - 4.0
    t.tick()
    node.orchestrator.request_mode_change.assert_called_once()


def test_idle_timer_idle_elapsed_helper():
    node = _FakeNode(current_mode='idle')
    t = IdlePatrolTimer(node)
    assert t.idle_elapsed_sec() == -1.0
    t._last_idle_entered_at = time.time() - 10.0
    assert 9.0 < t.idle_elapsed_sec() < 12.0


# ──────────────── 3. CompletionWatcher ────────────────

@pytest.mark.parametrize('mode,signal,done', [
    ('serving',  'idle',     True),
    ('serving',  'navigating', False),
    ('patrol',   'done',     True),
    ('patrol',   'aborted',  True),
    ('patrol',   'moving',   False),
    ('guiding',  'done',     True),
    ('guiding',  'aborted',  True),
    ('guiding',  'arrived',  False),
    ('engaging', 'done',     True),
    ('engaging', 'completed', True),
])
def test_completion_signals(mode, signal, done):
    """각 모드별 종료 시그널만 dwell 시작."""
    node = _FakeNode(current_mode=mode)
    w = CompletionWatcher(node)
    # 직접 _observe 호출
    w._observe(mode=mode, state_value=signal)
    if done:
        assert w._dwell_start[mode] is not None
    else:
        assert w._dwell_start[mode] is None


def test_completion_signal_ignored_if_not_current_mode():
    """node.current_mode 가 본 모드 아닐 때 신호 무시."""
    node = _FakeNode(current_mode='guiding')
    w = CompletionWatcher(node)
    # patrol 신호 들어왔지만 현재 모드는 guiding
    w._observe(mode='patrol', state_value='done')
    assert w._dwell_start['patrol'] is None


def test_completion_resume_signal_resets_dwell():
    """dwell 시작 후 활동 재개 신호 → dwell 리셋."""
    node = _FakeNode(current_mode='patrol')
    w = CompletionWatcher(node)
    w._observe(mode='patrol', state_value='done')
    assert w._dwell_start['patrol'] is not None
    # 활동 재개 (예: 다른 사이클 시작) — moving
    w._observe(mode='patrol', state_value='moving')
    assert w._dwell_start['patrol'] is None


def test_completion_tick_triggers_setmode_after_dwell():
    """dwell 만료 시 SetMode('idle', override=True) 호출."""
    node = _FakeNode(current_mode='patrol')
    node.config.completion_dwell_patrol = 0.1   # 100ms 단축
    w = CompletionWatcher(node)
    w.on_patrol_state('done')
    # dwell 시작 시각을 더 과거로 시뮬
    w._dwell_start['patrol'] = time.time() - 1.0
    w.tick()
    node.orchestrator.request_mode_change.assert_called_once()
    call = node.orchestrator.request_mode_change.call_args
    assert call.kwargs.get('target_mode') == 'idle' \
        or call.args[0] == 'idle'
    assert call.kwargs.get('override_priority') is True
    # 트리거 후 dwell 리셋
    assert w._dwell_start['patrol'] is None


def test_completion_tick_no_trigger_before_dwell():
    """dwell 미만 elapsed → 트리거 안 함."""
    node = _FakeNode(current_mode='patrol')
    node.config.completion_dwell_patrol = 2.0
    w = CompletionWatcher(node)
    w.on_patrol_state('done')
    # 0.5초만 elapsed
    w._dwell_start['patrol'] = time.time() - 0.5
    w.tick()
    node.orchestrator.request_mode_change.assert_not_called()


def test_completion_retrigger_cooldown_blocks_double():
    """트리거 후 짧은 시간 안 재트리거 차단."""
    node = _FakeNode(current_mode='patrol')
    node.config.completion_dwell_patrol = 0.1
    w = CompletionWatcher(node)
    w._retrigger_cooldown_sec = 5.0  # 5초 cooldown
    w.on_patrol_state('done')
    w._dwell_start['patrol'] = time.time() - 1.0
    w.tick()
    assert node.orchestrator.request_mode_change.call_count == 1
    # 두 번째 시그널 + dwell 만료 — cooldown 안이라 거부
    w.on_patrol_state('done')
    w._dwell_start['patrol'] = time.time() - 1.0
    w.tick()
    # 여전히 1회만
    assert node.orchestrator.request_mode_change.call_count == 1


def test_completion_tick_invalidates_dwell_if_mode_changed():
    """tick 시점 current_mode 가 본 모드 아니면 dwell invalidate (트리거 X)."""
    node = _FakeNode(current_mode='patrol')
    w = CompletionWatcher(node)
    w.on_patrol_state('done')
    # 시간 만료
    w._dwell_start['patrol'] = time.time() - 5.0
    # 모드 변경 (이미 다른 트리거로 idle 갔다고 가정)
    node.current_mode = 'idle'
    w.tick()
    # 호출 안 됨 + dwell 리셋
    node.orchestrator.request_mode_change.assert_not_called()
    assert w._dwell_start['patrol'] is None


def test_completion_dwell_per_mode_uses_config():
    """_dwell_for_mode 가 config 의 completion_dwell_X 를 반환."""
    node = _FakeNode(current_mode='serving')
    node.config.completion_dwell_serving = 7.5
    w = CompletionWatcher(node)
    assert w._dwell_for_mode('serving') == 7.5
    # default fallback (config 에 없는 모드) — _FakeConfig 에는 다 있지만 일반 dict
    # 미존재 모드는 default 사용
    assert w._dwell_for_mode('unknown') == 2.0


# ──────────────── 4. CompletionWatcher 적재(Serve) 후 자동 return ────────────────

class _FakeServingNode(_FakeNode):
    """serving auto-return 테스트용 — arm/return 인터페이스 추가."""

    def __init__(self, route='T03', routes=('T01', 'T02', 'T03')):
        super().__init__(current_mode='serving')
        self._active_serving_route = route
        self._serving_state_json = {'state': 'idle', 'routes': list(routes)}
        self._current_serving_has_drink = True
        self.goto_published = []
        self.arm_serve_cb = None   # send_arm_serve_goal 이 저장 → 테스트가 직접 호출

    def send_arm_serve_goal(self, done_cb, has_drink=None):
        self.arm_serve_cb = done_cb

    def publish_serving_goto_table(self, cmd):
        self.goto_published.append(cmd)


def _run_phase1(w):
    """serving idle dwell 만료 → phase1 tick (arm serve 요청)."""
    w._retrigger_cooldown_sec = 0.0   # 테스트는 phase1/2 가 ms 간격이라 cooldown off
    w.on_serving_state('idle')
    w._dwell_start['serving'] = time.time() - 10.0
    w.tick()


def _run_phase2_idle(w):
    """복귀 완료 idle → phase2 tick."""
    w.on_serving_state('idle')
    w._dwell_start['serving'] = time.time() - 10.0
    w.tick()


def test_autoreturn_phase1_requests_arm_serve():
    node = _FakeServingNode()
    w = CompletionWatcher(node)
    _run_phase1(w)
    assert node.arm_serve_cb is not None        # arm serve 요청됨
    assert w._arm_running['serving'] is True      # 콜백 전까지 진행 중
    assert node.goto_published == []
    node.orchestrator.request_mode_change.assert_not_called()  # 아직 idle 안 함


def test_autoreturn_publishes_return_on_serve_success():
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')                 # 적재 성공 시뮬
    assert node.goto_published == ['T03:return']  # return 발행
    assert w._serving_return_pending is True
    assert w._arm_running['serving'] is False
    node.orchestrator.request_mode_change.assert_not_called()  # idle 보류


def test_autoreturn_idle_after_return_completes():
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')
    w.on_serving_state('routing')                 # dispatcher 복귀 주행 시작
    assert w._serving_return_started is True
    _run_phase2_idle(w)                           # 복귀 완료 → idle
    node.orchestrator.request_mode_change.assert_called_once()
    call = node.orchestrator.request_mode_change.call_args
    assert (call.kwargs.get('target_mode') == 'idle') or (call.args[0] == 'idle')
    assert w._serving_return_pending is False
    assert node.goto_published == ['T03:return']  # return 한 번만


def test_autoreturn_phase2_waits_until_return_started():
    """return 발행 후 dispatcher 가 idle 벗어나기 전엔 조기 idle 안 함."""
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')
    _run_phase2_idle(w)                           # started=False, deadline 미래
    node.orchestrator.request_mode_change.assert_not_called()
    assert w._serving_return_pending is True


def test_autoreturn_deadline_fallback_when_return_noop():
    """빈/누락 return(no-op, started 안 됨) → deadline 후 idle."""
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')
    w._serving_return_deadline = time.time() - 1.0   # fallback 발동 시뮬
    _run_phase2_idle(w)
    node.orchestrator.request_mode_change.assert_called_once()
    assert w._serving_return_pending is False


def test_autoreturn_skipped_when_target_not_route():
    """대상이 routes 에 없으면(=table) return 없이 즉시 idle."""
    node = _FakeServingNode(route='T09', routes=('T01', 'T02', 'T03'))
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')
    assert node.goto_published == []
    node.orchestrator.request_mode_change.assert_called_once()


def test_autoreturn_skipped_when_toggle_off():
    node = _FakeServingNode(route='T03')
    node.config.auto_return_after_serve = False
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(True, 'ok')
    assert node.goto_published == []
    node.orchestrator.request_mode_change.assert_called_once()


def test_autoreturn_skipped_on_serve_failure():
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    _run_phase1(w)
    node.arm_serve_cb(False, 'arm error')         # 적재 실패
    assert node.goto_published == []
    node.orchestrator.request_mode_change.assert_called_once()  # 실패해도 idle


def test_autoreturn_state_reset_when_leaving_serving():
    """serving 이탈 시 return 플래그 리셋(다음 세션 클린)."""
    node = _FakeServingNode(route='T03')
    w = CompletionWatcher(node)
    w._serving_return_pending = True
    w._serving_return_started = True
    node.current_mode = 'idle'
    w._observe(mode='serving', state_value='idle')
    assert w._serving_return_pending is False
    assert w._serving_return_started is False
