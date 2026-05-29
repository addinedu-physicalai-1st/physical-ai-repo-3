"""dobi_gimbal serial protocol -- pure functions, ROS/pyserial free.

Ported from scout_reactor.scout_serial, adapted for the dobi pan-tilt gimbal:
  Pan  : MG995 270deg servo (Arduino D9)
  Tilt : MG995 180deg servo (Arduino D10)
Protocol carries ABSOLUTE servo degrees (not scout's centered +/-90).

PC -> Arduino : "P<int>,T<int>\\n"   target absolute servo deg (pan 0..270, tilt 0..180)
                "R\\n"               reset to home
Arduino -> PC : "S<int>,<int>\\n"    current absolute servo deg echo (~50Hz)
                "B\\n"               boot banner
"""
from __future__ import annotations

from typing import NamedTuple, Union


class ServoCmd(NamedTuple):
    pan_deg: float
    tilt_deg: float


class ServoState(NamedTuple):
    pan_deg: int
    tilt_deg: int


def build_cmd_line(cmd: ServoCmd) -> bytes:
    """ServoCmd -> sketch line. Arduino takes ints, so float is truncated."""
    return f'P{int(cmd.pan_deg)},T{int(cmd.tilt_deg)}\n'.encode()


def build_reset_line() -> bytes:
    return b'R\n'


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value into [lo, hi] (assumes lo <= hi)."""
    return max(lo, min(hi, value))


def parse_line(line: str) -> Union[ServoState, str, None]:
    """Parse one Arduino line. 'S..' -> ServoState, 'B' -> 'B', else None."""
    s = line.strip()
    if not s:
        return None
    if s == 'B':
        return 'B'
    if s[0] == 'S':
        parts = s[1:].split(',')
        if len(parts) != 2:
            return None
        try:
            return ServoState(int(parts[0]), int(parts[1]))
        except ValueError:
            return None
    return None
