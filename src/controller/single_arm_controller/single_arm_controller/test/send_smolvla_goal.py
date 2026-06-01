#!/usr/bin/env python3
"""
send_smolvla_goal.py — SmolVLA 액션 서버에 Pickup / Serve 목표를 수동으로 전송한다.

사용법:
  python3 send_smolvla_goal.py pickup
  python3 send_smolvla_goal.py serve --has-drink
  python3 send_smolvla_goal.py serve --no-drink
  python3 send_smolvla_goal.py pickup --timeout 60
"""

import argparse
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup, Serve


class SmolVLAGoalSender(Node):
    def __init__(self):
        super().__init__('smolvla_goal_sender')
        self._pickup_client = ActionClient(self, Pickup, 'pickup')
        self._serve_client  = ActionClient(self, Serve,  'serve')

    def send_pickup(self, timeout_s: float) -> bool:
        self.get_logger().info('Pickup 액션 서버 대기 중...')
        if not self._pickup_client.wait_for_server(timeout_sec=timeout_s):
            self.get_logger().error('Pickup 서버 연결 실패 (timeout)')
            return False

        goal = Pickup.Goal()
        self.get_logger().info('Pickup 목표 전송')
        return self._send_and_wait(self._pickup_client, goal, 'Pickup')

    def send_serve(self, has_drink: bool, timeout_s: float) -> bool:
        self.get_logger().info('Serve 액션 서버 대기 중...')
        if not self._serve_client.wait_for_server(timeout_sec=timeout_s):
            self.get_logger().error('Serve 서버 연결 실패 (timeout)')
            return False

        goal = Serve.Goal()
        goal.has_drink = has_drink
        self.get_logger().info(f'Serve 목표 전송 (has_drink={has_drink})')
        return self._send_and_wait(self._serve_client, goal, 'Serve')

    def _send_and_wait(self, client, goal, label: str) -> bool:
        send_future = client.send_goal_async(
            goal,
            feedback_callback=self._on_feedback,
        )
        rclpy.spin_until_future_complete(self, send_future)
        goal_handle = send_future.result()

        if not goal_handle.accepted:
            self.get_logger().error(f'{label} 목표 거절됨')
            return False

        self.get_logger().info(f'{label} 목표 수락됨 — 실행 대기 중...')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)

        result = result_future.result()
        status_map = {4: 'SUCCEEDED', 5: 'CANCELED', 6: 'ABORTED'}
        status_str = status_map.get(result.status, f'UNKNOWN({result.status})')

        self.get_logger().info(
            f'\n{"="*50}\n'
            f'{label} 완료\n'
            f'  status : {status_str}\n'
            f'  success: {result.result.success}\n'
            f'  message: {result.result.message}\n'
            f'{"="*50}'
        )
        return result.result.success

    def _on_feedback(self, feedback_msg):
        status = feedback_msg.feedback.status
        self.get_logger().info(f'[feedback] {status}')


def main():
    parser = argparse.ArgumentParser(
        description='SmolVLA 액션 서버에 Pickup / Serve 목표를 전송한다.',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        'action',
        choices=['pickup', 'serve'],
        help='전송할 액션 종류',
    )
    drink_group = parser.add_mutually_exclusive_group()
    drink_group.add_argument(
        '--has-drink',
        dest='has_drink',
        action='store_true',
        default=True,
        help='Serve: 음료 있음 (기본값)',
    )
    drink_group.add_argument(
        '--no-drink',
        dest='has_drink',
        action='store_false',
        help='Serve: 음료 없음',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=10.0,
        metavar='SEC',
        help='서버 연결 대기 시간 (기본값: 10초)',
    )

    args = parser.parse_args()

    rclpy.init()
    node = SmolVLAGoalSender()

    try:
        if args.action == 'pickup':
            success = node.send_pickup(timeout_s=args.timeout)
        else:
            success = node.send_serve(has_drink=args.has_drink, timeout_s=args.timeout)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
