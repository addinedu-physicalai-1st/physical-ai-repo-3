#!/usr/bin/env python3
"""Publish RViz markers for table poses and serving stop poses."""

import math
import os

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point, PoseStamped
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray


class TableMarkersNode(Node):
    def __init__(self):
        super().__init__('table_markers')

        default_yaml = os.path.join(
            get_package_share_directory('mobility_controller'),
            'config',
            'tables.yaml',
        )
        self.declare_parameter('tables_yaml', default_yaml)
        self.tables_yaml = self.get_parameter('tables_yaml').value
        self.tables: dict[str, dict] = {}
        self.home_pose: PoseStamped | None = None
        self._mtime: float | None = None

        self._marker_pub = self.create_publisher(
            MarkerArray, '/serving/table_markers', 10)
        self.create_timer(1.0, self._tick)
        self._load_tables(force=True)

    def _tick(self) -> None:
        self._load_tables(force=False)
        self._publish_markers()

    def _load_tables(self, force: bool) -> None:
        try:
            mtime = os.path.getmtime(self.tables_yaml)
        except OSError as e:
            self.get_logger().error(f'tables_yaml 파일 없음: {self.tables_yaml!r}: {e}')
            return
        if not force and self._mtime == mtime:
            return

        try:
            with open(self.tables_yaml, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.get_logger().error(f'tables_yaml 파싱 실패: {e}')
            return

        home_pose = None
        home_d = data.get('home_pose')
        if home_d:
            home_pose = self._dict_to_pose(home_d)

        tables: dict[str, dict] = {}
        for entry in data.get('tables', []):
            tid = entry.get('id')
            pose_d = entry.get('pose', {})
            if not tid or not pose_d:
                continue
            approach_dist = float(entry.get('approach_dist', 0.0))
            table_pose = self._dict_to_pose(pose_d)
            stop_pose = self._dict_to_pose(pose_d, approach_dist=approach_dist)
            if table_pose and stop_pose:
                tables[tid] = {
                    'table_pose': table_pose,
                    'stop_pose': stop_pose,
                    'approach_dist': approach_dist,
                }

        self.tables = tables
        self.home_pose = home_pose
        self._mtime = mtime
        self.get_logger().info(
            f'table markers loaded: {sorted(self.tables.keys())} '
            f'home={"OK" if self.home_pose else "MISSING"} from {self.tables_yaml}')

    def _dict_to_pose(self, d: dict, approach_dist: float = 0.0) -> PoseStamped | None:
        try:
            ps = PoseStamped()
            ps.header.frame_id = d.get('frame_id', 'map')
            x = float(d.get('x', 0.0))
            y = float(d.get('y', 0.0))
            yaw = float(d.get('yaw', 0.0))
            if approach_dist:
                x -= math.cos(yaw) * approach_dist
                y -= math.sin(yaw) * approach_dist
            ps.pose.position.x = x
            ps.pose.position.y = y
            ps.pose.position.z = 0.0
            ps.pose.orientation.z = math.sin(yaw / 2.0)
            ps.pose.orientation.w = math.cos(yaw / 2.0)
            return ps
        except (TypeError, ValueError) as e:
            self.get_logger().warn(f'pose 파싱 실패: {e}')
            return None

    def _publish_markers(self) -> None:
        arr = MarkerArray()
        delete = Marker()
        delete.header.frame_id = 'map'
        delete.header.stamp = self.get_clock().now().to_msg()
        delete.action = Marker.DELETEALL
        arr.markers.append(delete)

        marker_id = 1
        if self.home_pose is not None:
            home = self._marker(marker_id, 'serving_home', Marker.SPHERE, self.home_pose)
            marker_id += 1
            home.pose.position.z = 0.10
            home.scale.x = 0.35
            home.scale.y = 0.35
            home.scale.z = 0.14
            self._set_color(home, 0.65, 0.25, 1.0, 0.95)
            arr.markers.append(home)

            heading = self._marker(
                marker_id, 'serving_home_heading', Marker.ARROW, self.home_pose)
            marker_id += 1
            heading.pose.position.z = 0.16
            heading.scale.x = 0.55
            heading.scale.y = 0.10
            heading.scale.z = 0.10
            self._set_color(heading, 0.65, 0.25, 1.0, 0.95)
            arr.markers.append(heading)

            label = self._marker(
                marker_id, 'serving_home_label', Marker.TEXT_VIEW_FACING, self.home_pose)
            marker_id += 1
            label.pose.position.z = 0.50
            label.scale.z = 0.30
            label.text = 'HOME'
            self._set_color(label, 1.0, 1.0, 1.0, 1.0)
            arr.markers.append(label)

        for tid in sorted(self.tables.keys()):
            entry = self.tables[tid]
            table_pose = entry['table_pose']
            stop_pose = entry['stop_pose']

            table = self._marker(marker_id, 'serving_table', Marker.CUBE, table_pose)
            marker_id += 1
            table.scale.x = 0.7
            table.scale.y = 0.7
            table.scale.z = 0.05
            self._set_color(table, 1.0, 0.45, 0.05, 0.45)
            arr.markers.append(table)

            stop = self._marker(marker_id, 'serving_stop', Marker.SPHERE, stop_pose)
            marker_id += 1
            stop.pose.position.z = 0.08
            stop.scale.x = 0.28
            stop.scale.y = 0.28
            stop.scale.z = 0.12
            self._set_color(stop, 0.05, 0.85, 0.25, 0.9)
            arr.markers.append(stop)

            heading = self._marker(
                marker_id, 'serving_stop_heading', Marker.ARROW, stop_pose)
            marker_id += 1
            heading.pose.position.z = 0.12
            heading.scale.x = 0.45
            heading.scale.y = 0.08
            heading.scale.z = 0.08
            self._set_color(heading, 0.05, 0.55, 1.0, 0.9)
            arr.markers.append(heading)

            line = self._marker(
                marker_id, 'serving_approach_offset', Marker.LINE_STRIP, stop_pose)
            marker_id += 1
            line.pose.position.x = 0.0
            line.pose.position.y = 0.0
            line.pose.position.z = 0.0
            line.pose.orientation.x = 0.0
            line.pose.orientation.y = 0.0
            line.pose.orientation.z = 0.0
            line.pose.orientation.w = 1.0
            line.scale.x = 0.04
            line.points = [
                Point(x=table_pose.pose.position.x, y=table_pose.pose.position.y, z=0.04),
                Point(x=stop_pose.pose.position.x, y=stop_pose.pose.position.y, z=0.04),
            ]
            self._set_color(line, 1.0, 1.0, 1.0, 0.85)
            arr.markers.append(line)

            label = self._marker(
                marker_id, 'serving_stop_label', Marker.TEXT_VIEW_FACING, stop_pose)
            marker_id += 1
            label.pose.position.z = 0.45
            label.scale.z = 0.28
            label.text = f'{tid} stop'
            self._set_color(label, 1.0, 1.0, 1.0, 1.0)
            arr.markers.append(label)

        self._marker_pub.publish(arr)

    def _marker(self, marker_id: int, ns: str, marker_type: int, pose: PoseStamped) -> Marker:
        marker = Marker()
        marker.header.frame_id = pose.header.frame_id or 'map'
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = ns
        marker.id = marker_id
        marker.type = marker_type
        marker.action = Marker.ADD
        marker.pose = pose.pose
        marker.pose.position.z = 0.02
        marker.lifetime.sec = 2
        return marker

    @staticmethod
    def _set_color(marker: Marker, r: float, g: float, b: float, a: float) -> None:
        marker.color.r = r
        marker.color.g = g
        marker.color.b = b
        marker.color.a = a


def main(args=None):
    rclpy.init(args=args)
    node = TableMarkersNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
