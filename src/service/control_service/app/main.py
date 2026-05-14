import logging
import os
import socket
import socketserver

SERVICE_NAME = os.getenv("CONTROL_SERVICE_NAME", "control_service")
HOST = os.getenv("CONTROL_SERVICE_HOST", "0.0.0.0")
PORT = int(os.getenv("CONTROL_SERVICE_PORT", "9002"))
BUSINESS_SERVICE_HOST = os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_HOST", "business_service")
BUSINESS_SERVICE_PORT = int(os.getenv("CONTROL_SERVICE_BUSINESS_SERVICE_PORT", "9001"))
VISION_SERVICE_HOST = os.getenv("CONTROL_SERVICE_VISION_SERVICE_HOST", "vision_service")
VISION_SERVICE_TCP_PORT = int(os.getenv("CONTROL_SERVICE_VISION_SERVICE_TCP_PORT", "9003"))
ROS_DOMAIN_ID = int(os.getenv("CONTROL_SERVICE_ROS_DOMAIN_ID", "0"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(SERVICE_NAME)

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


def send_status(host: str, port: int, seq: int, target_name: str) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3.0) as sock:
            sock.sendall(build_status_frame(seq))
    except OSError as exc:
        logger.warning("failed to send STATUS to %s at %s:%s: %s", target_name, host, port, exc)
        return False

    logger.info("sent STATUS to %s seq=%s", target_name, seq)
    return True


def run_health_test(seq: int) -> None:
    send_status(BUSINESS_SERVICE_HOST, BUSINESS_SERVICE_PORT, seq, "BusinessService")


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class RequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer = self.client_address
        logger.info("client connected: %s", peer)

        try:
            while True:
                frame = self._read_exact()
                if frame is None:
                    return

                try:
                    cmd, seq = parse_frame(frame)
                except ValueError as exc:
                    logger.warning("invalid tcp test frame from %s: %s", peer, exc)
                    continue

                if cmd == HEALTH_CMD:
                    logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
                    run_health_test(seq)
                elif cmd == STATUS_CMD:
                    logger.info("received STATUS probe from %s seq=%s", peer, seq)
        finally:
            logger.info("client disconnected: %s", peer)

    def _read_exact(self) -> bytes | None:
        chunks = bytearray()
        while len(chunks) < FRAME_SIZE:
            try:
                chunk = self.request.recv(FRAME_SIZE - len(chunks))
            except OSError as exc:
                logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    logger.warning(
                        "partial tcp test frame from %s: %s",
                        self.client_address,
                        bytes(chunks).hex(" "),
                    )
                return None
            chunks.extend(chunk)
        return bytes(chunks)


def main() -> None:
    with ThreadingTcpServer((HOST, PORT), RequestHandler) as server:
        logger.info("%s listening on %s", SERVICE_NAME, server.server_address)
        server.serve_forever()


if __name__ == "__main__":
    main()
