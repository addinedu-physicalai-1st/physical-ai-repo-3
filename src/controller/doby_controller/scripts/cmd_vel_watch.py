#!/usr/bin/env python3
"""
cmd_vel_watch.py — /cmd_vel 안전 모니터 (Approach Nav2 통합 검증용)

역할:
  - /cmd_vel (geometry_msgs/Twist) 구독
  - 임계값 (linear|angular) 초과 시 SCREAM 로그 + 옵션으로 RPi bringup 자동 종료
  - 통과 메시지는 카운트 + 주기 요약

용도 (체크리스트 §4.2):
  Approach BT가 Nav2에 goal 송신 후 Nav2 → cmd_vel 흐름이 살아있을 때
  vic_pinky가 의도치 않게 이동하려는 시도를 즉시 감지·차단.

종료: Ctrl+C → 마지막 통계 출력 후 정리.

옵션:
  --linear-thresh   기본 0.05 m/s
  --angular-thresh  기본 0.05 rad/s
  --kill-on-trip    위반 시 RPi bringup 종료 (sshpass 필요)
  --robot-ip        기본 192.168.0.138
  --robot-user      기본 vic
  --robot-pass      기본 1
"""

import argparse
import math
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import Twist


class CmdVelWatcher(Node):
    def __init__(self, args):
        super().__init__('cmd_vel_watch')
        self.linear_thresh = args.linear_thresh
        self.angular_thresh = args.angular_thresh
        self.kill_on_trip = args.kill_on_trip
        self.robot_ip = args.robot_ip
        self.robot_user = args.robot_user
        self.robot_pass = args.robot_pass

        self.tripped = False
        self.total_msgs = 0
        self.zero_msgs = 0
        self.nonzero_msgs = 0
        self.peak_lin = 0.0
        self.peak_ang = 0.0
        self.start_t = time.time()

        # bringup이 reliable로 발행할 가능성 높음. reliable로 받으면 best_effort 발행도 못 받지만,
        # Nav2의 velocity_smoother는 보통 reliable 발행 — 동일 정책으로 안전 수신.
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.sub_ = self.create_subscription(
            Twist, '/cmd_vel', self._on_cmd_vel, qos)

        # 5초마다 요약
        self.timer_ = self.create_timer(5.0, self._summary)

        self.get_logger().info(
            f'WATCHING /cmd_vel  (lin>{self.linear_thresh}m/s, '
            f'ang>{self.angular_thresh}rad/s)  '
            f'kill_on_trip={self.kill_on_trip}')

    def _on_cmd_vel(self, msg: Twist):
        self.total_msgs += 1
        lin = math.hypot(msg.linear.x, msg.linear.y)
        ang = abs(msg.angular.z)

        if lin > self.peak_lin:
            self.peak_lin = lin
        if ang > self.peak_ang:
            self.peak_ang = ang

        is_zero = (lin < 1e-4 and ang < 1e-4)
        if is_zero:
            self.zero_msgs += 1
            return

        self.nonzero_msgs += 1
        violated = (lin > self.linear_thresh) or (ang > self.angular_thresh)
        if not violated:
            return

        # === TRIP ===
        if not self.tripped:
            self.tripped = True
            self.get_logger().error(
                '!!! TRIP: /cmd_vel 임계 초과 — '
                f'linear={lin:.3f}m/s (>={self.linear_thresh}), '
                f'angular={ang:.3f}rad/s (>={self.angular_thresh}) '
                f'twist=(x={msg.linear.x:.3f}, y={msg.linear.y:.3f}, '
                f'wz={msg.angular.z:.3f})')
            if self.kill_on_trip:
                self._kill_remote_bringup()
        else:
            self.get_logger().warning(
                f'(이미 TRIP) lin={lin:.3f} ang={ang:.3f}')

    def _kill_remote_bringup(self):
        self.get_logger().error('>>> RPi bringup 비상 종료 시도...')
        cmd = [
            'sshpass', '-p', self.robot_pass,
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'LogLevel=ERROR',
            '-o', 'ConnectTimeout=3',
            f'{self.robot_user}@{self.robot_ip}',
            "pkill -KILL -f '[v]icpinky_bringup' 2>/dev/null; "
            "pkill -KILL -f '[r]os2 launch vicpinky' 2>/dev/null; "
            "pkill -KILL -f '[c]ontroller_server\\|[v]elocity_smoother' 2>/dev/null; "
            "echo 'remote bringup killed'"
        ]
        try:
            r = subprocess.run(cmd, timeout=6, capture_output=True, text=True)
            self.get_logger().error(f'>>> kill stdout: {r.stdout.strip()}')
            if r.stderr.strip():
                self.get_logger().error(f'>>> kill stderr: {r.stderr.strip()}')
        except Exception as e:
            self.get_logger().error(f'>>> kill failed: {e}')

    def _summary(self):
        elapsed = time.time() - self.start_t
        self.get_logger().info(
            f'[{elapsed:5.1f}s] msgs total={self.total_msgs} '
            f'zero={self.zero_msgs} nonzero={self.nonzero_msgs} '
            f'peak lin={self.peak_lin:.3f}m/s '
            f'peak ang={self.peak_ang:.3f}rad/s '
            f'TRIPPED={self.tripped}')


def main(argv=None):
    p = argparse.ArgumentParser(description='/cmd_vel 안전 모니터')
    p.add_argument('--linear-thresh', type=float, default=0.05,
                   help='linear 속도 임계 m/s (기본 0.05)')
    p.add_argument('--angular-thresh', type=float, default=0.05,
                   help='angular 속도 임계 rad/s (기본 0.05)')
    p.add_argument('--kill-on-trip', action='store_true',
                   help='임계 초과 시 RPi bringup SSH로 KILL')
    p.add_argument('--robot-ip', default='192.168.0.138')
    p.add_argument('--robot-user', default='vic')
    p.add_argument('--robot-pass', default='1')
    args, _ = p.parse_known_args(argv)

    rclpy.init()
    node = CmdVelWatcher(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # 종료 시 마지막 요약
        node._summary()
        node.get_logger().info(
            f'FINAL: {"TRIPPED" if node.tripped else "CLEAN"} — '
            f'total={node.total_msgs} '
            f'peak lin={node.peak_lin:.3f} ang={node.peak_ang:.3f}')
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
