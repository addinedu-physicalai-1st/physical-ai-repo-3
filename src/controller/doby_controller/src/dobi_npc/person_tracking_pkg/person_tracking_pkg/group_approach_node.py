#!/usr/bin/env python3
"""
group_approach_node — 추적 결과를 기반으로 접근 대상 그룹 결정

구독: /person_tracking/tracks  (dobi_npc_msgs/PersonTrackArray)
발행: /person_tracking/approach_target  (std_msgs/Int32, group_id / -1=없음)
"""
from __future__ import annotations

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from std_msgs.msg import Int32
from dobi_npc_msgs.msg import PersonTrackArray


class GroupApproachNode(Node):
    """가장 큰 그룹(인원 수 최대)을 접근 대상으로 선정."""

    def __init__(self):
        super().__init__('group_approach_node')

        self.declare_parameter('min_group_size', 2)
        self.declare_parameter('no_group_threshold', 10)

        self._min_size = int(self.get_parameter('min_group_size').value)
        self._no_group_threshold = int(self.get_parameter('no_group_threshold').value)
        self._no_group_count = 0
        self._last_target = -1

        self._sub = self.create_subscription(
            PersonTrackArray,
            '/person_tracking/tracks',
            self._cb_tracks,
            10,
        )
        self._pub = self.create_publisher(Int32, '/person_tracking/approach_target', 10)

        self.get_logger().info('group_approach_node 준비 완료')

    def _cb_tracks(self, msg: PersonTrackArray) -> None:
        if not msg.tracks:
            self._publish(-1)
            return

        # 그룹별 인원 수 집계 (solo 제외)
        group_counts: dict[int, int] = {}
        for track in msg.tracks:
            gid = track.group_id
            if gid >= 0:
                group_counts[gid] = group_counts.get(gid, 0) + 1

        # 최소 인원 이상인 그룹 중 가장 큰 그룹 선택
        candidates = {gid: cnt for gid, cnt in group_counts.items()
                      if cnt >= self._min_size}

        if candidates:
            target = max(candidates, key=candidates.__getitem__)
            self._no_group_count = 0
            self._last_target = target
            self.get_logger().debug(
                f'접근 대상: Group {target} ({candidates[target]}명)'
            )
        else:
            self._no_group_count += 1
            if self._no_group_count < self._no_group_threshold:
                return  # 히스테리시스: 연속 미탐지 threshold 미만이면 유지
            target = -1
            self._last_target = -1

        self._publish(target)

    def _publish(self, group_id: int) -> None:
        msg = Int32()
        msg.data = group_id
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = GroupApproachNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
