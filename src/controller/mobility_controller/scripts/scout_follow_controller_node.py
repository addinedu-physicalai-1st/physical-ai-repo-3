#!/usr/bin/env python3
"""scout_follow_controller — scout 일원화 follow 집중형 컨트롤러.

순수 제어함수(상단, ROS 무관) + ScoutFollowController FSM(하단).
스펙: docs/superpowers/specs/2026-05-29-scout-unified-follow-design.md
"""
from __future__ import annotations

import json
import math


def cx_to_angular(cx: float, image_width: int, kp: float, max_w: float,
                  deadband_px: float, sign: int = 1) -> float:
    """bbox 중심x(px) → base 각속도(rad/s). +w=CCW(좌회전).

    err = cx - W/2 (>0: 사람이 화면 오른쪽). sign=1 기본, 라이브 좌/우 1회 검증.
    """
    half = image_width / 2.0
    err = cx - half
    if abs(err) < deadband_px:
        return 0.0
    w = sign * (-kp) * (err / half)
    return max(-max_w, min(max_w, w))


def bh_to_linear(bh: float, target_bh: float, kp: float, max_v: float,
                 bh_stop: float, deadband: float) -> float:
    """bbox 높이비율(0..1, 클수록 가까움) → 전진 선속도(>=0, 절대 후진 X).

    bh>=bh_stop: 너무 가까움→0. err=target_bh-bh (>0: 멀다→전진).
    """
    if bh >= bh_stop:
        return 0.0
    err = target_bh - bh
    if abs(err) < deadband:
        return 0.0
    v = kp * err
    return max(0.0, min(max_v, v))


