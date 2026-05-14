STX = 0x02
HEALTH_CMD = 0x01
STATUS_CMD = 0x10
ETX = 0x03
FRAME_SIZE = 4


def build_frame(cmd: int, seq: int) -> bytes:
    return bytes([STX, cmd & 0xFF, seq & 0xFF, ETX])


def build_status_frame(seq: int) -> bytes:
    return build_frame(STATUS_CMD, seq)


def parse_frame(frame: bytes) -> tuple[int, int]:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"invalid frame length: {len(frame)}")
    stx, cmd, seq, etx = frame
    if stx != STX:
        raise ValueError(f"invalid STX: 0x{stx:02X}")
    if cmd not in {HEALTH_CMD, STATUS_CMD}:
        raise ValueError(f"unsupported CMD: 0x{cmd:02X}")
    if etx != ETX:
        raise ValueError(f"invalid ETX: 0x{etx:02X}")
    return cmd, seq
