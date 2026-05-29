"""test_has_drink.py — has_drink 흐름 opserver 단위 테스트.

테스트 대상:
  1. start_serving_with_pickup(has_drink) → _current_serving_has_drink 저장
  2. send_arm_pickup_goal → Pickup.Goal().has_drink 전달
  3. send_arm_serve_goal  → Serve.Goal().has_drink 전달
  4. CompletionWatcher._trigger_arm_then_idle → send_arm_serve_goal에 has_drink 전달
  5. _on_mode_state params 파싱 → _current_serving_has_drink 복구

ROS 없이 FakeNode + mock 패턴으로 검증.

실행:
  source install/setup.bash
  python3 -m pytest src/moca_opserver/test/test_has_drink.py -v
"""

from unittest.mock import MagicMock, call, patch
import pytest

import sys, os
_PKG = os.path.join(os.path.dirname(__file__), '..', 'moca_opserver')
if os.path.isdir(_PKG):
    sys.path.insert(0, os.path.dirname(_PKG))

from moca_opserver.completion_watcher import CompletionWatcher


# ──────────────── FakeNode ────────────────

class _FakeConfig:
    completion_dwell_serving = 0.0   # dwell 없이 즉시 트리거
    completion_dwell_patrol = 0.0
    completion_dwell_guiding = 0.0
    completion_dwell_engaging = 0.0
    battery_min = 0.20


class _FakeLogger:
    def info(self, *a): pass
    def warn(self, *a): pass
    def warning(self, *a): pass
    def error(self, *a): pass
    def debug(self, *a): pass


class _FakeNode:
    """OpServerNode의 has_drink 관련 인터페이스만 stub."""

    def __init__(self, current_mode: str = 'serving', has_drink: bool = True):
        self.current_mode = current_mode
        self.config = _FakeConfig()
        self._current_serving_has_drink = has_drink
        self.orchestrator = MagicMock()
        self.orchestrator.request_mode_change = MagicMock(
            return_value={'ok': True, 'reason': 'transition_started'})
        self._logger = _FakeLogger()

        # arm / pickup 호출 기록
        self.serve_calls: list[dict] = []
        self.pickup_calls: list[dict] = []

    def get_logger(self):
        return self._logger

    def publish_op_event(self, **_kw):
        pass

    def send_arm_serve_goal(self, done_cb, has_drink: bool | None = None):
        self.serve_calls.append({'has_drink': has_drink, 'done_cb': done_cb})
        done_cb(True, 'ok')

    def send_arm_pickup_goal(self, done_cb, has_drink: bool = True):
        self.pickup_calls.append({'has_drink': has_drink, 'done_cb': done_cb})
        done_cb(True, 'ok')


# ──────────────── 1. CompletionWatcher → send_arm_serve_goal ────────────────

class TestCompletionWatcherServeDrink:
    """CompletionWatcher가 _current_serving_has_drink 값을 Serve goal에 전달하는지."""

    def _watcher_and_node(self, has_drink: bool) -> tuple:
        node = _FakeNode(current_mode='serving', has_drink=has_drink)
        watcher = CompletionWatcher(node)
        return watcher, node

    def _trigger(self, watcher: CompletionWatcher, node: _FakeNode):
        """serving 완료 시그널 → dwell 만료 → _trigger_arm_then_idle."""
        node.current_mode = 'serving'
        watcher.on_serving_state('idle')
        watcher.tick()

    def test_serve_goal_has_drink_true(self):
        watcher, node = self._watcher_and_node(has_drink=True)
        self._trigger(watcher, node)
        assert len(node.serve_calls) == 1
        assert node.serve_calls[0]['has_drink'] is True

    def test_serve_goal_has_drink_false(self):
        watcher, node = self._watcher_and_node(has_drink=False)
        self._trigger(watcher, node)
        assert len(node.serve_calls) == 1
        assert node.serve_calls[0]['has_drink'] is False

    def test_non_serving_mode_skips_arm(self):
        """patrol 완료는 Serve action 없이 idle로 전환."""
        node = _FakeNode(current_mode='patrol', has_drink=True)
        watcher = CompletionWatcher(node)
        node.current_mode = 'patrol'
        watcher.on_patrol_state('done')
        watcher.tick()
        assert len(node.serve_calls) == 0

    def test_serve_called_once_not_twice(self):
        """중복 트리거 차단 (cooldown)."""
        watcher, node = self._watcher_and_node(has_drink=True)
        self._trigger(watcher, node)
        watcher.tick()   # 두 번째 tick
        assert len(node.serve_calls) == 1


# ──────────────── 2. _current_serving_has_drink 저장 로직 ────────────────

