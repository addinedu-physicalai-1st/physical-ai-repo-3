#!/usr/bin/env python3
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray


class GripperMimicFollower(Node):
    def __init__(self):
        super().__init__("openarm_gripper_mimic_follower")
        self.declare_parameter("min_position", 0.0)
        self.declare_parameter("max_position", 0.044)
        self.declare_parameter("publish_rate", 50.0)

        self.min_position = float(self.get_parameter("min_position").value)
        self.max_position = float(self.get_parameter("max_position").value)
        publish_rate = float(self.get_parameter("publish_rate").value)

        self.source_joints = {
            "left": "openarm_left_finger_joint1",
            "right": "openarm_right_finger_joint1",
        }
        self.last_positions = {}

        self.command_publishers = {
            "left": self.create_publisher(
                Float64MultiArray,
                "/left_finger_mimic_controller/commands",
                10,
            ),
            "right": self.create_publisher(
                Float64MultiArray,
                "/right_finger_mimic_controller/commands",
                10,
            ),
        }

        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        self.create_timer(1.0 / publish_rate, self._publish_commands)

    def _on_joint_states(self, msg):
        positions = dict(zip(msg.name, msg.position))
        for side, joint_name in self.source_joints.items():
            if joint_name in positions:
                value = positions[joint_name]
                if math.isfinite(value):
                    self.last_positions[side] = min(
                        self.max_position,
                        max(self.min_position, float(value)),
                    )

    def _publish_commands(self):
        for side, publisher in self.command_publishers.items():
            if side not in self.last_positions:
                continue
            msg = Float64MultiArray()
            msg.data = [self.last_positions[side]]
            publisher.publish(msg)


def main():
    rclpy.init()
    node = GripperMimicFollower()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
