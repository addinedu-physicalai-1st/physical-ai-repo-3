#!/usr/bin/env python3
"""Phase 0-B placeholder for dobi_npc_emotion.

Real implementation: Phase 2 Week 4-6 (GEFA, GEVA, V-A mapper, decision rule)

Note: This file uses the canonical ROS2 Jazzy node lifecycle pattern.
Phase 1+ real nodes should follow the same skeleton.
"""

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException


class DummyEmotionNode(Node):
    """Phase 0-B placeholder. Real logic added in: Phase 2 Week 4-6 (GEFA, GEVA, V-A mapper, decision rule)"""

    def __init__(self):
        super().__init__('dummy_emotion_node')
        self.get_logger().info(
            f"Phase 0-B placeholder for {self.get_name()}. "
            f"Real impl: Phase 2 Week 4-6 (GEFA, GEVA, V-A mapper, decision rule)"
        )


def main(args=None):
    rclpy.init(args=args)
    node = DummyEmotionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # KeyboardInterrupt: Ctrl+C
        # ExternalShutdownException: SIGTERM, ros2 lifecycle, etc.
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
