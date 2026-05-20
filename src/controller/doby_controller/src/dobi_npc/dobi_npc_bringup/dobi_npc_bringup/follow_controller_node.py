#!/usr/bin/env python3
"""follow_controller — person_detector 결과 → /cmd_vel reactive 제어.

mode_follow 의 본체. mode_follow.launch.py 가 spawn 시 person_detector_node와
함께 띄워져 다음을 수행:

  /robot_cam/persons (Detection2DArray)
        │
        ▼  (가장 큰 bbox 선택 = 가장 가까운 사람)
  err_angle = (image_cx - bbox_cx) / (image_w / 2)
  err_dist  = target_height_ratio - (bbox_h / image_h)
        │
        ▼  P 제어 + 클램프
  /cmd_vel (geometry_msgs/Twist)

안전 가드 (publish 0 또는 v=0 강제):
  1) /rapport/event abort_trigger → 즉시 v=ω=0 + dwell 동안 송신 중단
  2) /scan 전방 ±front_arc_deg(기본 30°) 구간 < scan_stop_dist(0.8m) → v=0 (회전은 허용)
  3) detection_lost_sec(기본 1.0s) 동안 person 미검출 → v=ω=0
  4) image_size 미수신 → 0 (첫 sample 들어와야 정상 평가)

dialog_router 권한과 무관하게 본 노드가 직접 /cmd_vel 발행. mode_manager가 mode를
follow 외로 전환하면 본 launch 가 SIGINT 받고 destroy_node에서 마지막 stop msg
발행 후 종료.
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

from dobi_npc_msgs.msg import RapportEvent


class FollowControllerNode(Node):
    """Detection2DArray → reactive cmd_vel + multi-source safety gate."""

    def __init__(self):
        super().__init__('follow_controller_node')

        self.declare_parameter('persons_topic', '/robot_cam/persons')
        self.declare_parameter('scan_topic', '/scan')
        self.declare_parameter('rapport_topic', '/rapport/event')
        # Phase A (2026-05-09): twist_mux 도입으로 follow 전용 토픽으로 분리.
        # twist_mux 가 /joy /bt /follow priority 통합 → /cmd_vel 출력 (Phase B 부터 /cmd_vel_raw).
        self.declare_parameter('cmd_vel_topic', '/follow/cmd_vel')

        # 카메라 frame 가정 (person_detector는 이미지 px 좌표 그대로 publish)
        # 첫 detection msg에서 갱신해도 되지만, 빠른 첫 사이클 위해 기본값.
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)

        # 추종 목표
        self.declare_parameter('target_height_ratio', 0.5)   # bbox_h / image_h (미사용 — 라이다로 대체)
        self.declare_parameter('target_dist', 0.7)           # 라이다 기준 유지할 거리 (m)
        self.declare_parameter('dist_deadband', 0.05)        # ±0.05m 안쪽이면 정지
        self.declare_parameter('angle_deadband', 0.10)       # ±10% (≈ ±20° at 60° HFOV).
                                                              # 너무 좁으면 jitter, 너무 넓으면 dead zone.

        # P 제어 게인 — close-range follow 기준 매우 보수적 (카페 시나리오)
        self.declare_parameter('kp_linear', 0.4)             # err_dist → m/s
        self.declare_parameter('kp_angular', 0.4)            # err_angle (-1..1) → rad/s.

        # EMA 저역통과 필터 — bbox center jitter + detector noise 평탄화
        # 0=비활성(생값 그대로), 1=완전 평탄(이전 값만, 응답 없음).
        # 0.2=신값 20% + 이전 80% (느린 응답, 부드러움 우선).
        self.declare_parameter('angle_smoothing_alpha', 0.2)

        # 속도 한계 — 카페 환경 부드러운 follow 우선
        self.declare_parameter('max_linear', 0.20)           # m/s ≈ 느린 도보
        self.declare_parameter('max_angular', 0.25)          # rad/s ≈ 14°/s

        # 각도 정렬 게이트 — |err_angle| 이 이 값 초과하면 전진 0 (회전만 먼저).
        # 지그재그 방지: 회전 + 전진 동시 시 trajectory 카브 → 오버슈트 → 진동.
        # 0이면 비활성. 0.2 ≈ ±20% (≈ ±12° at 60° HFOV).
        self.declare_parameter('align_gate', 0.2)

        # 안전
        self.declare_parameter('detection_lost_sec', 1.0)
        self.declare_parameter('abort_dwell_sec', 2.0)
        self.declare_parameter('scan_stop_dist', 0.8)
        self.declare_parameter('scan_min_range', 0.25)       # safety_check.hpp와 동일 vicpinky 섀시 마스킹
        self.declare_parameter('front_arc_deg', 30.0)

        # 제어 publish rate
        self.declare_parameter('control_rate_hz', 20.0)

        # mode_manager가 SetMode 서비스 JSON params를 그대로 reflect 하기 위함 (현 미사용).
        self.declare_parameter('params_json', '')

        self.persons_topic = self.get_parameter('persons_topic').value
        self.scan_topic = self.get_parameter('scan_topic').value
        self.rapport_topic = self.get_parameter('rapport_topic').value
        cmd_topic = self.get_parameter('cmd_vel_topic').value

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
        self._target_bbox = None        # (cx, cy, w, h) 가장 큰 person bbox (raw)
        self._err_angle_filt = 0.0       # EMA 평활화된 err_angle
        self._err_dist_filt = 0.0        # EMA 평활화된 err_dist
        self._dwell_until = 0.0          # abort dwell timer (monotonic)
        self._scan_front_min = float('inf')
        self._scan_received = False
        self._last_log = time.time()
        self._cmd_count = 0

        # I/O
        self.sub_persons = self.create_subscription(
            Detection2DArray, self.persons_topic, self._on_persons, 10)
        self.sub_scan = self.create_subscription(
            LaserScan, self.scan_topic, self._on_scan, 5)
        self.sub_rapport = self.create_subscription(
            RapportEvent, self.rapport_topic, self._on_rapport, 10)
        self.pub_cmd = self.create_publisher(Twist, cmd_topic, 5)

        self.timer = self.create_timer(1.0 / ctl_hz, self._control_tick)

        # 라이브 튜닝 — follow_tuner GUI / ros2 param set 으로 게인/max 조정.
        # init 시 한 번 읽어 self.* 인스턴스 변수에 박혀 있던 값을 callback 에서 동기화.
        # 모든 param 라이브 가능 X — 안전 가드/사이즈/topic 류는 재시동 필요.
        self._LIVE_TUNABLE = {
            'kp_linear', 'kp_angular',
            'max_linear', 'max_angular',
            'target_height_ratio', 'target_dist', 'angle_deadband', 'dist_deadband',
            'align_gate', 'angle_smoothing_alpha',
            'detection_lost_sec', 'abort_dwell_sec',
            'scan_stop_dist', 'scan_min_range', 'front_arc_deg',
        }
        self.add_on_set_parameters_callback(self._on_set_params)

        self.get_logger().info(
            f"follow_controller ready: "
            f"persons={self.persons_topic} scan={self.scan_topic} "
            f"cmd={cmd_topic} image={self.image_w}x{self.image_h} "
            f"target_h={self.target_h_ratio:.2f} "
            f"kp_v={self.kp_linear:.2f} kp_w={self.kp_angular:.2f} "
            f"max_v={self.max_linear:.2f} max_w={self.max_angular:.2f} "
            f"ema_alpha={self.angle_alpha:.2f} align_gate={self.align_gate:.2f} "
            f"deadband_a={self.angle_deadband:.2f} d={self.dist_deadband:.2f} "
            f"abort_dwell={self.abort_dwell_sec:.1f}s "
            f"front_arc=±{self.front_arc_deg:.0f}° stop<{self.scan_stop_dist:.2f}m"
        )

    # ── 콜백 ────────────────────────────────────────────────

    def _on_set_params(self, params):
        """ros2 param set / follow_tuner 가 호출. 화이트리스트 만 self.* 에 반영."""
        applied = []
        for p in params:
            if p.name not in self._LIVE_TUNABLE:
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

    def _on_persons(self, msg: Detection2DArray):
        # 가장 큰 bbox 선택 = 가장 가까운 사람으로 가정. tracking은 후속.
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
        # 전방 ±front_arc_deg 구간의 가장 가까운 ray.
        # angle_min ~ angle_max 범위에서 0 rad 근처 인덱스 추출.
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
        # tts/face_avatar dwell과 같은 정책 (face_avatar pygame, tts time.monotonic).
        if self.abort_dwell_sec > 0:
            self._dwell_until = time.monotonic() + self.abort_dwell_sec
        # 즉시 정지 cmd 1회. 이후 dwell 동안 매 tick 정지 유지.
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
            # detection 잃으면 EMA도 reset (이후 reacquire 시 다시 가속하지 말고 부드럽게).
            self._err_angle_filt = 0.0
            self._err_dist_filt = 0.0
            return

        cx, _cy, _w, _h = self._target_bbox

        # err_angle: 양수 = 사람이 화면 왼쪽 → 로봇은 좌회전 (ω > 0)
        err_angle_raw = (self.image_w / 2.0 - cx) / (self.image_w / 2.0)

        # err_dist: 라이다 기반 — 양수 = 너무 멀다 → 전진, 음수 = 너무 가깝다 → 후진
        # scan_front_min이 유효할 때만 계산, 아니면 정지
        if self._scan_received and math.isfinite(self._scan_front_min):
            err_dist_raw = self._scan_front_min - self.target_dist
        else:
            err_dist_raw = 0.0

        # EMA 저역통과 — bbox 검출 jitter 평탄화
        # alpha=0이면 raw 그대로, alpha=1이면 이전 값 고정.
        a = self.angle_alpha
        if a > 0:
            self._err_angle_filt = a * err_angle_raw + (1 - a) * self._err_angle_filt
            self._err_dist_filt = a * err_dist_raw + (1 - a) * self._err_dist_filt
            err_angle = self._err_angle_filt
            err_dist = self._err_dist_filt
        else:
            err_angle = err_angle_raw
            err_dist = err_dist_raw

        # deadband — 작은 오차에서 cmd 0 (정지/안정)
        if abs(err_angle) < self.angle_deadband:
            err_angle = 0.0
        if abs(err_dist) < self.dist_deadband:
            err_dist = 0.0

        v = self._clamp(self.kp_linear * err_dist, -self.max_linear, self.max_linear)
        w = self._clamp(self.kp_angular * err_angle, -self.max_angular, self.max_angular)

        # 각도 정렬 우선 게이트 — 회전 먼저, 정렬되면 전진. 지그재그 방지.
        # |err_angle| > align_gate 면 전진 v=0 → 회전만 → robot이 사람 방향으로 정렬.
        # 정렬 후 (deadband 안) 전진 활성.
        if self.align_gate > 0 and abs(err_angle) > self.align_gate:
            v = 0.0

        # 가드 3: 전방 obstacle → 전진만 차단 (회전은 허용)
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
        # 모든 필드 0 (geometry_msgs Twist 기본값)
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
            self.get_logger().info(
                f"cmd_rate={rate:.1f}Hz "
                f"v={v:+.2f} w={w:+.2f} "
                f"err_angle={err_a:+.2f} err_dist={err_d:+.2f} "
                f"bbox_h={bbox_h:.0f} scan_front={self._scan_front_min:.2f}m"
            )
            self._cmd_count = 0
            self._last_log = now

    def destroy_node(self):
        # 종료 직전 정지 메시지 1회 (BR 신호).
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
