"""Launch the read-only operational debug monitor."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='debug_monitor',
            executable='doby_debug_monitor',
            name='doby_debug_monitor',
            output='screen',
        ),
    ])
