import time
from unittest.mock import MagicMock

from dobi_npc_bringup.task_orchestrator_node import (
    OrchestratorConfig,
    TaskOrchestratorNode,
)


def make_node(current_mode='serving', state_seq=2):
    node = object.__new__(TaskOrchestratorNode)
    node.current_mode = current_mode
    node._serving_state_seq = state_seq
    return node


def make_autoreturn_node(route='T03', routes=('T01', 'T02', 'T03')):
    node = object.__new__(TaskOrchestratorNode)
    node.current_mode = 'serving'
    node.config = OrchestratorConfig()
    node._active_serving_route = route
    node._last_serving_state_json = {'state': 'idle', 'routes': list(routes)}
    node._serving_return_pending = False
    node._serving_return_started = False
    node._serving_return_deadline = 0.0
    node._return_fallback_sec = 8.0
    node._serving_done_started_at = None
    node._serving_progress_seen = True
    node._completion_running = {'serving'}
    node._mode_done_started_at = {
        'patrol': None,
        'guiding': None,
        'engaging': None,
    }
    node._serving_goto_pub = MagicMock()
    node._request_idle_after_completion = MagicMock()
    node.get_logger = MagicMock(return_value=MagicMock())
    return node


def test_serving_idle_without_progress_is_failure():
    node = make_node()

    assert node._serving_failed_before_progress(
        {'state': 'idle', 'current_table': None, 'queue': []},
        progress_seen=False,
        start_state_seq=1,
    )


def test_serving_failure_needs_new_state_after_action_start():
    node = make_node(state_seq=1)

    assert not node._serving_failed_before_progress(
        {'state': 'idle', 'current_table': None, 'queue': []},
        progress_seen=False,
        start_state_seq=1,
    )


def test_serving_failure_ignores_progress_and_non_empty_queue():
    node = make_node()

    assert not node._serving_failed_before_progress(
        {'state': 'idle', 'current_table': None, 'queue': []},
        progress_seen=True,
        start_state_seq=1,
    )
    assert not node._serving_failed_before_progress(
        {'state': 'idle', 'current_table': None, 'queue': ['T01']},
        progress_seen=False,
        start_state_seq=1,
    )
    assert not node._serving_failed_before_progress(
        {'state': 'navigating', 'current_table': 'T01', 'queue': []},
        progress_seen=False,
        start_state_seq=1,
    )


def test_after_serve_success_requests_route_return_before_idle():
    node = make_autoreturn_node(route='T03')

    node._after_serve(True, 'ok')

    published = node._serving_goto_pub.publish.call_args.args[0]
    assert published.data == 'T03:return'
    assert node._serving_return_pending is True
    assert node._serving_return_started is False
    assert 'serving' in node._completion_running
    node._request_idle_after_completion.assert_not_called()


def test_after_serve_skips_return_for_non_route_target():
    node = make_autoreturn_node(route='T09', routes=('T01', 'T02', 'T03'))

    node._after_serve(True, 'ok')

    node._serving_goto_pub.publish.assert_not_called()
    assert node._serving_return_pending is False
    assert 'serving' not in node._completion_running
    node._request_idle_after_completion.assert_called_once_with(
        'serving', override_priority=True)


def test_tick_completion_waits_for_return_to_start_or_deadline():
    node = make_autoreturn_node(route='T03')
    node._serving_return_pending = True
    node._serving_return_started = False
    node._serving_return_deadline = time.time() + 10.0
    node._serving_done_started_at = time.time() - 10.0

    node._tick_completion()

    node._request_idle_after_completion.assert_not_called()
    assert node._serving_return_pending is True


def test_tick_completion_idles_after_return_completes():
    node = make_autoreturn_node(route='T03')
    node._serving_return_pending = True
    node._serving_return_started = True
    node._serving_done_started_at = time.time() - 10.0

    node._tick_completion()

    assert node._serving_return_pending is False
    assert 'serving' not in node._completion_running
    node._request_idle_after_completion.assert_called_once_with(
        'serving', override_priority=True)
