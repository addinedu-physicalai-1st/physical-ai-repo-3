from controller_status_msgs.msg import Status
import rclpy
from rclpy.node import Node


class ControllerStatusMonitor(Node):
    def __init__(self):
        super().__init__('controller_status_monitor')
        self.declare_parameter('controller_name', 'single_arm_controller')
        controller_name = self.get_parameter('controller_name').value
        self._controller_status_subscription = self.create_subscription(
            Status,
            '/dobi_controller/status',
            self.handle_controller_status,
            10,
        )
        self.get_logger().info(f'{controller_name} started')

    def handle_controller_status(self, message):
        self.get_logger().info(
            'single_arm_controller received /dobi_controller/status: '
            f'request_id={message.request_id}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = ControllerStatusMonitor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
