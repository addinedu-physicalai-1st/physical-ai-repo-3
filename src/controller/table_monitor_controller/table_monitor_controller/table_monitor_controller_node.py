import rclpy
from rclpy.node import Node


class TableMonitorControllerNode(Node):
    def __init__(self):
        super().__init__('table_monitor_controller')
        self.declare_parameter('controller_name', 'table_monitor_controller')
        controller_name = self.get_parameter('controller_name').value
        self.get_logger().info(f'{controller_name} started')


def main(args=None):
    rclpy.init(args=args)
    node = TableMonitorControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
