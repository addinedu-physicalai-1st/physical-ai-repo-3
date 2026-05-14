import rclpy
from rclpy.node import Node


class SingleArmControllerNode(Node):
    def __init__(self):
        super().__init__('single_arm_controller')
        self.declare_parameter('controller_name', 'single_arm_controller')
        controller_name = self.get_parameter('controller_name').value
        self.get_logger().info(f'{controller_name} started')


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