def yaw_from_quat(x: float, y: float, z: float, w: float) -> float:
    """쿼터니언 → yaw(rad)."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def handoff_servo_pan(lock_bearing: float, base_yaw_delta: float,
                      servo_limit: float) -> float:
    """co-rotation: 네트 지향(base_yaw+servo_pan)=lock_bearing 유지.
    servo_pan = lock_bearing - base_yaw_delta (clamp)."""
    pan = lock_bearing - base_yaw_delta
    return max(-servo_limit, min(servo_limit, pan))


def handoff_done(base_yaw_delta: float, lock_bearing: float,
                 tol_rad: float) -> bool:
    """차체가 lock_bearing(±tol) 회전 완료 → 서보 0 도달."""
    return abs(base_yaw_delta - lock_bearing) <= tol_rad


def select_target_track(tracks, image_width: int):
    """tracks: [(track_id, cx, cy, w, h)]. 화면 중앙 최근접 track_id (없으면 None)."""
    if not tracks:
        return None
    center = image_width / 2.0
    return min(tracks, key=lambda t: abs(t[1] - center))[0]


def next_state(state: str, call_state: str, target_visible: bool,
               handoff_complete: bool, lost_elapsed: float,
               lost_dwell: float) -> str:
    """순수 FSM. SEARCH→HANDOFF→FOLLOW→LOST."""
    if state == 'SEARCH':
        return 'HANDOFF' if call_state == 'locked' else 'SEARCH'
    if state == 'HANDOFF':
        return 'FOLLOW' if handoff_complete else 'HANDOFF'
    if state == 'FOLLOW':
        return 'FOLLOW' if target_visible else 'LOST'
    if state == 'LOST':
        if target_visible:
            return 'FOLLOW'
        return 'SEARCH' if lost_elapsed >= lost_dwell else 'LOST'
    return 'SEARCH'


import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import (QoSProfile, QoSDurabilityPolicy,
                       QoSReliabilityPolicy, QoSHistoryPolicy)

from geometry_msgs.msg import Twist
from sensor_msgs.msg import JointState
from std_msgs.msg import String, Bool
from nav_msgs.msg import Odometry
from dobi_npc_msgs.msg import PersonTrackArray
from rcl_interfaces.msg import SetParametersResult


class ScoutFollowController(Node):
    """scout 일원화 follow FSM. SEARCH→HANDOFF(co-rotation)→FOLLOW→LOST."""

    def __init__(self):
        super().__init__('scout_follow_controller')
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)
        self.declare_parameter('kp_angular', 0.5)
        self.declare_parameter('max_angular', 0.5)
        self.declare_parameter('angular_deadband_px', 24.0)
        self.declare_parameter('angular_sign', 1)
        self.declare_parameter('kp_linear', 0.8)
        self.declare_parameter('max_linear', 0.15)
        self.declare_parameter('target_bh', 0.45)
        self.declare_parameter('bh_stop', 0.75)
        self.declare_parameter('linear_deadband', 0.03)
        self.declare_parameter('ema_alpha', 0.5)
        self.declare_parameter('servo_limit_rad', 0.8)
        self.declare_parameter('handoff_yaw_tol_rad', 0.06)
        self.declare_parameter('handoff_base_w', 0.4)
        self.declare_parameter('handoff_timeout_sec', 3.0)
        self.declare_parameter('handoff_sign', -1)
        self.declare_parameter('lost_dwell_sec', 2.0)
        self.declare_parameter('rate_hz', 20.0)
        self.declare_parameter('cmd_topic', '/follow/cmd_vel')
        self.declare_parameter('servo_cmd_topic', '/scout_cam/cmd_pan_tilt')

        g = self.get_parameter
        self.W = int(g('image_width').value)
        self.H = int(g('image_height').value)
        self.kp_w = float(g('kp_angular').value)
        self.max_w = float(g('max_angular').value)
        self.dead_px = float(g('angular_deadband_px').value)
        self.sign = int(g('angular_sign').value)
        self.kp_v = float(g('kp_linear').value)
        self.max_v = float(g('max_linear').value)
        self.target_bh = float(g('target_bh').value)
        self.bh_stop = float(g('bh_stop').value)
        self.dead_bh = float(g('linear_deadband').value)
        self.alpha = float(g('ema_alpha').value)
        self.servo_limit = float(g('servo_limit_rad').value)
        self.yaw_tol = float(g('handoff_yaw_tol_rad').value)
        self.handoff_w = float(g('handoff_base_w').value)
        self.handoff_timeout = float(g('handoff_timeout_sec').value)
        self.handoff_sign = int(g('handoff_sign').value)
        self.lost_dwell = float(g('lost_dwell_sec').value)
        rate = float(g('rate_hz').value)

        self.state = 'SEARCH'
        self.call_state = 'searching'
        self.lock_bearing = 0.0
        self.base_yaw = None
        self.base_yaw_at_lock = None
        self.tracks = []
        self.target_track_id = None
        self.lost_since = None
        self._handoff_start = None
        self._v = 0.0
        self._w = 0.0

        self.pub_cmd = self.create_publisher(Twist, g('cmd_topic').value, 10)
        self.pub_servo = self.create_publisher(JointState, g('servo_cmd_topic').value, 10)
        # call_detector 의 /call/enable 구독은 latched(TRANSIENT_LOCAL) → 매칭 필수.
        # volatile 로 발행하면 QoS 불일치로 전달 안 돼 서보 freeze 가 안 먹음.
        enable_qos = QoSProfile(
            depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST)
        self.pub_enable = self.create_publisher(Bool, '/call/enable', enable_qos)

        self.create_subscription(String, '/call/state', self._on_call_state, 10)
        self.create_subscription(String, '/call/event', self._on_call_event, 10)
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.create_subscription(PersonTrackArray, '/person_tracking/tracks', self._on_tracks, 10)

        self.timer = self.create_timer(1.0 / max(1.0, rate), self._tick)
        self.get_logger().info(
            f'scout_follow_controller ready: {self.W}x{self.H} sign={self.sign:+d} '
            f'max_v={self.max_v} max_w={self.max_w} target_bh={self.target_bh}')

        # 라이브 튜닝: ros2 param set 으로 게인 즉시 반영 (지그재그 비교 등)
        self._tunable = {
            'kp_angular': 'kp_w', 'max_angular': 'max_w', 'angular_deadband_px': 'dead_px',
            'angular_sign': 'sign', 'kp_linear': 'kp_v', 'max_linear': 'max_v',
            'target_bh': 'target_bh', 'bh_stop': 'bh_stop', 'linear_deadband': 'dead_bh',
            'ema_alpha': 'alpha', 'handoff_base_w': 'handoff_w', 'handoff_sign': 'handoff_sign',
            'lost_dwell_sec': 'lost_dwell',
        }
        self.add_on_set_parameters_callback(self._on_set_params)

    def _on_set_params(self, params):
        for p in params:
            attr = self._tunable.get(p.name)
            if attr is None:
                continue
            try:
                setattr(self, attr,
                        int(p.value) if attr in ('sign', 'handoff_sign') else float(p.value))
            except (TypeError, ValueError):
                pass
        return SetParametersResult(successful=True)

    def _on_call_state(self, m: String):
        self.call_state = m.data.strip()

    def _on_call_event(self, m: String):
        try:
            self.lock_bearing = float(json.loads(m.data).get('bearing_rad', self.lock_bearing))
        except (ValueError, KeyError, TypeError):
            pass

    def _on_odom(self, m: Odometry):
        q = m.pose.pose.orientation
        self.base_yaw = yaw_from_quat(q.x, q.y, q.z, q.w)

    def _on_tracks(self, m: PersonTrackArray):
        out = []
        for t in m.tracks:
            if len(t.bbox) < 4:
                continue
            x1, y1, x2, y2 = (float(t.bbox[0]), float(t.bbox[1]),
                              float(t.bbox[2]), float(t.bbox[3]))
            out.append((int(t.track_id), (x1 + x2) / 2.0, (y1 + y2) / 2.0,
                        x2 - x1, y2 - y1))
        self.tracks = out

    def _base_yaw_delta(self) -> float:
        if self.base_yaw is None or self.base_yaw_at_lock is None:
            return 0.0
        d = self.base_yaw - self.base_yaw_at_lock
        return math.atan2(math.sin(d), math.cos(d))

    def _target_bbox(self):
        for (tid, cx, cy, w, h) in self.tracks:
            if tid == self.target_track_id:
                return (cx, cy, w, h)
        return None

    def _publish_cmd(self, v: float, w: float):
        self._v = self.alpha * v + (1 - self.alpha) * self._v
        self._w = self.alpha * w + (1 - self.alpha) * self._w
        msg = Twist()
        msg.linear.x = self._v
        msg.angular.z = self._w
        self.pub_cmd.publish(msg)

    def _publish_servo(self, pan: float):
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = ['pan', 'tilt']
        js.position = [float(pan), 0.0]
        self.pub_servo.publish(js)

    def _tick(self):
        now = self.get_clock().now()

        if self.state == 'SEARCH' and self.call_state == 'locked':
            self.base_yaw_at_lock = self.base_yaw if self.base_yaw is not None else 0.0
            self.pub_enable.publish(Bool(data=False))

        # 트랙이 하나라도 있으면 추종 가능 — FOLLOW 중 target track_id 가 바뀌어도
        # (BoT-SORT 재할당) SEARCH 로 빠지지 않고 최근접으로 자동 재획득.
        target_present = len(self.tracks) > 0
        if target_present:
            self.lost_since = None
        elif self.lost_since is None and self.state in ('FOLLOW', 'LOST'):
            self.lost_since = now
        lost_elapsed = 0.0 if self.lost_since is None else \
            (now - self.lost_since).nanoseconds * 1e-9

        if self.state == 'HANDOFF':
            if self._handoff_start is None:
                self._handoff_start = now
        else:
            self._handoff_start = None
        timeout_elapsed = (self._handoff_start is not None and
                           (now - self._handoff_start).nanoseconds * 1e-9 >= self.handoff_timeout)
        hdone = handoff_done(self._base_yaw_delta(), self.lock_bearing, self.yaw_tol) or timeout_elapsed
        new = next_state(self.state, self.call_state, target_present,
                         hdone, lost_elapsed, self.lost_dwell)

        if new == 'SEARCH':
            self._publish_cmd(0.0, 0.0)
            self.target_track_id = None
            # SEARCH 중 항상 call_detector 활성 보장 — 컨트롤러만 재기동 시 죽은
            # 이전 인스턴스의 latched enable=false 가 남아 교착되는 것 방지.
            self.pub_enable.publish(Bool(data=True))
        elif new == 'HANDOFF':
            delta = self._base_yaw_delta()
            w = self.handoff_sign * self.handoff_w * (1.0 if self.lock_bearing >= delta else -1.0)
            self._publish_cmd(0.0, max(-self.max_w, min(self.max_w, w)))
            self._publish_servo(handoff_servo_pan(self.lock_bearing, delta, self.servo_limit))
        elif new == 'FOLLOW':
            # 자동 (재)획득: 타깃 없거나 사라졌으면 화면 내 최근접 track 으로 교체
            if self.target_track_id is None or self._target_bbox() is None:
                new_tid = select_target_track(self.tracks, self.W)
                if new_tid is not None and new_tid != self.target_track_id:
                    self.target_track_id = new_tid
                    self._publish_servo(0.0)
            bbox = self._target_bbox()
            if bbox is None:
                self._publish_cmd(0.0, 0.0)
            else:
                cx, cy, bw, bh_px = bbox
                bh = bh_px / max(1.0, float(self.H))
                w = cx_to_angular(cx, self.W, self.kp_w, self.max_w, self.dead_px, self.sign)
                v = bh_to_linear(bh, self.target_bh, self.kp_v, self.max_v, self.bh_stop, self.dead_bh)
                self._publish_cmd(v, w)
        elif new == 'LOST':
            self._publish_cmd(0.0, 0.0)

        self.state = new


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ScoutFollowController()
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
