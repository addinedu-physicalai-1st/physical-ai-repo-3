"""dock_perception_node -- Astra depth -> 테이블 엣지(횡오차/각도) 발행.

/camera/depth/points (PointCloud2, optical 프레임) 구독 -> 고정 도킹포즈의
optical->base extrinsic(SE3, config/gimbal_extrinsic.yaml) 적용 -> base 프레임에서
edge_perception.analyze_table_edge 호출 -> EMA 스무딩 -> 발행.

출력(임시): /dock_perception/table_edge (std_msgs/Float64MultiArray)
  data = [valid, table_found, horizontal, table_height, lateral_error,
          angle_deg, n_inliers, inlier_ratio]
  (이후 dobi_dock_msgs/TableEdge 커스텀 메시지로 교체 예정)

enable: /dock_perception/enable (std_msgs/Bool) 또는 param 'enabled'. 도킹 단계에서만.
extrinsic 은 1회 캘리브 필요 -- 미캘리브 시 경고 + identity(=optical 그대로) 사용.
"""
from __future__ import annotations

import os

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Bool, Float64MultiArray

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from dobi_dock.edge_perception import analyze_table_edge


def load_extrinsic(path):
    """gimbal_extrinsic.yaml -> (R 3x3, t 3, calibrated). 없거나 미설정 시 identity."""
    R = np.eye(3)
    t = np.zeros(3)
    calibrated = False
    if path and yaml is not None and os.path.exists(path):
        try:
            with open(path) as f:
                d = yaml.safe_load(f) or {}
            g = d.get('optical_to_base', d)
            if 'R' in g and 't' in g:
                R = np.asarray(g['R'], dtype=float).reshape(3, 3)
                t = np.asarray(g['t'], dtype=float).reshape(3)
                calibrated = bool(g.get('calibrated', True))
        except Exception:
            pass
    return R, t, calibrated


class DockPerceptionNode(Node):

    def __init__(self):
        super().__init__('dock_perception_node')
        self.declare_parameter('input_topic', '/camera/depth/points')
        self.declare_parameter('output_topic', '/dock_perception/table_edge')
        self.declare_parameter('enable_topic', '/dock_perception/enable')
        self.declare_parameter('docking_side', 'left')
        self.declare_parameter('extrinsic_path', '')
        self.declare_parameter('enabled', True)
        self.declare_parameter('stride', 4)
        self.declare_parameter('ema_alpha', 0.4)
        self.declare_parameter('roi_x', [-1.0, 1.5])
        self.declare_parameter('roi_y', [-1.2, 1.2])
        self.declare_parameter('roi_z', [0.5, 0.95])
        self.declare_parameter('table_z', [0.0, 0.0])     # [0,0] = 비활성
        self.declare_parameter('thresh', 0.018)

        g = self.get_parameter
        self.side = str(g('docking_side').value)
        self.stride = max(1, int(g('stride').value))
        self.alpha = float(g('ema_alpha').value)
        self.enabled = bool(g('enabled').value)
        self.thresh = float(g('thresh').value)
        self.roi = dict(x=tuple(g('roi_x').value), y=tuple(g('roi_y').value),
                        z=tuple(g('roi_z').value))
        tz = list(g('table_z').value)
        self.table_z = None if float(tz[0]) == float(tz[1]) else (float(tz[0]), float(tz[1]))

        ext_path = str(g('extrinsic_path').value) or None
        self.R, self.t, calib = load_extrinsic(ext_path)
        if not calib:
            self.get_logger().warn(
                'extrinsic 미캘리브(identity 사용) -> optical 점이 그대로 base 로 취급됨. '
                'config/gimbal_extrinsic.yaml 1회 캘리브 필요(고정 도킹포즈 optical->base SE3).')
        else:
            self.get_logger().info(f'extrinsic loaded: {ext_path}')

        self._ema_lat = None
        self._ema_ang = None

        self.pub = self.create_publisher(
            Float64MultiArray, str(g('output_topic').value), 10)
        self.create_subscription(
            PointCloud2, str(g('input_topic').value), self._on_cloud,
            qos_profile_sensor_data)
        self.create_subscription(
            Bool, str(g('enable_topic').value), self._on_enable, 10)
        self.get_logger().info(
            f'dock_perception ready: side={self.side} stride={self.stride} '
            f'roi={self.roi} table_z={self.table_z} enabled={self.enabled}')

    def _on_enable(self, msg: Bool):
        self.enabled = bool(msg.data)
        if not self.enabled:
            self._ema_lat = None
            self._ema_ang = None

    def _on_cloud(self, msg: PointCloud2):
        if not self.enabled:
            return
        try:
            arr = point_cloud2.read_points_numpy(
                msg, field_names=('x', 'y', 'z'), skip_nans=True)
            opt = np.asarray(arr, dtype=float).reshape(-1, 3)
        except Exception as e:
            self.get_logger().warn(f'cloud read fail: {e}', throttle_duration_sec=5.0)
            return
        if self.stride > 1:
            opt = opt[::self.stride]
        if len(opt) < 50:
            return
        base = opt @ self.R.T + self.t            # optical -> base

        r = analyze_table_edge(base, docking_side=self.side, roi=self.roi,
                               thresh=self.thresh, table_z=self.table_z)

        lat, ang = r.lateral_error, r.angle_deg
        if lat is not None and ang is not None:
            self._ema_lat = lat if self._ema_lat is None else \
                self.alpha * lat + (1 - self.alpha) * self._ema_lat
            self._ema_ang = ang if self._ema_ang is None else \
                self.alpha * ang + (1 - self.alpha) * self._ema_ang

        valid = 1.0 if (r.table_found and lat is not None) else 0.0
        nan = float('nan')
        out = Float64MultiArray()
        out.data = [
            valid,
            1.0 if r.table_found else 0.0,
            1.0 if r.horizontal else 0.0,
            float(r.table_height) if r.table_height is not None else nan,
            float(self._ema_lat) if self._ema_lat is not None else nan,
            float(self._ema_ang) if self._ema_ang is not None else nan,
            float(r.n_inliers),
            float(r.inlier_ratio),
        ]
        self.pub.publish(out)
        if valid:
            self.get_logger().info(
                f'table h={r.table_height:+.3f} lat={self._ema_lat:+.3f}m '
                f'ang={self._ema_ang:+.1f}deg inl={r.n_inliers}({r.inlier_ratio:.2f})',
                throttle_duration_sec=1.0)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = DockPerceptionNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
