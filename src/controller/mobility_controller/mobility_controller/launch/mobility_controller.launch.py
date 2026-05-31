from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('mobility_controller'),
        'config',
        'mobility_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='mobility_controller',
            executable='mobility_controller_node',
            name='mobility_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
