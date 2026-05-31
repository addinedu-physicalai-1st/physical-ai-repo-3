"""Mode transition policy shared by mode_manager tests and runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json


PRIORITY = {
    'serving': 1,
    'guiding': 2,
    'patrol': 3,
    'follow': 4,
    'engaging': 5,
    'idle': 99,
}

VALID_MODES = tuple(PRIORITY.keys())


@dataclass(frozen=True)
class ModeDecision:
    allowed: bool
    reason: str
    noop: bool = False


def validate_params(params: str) -> str:
    """Return an empty string when params is valid, otherwise a reject reason."""
    if not params or not params.strip():
        return ''
    try:
        json.loads(params)
    except json.JSONDecodeError as exc:
        return f'invalid_json_params:{exc.msg}'
    return ''


def decide_transition(
    current_mode: str,
    requested_mode: str,
    *,
    override_priority: bool = False,
) -> ModeDecision:
    """Evaluate mode-only transition rules.

    Battery, safety, and transition-busy guards are deliberately kept in
    mode_manager because they depend on live node state.
    """
    if requested_mode not in PRIORITY:
        return ModeDecision(False, f'unknown_mode:{requested_mode}')

    if requested_mode == current_mode:
        if requested_mode == 'idle':
            return ModeDecision(True, 'idle_noop', noop=True)
        return ModeDecision(True, 'same_mode_noop', noop=True)

    if requested_mode == 'idle':
        return ModeDecision(True, 'idle_allowed')

    if (
        not override_priority
        and current_mode != 'idle'
        and PRIORITY[requested_mode] >= PRIORITY.get(current_mode, PRIORITY['idle'])
    ):
        return ModeDecision(False, f'lower_priority_during_{current_mode}')

    return ModeDecision(True, 'transition_allowed')
