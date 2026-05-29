"""gimbal_bridge_node -- Arduino serial bridge for the dobi pan-tilt gimbal.

Ported from scout_reactor.scout_servo_node, adapted for our gimbal:
  Pan  : MG995 270deg servo (Arduino D9)
  Tilt : MG995 180deg servo (Arduino D10)
  - ABSOLUTE servo-degree protocol (not scout's centered +/-90)
  - safe-range clamping on the effective command (the firmware hard-clamps too)

ROS topics (kept identical to the scout contract so the existing
scout_follow_controller in mobility_controller works against this bridge without
remapping):
  subscribe /scout_cam/cmd_pan_tilt  (sensor_msgs/JointState, name=[pan, tilt], position rad)
  publish   /scout_cam/servo_state   (sensor_msgs/JointState, 50Hz, same format)

cmd  : desired_rad -> deg -> eff = desired*sign+offset -> clamp[min,max] -> "P<int>,T<int>\\n"
state: sketch "S<int>,<int>" -> desired = (eff-offset)/sign -> rad -> publish

A reader thread does serial readline; a ROS timer publishes the latest state.
On Arduino reset (B banner) the last command is resent. On shutdown a reset
(-> home) is sent before close.
"""
from __future__ import annotations

import math
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState

import serial  # pyserial

from dobi_gimbal.gimbal_calib import load_calib_or_default
from dobi_gimbal.gimbal_serial import (
    ServoCmd,
    ServoState,
    build_cmd_line,
    build_reset_line,
    parse_line,
)


