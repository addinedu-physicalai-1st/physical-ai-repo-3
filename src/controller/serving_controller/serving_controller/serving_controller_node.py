import json
import socket
import socketserver
import threading

from controller_status_msgs.msg import Status
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger

STX = 0x02
STATUS_CMD = 0x10
ETX = 0x03
FRAME_SIZE = 4


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def build_status_frame(seq: int) -> bytes:
    return bytes([STX, STATUS_CMD, seq & 0xFF, ETX])


def parse_frame(frame: bytes) -> tuple[int, int]:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f'invalid frame length: {len(frame)}')

    stx, cmd, seq, etx = frame
    if stx != STX:
        raise ValueError(f'invalid STX: 0x{stx:02X}')
    if cmd != STATUS_CMD:
        raise ValueError(f'unsupported CMD: 0x{cmd:02X}')
    if etx != ETX:
        raise ValueError(f'invalid ETX: 0x{etx:02X}')

    return cmd, seq


def create_service_status_handler(node: 'ServingControllerNode'):
    class RequestHandler(socketserver.BaseRequestHandler):
        def handle(self):
            peer = self.client_address
            node.get_logger().debug(f'control_service tcp client connected: {peer}')
            try:
                while True:
                    frame = self._read_exact()
                    if frame is None:
                        return

                    try:
                        _, seq = parse_frame(frame)
                    except ValueError as exc:
                        node.get_logger().warning(
                            f'invalid control_service tcp frame from {peer}: {exc}'
                        )
                        continue

                    node.publish_control_service_status(seq)
            finally:
                node.get_logger().debug(f'control_service tcp client disconnected: {peer}')

        def _read_exact(self):
            chunks = bytearray()
            while len(chunks) < FRAME_SIZE:
                try:
                    chunk = self.request.recv(FRAME_SIZE - len(chunks))
                except OSError as exc:
                    node.get_logger().warning(
                        f'control_service tcp read failed from {self.client_address}: {exc}'
                    )
                    return None

                if not chunk:
                    return None

                chunks.extend(chunk)

            return bytes(chunks)

    return RequestHandler


class ServingControllerNode(Node):
    def __init__(self):
        super().__init__('serving_controller')
        self.declare_parameter('controller_name', 'serving_controller')
        self.declare_parameter('control_service_host', '127.0.0.1')
        self.declare_parameter('control_service_port', 9002)
        self.declare_parameter('tcp_timeout_sec', 3.0)
        self.declare_parameter('service_listener_host', '0.0.0.0')
        self.declare_parameter('service_listener_port', 9006)
        self.declare_parameter('control_status_topic', '/control_service/status')
        controller_name = self.get_parameter('controller_name').value
        self._control_service_host = self.get_parameter('control_service_host').value
        self._control_service_port = int(self.get_parameter('control_service_port').value)
        self._tcp_timeout = float(self.get_parameter('tcp_timeout_sec').value)
        self._service_listener_host = self.get_parameter('service_listener_host').value
        self._service_listener_port = int(self.get_parameter('service_listener_port').value)
        self._control_status_topic = self.get_parameter('control_status_topic').value
        self._request_id = 0
        self._targets = [
            'vic_pinky_controller',
            'single_arm_controller',
            'interaction_controller',
            'control_service',
        ]
        self._status_publisher = self.create_publisher(
            Status,
            '/serving_controller/status',
            10,
        )
        self._control_service_status_publisher = self.create_publisher(
            String,
            self._control_status_topic,
            10,
        )
        self._health_service = self.create_service(
            Trigger,
            '/serving_controller/health_check',
            self._handle_health_check,
        )
        self._server = ThreadingTcpServer(
            (self._service_listener_host, self._service_listener_port),
            create_service_status_handler(self),
        )
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name='serving-controller-tcp-bridge',
            daemon=True,
        )
        self._server_thread.start()
        self.get_logger().info(f'{controller_name} started')
        self.get_logger().info(
            f'bridging serving_controller status to control_service TCP '
            f'{self._control_service_host}:{self._control_service_port}'
        )
        self.get_logger().info(
            f'bridging control_service TCP '
            f'{self._service_listener_host}:{self._service_listener_port} '
            f'to ROS topic {self._control_status_topic}'
        )

    def _handle_health_check(self, request, response):
        del request
        self._request_id += 1
        payload = {
            'source': 'serving_controller',
            'event': 'health_status',
            'status': 'ok',
            'request_id': self._request_id,
            'targets': self._targets,
        }

        self.get_logger().info(
            f'received health check request_id={self._request_id}'
        )
        message = Status()
        message.request_id = payload['request_id']
        self._status_publisher.publish(message)
        self._send_status_to_control_service(self._request_id)
        self.get_logger().info(
            f'published status request_id={self._request_id} '
            f'targets=[{",".join(self._targets)}]'
        )

        response.success = True
        response.message = 'serving_controller health status published'
        return response

    def _send_status_to_control_service(self, seq: int) -> None:
        try:
            with socket.create_connection(
                (self._control_service_host, self._control_service_port),
                timeout=self._tcp_timeout,
            ) as sock:
                sock.sendall(build_status_frame(seq))
        except OSError as exc:
            self.get_logger().warning(
                f'failed to send STATUS seq={seq} to control_service '
                f'{self._control_service_host}:{self._control_service_port}: {exc}'
            )
            return

        self.get_logger().info(f'sent STATUS seq={seq} to control_service')

    def publish_control_service_status(self, seq: int) -> None:
        payload = {
            'source': 'control_service',
            'target': 'serving_controller',
            'event': 'health_status',
            'status': 'ok',
            'request_id': seq,
        }
        message = String()
        message.data = json.dumps(payload, separators=(',', ':'))
        self._control_service_status_publisher.publish(message)
        self.get_logger().info(
            f'published control_service STATUS seq={seq} to {self._control_status_topic}'
        )

    def destroy_node(self):
        self._server.shutdown()
        self._server.server_close()
        self._server_thread.join(timeout=1.0)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ServingControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
