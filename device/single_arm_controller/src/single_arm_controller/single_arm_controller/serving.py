import time

import rclpy as rp
from rclpy.action import ActionServer
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup, Serve


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
            goal_handle.succeed()
            result = Serve.Result()
            result.success = True
            result.message = 'Serve completed.'
        except Exception as e:
            goal_handle.abort()
            result = Serve.Result()
            result.success = False
            result.message = str(e)

        self.get_logger().info(f'Serve finished: {result.message}')
        return result

    def _do_pickup(self, goal_handle):
        self.get_logger().info('_do_pickup!')
        time.sleep(3)

    def _do_serve(self, goal_handle):
        self.get_logger().info('_do_serve!')
        time.sleep(3)


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