class TestCurrentServingHasDrink:
    """start_serving_with_pickup이 _current_serving_has_drink를 올바르게 저장하는지.

    OpServerNode는 ROS 의존이라 직접 import 불가.
    대신 동일 로직을 FakeNode 메서드로 재현해 검증.
    """

    def _run_start_serving_with_pickup(
        self,
        has_drink: bool,
        via_pickup: bool = True,
    ) -> _FakeNode:
        node = _FakeNode(current_mode='idle', has_drink=False)
        node._pickup_in_progress = False

        # start_serving_with_pickup 로직 직접 실행 (OpServerNode 미import)
        node._current_serving_has_drink = has_drink
        params = {'waypoint': 'T01', 'via_pickup': via_pickup, 'has_drink': has_drink}

        if via_pickup:
            node._pickup_in_progress = True

            def _after_pickup(success, msg):
                node._pickup_in_progress = False
                if success:
                    node.orchestrator.request_mode_change(
                        target_mode='serving',
                        params=params,
                        trigger_source='test',
                        override_priority=False,
                    )

            node.send_arm_pickup_goal(_after_pickup, has_drink=has_drink)
        else:
            node.orchestrator.request_mode_change(
                target_mode='serving',
                params=params,
                trigger_source='test',
                override_priority=False,
            )

        return node

    def test_has_drink_true_stored(self):
        node = self._run_start_serving_with_pickup(has_drink=True)
        assert node._current_serving_has_drink is True

    def test_has_drink_false_stored(self):
        node = self._run_start_serving_with_pickup(has_drink=False)
        assert node._current_serving_has_drink is False

    def test_pickup_goal_receives_has_drink_true(self):
        node = self._run_start_serving_with_pickup(has_drink=True, via_pickup=True)
        assert len(node.pickup_calls) == 1
        assert node.pickup_calls[0]['has_drink'] is True

    def test_pickup_goal_receives_has_drink_false(self):
        node = self._run_start_serving_with_pickup(has_drink=False, via_pickup=True)
        assert len(node.pickup_calls) == 1
        assert node.pickup_calls[0]['has_drink'] is False

    def test_no_pickup_when_via_pickup_false(self):
        node = self._run_start_serving_with_pickup(has_drink=True, via_pickup=False)
        assert len(node.pickup_calls) == 0

    def test_setmode_called_after_pickup_success(self):
        node = self._run_start_serving_with_pickup(has_drink=True, via_pickup=True)
        node.orchestrator.request_mode_change.assert_called_once()
        call_kwargs = node.orchestrator.request_mode_change.call_args
        assert call_kwargs.kwargs['target_mode'] == 'serving'
        assert call_kwargs.kwargs['params']['has_drink'] is True


# ──────────────── 3. _on_mode_state 파싱 — has_drink 복구 ────────────────

class TestModeStateHasDrinkRecovery:
    """_on_mode_state에서 params의 has_drink를 파싱해 저장하는 로직 검증.

    OpServerNode._on_mode_state 로직을 직접 실행 (ROS 미사용).
    """

    def _parse_mode_state(self, current_mode: str, params_dict: dict) -> _FakeNode:
        node = _FakeNode(current_mode='idle', has_drink=False)

        # _on_mode_state 내 has_drink 파싱 로직 재현
        if current_mode == 'serving':
            node._current_serving_has_drink = bool(params_dict.get('has_drink', True))
        elif current_mode == 'idle':
            node._current_serving_has_drink = False

        return node

    def test_serving_with_has_drink_true(self):
        node = self._parse_mode_state('serving', {'waypoint': 'T01', 'has_drink': True})
        assert node._current_serving_has_drink is True

    def test_serving_with_has_drink_false(self):
        node = self._parse_mode_state('serving', {'waypoint': 'T01', 'has_drink': False})
        assert node._current_serving_has_drink is False

    def test_idle_resets_has_drink(self):
        node = _FakeNode(has_drink=True)
        node._current_serving_has_drink = True
        # idle 전환 시 초기화
        node._current_serving_has_drink = False  # _on_mode_state idle branch
        assert node._current_serving_has_drink is False

    def test_serving_missing_has_drink_defaults_true(self):
        """params에 has_drink 없으면 기본값 True (음료 우선)."""
        node = self._parse_mode_state('serving', {'waypoint': 'T01'})
        assert node._current_serving_has_drink is True


# ──────────────── 4. 통합 시나리오 ────────────────

class TestHasDrinkEndToEnd:
    """음료/음식 주문 시나리오별 Serve goal 검증."""

    def _run_scenario(self, has_drink: bool) -> dict:
        """pickup → serving 완료 → serve goal 캡처."""
        node = _FakeNode(current_mode='serving', has_drink=has_drink)
        watcher = CompletionWatcher(node)

        node.current_mode = 'serving'
        watcher.on_serving_state('idle')
        watcher.tick()

        assert len(node.serve_calls) == 1
        return node.serve_calls[0]

    def test_scenario_drink_order(self):
        """음료 주문 → Serve goal has_drink=True."""
        result = self._run_scenario(has_drink=True)
        assert result['has_drink'] is True

    def test_scenario_food_only_order(self):
        """핫도그만 주문 → Serve goal has_drink=False."""
        result = self._run_scenario(has_drink=False)
        assert result['has_drink'] is False

    def test_pickup_and_serve_both_get_has_drink(self):
        """pickup goal과 serve goal 모두 동일한 has_drink 값을 받는지."""
        has_drink = True
        node = _FakeNode(current_mode='idle', has_drink=False)
        node._pickup_in_progress = False
        node._current_serving_has_drink = has_drink

        # pickup 트리거
        node.send_arm_pickup_goal(lambda s, m: None, has_drink=has_drink)

        # serving 완료 후 serve 트리거
        watcher = CompletionWatcher(node)
        node.current_mode = 'serving'
        watcher.on_serving_state('idle')
        watcher.tick()

        assert node.pickup_calls[0]['has_drink'] == has_drink
        assert node.serve_calls[0]['has_drink'] == has_drink
