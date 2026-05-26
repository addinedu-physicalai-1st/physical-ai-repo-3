#!/usr/bin/env python3
"""follow_controller — customer_id 기반 특정 인물 추종 + /cmd_vel reactive 제어.

mode_follow 의 본체. mode_follow.launch.py 가 spawn 시 person_detector_node와
함께 띄워져 다음을 수행:

  target_customer_id 파라미터로 추종 대상 지정 (빈 문자열이면 가장 큰 사람)

  [customer_id 지정 시]
  /customer/registry (CustomerRegistry)
        │  customer_id → track_id 매핑
        ▼
  /person_tracking/tracks (PersonTrackArray)
        │  track_id → bbox
        ▼
  err_angle = (image_cx - bbox_cx) / (image_w / 2)
  err_dist  = scan_front - target_dist
        │
        ▼  PD 제어 + 클램프
  /follow/cmd_vel (geometry_msgs/Twist)

  [customer_id 미지정 시 — 폴백]
  /robot_cam/persons (Detection2DArray) → 가장 큰 bbox 사람 추종 (기존 동작)

안전 가드 (publish 0 또는 v=0 강제):
  1) /rapport/event abort_trigger → 즉시 v=ω=0 + dwell 동안 송신 중단
  2) /scan 전방 ±front_arc_deg(기본 30°) 구간 < scan_stop_dist → v=0 (회전은 허용)
  3) detection_lost_sec(기본 1.0s) 동안 person 미검출 → v=ω=0
  4) image_size 미수신 → 0 (첫 sample 들어와야 정상 평가)

이관: mobility_controller (RPi) — 2026-05-26
  원본: dobi_npc_bringup/follow_controller_node.py (노트북)
"""
from __future__ import annotations

import math
import time

import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from vision_msgs.msg import Detection2DArray

from std_msgs.msg import String
from dobi_npc_msgs.msg import RapportEvent, CustomerRegistry, PersonTrackArray


