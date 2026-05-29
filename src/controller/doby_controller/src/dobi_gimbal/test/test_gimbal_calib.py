"""gimbal_calib unit tests -- desired<->effective transform + safe clamp."""
from __future__ import annotations

from dobi_gimbal.gimbal_calib import AxisCalib, ServoCalib


def test_default_is_dobi_gimbal():
    c = ServoCalib.default()
    # pan: front 198, safe 90..320 (extended for dock), home 198
    assert c.pan.sign == 1
    assert c.pan.offset == 150.0
    assert (c.pan.min_deg, c.pan.max_deg) == (90.0, 320.0)
    assert c.pan.home_deg == 150.0
    # tilt: horizontal 69, down toward 0 and below, safe -45..90, home 69, +=down
    assert c.tilt.sign == -1
    assert c.tilt.offset == 115.0
    assert (c.tilt.min_deg, c.tilt.max_deg) == (-45.0, 240.0)
    assert c.tilt.home_deg == 115.0


def test_pan_front_left_right():
    pan = AxisCalib(sign=1, offset=150.0, min_deg=90.0, max_deg=320.0)
    assert pan.desired_to_effective(0.0) == 150.0      # front (re-mounted + re-calibrated)
    assert pan.desired_to_effective(170.0) == 320.0    # +170 deg left -> safe max
    assert pan.desired_to_effective(-60.0) == 90.0     # -60 deg right -> safe min


def test_tilt_level_down_up():
    tilt = AxisCalib(sign=-1, offset=115.0, min_deg=-45.0, max_deg=240.0)
    assert tilt.desired_to_effective(0.0) == 115.0     # level (re-calibrated horizontal)
    assert tilt.desired_to_effective(160.0) == -45.0   # +160 deg down -> safe min
    assert tilt.desired_to_effective(-125.0) == 240.0  # -125 deg up -> safe max
    assert tilt.effective_to_desired(115.0) == 0.0     # eff 115 -> level
    assert tilt.clamp_effective(300.0) == 240.0
    assert tilt.clamp_effective(-100.0) == -45.0


def test_clamp_effective_safe_range():
    pan = AxisCalib(sign=1, offset=198.0, min_deg=90.0, max_deg=320.0)
    assert pan.clamp_effective(400.0) == 320.0
    assert pan.clamp_effective(50.0) == 90.0
    assert pan.clamp_effective(150.0) == 150.0


def test_inverse_round_trip():
    pan = AxisCalib(sign=1, offset=150.0)
    eff = pan.desired_to_effective(20.0)
    assert pan.effective_to_desired(eff) == 20.0


def test_sign_negative_inverts():
    ax = AxisCalib(sign=-1, offset=115.0)
    assert ax.desired_to_effective(10.0) == 105.0
    assert ax.effective_to_desired(105.0) == 10.0


def test_from_dict_overrides_and_defaults():
    c = ServoCalib.from_dict({'pan': {'offset': 200.0}})
    assert c.pan.offset == 200.0
    # unspecified fields fall back to dobi defaults
    assert c.pan.sign == 1
    assert c.pan.max_deg == 320.0
    # tilt entirely defaulted
    assert c.tilt.sign == -1
    assert c.tilt.offset == 115.0
    assert c.tilt.min_deg == -45.0
    assert c.tilt.max_deg == 240.0
