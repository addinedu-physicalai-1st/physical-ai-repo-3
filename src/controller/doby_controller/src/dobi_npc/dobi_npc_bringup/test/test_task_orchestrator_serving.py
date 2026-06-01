from dobi_npc_bringup.task_orchestrator_node import TaskOrchestratorNode


def make_node(current_mode='serving', state_seq=2):
    node = object.__new__(TaskOrchestratorNode)
    node.current_mode = current_mode
    node._serving_state_seq = state_seq
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
