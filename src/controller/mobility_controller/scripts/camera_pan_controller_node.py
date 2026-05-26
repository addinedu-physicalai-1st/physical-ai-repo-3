#!/usr/bin/env python3
"""
camera_pan_controller_node — bbox 중심 x → 카메라 Pan 서보 P제어 (RPi 실행)

구독: /person_tracking/tracks  (dobi_npc_msgs/PersonTrackArray)
      /person_tracking/approach_target (std_msgs/Int32, 접근 중 그룹 id)
      /follow/target              (std_msgs/Int32, 추종 중 track_id / -1=없음)

동작:
  - approach 모드 (/person_tracking/approach_target >= 0):
      해당 그룹에서 가장 큰 bbox 중심 x → 서보 P제어
  - follow 모드 (/follow/target >= 0):
      해당 track_id bbox 중심 x → 서보 P제어
  - 둘 다 -1: 서보 중앙(0°) 복귀

서보 각도 범위: -pan_limit_deg ~ +pan_limit_deg (기본 ±45°)
PWM 핀 / 서보 타입: ⚠ 내일 하드웨어 확인 후 채울 것

RPi 전제조건:
  - RPi GPIO 또는 PCA9685 서보 드라이버 연결 확인 필요
  - 현재는 서보 제어 코드 TODO 처리 — 구조만 완성
"""
from __future__ import annotations

import time
import math

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from std_msgs.msg import Int32
from dobi_npc_msgs.msg import PersonTrackArray


