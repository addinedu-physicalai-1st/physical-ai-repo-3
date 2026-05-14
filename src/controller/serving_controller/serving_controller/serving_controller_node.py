import rclpy
from rclpy.node import Node


class ServingControllerNode(Node):
    def __init__(self):
        super().__init__('serving_controller')
        self.declare_parameter('controller_name', 'serving_controller')
        controller_name = self.get_parameter('controller_name').value
        self.get_logger().info(f'{controller_name} started')


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
