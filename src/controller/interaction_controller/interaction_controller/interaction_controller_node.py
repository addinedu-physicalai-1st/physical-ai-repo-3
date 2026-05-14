import rclpy
from rclpy.node import Node


class InteractionControllerNode(Node):
    def __init__(self):
        super().__init__('interaction_controller')
        self.declare_parameter('controller_name', 'interaction_controller')
        controller_name = self.get_parameter('controller_name').value
        self.get_logger().info(f'{controller_name} started')


def main(args=None):
    rclpy.init(args=args)
    node = InteractionControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
