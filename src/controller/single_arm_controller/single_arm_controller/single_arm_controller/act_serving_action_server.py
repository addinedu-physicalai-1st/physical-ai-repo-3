"""
ACT serving ROS action server.

This file is intentionally limited to the communication layer:
it receives external Pickup/Serve action goals, delegates business logic to
ActServingOrchestrator, and converts the outcome back into ROS action results.
"""

from pathlib import Path

import threading

import rclpy as rp
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Empty, String

from single_arm_controller.act_serving_orchestrator import ActServingOrchestrator
from single_arm_controller_interfaces.action import Pickup, Serve

_PALM_DIRECTION_TOPIC = '/palm_direction'
_PALM_DIRECTION_TIMEOUT_S = 30.0


_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / 'config' / 'act_serving_config.yaml')


class ActServingActionServer(Node):
    def __init__(self):
        super().__init__('act_serving_controller')

        self.declare_parameter('config_path',    _DEFAULT_CONFIG_PATH)
        self.declare_parameter('top_cam_path',   '')
        self.declare_parameter('wrist_cam_path', '')
        self.declare_parameter('vlm_host',       '')

        self._orchestrator = ActServingOrchestrator(
            config_path=self.get_parameter('config_path').value,
            node=self,
            vlm_host=self.get_parameter('vlm_host').value,
        )

        self._trigger_pub = self.create_publisher(Empty, '/palm_detect_trigger', 10)

        cb = ReentrantCallbackGroup()
        self._pickup_server = ActionServer(
            self, Pickup, 'pickup', self.execute_pickup_action,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )
        self._serve_server = ActionServer(
            self, Serve, 'serve', self.execute_serve_action,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )
        self.get_logger().info('ACT serving action server ready (Pickup + Serve)')

    def _wait_for_palm_direction(self) -> str:
        """has_drink=True일 때 /palm_direction 메시지를 딱 한 번 기다린다."""
        received = threading.Event()
        direction_holder = ['left']

        def _one_shot(msg: String):
            if received.is_set():
                return
            val = msg.data.strip().lower()
            if val in ('left', 'right'):
                direction_holder[0] = val
            else:
                self.get_logger().warn(
                    f'Invalid palm_direction: "{msg.data}". Use "left" or "right". Defaulting to left.'
                )
            received.set()

        self.get_logger().info(
            f'has_drink=True: waiting for /palm_direction message '
            f'(timeout {_PALM_DIRECTION_TIMEOUT_S}s)...'
        )
        sub = self.create_subscription(String, _PALM_DIRECTION_TOPIC, _one_shot, 1)
        timed_out = not received.wait(timeout=_PALM_DIRECTION_TIMEOUT_S)
        self.destroy_subscription(sub)

        if timed_out:
            self.get_logger().warn(
                'palm_direction timeout — defaulting to "left" (blue marker).'
            )
        else:
            self.get_logger().info(f'palm_direction received: {direction_holder[0]}')

        return direction_holder[0]

    def destroy_node(self):
        self._orchestrator.close()
        super().destroy_node()

    def resolve_camera_path(self, goal_value: str, yaml_key: str, ros_param: str) -> str:
        return self._orchestrator.resolve_camera_path(
            goal_value=goal_value,
            yaml_key=yaml_key,
            ros_override=self.get_parameter(ros_param).value,
        )

    def publish_feedback(self, goal_handle, feedback, status: str):
        feedback.status = status
        goal_handle.publish_feedback(feedback)

    def execute_pickup_action(self, goal_handle):
        goal = goal_handle.request
        top_cam = self.resolve_camera_path(
            getattr(goal, 'top_cam_path', ''), 'top_path', 'top_cam_path'
        )
        wrist_cam = self.resolve_camera_path(
            getattr(goal, 'wrist_cam_path', ''), 'wrist_path', 'wrist_cam_path'
        )

        self.get_logger().info(f'Pickup started - top={top_cam} wrist={wrist_cam}')
        feedback = Pickup.Feedback()
        self.publish_feedback(goal_handle, feedback, 'Pickup in progress')

        try:
            outcome = self._orchestrator.run_pickup(
                top_cam_path=top_cam,
                wrist_cam_path=wrist_cam,
                feedback_cb=lambda status: self.publish_feedback(goal_handle, feedback, status),
                cancel_cb=lambda: goal_handle.is_cancel_requested,
            )
        except Exception as e:
            goal_handle.abort()
            result = Pickup.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().error(f'Pickup aborted: {e}')
            return result

        result = Pickup.Result()
        result.success = outcome.success
        result.message = outcome.message
        if outcome.canceled:
            goal_handle.canceled()
        else:
            goal_handle.succeed()

        self.get_logger().info(result.message)
        return result

    def execute_serve_action(self, goal_handle):
        goal = goal_handle.request
        has_drink = bool(goal.has_drink)
        top_cam = self.resolve_camera_path('', 'top_path', 'top_cam_path')
        wrist_cam = self.resolve_camera_path('', 'wrist_path', 'wrist_cam_path')

        self.get_logger().info(
            f'Serve started - has_drink={has_drink} top={top_cam} wrist={wrist_cam}'
        )
        feedback = Serve.Feedback()
        self.publish_feedback(goal_handle, feedback, 'Serve in progress')

        if has_drink:
            self.publish_feedback(goal_handle, feedback, 'Waiting for palm direction...')
            self._trigger_pub.publish(Empty())
            self.get_logger().info('palm_detect_trigger 발행 → palm_side_publisher 감지 시작')
            direction = self._wait_for_palm_direction()
        else:
            direction = 'left'

        try:
            outcome = self._orchestrator.run_serve(
                top_cam_path=top_cam,
                wrist_cam_path=wrist_cam,
                has_drink=has_drink,
                direction=direction,
                feedback_cb=lambda status: self.publish_feedback(goal_handle, feedback, status),
                cancel_cb=lambda: goal_handle.is_cancel_requested,
            )
        except Exception as e:
            goal_handle.abort()
            result = Serve.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().error(f'Serve aborted: {e}')
            return result

        result = Serve.Result()
        result.success = outcome.success
        result.message = outcome.message
        if outcome.canceled:
            goal_handle.canceled()
        else:
            goal_handle.succeed()

        self.get_logger().info(result.message)
        return result


def main(args=None):
    rp.init(args=args)
    node = ActServingActionServer()
    executor = MultiThreadedExecutor(num_threads=4)
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
