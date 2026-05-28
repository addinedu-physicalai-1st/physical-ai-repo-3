from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('single_arm_controller'),
        'config',
        'single_arm_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='single_arm_controller',
            executable='controller_status_monitor',
            name='controller_status_monitor',
            output='screen',
            parameters=[config_file],
        ),
    ])
