"""dobi_gimbal bridge launch -- Arduino pan-tilt serial bridge.

Loads config/dobi_gimbal_calib.yaml from the installed share dir by default.
Keeps the /scout_cam/cmd_pan_tilt + /scout_cam/servo_state topic contract so the
existing scout_follow_controller (mobility_controller) works against this bridge
without remapping.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_calib = os.path.join(
        get_package_share_directory('dobi_gimbal'), 'config', 'dobi_gimbal_calib.yaml')

    serial_port = DeclareLaunchArgument(
        'serial_port', default_value='/dev/ttyACM0',
        description='Arduino serial port. Prefer a /dev/serial/by-id/... path for stability.')
    calib_path = DeclareLaunchArgument(
        'calib_path', default_value=default_calib,
        description='gimbal calibration yaml path')

    bridge = Node(
        package='dobi_gimbal', executable='gimbal_bridge_node',
        name='dobi_gimbal_bridge', output='screen',
        parameters=[{
            'serial_port': LaunchConfiguration('serial_port'),
            'calib_path': LaunchConfiguration('calib_path'),
        }],
    )
    return LaunchDescription([serial_port, calib_path, bridge])
