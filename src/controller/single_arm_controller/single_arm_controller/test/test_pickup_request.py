#!/usr/bin/env python3
"""
test_pickup_request.py - act_serving_controller Pickup 실제 호출 테스트

실행:
  터미널 1: source install/setup.bash && ros2 launch single_arm_controller act_serving.launch.py
  터미널 2: source install/setup.bash && python3 src/controller/single_arm_controller/single_arm_controller/test/test_pickup_request.py
"""

import time
import threading
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup

DWELL_SEC = 3.0


class PickupRequestNode(Node):

    def __init__(self):
        super().__init__('pickup_request_test')
        self._cb_group = ReentrantCallbackGroup()
        self._pickup_ac = ActionClient(
            self, Pickup, 'pickup',
            callback_group=self._cb_group,
        )
        self._done = False

    def run(self):
        # ── 1. 서버 대기 ──────────────────────────────────────────────
        print('\n[1] serving.py action server 대기 중...')
        if not self._pickup_ac.wait_for_server(timeout_sec=10.0):
            print('[FAIL] serving.py 가 실행되지 않았습니다.')
            print('       터미널 1에서 먼저 실행하세요:')
            print('       ros2 run single_arm_controller serving')
            self._done = True
            return

        print('[OK] server ready')

        # ── 2. send_goal ──────────────────────────────────────────────
        goal = Pickup.Goal()  # Goal 필드 없음 (empty trigger)

        print('\n[2] send_goal_async → serving.py (pickup)')
        self._goal_sent_at = time.time()

        send_future = self._pickup_ac.send_goal_async(
            goal,
            feedback_callback=self._on_feedback,
        )
        send_future.add_done_callback(self._on_goal_accepted)

    # ── goal 수락 확인 ────────────────────────────────────────────────
    def _on_goal_accepted(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            print('[FAIL] goal rejected')
            self._done = True
            return

        elapsed = time.time() - self._goal_sent_at
        print(f'[OK] goal accepted ({elapsed*1000:.0f}ms)')

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    # ── feedback ─────────────────────────────────────────────────────
    def _on_feedback(self, feedback_msg):
        status = feedback_msg.feedback.status
        elapsed = time.time() - self._goal_sent_at
        print(f'    feedback [{elapsed:.1f}s]: {status}')

    # ── result 수신 ───────────────────────────────────────────────────
    def _on_result(self, future):
        result = future.result().result
        latency = time.time() - self._goal_sent_at

        print(f'\n[3] result 수신 (latency={latency:.2f}s):')
        print(f'    success = {result.success}')
        print(f'    message = "{result.message}"')

        if result.success:
            print('\n[OK] pickup 성공')
        else:
            print('\n[WARN] pickup 실패')

        # ── dwell 3.0s ────────────────────────────────────────────────
        print(f'\n[4] dwell {DWELL_SEC}s 시작...')
        for i in range(int(DWELL_SEC)):
            time.sleep(1.0)
            print(f'    ... {i+1}/{int(DWELL_SEC)}s')

        print('\n[5] dwell 완료')
        self._done = True


def main():
    rclpy.init()
    node = PickupRequestNode()

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    node.run()

    while not node._done:
        time.sleep(0.1)

    executor.shutdown(timeout_sec=2.0)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
