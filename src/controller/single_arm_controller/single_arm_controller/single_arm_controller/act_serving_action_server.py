"""
ACT serving ROS action server.

This file is intentionally limited to the communication layer:
it receives external Pickup/Serve action goals, delegates business logic to
ActServingOrchestrator, and converts the outcome back into ROS action results.
"""

from pathlib import Path

import rclpy as rp
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller.act_serving_orchestrator import ActServingOrchestrator
from single_arm_controller_interfaces.action import Pickup, Serve


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
            logger=self.get_logger(),
            vlm_host=self.get_parameter('vlm_host').value,
        )

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
        top_cam = self.resolve_camera_path(
            getattr(goal, 'top_cam_path', ''), 'top_path', 'top_cam_path'
        )
        wrist_cam = self.resolve_camera_path(
            getattr(goal, 'wrist_cam_path', ''), 'wrist_path', 'wrist_cam_path'
        )

        self.get_logger().info(f'Serve started - top={top_cam} wrist={wrist_cam}')
        feedback = Serve.Feedback()
        self.publish_feedback(goal_handle, feedback, 'Serve in progress')

        try:
            outcome = self._orchestrator.run_serve(
                top_cam_path=top_cam,
                wrist_cam_path=wrist_cam,
                task=getattr(goal, 'task', ''),
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
