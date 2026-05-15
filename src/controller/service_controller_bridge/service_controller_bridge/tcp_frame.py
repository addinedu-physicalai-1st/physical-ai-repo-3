STX = 0x02
STATUS_CMD = 0x10
ETX = 0x03


def build_status_frame(seq: int) -> bytes:
    return bytes([STX, STATUS_CMD, seq & 0xFF, ETX])