class FollowControllerNode(Node):
    """customer_id or Detection2DArray → reactive cmd_vel + multi-source safety gate."""

    def __init__(self):
        super().__init__('follow_controller_node')

        self.declare_parameter('persons_topic', '/robot_cam/persons')
        self.declare_parameter('scan_topic', '/scan')
        self.declare_parameter('rapport_topic', '/rapport/event')
        self.declare_parameter('cmd_vel_topic', '/follow/cmd_vel')

        # 추종 대상 customer_id (빈 문자열이면 가장 큰 사람 폴백)
        self.declare_parameter('target_customer_id', '')

        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)

        self.declare_parameter('target_height_ratio', 0.5)
        self.declare_parameter('target_dist', 0.7)
        self.declare_parameter('dist_deadband', 0.05)
        self.declare_parameter('angle_deadband', 0.10)

        self.declare_parameter('kp_linear', 0.4)
        self.declare_parameter('kp_angular', 0.4)

        self.declare_parameter('angle_smoothing_alpha', 0.2)

        self.declare_parameter('max_linear', 0.20)
        self.declare_parameter('max_angular', 0.25)

        self.declare_parameter('align_gate', 0.2)

        self.declare_parameter('detection_lost_sec', 1.0)
        self.declare_parameter('abort_dwell_sec', 2.0)
        self.declare_parameter('scan_stop_dist', 0.8)
        self.declare_parameter('scan_min_range', 0.25)
        self.declare_parameter('front_arc_deg', 30.0)

        self.declare_parameter('control_rate_hz', 20.0)
        self.declare_parameter('params_json', '')

        self.persons_topic = self.get_parameter('persons_topic').value
        self.scan_topic = self.get_parameter('scan_topic').value
        self.rapport_topic = self.get_parameter('rapport_topic').value
        cmd_topic = self.get_parameter('cmd_vel_topic').value

        self._target_customer_id: str = str(
            self.get_parameter('target_customer_id').value)

        self.image_w = int(self.get_parameter('image_width').value)
        self.image_h = int(self.get_parameter('image_height').value)

        self.target_h_ratio = float(self.get_parameter('target_height_ratio').value)
        self.target_dist = float(self.get_parameter('target_dist').value)
        self.dist_deadband = float(self.get_parameter('dist_deadband').value)
        self.angle_deadband = float(self.get_parameter('angle_deadband').value)
        self.kp_linear = float(self.get_parameter('kp_linear').value)
        self.kp_angular = float(self.get_parameter('kp_angular').value)
        self.max_linear = float(self.get_parameter('max_linear').value)
        self.max_angular = float(self.get_parameter('max_angular').value)
        self.angle_alpha = float(self.get_parameter('angle_smoothing_alpha').value)
        self.angle_alpha = max(0.0, min(1.0, self.angle_alpha))
        self.align_gate = float(self.get_parameter('align_gate').value)

        self.detection_lost_sec = float(self.get_parameter('detection_lost_sec').value)
        self.abort_dwell_sec = float(self.get_parameter('abort_dwell_sec').value)
        self.scan_stop_dist = float(self.get_parameter('scan_stop_dist').value)
        self.scan_min_range = float(self.get_parameter('scan_min_range').value)
        self.front_arc_deg = float(self.get_parameter('front_arc_deg').value)

        ctl_hz = float(self.get_parameter('control_rate_hz').value)

        # 상태
        self._last_detection_time = 0.0
        self._target_bbox = None        # (cx, cy, w, h)
        self._err_angle_filt = 0.0
        self._err_dist_filt = 0.0
        self._dwell_until = 0.0
        self._scan_front_min = float('inf')
        self._scan_received = False
        self._last_log = time.time()
        self._cmd_count = 0

        # customer_id → track_id 매핑 캐시
        self._customer_to_track: dict[str, int] = {}
        # track_id → bbox 캐시 (PersonTrackArray에서 갱신)
        self._track_to_bbox: dict[int, tuple] = {}

        # I/O
        self.sub_persons = self.create_subscription(
            Detection2DArray, self.persons_topic, self._on_persons, 10)
        self.sub_scan = self.create_subscription(
            LaserScan, self.scan_topic, self._on_scan, 5)
        self.sub_rapport = self.create_subscription(
            RapportEvent, self.rapport_topic, self._on_rapport, 10)

        # customer_id 기반 추종을 위한 추가 구독
        self.create_subscription(
            CustomerRegistry, '/customer/registry', self._on_registry, 10)
        self.create_subscription(
            PersonTrackArray, '/person_tracking/tracks', self._on_tracks, 10)
        # target_selector_node 가 발행하는 추종 대상 customer_id 자동 수신
        self.create_subscription(
            String, '/follow/target', self._on_follow_target, 10)

        self.pub_cmd = self.create_publisher(Twist, cmd_topic, 5)
        self.timer = self.create_timer(1.0 / ctl_hz, self._control_tick)

        self._LIVE_TUNABLE = {
            'kp_linear', 'kp_angular',
            'max_linear', 'max_angular',
            'target_height_ratio', 'target_dist', 'angle_deadband', 'dist_deadband',
            'align_gate', 'angle_smoothing_alpha',
            'detection_lost_sec', 'abort_dwell_sec',
            'scan_stop_dist', 'scan_min_range', 'front_arc_deg',
            'target_customer_id',
        }
        self.add_on_set_parameters_callback(self._on_set_params)

        mode = (f'customer_id="{self._target_customer_id}"'
                if self._target_customer_id else '가장 큰 사람 (폴백)')
        self.get_logger().info(
            f"follow_controller ready: mode={mode} "
            f"cmd={cmd_topic} image={self.image_w}x{self.image_h} "
            f"target_dist={self.target_dist:.2f}m "
            f"kp_v={self.kp_linear:.2f} kp_w={self.kp_angular:.2f}"
        )

    # ── 콜백 ────────────────────────────────────────────────

    def _on_set_params(self, params):
        applied = []
        for p in params:
            if p.name not in self._LIVE_TUNABLE:
                continue
            if p.name == 'target_customer_id':
                self._target_customer_id = str(p.value)
                applied.append(f'target_customer_id="{p.value}"')
                continue
            attr_map = {
                'kp_linear': 'kp_linear',
                'kp_angular': 'kp_angular',
                'max_linear': 'max_linear',
                'max_angular': 'max_angular',
                'target_height_ratio': 'target_h_ratio',
                'target_dist': 'target_dist',
                'angle_deadband': 'angle_deadband',
                'dist_deadband': 'dist_deadband',
                'align_gate': 'align_gate',
                'angle_smoothing_alpha': 'angle_alpha',
                'detection_lost_sec': 'detection_lost_sec',
                'abort_dwell_sec': 'abort_dwell_sec',
                'scan_stop_dist': 'scan_stop_dist',
                'scan_min_range': 'scan_min_range',
                'front_arc_deg': 'front_arc_deg',
            }
            attr = attr_map.get(p.name)
            if attr is None:
                continue
            setattr(self, attr, float(p.value))
            applied.append(f"{p.name}={p.value}")
        if applied:
            self.get_logger().info(f"live param: {' '.join(applied)}")
        return SetParametersResult(successful=True)

    def _on_follow_target(self, msg: String):
        """target_selector_node 가 발행한 customer_id 자동 수신 → 추종 대상 갱신."""
        new_target = msg.data.strip()
        if new_target != self._target_customer_id:
            self._target_customer_id = new_target
            self.get_logger().info(f'추종 대상 자동 변경: customer_id="{new_target}"')

    def _on_registry(self, msg: CustomerRegistry):
        """customer_id → track_id 매핑 갱신."""
        self._customer_to_track = {
            c.customer_id: int(c.track_id)
            for c in msg.customers
        }

    def _on_tracks(self, msg: PersonTrackArray):
        """track_id → bbox 캐시 갱신."""
        self._track_to_bbox = {}
        for track in msg.tracks:
            x1, y1, x2, y2 = track.bbox
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            w = x2 - x1
            h = y2 - y1
            self._track_to_bbox[int(track.track_id)] = (cx, cy, w, h)

        # customer_id 지정돼 있으면 tracks에서 bbox 업데이트
        if self._target_customer_id:
            track_id = self._customer_to_track.get(self._target_customer_id)
            if track_id is not None and track_id in self._track_to_bbox:
                self._target_bbox = self._track_to_bbox[track_id]
                self._last_detection_time = time.monotonic()

    def _on_persons(self, msg: Detection2DArray):
        """폴백: customer_id 미지정 시 가장 큰 bbox 사람 추종."""
        if self._target_customer_id:
            return  # customer_id 지정돼 있으면 tracks 기반으로 처리

        if not msg.detections:
            self._target_bbox = None
            return

        best = None
        best_area = 0.0
        for d in msg.detections:
            w = d.bbox.size_x
            h = d.bbox.size_y
            if w <= 0 or h <= 0:
                continue
            area = w * h
            if area > best_area:
                best_area = area
                best = (d.bbox.center.position.x,
                        d.bbox.center.position.y, w, h)
        if best is not None:
            self._target_bbox = best
            self._last_detection_time = time.monotonic()

    def _on_scan(self, msg: LaserScan):
        if not msg.ranges:
            return
        front_arc_rad = math.radians(self.front_arc_deg)
        nearest = float('inf')
        ang = msg.angle_min
        for r in msg.ranges:
            if -front_arc_rad <= ang <= front_arc_rad:
                if math.isfinite(r) and r > self.scan_min_range and r <= msg.range_max:
                    if r < nearest:
                        nearest = r
            ang += msg.angle_increment
        self._scan_front_min = nearest
        self._scan_received = True

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type != "abort_trigger":
            return
        if self.abort_dwell_sec > 0:
            self._dwell_until = time.monotonic() + self.abort_dwell_sec
        self._publish_stop(reason=f"abort_trigger ({msg.reason})")

    # ── 제어 ────────────────────────────────────────────────

    def _control_tick(self):
        now = time.monotonic()

        # 가드 1: abort dwell
        if now < self._dwell_until:
            self._publish_stop()
            return

        # 가드 2: detection lost
        if (self._target_bbox is None or
                (now - self._last_detection_time) > self.detection_lost_sec):
            self._publish_stop()
            self._err_angle_filt = 0.0
            self._err_dist_filt = 0.0
            return

        cx, _cy, _w, _h = self._target_bbox

        err_angle_raw = (self.image_w / 2.0 - cx) / (self.image_w / 2.0)

        if self._scan_received and math.isfinite(self._scan_front_min):
            err_dist_raw = self._scan_front_min - self.target_dist
        else:
            err_dist_raw = 0.0

        a = self.angle_alpha
        if a > 0:
            self._err_angle_filt = a * err_angle_raw + (1 - a) * self._err_angle_filt
            self._err_dist_filt = a * err_dist_raw + (1 - a) * self._err_dist_filt
            err_angle = self._err_angle_filt
            err_dist = self._err_dist_filt
        else:
            err_angle = err_angle_raw
            err_dist = err_dist_raw

        if abs(err_angle) < self.angle_deadband:
            err_angle = 0.0
        if abs(err_dist) < self.dist_deadband:
            err_dist = 0.0

        v = self._clamp(self.kp_linear * err_dist, -self.max_linear, self.max_linear)
        w = self._clamp(self.kp_angular * err_angle, -self.max_angular, self.max_angular)

        if self.align_gate > 0 and abs(err_angle) > self.align_gate:
            v = 0.0

        # 가드 3: 전방 obstacle → 전진만 차단
        if (self._scan_received and
                self._scan_front_min < self.scan_stop_dist and
                v > 0.0):
            v = 0.0

        msg = Twist()
        msg.linear.x = v
        msg.angular.z = w
        self.pub_cmd.publish(msg)
        self._cmd_count += 1
        self._maybe_log(v, w, err_angle, err_dist, _h)

    def _publish_stop(self, reason: str | None = None):
        msg = Twist()
        self.pub_cmd.publish(msg)
        self._cmd_count += 1
        if reason:
            self.get_logger().warning(f"STOP: {reason}")

    @staticmethod
    def _clamp(x, lo, hi):
        return max(lo, min(hi, x))

    def _maybe_log(self, v, w, err_a, err_d, bbox_h):
        now = time.time()
        if now - self._last_log >= 5.0:
            elapsed = now - self._last_log
            rate = self._cmd_count / elapsed
            target_info = (f'customer={self._target_customer_id}'
                           if self._target_customer_id else '최대bbox')
            self.get_logger().info(
                f"[{target_info}] "
                f"cmd_rate={rate:.1f}Hz "
                f"v={v:+.2f} w={w:+.2f} "
                f"err_angle={err_a:+.2f} err_dist={err_d:+.2f} "
                f"scan_front={self._scan_front_min:.2f}m"
            )
            self._cmd_count = 0
            self._last_log = now

    def destroy_node(self):
        try:
            self._publish_stop()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowControllerNode()
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