class CameraPanControllerNode(Node):
    """카메라 Pan 서보를 사람 bbox 중심으로 P제어."""

    def __init__(self):
        super().__init__('camera_pan_controller_node')

        # ── 파라미터 ────────────────────────────────────────────────
        self.declare_parameter('kp_pan',        0.05)   # P 게인 (정규화 오차 → 각도 보정 deg)
        self.declare_parameter('pan_limit_deg', 45.0)   # 서보 최대 회전 각도
        self.declare_parameter('deadband',      0.04)   # 중앙 ±deadband 이내는 보정 안 함 (정규화)
        self.declare_parameter('cmd_rate',      20.0)   # 서보 발행 주파수 (Hz)
        self.declare_parameter('center_on_lost',True)   # 타겟 소실 시 중앙 복귀 여부

        # ⚠ 하드웨어 파라미터 — 내일 서보 확인 후 기본값 수정
        self.declare_parameter('servo_channel',   0)    # PCA9685 채널 or GPIO 핀 번호
        self.declare_parameter('servo_freq_hz',  50)    # PWM 주파수 (서보 표준: 50Hz)
        self.declare_parameter('servo_min_us',  500)    # 최소 펄스폭 (us) — 서보 스펙 확인 필요
        self.declare_parameter('servo_max_us', 2500)    # 최대 펄스폭 (us) — 서보 스펙 확인 필요
        self.declare_parameter('servo_center_us', 1500) # 중앙 펄스폭 (us)

        self._kp           = float(self.get_parameter('kp_pan').value)
        self._limit        = float(self.get_parameter('pan_limit_deg').value)
        self._deadband     = float(self.get_parameter('deadband').value)
        self._center_lost  = bool(self.get_parameter('center_on_lost').value)

        # 서보 하드웨어 파라미터
        self._servo_ch      = int(self.get_parameter('servo_channel').value)
        self._servo_freq    = int(self.get_parameter('servo_freq_hz').value)
        self._servo_min_us  = int(self.get_parameter('servo_min_us').value)
        self._servo_max_us  = int(self.get_parameter('servo_max_us').value)
        self._servo_ctr_us  = int(self.get_parameter('servo_center_us').value)

        # 상태
        self._tracks        = []
        self._approach_gid  = -1    # 접근 대상 그룹 id
        self._follow_tid    = -1    # 추종 대상 track_id
        self._current_deg   = 0.0   # 현재 서보 각도 (0 = 중앙)
        self._last_track_t  = 0.0

        # ── 서보 초기화 ─────────────────────────────────────────────
        self._servo = None
        self._init_servo()

        # ── 구독 ────────────────────────────────────────────────────
        self._sub_tracks = self.create_subscription(
            PersonTrackArray,
            '/person_tracking/tracks',
            self._cb_tracks,
            10,
        )
        self._sub_approach = self.create_subscription(
            Int32,
            '/person_tracking/approach_target',
            self._cb_approach,
            10,
        )
        self._sub_follow = self.create_subscription(
            Int32,
            '/follow/target',
            self._cb_follow,
            10,
        )

        rate = float(self.get_parameter('cmd_rate').value)
        self._timer = self.create_timer(1.0 / rate, self._tick)

        self.get_logger().info(
            f'camera_pan_controller_node 준비 완료 '
            f'(ch={self._servo_ch}, kp={self._kp}, limit=±{self._limit}°)'
        )

    # ── 서보 초기화 ─────────────────────────────────────────────────
    def _init_servo(self) -> None:
        """
        ⚠ TODO: 내일 서보 타입 확인 후 구현
        선택지:
          A) RPi GPIO PWM (pigpio 또는 RPi.GPIO)
          B) PCA9685 I2C 서보 드라이버 (adafruit-circuitpython-pca9685)

        확인 항목:
          - 서보 연결 방식 (직접 GPIO vs PCA9685 보드)
          - PWM 핀 번호 (GPIO 방식) 또는 I2C 채널 번호
          - 서보 스펙: 동작 각도 범위, 펄스폭 범위 (us)
        """
        try:
            # ── A안: pigpio (GPIO 직접 연결) ──────────────────────
            # import pigpio
            # self._pi = pigpio.pi()
            # if not self._pi.connected:
            #     raise RuntimeError('pigpio daemon not running — run: sudo pigpiod')
            # self._servo = self._pi
            # self._set_servo_deg(0.0)  # 중앙 초기화

            # ── B안: PCA9685 I2C 드라이버 ────────────────────────
            # import board, busio
            # from adafruit_pca9685 import PCA9685
            # i2c = busio.I2C(board.SCL, board.SDA)
            # pca = PCA9685(i2c)
            # pca.frequency = self._servo_freq
            # self._servo = pca.channels[self._servo_ch]
            # self._set_servo_deg(0.0)

            self.get_logger().warn(
                '⚠ 서보 드라이버 미초기화 — 내일 하드웨어 확인 후 _init_servo() 구현 필요'
            )
        except Exception as e:
            self.get_logger().error(f'서보 초기화 실패: {e}')
            self._servo = None

    # ── 서보 각도 설정 ───────────────────────────────────────────────
    def _set_servo_deg(self, deg: float) -> None:
        """
        deg: -pan_limit ~ +pan_limit (0 = 중앙, 양수 = 오른쪽)

        ⚠ TODO: 서보 타입 결정 후 아래 주석 중 하나 활성화

        # pigpio 방식:
        # us = self._servo_ctr_us + int(deg / 90.0 * (self._servo_max_us - self._servo_ctr_us))
        # us = max(self._servo_min_us, min(self._servo_max_us, us))
        # self._pi.set_servo_pulsewidth(self._servo_ch, us)

        # PCA9685 방식:
        # us = self._servo_ctr_us + int(deg / 90.0 * (self._servo_max_us - self._servo_ctr_us))
        # us = max(self._servo_min_us, min(self._servo_max_us, us))
        # duty = int(us / (1_000_000 / self._servo_freq) * 65535)
        # self._servo.duty_cycle = duty
        """
        self._current_deg = max(-self._limit, min(self._limit, deg))
        # 실제 서보 출력은 TODO 구현 후 활성화
        self.get_logger().debug(f'서보 목표: {self._current_deg:.1f}°')

    # ── 콜백 ────────────────────────────────────────────────────────
    def _cb_tracks(self, msg: PersonTrackArray) -> None:
        self._tracks = msg.tracks
        if msg.tracks:
            self._last_track_t = time.time()

    def _cb_approach(self, msg: Int32) -> None:
        self._approach_gid = msg.data

    def _cb_follow(self, msg: Int32) -> None:
        self._follow_tid = msg.data

    # ── 메인 틱 ────────────────────────────────────────────────────
    def _tick(self) -> None:
        target_cx = self._find_target_cx()

        if target_cx is None:
            # 타겟 없음 → 중앙 복귀
            if self._center_lost:
                self._set_servo_deg(0.0)
            return

        # err_x: 화면 중앙(0.5) 기준 정규화 오차 (-0.5 ~ +0.5)
        err_x = target_cx - 0.5
        if abs(err_x) < self._deadband:
            return  # 무감대 내 → 보정 불필요

        # P제어: 오차 → 각도 보정
        # err_x > 0: 오른쪽 → 서보 오른쪽 회전 (양수)
        correction = self._kp * err_x * 100.0  # 정규화 → deg 스케일
        new_deg = self._current_deg + correction
        self._set_servo_deg(new_deg)

        self.get_logger().debug(
            f'pan: err={err_x:.3f} → correction={correction:.1f}° → deg={self._current_deg:.1f}°'
        )

    def _find_target_cx(self) -> float | None:
        """follow > approach 우선순위로 타겟 bbox 중심 x(정규화) 반환."""
        if not self._tracks:
            return None

        # follow 모드 우선
        if self._follow_tid >= 0:
            for t in self._tracks:
                if t.track_id == self._follow_tid:
                    return (float(t.bbox[0]) + float(t.bbox[2])) / 2.0 / 640.0
            return None

        # approach 모드
        if self._approach_gid >= 0:
            best_cx, best_area = None, 0.0
            for t in self._tracks:
                if t.group_id != self._approach_gid:
                    continue
                area = (float(t.bbox[2]) - float(t.bbox[0])) * (float(t.bbox[3]) - float(t.bbox[1]))
                if area > best_area:
                    best_area = area
                    best_cx = (float(t.bbox[0]) + float(t.bbox[2])) / 2.0 / 640.0
            return best_cx

        return None

    def destroy_node(self):
        # 서보 중앙 복귀 후 종료
        try:
            self._set_servo_deg(0.0)
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraPanControllerNode()
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
