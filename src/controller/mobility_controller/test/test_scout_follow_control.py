import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from scout_follow_controller_node import (  # noqa: E402
    cx_to_angular, bh_to_linear, yaw_from_quat, handoff_servo_pan, handoff_done,
    select_target_track, next_state,
)


def test_cx_center_returns_zero():
    assert cx_to_angular(320.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) == 0.0


def test_cx_within_deadband_returns_zero():
    assert cx_to_angular(327.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) == 0.0


def test_cx_right_of_center_turns_right_when_sign_pos():
    assert cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) < 0.0


def test_cx_left_of_center_turns_left_when_sign_pos():
    assert cx_to_angular(80.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) > 0.0


def test_cx_sign_flip_inverts_direction():
    a = cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1)
    b = cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=-1)
    assert a == -b


def test_cx_clamps_to_max_w():
    w = cx_to_angular(640.0, 640, kp=10.0, max_w=0.5, deadband_px=10.0, sign=1)
    assert w == -0.5


def test_bh_far_goes_forward():
    assert bh_to_linear(0.20, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) > 0.0


def test_bh_at_target_returns_zero():
    assert bh_to_linear(0.45, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_within_deadband_returns_zero():
    assert bh_to_linear(0.47, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_closer_than_target_never_reverses():
    assert bh_to_linear(0.60, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_too_close_stop():
    assert bh_to_linear(0.80, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_clamps_to_max_v():
    assert bh_to_linear(0.0, target_bh=0.45, kp=10.0, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.15


def test_yaw_from_quat_identity_is_zero():
    assert abs(yaw_from_quat(0.0, 0.0, 0.0, 1.0)) < 1e-9


def test_yaw_from_quat_90deg():
    z, w = math.sin(math.pi / 4), math.cos(math.pi / 4)
    assert abs(yaw_from_quat(0.0, 0.0, z, w) - math.pi / 2) < 1e-6


def test_handoff_servo_pan_unwinds_with_base():
    assert abs(handoff_servo_pan(0.6, 0.2, servo_limit=1.0) - 0.4) < 1e-9


def test_handoff_servo_pan_clamps():
    assert handoff_servo_pan(2.0, 0.0, servo_limit=0.8) == 0.8
    assert handoff_servo_pan(-2.0, 0.0, servo_limit=0.8) == -0.8


def test_handoff_done_true():
    assert handoff_done(0.58, 0.6, tol_rad=0.05) is True


def test_handoff_done_false():
    assert handoff_done(0.2, 0.6, tol_rad=0.05) is False


def test_select_target_track_picks_centermost():
    tracks = [(3, 100.0, 240, 50, 200), (7, 330.0, 240, 50, 200), (9, 600.0, 240, 50, 200)]
    assert select_target_track(tracks, image_width=640) == 7


def test_select_target_track_empty_returns_none():
    assert select_target_track([], image_width=640) is None


def test_fsm_search_to_handoff_on_locked():
    assert next_state('SEARCH', 'locked', False, False, 0.0, 2.0) == 'HANDOFF'


def test_fsm_search_stays():
    assert next_state('SEARCH', 'searching', False, False, 0.0, 2.0) == 'SEARCH'


def test_fsm_handoff_to_follow():
    assert next_state('HANDOFF', 'locked', True, True, 0.0, 2.0) == 'FOLLOW'


def test_fsm_follow_to_lost():
    assert next_state('FOLLOW', 'locked', False, True, 0.0, 2.0) == 'LOST'


def test_fsm_lost_back_to_follow():
    assert next_state('LOST', 'locked', True, True, 0.5, 2.0) == 'FOLLOW'


def test_fsm_lost_to_search_after_dwell():
    assert next_state('LOST', 'searching', False, True, 2.5, 2.0) == 'SEARCH'
