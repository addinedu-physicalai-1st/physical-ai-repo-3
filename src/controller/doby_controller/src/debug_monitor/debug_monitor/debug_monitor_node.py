#!/usr/bin/env python3
# flake8: noqa
"""Read-only ROS console monitor for operational debugging."""

from __future__ import annotations

import json

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from dobi_npc_msgs.msg import GuidingState, ModeState, OpEvent, PatrolState, TableReport


class DebugMonitorNode(Node):
    """Subscribes to state topics only. It never calls services or actions."""

    def __init__(self):
        super().__init__('doby_debug_monitor')
        self.create_subscription(ModeState, '/mode/state', self._on_mode, 10)
        self.create_subscription(String, '/serving/state', self._on_serving, 10)
        self.create_subscription(PatrolState, '/patrol/state', self._on_patrol, 10)
        self.create_subscription(GuidingState, '/guiding/state', self._on_guiding, 10)
        self.create_subscription(BatteryState, '/battery_state', self._on_battery, 10)
        self.create_subscription(TableReport, '/patrol/table_report', self._on_table, 10)
        self.create_subscription(OpEvent, '/doby/event', self._on_event, 10)
        self.get_logger().info('debug monitor ready (read-only)')

    def _on_mode(self, msg: ModeState) -> None:
        self.get_logger().info(
            f'mode={msg.current_mode} battery_ok={msg.battery_ok} '
            f'safety_ok={msg.safety_ok} reason={msg.last_reject_reason}')

    def _on_serving(self, msg: String) -> None:
        try:
            state = json.loads(msg.data).get('state', msg.data)
        except Exception:
            state = msg.data
        self.get_logger().info(f'serving_state={state}')

    def _on_patrol(self, msg: PatrolState) -> None:
        self.get_logger().info(
            f'patrol_state={msg.current_state} table={msg.current_table} '
            f'{msg.tables_visited}/{msg.tables_total}')

    def _on_guiding(self, msg: GuidingState) -> None:
        self.get_logger().info(
            f'guiding_state={msg.current_state} target={msg.target_table} '
            f'customer={msg.customer_id}')

    def _on_battery(self, msg: BatteryState) -> None:
        self.get_logger().info(f'battery={msg.percentage:.2f} voltage={msg.voltage:.2f}')

    def _on_table(self, msg: TableReport) -> None:
        self.get_logger().info(
            f'table={msg.table_id} occupancy={msg.occupancy} persons={msg.person_count} '
            f'confidence={msg.confidence:.2f}')

    def _on_event(self, msg: OpEvent) -> None:
        self.get_logger().info(
            f'event source={msg.source} type={msg.event_type} outcome={msg.outcome}')


def main(args=None):
    rclpy.init(args=args)
    node = DebugMonitorNode()
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
