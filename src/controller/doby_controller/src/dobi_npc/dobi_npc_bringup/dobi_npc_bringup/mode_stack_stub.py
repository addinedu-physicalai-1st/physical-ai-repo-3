#!/usr/bin/env python3
"""
mode_stack_stub.py
모드별 stack 의 자리표시 노드 (B 단계 검증용).

serving / follow 모드는 실 구현(Nav2 waypoint follower / person tracker)이
별 트랙에서 진행될 예정. 본 노드는 mode_manager 의 spawn/kill 흐름을 검증할
때 "stack 노드가 실제로 떠있다" 는 사실만 ros2 node list 로 확인 가능하게
만드는 더미.

파라미터:
  mode_label   : "serving" | "follow"
  params_json  : 모드 진입 시 전달된 JSON params (운영자 UI/SetMode srv 입력)

동작:
  1Hz 로 "{mode_label} stack alive: {params_json}" INFO log.

추후 작업:
  serving 실 구현 시 Nav2 NavigateThroughPoses client 추가
  follow 실 구현 시 person tracker 구독 + reactive controller
"""

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException


class ModeStackStub(Node):
    def __init__(self):
        super().__init__('mode_stack_stub')

        self.declare_parameter('mode_label', 'unknown')
        self.declare_parameter('params_json', '')

        self.mode_label = self.get_parameter('mode_label').value
        self.params_json = self.get_parameter('params_json').value

        self.get_logger().info(
            f'mode_stack_stub start: mode={self.mode_label} '
            f'params={self.params_json!r}')

        self.create_timer(1.0, self._tick)

    def _tick(self):
        self.get_logger().info(
            f'{self.mode_label} stack alive: {self.params_json!r}')


def main(args=None):
    rclpy.init(args=args)
    node = ModeStackStub()
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