class GimbalBridgeNode(Node):

    def __init__(self):
        super().__init__('dobi_gimbal_bridge')

        self.declare_parameter('serial_port', '/dev/ttyACM0')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('calib_path', '')
        self.declare_parameter('cmd_topic', '/scout_cam/cmd_pan_tilt')
        self.declare_parameter('state_topic', '/scout_cam/servo_state')
        self.declare_parameter('state_publish_rate_hz', 50.0)
        self.declare_parameter('cmd_rate_limit_hz', 20.0)

        port = str(self.get_parameter('serial_port').value)
        baud = int(self.get_parameter('baud').value)
        calib_path = str(self.get_parameter('calib_path').value) or None
        cmd_topic = str(self.get_parameter('cmd_topic').value)
        state_topic = str(self.get_parameter('state_topic').value)
        publish_rate = float(self.get_parameter('state_publish_rate_hz').value)
        cmd_min_period = 1.0 / max(0.1, float(self.get_parameter('cmd_rate_limit_hz').value))

        # calib
        self._calib = load_calib_or_default(calib_path)
        self.get_logger().info(
            f'calib: pan(sign={self._calib.pan.sign:+d}, off={self._calib.pan.offset:+g}, '
            f'safe[{self._calib.pan.min_deg:g},{self._calib.pan.max_deg:g}]), '
            f'tilt(sign={self._calib.tilt.sign:+d}, off={self._calib.tilt.offset:+g}, '
            f'safe[{self._calib.tilt.min_deg:g},{self._calib.tilt.max_deg:g}])'
        )
        if calib_path:
            self.get_logger().info(f'calib loaded from {calib_path}')
        else:
            self.get_logger().warn('calib_path empty -- using built-in dobi defaults')

        # serial open
        try:
            self._ser = serial.Serial(port, baud, timeout=0.2)
        except serial.SerialException as e:
            self.get_logger().error(f'Failed to open {port}: {e}')
            raise
        time.sleep(2.5)  # Arduino reset settle (DTR auto-reset)
        self._ser.reset_input_buffer()
        self.get_logger().info(f'serial open: {port} @ {baud}')

        # ROS
        self._sub = self.create_subscription(JointState, cmd_topic, self._on_cmd, 10)
        self._pub = self.create_publisher(JointState, state_topic, 10)
        self._state_timer = self.create_timer(1.0 / publish_rate, self._publish_state)

        # last known state (effective servo deg) -- seed with home
        self._last_state_pan_deg = int(round(self._calib.pan.home_deg))
        self._last_state_tilt_deg = int(round(self._calib.tilt.home_deg))
        self._state_lock = threading.Lock()
        self._last_cmd_t = 0.0
        self._last_cmd_pan_eff: int | None = None
        self._last_cmd_tilt_eff: int | None = None
        self._cmd_min_period = cmd_min_period

        # reader thread
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # -- subscribe callback ---------------------------------
    def _on_cmd(self, msg: JointState):
        try:
            pan_idx = msg.name.index('pan')
            tilt_idx = msg.name.index('tilt')
            desired_pan_rad = float(msg.position[pan_idx])
            desired_tilt_rad = float(msg.position[tilt_idx])
        except (ValueError, IndexError) as e:
            self.get_logger().warn(f'cmd parse fail: {e}', throttle_duration_sec=5.0)
            return

        eff_pan = self._calib.pan.clamp_effective(
            self._calib.pan.desired_to_effective(math.degrees(desired_pan_rad)))
        eff_tilt = self._calib.tilt.clamp_effective(
            self._calib.tilt.desired_to_effective(math.degrees(desired_tilt_rad)))
        eff_pan = int(round(eff_pan))
        eff_tilt = int(round(eff_tilt))

        now = time.time()
        if (eff_pan == self._last_cmd_pan_eff
                and eff_tilt == self._last_cmd_tilt_eff
                and now - self._last_cmd_t < self._cmd_min_period):
            return

        try:
            self._ser.write(build_cmd_line(ServoCmd(eff_pan, eff_tilt)))
            self._ser.flush()
            self._last_cmd_pan_eff = eff_pan
            self._last_cmd_tilt_eff = eff_tilt
            self._last_cmd_t = now
        except serial.SerialException as e:
            self.get_logger().warn(f'serial write fail: {e}', throttle_duration_sec=5.0)

    # -- reader thread --------------------------------------
    def _read_loop(self):
        while not self._stop.is_set():
            try:
                line = self._ser.readline().decode(errors='replace')
            except serial.SerialException as e:
                self.get_logger().warn(
                    f'serial read fail: {e}', throttle_duration_sec=5.0)
                time.sleep(0.5)
                continue
            ev = parse_line(line)
            if isinstance(ev, ServoState):
                with self._state_lock:
                    self._last_state_pan_deg = ev.pan_deg
                    self._last_state_tilt_deg = ev.tilt_deg
            elif ev == 'B':
                self.get_logger().warn('Arduino boot detected -- resending last cmd')
                if self._last_cmd_pan_eff is not None:
                    try:
                        self._ser.write(build_cmd_line(ServoCmd(
                            self._last_cmd_pan_eff, self._last_cmd_tilt_eff)))
                        self._ser.flush()
                    except serial.SerialException:
                        pass

    # -- state publisher (timer) ----------------------------
    def _publish_state(self):
        with self._state_lock:
            eff_pan = self._last_state_pan_deg
            eff_tilt = self._last_state_tilt_deg
        # calib inverse: effective deg -> user desired deg -> rad
        desired_pan_deg = self._calib.pan.effective_to_desired(eff_pan)
        desired_tilt_deg = self._calib.tilt.effective_to_desired(eff_tilt)
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = ['pan', 'tilt']
        msg.position = [math.radians(desired_pan_deg), math.radians(desired_tilt_deg)]
        self._pub.publish(msg)

    # -- cleanup --------------------------------------------
    def destroy_node(self):
        self._stop.set()
        try:
            if self._ser and self._ser.is_open:
                # reset to home then close (safe rest)
                try:
                    self._ser.write(build_reset_line())
                    self._ser.flush()
                except Exception:
                    pass
                self._ser.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = GimbalBridgeNode()
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
