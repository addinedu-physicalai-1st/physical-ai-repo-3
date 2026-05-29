"""dobi_gimbal calibration -- YAML load + effective_cmd transform.

Ported from scout_reactor.calib. ROS-free pure python.

Apply (host side, just before sketch TX):
    effective_cmd_deg = desired_deg * sign + offset
    then clamped to [min_deg, max_deg]  (servo safe range)

Inverse (sketch servo_state echo -> host desired):
    desired_deg = (effective_deg - offset) / sign

All *_deg values are ABSOLUTE servo degrees. YAML format -- see
config/dobi_gimbal_calib.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import yaml  # pyyaml -- if missing, defaults are used
except ImportError:
    yaml = None  # type: ignore


@dataclass(frozen=True)
class AxisCalib:
    """One axis: sign + zero offset + linear scale + safe range + home."""
    sign: int = 1          # +1 or -1
    offset: float = 0.0    # effective deg that corresponds to desired 0
    scale: float = 1.0     # linear-fit slope -- 1.0 = uncalibrated
    min_deg: float = 0.0   # effective servo deg lower safe bound
    max_deg: float = 180.0  # effective servo deg upper safe bound
    home_deg: float = 0.0  # rest / reset position (effective servo deg)

    def desired_to_effective(self, desired_deg: float) -> float:
        """user desired (deg) -> sketch TX value (effective servo deg)."""
        return desired_deg * self.sign + self.offset

    def effective_to_desired(self, effective_deg: float) -> float:
        """sketch servo_state echo (deg) -> user desired (deg)."""
        return (effective_deg - self.offset) / self.sign

    def clamp_effective(self, effective_deg: float) -> float:
        """Clamp an effective command into the servo safe range."""
        return max(self.min_deg, min(self.max_deg, effective_deg))


@dataclass(frozen=True)
class ServoCalib:
    """pan/tilt two-axis bundle."""
    pan: AxisCalib
    tilt: AxisCalib

    @classmethod
    def default(cls) -> 'ServoCalib':
        # dobi gimbal physical defaults (see memory: gimbal camera mount geometry).
        # Both axes are 270deg MG995 servos, 500..2500us full range.
        # Pan  D9 : front = 150 (horn re-mounted + re-calibrated), left = toward 320,
        #           right = toward 90, home 150, safe 90..320 (~170deg left travel).
        # Tilt D10: horn re-mounted + re-calibrated 2026-05-30. horizontal (level)
        #           = 115, home 115, down toward -45, up toward 240, safe -45..240.
        return cls(
            pan=AxisCalib(sign=1, offset=150.0, scale=1.0,
                          min_deg=90.0, max_deg=320.0, home_deg=150.0),
            tilt=AxisCalib(sign=-1, offset=115.0, scale=1.0,
                           min_deg=-45.0, max_deg=240.0, home_deg=115.0),
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'ServoCalib':
        dflt = cls.default()

        def axis(d: dict, dflt_axis: AxisCalib) -> AxisCalib:
            d = d or {}
            return AxisCalib(
                sign=int(d.get('sign', dflt_axis.sign)),
                offset=float(d.get('offset', dflt_axis.offset)),
                scale=float(d.get('scale', dflt_axis.scale)),
                min_deg=float(d.get('min_deg', dflt_axis.min_deg)),
                max_deg=float(d.get('max_deg', dflt_axis.max_deg)),
                home_deg=float(d.get('home_deg', dflt_axis.home_deg)),
            )

        return cls(
            pan=axis(data.get('pan', {}), dflt.pan),
            tilt=axis(data.get('tilt', {}), dflt.tilt),
        )


def load_calib_or_default(path) -> ServoCalib:
    """Load YAML. Falls back to dobi defaults if missing / pyyaml absent."""
    if path is None or yaml is None:
        return ServoCalib.default()
    p = Path(path)
    if not p.exists():
        return ServoCalib.default()
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return ServoCalib.from_dict(data)
    except Exception:
        return ServoCalib.default()
