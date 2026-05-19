import pytest

from app.protocol.health_status_protocol import (
    HEALTH_CMD,
    STATUS_CMD,
    build_frame,
    build_status_frame,
    parse_frame,
)


def test_health_status_frame_round_trip():
    assert parse_frame(build_frame(HEALTH_CMD, 7)) == (HEALTH_CMD, 7)
    assert parse_frame(build_status_frame(9)) == (STATUS_CMD, 9)


def test_health_status_frame_masks_command_and_sequence_to_one_byte():
    assert build_frame(0x110, 0x107) == bytes([0x02, 0x10, 0x07, 0x03])


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        bytes([0x00, HEALTH_CMD, 1, 0x03]),
        bytes([0x02, 0x99, 1, 0x03]),
        bytes([0x02, HEALTH_CMD, 1, 0x00]),
    ],
)
def test_health_status_frame_rejects_invalid_frames(frame):
    with pytest.raises(ValueError):
        parse_frame(frame)
