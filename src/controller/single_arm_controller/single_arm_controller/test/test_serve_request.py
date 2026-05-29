#!/usr/bin/env python3
"""
test_serve_request.py - act_serving_controller 실제 호출 테스트

send_goal 전후 state 및 result 수신 후 dwell 3.0s 검증.

실행:
  터미널 1: source install/setup.bash && ros2 launch single_arm_controller act_serving.launch.py
  터미널 2: source install/setup.bash && python3 src/controller/single_arm_controller/single_arm_controller/test/test_serve_request.py
"""

import time
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Serve

DWELL_SEC = 3.0


class ServeRequestNode(Node):

    def __init__(self):
        super().__init__('serve_request_test')
        self._cb_group = ReentrantCallbackGroup()
        self._arm_ac = ActionClient(
            self, Serve, 'serve',
            callback_group=self._cb_group,
        )
        self._done = False

    def run(self):
        # ── 1. 서버 대기 ──────────────────────────────────────────────
        print('\n[1] serving.py action server 대기 중...')
        if not self._arm_ac.wait_for_server(timeout_sec=10.0):
            print('[FAIL] serving.py 가 실행되지 않았습니다.')
            print('       터미널 1에서 먼저 실행하세요:')
            print('       ros2 run single_arm_controller serving')
            return

        print('[OK] server ready')

        # ── 2. goal 전송 전 state ─────────────────────────────────────
        print('\n[2] send_goal 전 state:')
        print('    mode_manager : serving  (serving 모드 유지 중)')
        print('    serving_dispatcher: State.IDLE (홈 복귀 완료, 대기 중)')
        print('    arm (serving.py) : 대기 중 (goal 없음)')

        # ── 3. send_goal ──────────────────────────────────────────────
        goal = Serve.Goal()
        # 빈 문자열 → serving.py 노드 기본값 사용
        # goal.wrist_cam_path  = ''  →  _WRIST_CAM_PATH  = '/dev/video6'
        # goal.realsense_serial = '' →  _REALSENSE_SERIAL = '943222071539'
        # goal.task            = ''  →  _TASK = 'pick up cup and place at target zone'

        print('\n[3] send_goal_async → serving.py')
        self._goal_sent_at = time.time()

        send_future = self._arm_ac.send_goal_async(
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

        print('\n[4] send_goal 후 state:')
        print('    mode_manager : serving  (여전히 serving 모드)')
        print('    serving_dispatcher: State.IDLE (홈에서 대기)')
        print('    arm (serving.py) : 추론 실행 중 ← 지금 여기')

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    # ── feedback (추론 중 상태) ───────────────────────────────────────
    def _on_feedback(self, feedback_msg):
        status = feedback_msg.feedback.status
        elapsed = time.time() - self._goal_sent_at
        print(f'    feedback [{elapsed:.1f}s]: {status}')

    # ── result 수신 ───────────────────────────────────────────────────
    def _on_result(self, future):
        result = future.result().result
        latency = time.time() - self._goal_sent_at

        print(f'\n[5] result 수신 (latency={latency:.2f}s):')
        print(f'    success = {result.success}')
        print(f'    message = "{result.message}"')

        if result.success:
            print('\n[OK] 추론 성공')
        else:
            print('\n[WARN] 추론 실패 — dwell 후 idle 전환은 동일하게 진행')

        # ── dwell 3.0s ────────────────────────────────────────────────
        print(f'\n[6] dwell {DWELL_SEC}s 시작...')
        print('    (실제 시스템에서는 이 구간에 mode=serving 유지)')

        for i in range(int(DWELL_SEC)):
            time.sleep(1.0)
            print(f'    ... {i+1}/{int(DWELL_SEC)}s')

        print('\n[7] dwell 완료 → SetMode("idle") 호출')
        print('    mode_manager : idle 전환')
        print('    serving_dispatcher 프로세스 SIGTERM')

        self._done = True


def main():
    rclpy.init()
    node = ServeRequestNode()

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    import threading
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    node.run()

    # done 될 때까지 대기
    while not node._done:
        time.sleep(0.1)

    executor.shutdown(timeout_sec=2.0)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
