import json
import socket
from functools import partial

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from service_controller_bridge.tcp_frame import build_status_frame


class ServiceControllerBridgeNode(Node):
    def __init__(self):
        super().__init__('service_controller_bridge')
        self.declare_parameter(
            'status_topics',
            ['/cooking_controller/status', '/serving_controller/status'],
        )
        self.declare_parameter('control_service_host', '127.0.0.1')
        self.declare_parameter('control_service_port', 9002)
        self.declare_parameter('tcp_timeout_sec', 3.0)

        status_topics = self.get_parameter('status_topics').value
        self._host = self.get_parameter('control_service_host').value
        self._port = int(self.get_parameter('control_service_port').value)
        self._timeout = float(self.get_parameter('tcp_timeout_sec').value)
        self._subscriptions = [
            self.create_subscription(
                String,
                topic,
                partial(self._handle_status, topic),
                10,
            )
            for topic in status_topics
        ]

        self.get_logger().info(
            f'bridging controller status topics to control_service TCP '
            f'{self._host}:{self._port}: {list(status_topics)}'
        )

    def _handle_status(self, topic: str, message: String) -> None:
        seq = self._extract_seq(topic, message.data)
        try:
            with socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout,
            ) as sock:
                sock.sendall(build_status_frame(seq))
        except OSError as exc:
            self.get_logger().warning(
                f'failed to send STATUS seq={seq} from {topic} '
                f'to {self._host}:{self._port}: {exc}'
            )
            return

        self.get_logger().info(f'sent STATUS seq={seq} from {topic} to control_service')

    def _extract_seq(self, topic: str, payload: str) -> int:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.get_logger().warning(f'{topic} status payload is not JSON; using seq=0')
            return 0

        try:
            return int(data.get('request_id', 0))
        except (TypeError, ValueError):
            self.get_logger().warning(f'{topic} request_id is invalid; using seq=0')
            return 0


def main(args=None):
    rclpy.init(args=args)
    node = ServiceControllerBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
