#!/usr/bin/env python3
"""
fake_customer_publisher.py
Phase 1 W2 Step C+D — 가짜 고객 위치 publisher.

dobi_npc_bt의 Approach 노드 검증용 임시 노드.
geometry_msgs/PoseStamped를 /customer_pose 토픽으로 1Hz 발행.

=== 사용 예 ===
  # 기본 (3.0m 앞)
  ros2 run dobi_npc_bringup fake_customer_publisher

  # 고객 위치 변경
  ros2 run dobi_npc_bringup fake_customer_publisher --ros-args -p customer_x:=2.0 -p customer_y:=1.0

  # abort 시나리오 검증 (0.5m → 1.0m 임계 안)
  ros2 run dobi_npc_bringup fake_customer_publisher --ros-args -p customer_x:=0.5

=== Phase 진화 ===
  Phase 2: 카메라 2 (RPC-20F) GEFA 사람 검출 노드로 교체.
"""

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import PoseStamped


class FakeCustomerPublisher(Node):
    def __init__(self):
        super().__init__('fake_customer_publisher')

        self.declare_parameter('customer_x', 3.0)
        self.declare_parameter('customer_y', 0.0)
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('publish_period_sec', 1.0)

        self.customer_x = float(self.get_parameter('customer_x').value)
        self.customer_y = float(self.get_parameter('customer_y').value)
        self.frame_id = self.get_parameter('frame_id').value
        period = float(self.get_parameter('publish_period_sec').value)

        self.pub_ = self.create_publisher(PoseStamped, '/customer_pose', 10)
        self.timer_ = self.create_timer(period, self.publish_pose)

        self.get_logger().info(
            f'Fake customer publisher: '
            f'({self.customer_x:.2f}, {self.customer_y:.2f}) '
            f'frame={self.frame_id}, period={period:.1f}s')

    def publish_pose(self):
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.pose.position.x = self.customer_x
        msg.pose.position.y = self.customer_y
        msg.pose.position.z = 0.0
        msg.pose.orientation.w = 1.0
        self.pub_.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = FakeCustomerPublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
