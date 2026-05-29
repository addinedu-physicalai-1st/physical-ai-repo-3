"""gimbal_serial unit tests -- pure python, no hardware/serial."""
from __future__ import annotations

from dobi_gimbal.gimbal_serial import (
    ServoCmd,
    ServoState,
    build_cmd_line,
    build_reset_line,
    clamp,
    parse_line,
)


def test_build_cmd_home():
    # home = front: pan 198, tilt 90
    assert build_cmd_line(ServoCmd(198, 90)) == b'P198,T90\n'


def test_build_cmd_absolute_range():
    assert build_cmd_line(ServoCmd(270, 0)) == b'P270,T0\n'
    assert build_cmd_line(ServoCmd(90, 90)) == b'P90,T90\n'


def test_build_cmd_truncates_float():
    # Arduino takes int only -- float is truncated
    assert build_cmd_line(ServoCmd(180.7, 90.2)) == b'P180,T90\n'


def test_build_reset_line():
    assert build_reset_line() == b'R\n'


def test_clamp_within():
    assert clamp(150, 90, 270) == 150


def test_clamp_low():
    assert clamp(50, 90, 270) == 90


def test_clamp_high():
    assert clamp(300, 90, 270) == 270


def test_parse_boot():
    assert parse_line('B') == 'B'
    assert parse_line('B\r\n') == 'B'      # CRLF strip


def test_parse_state_normal():
    assert parse_line('S180,90') == ServoState(180, 90)
    assert parse_line('S90,0\r\n') == ServoState(90, 0)
    assert parse_line('S270,0') == ServoState(270, 0)


def test_parse_empty_or_none():
    assert parse_line('') is None
    assert parse_line('   ') is None
    assert parse_line('\r\n') is None


def test_parse_garbage():
    assert parse_line('hello') is None
    assert parse_line('P180,T90') is None   # cmd echo -- we only handle 'S'
    assert parse_line('S180') is None        # no comma
    assert parse_line('S180,abc') is None    # int parse fail
    assert parse_line('S180,90,9') is None   # 3 fields


def test_round_trip():
    cmd = ServoCmd(270, 0)
    line = build_cmd_line(cmd)
    assert line == b'P270,T0\n'
    echo = f'S{int(cmd.pan_deg)},{int(cmd.tilt_deg)}'
    parsed = parse_line(echo)
    assert isinstance(parsed, ServoState)
    assert (parsed.pan_deg, parsed.tilt_deg) == (270, 0)
