import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SingleArmControllerNode(Node):
    def __init__(self):
        super().__init__('single_arm_controller')
        self.declare_parameter('controller_name', 'single_arm_controller')
        controller_name = self.get_parameter('controller_name').value
        self._serving_status_subscription = self.create_subscription(
            String,
            '/serving_controller/status',
            self._handle_serving_status,
            10,
        )
        self.get_logger().info(f'{controller_name} started')

    def _handle_serving_status(self, message):
        self.get_logger().info(
            f'single_arm_controller received /serving_controller/status: {message.data}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = SingleArmControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
