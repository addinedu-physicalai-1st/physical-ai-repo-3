import json
import select
import subprocess
import time

import rclpy as rp
from rclpy.action import ActionServer
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup, Serve

_LEROBOT_WD = '/home/jr/ws/lerobot'

_CAMERAS = {
    'top': {
        'type': 'intelrealsense',
        'serial_number_or_name': '943222071539',
        'width': 640,
        'height': 480,
        'fps': 30,
    },
    'wrist': {
        'type': 'opencv',
        'index_or_path': '/dev/video2',
        'width': 640,
        'height': 480,
        'fps': 30,
    },
}

_SERVE_CMD = [
    '/home/jr/ws/lerobot/.venv/bin/lerobot-rollout',
    '--strategy.type=base',
    '--policy.path=/home/jr/ws/lerobot/outputs/300000/pretrained_model',
    '--inference.type=rtc',
    '--inference.rtc.execution_horizon=10',
    '--interpolation_multiplier=5',
    '--action_ema_alpha=0.43',
    '--compile_warmup_inferences=3',
    '--robot.type=omx_follower',
    '--robot.port=/dev/ttyACM0',
    f'--robot.cameras={json.dumps(_CAMERAS)}',
    '--task=pick up cup and place at target zone',
    '--duration=9000',
]


class SingleArmControllerNode(Node):
    def __init__(self):
        super().__init__('single_arm_controller')

        self._pickup_action_server = ActionServer(
            self, Pickup, 'pickup', self._execute_pickup
        )
        self._serve_action_server = ActionServer(
            self, Serve, 'serve', self._execute_serve
        )

        self.get_logger().info('SingleArmController node started.')

    def _execute_pickup(self, goal_handle):
        self.get_logger().info('Pickup started.')

        feedback = Pickup.Feedback()
        feedback.status = 'Pickup in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_pickup(goal_handle)
            goal_handle.succeed()
            result = Pickup.Result()
            result.success = True
            result.message = 'Pickup completed.'
        except Exception as e:
            goal_handle.abort()
            result = Pickup.Result()
            result.success = False
            result.message = str(e)

        self.get_logger().info(f'Pickup finished: {result.message}')
        return result

    def _execute_serve(self, goal_handle):
        self.get_logger().info('Serve started.')

        feedback = Serve.Feedback()
        feedback.status = 'Serve in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_serve(goal_handle)
        except Exception as e:
            goal_handle.abort()
            result = Serve.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().info(f'Serve aborted: {result.message}')
            return result

        if goal_handle.is_cancel_requested or not goal_handle.is_active:
            result = Serve.Result()
            result.success = False
            result.message = 'Serve canceled.'
            self.get_logger().info(result.message)
            return result

        goal_handle.succeed()
        result = Serve.Result()
        result.success = True
        result.message = 'Serve completed.'
        self.get_logger().info(f'Serve finished: {result.message}')
        return result

    def _do_pickup(self, goal_handle):
        self.get_logger().info('_do_pickup!')
        time.sleep(3)

    def _do_serve(self, goal_handle):
        self.get_logger().info('_do_serve!')

        process = subprocess.Popen(
            _SERVE_CMD,
            cwd=_LEROBOT_WD,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        feedback = Serve.Feedback()

        while process.poll() is None:
            ready, _, _ = select.select([process.stdout], [], [], 1.0)
            if ready:
                line = process.stdout.readline()
                if line:
                    self.get_logger().info(f'[lerobot] {line.rstrip()}')
                    feedback.status = line.strip()
                    goal_handle.publish_feedback(feedback)

            if goal_handle.is_cancel_requested:
                self.get_logger().info('Serve cancelled, terminating lerobot process.')
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                goal_handle.canceled()
                return

        if process.returncode != 0:
            raise RuntimeError(f'lerobot-rollout exited with code {process.returncode}')


def main(args=None):
    rp.init(args=args)
    node = SingleArmControllerNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rp.shutdown()


if __name__ == '__main__':
    main()
