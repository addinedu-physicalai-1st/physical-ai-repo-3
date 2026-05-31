from dobi_npc_bringup.mode_policy import decide_transition, validate_params


def test_priority_blocks_lower_or_equal_active_mode():
    decision = decide_transition('guiding', 'patrol')
    assert not decision.allowed
    assert decision.reason == 'lower_priority_during_guiding'


def test_priority_allows_higher_active_mode():
    decision = decide_transition('guiding', 'serving')
    assert decision.allowed
    assert decision.reason == 'transition_allowed'


def test_override_bypasses_priority_only():
    decision = decide_transition('serving', 'engaging', override_priority=True)
    assert decision.allowed


def test_idle_always_allowed_and_idle_noop_success():
    assert decide_transition('serving', 'idle').allowed
    decision = decide_transition('idle', 'idle')
    assert decision.allowed
    assert decision.noop
    assert decision.reason == 'idle_noop'


def test_same_non_idle_is_noop():
    decision = decide_transition('serving', 'serving')
    assert decision.allowed
    assert decision.noop
    assert decision.reason == 'same_mode_noop'


def test_invalid_mode_and_params_validation():
    assert decide_transition('idle', 'invalid').reason == 'unknown_mode:invalid'
    assert validate_params('{"ok": true}') == ''
    assert validate_params('{bad') == (
        'invalid_json_params:Expecting property name enclosed in double quotes'
    )
