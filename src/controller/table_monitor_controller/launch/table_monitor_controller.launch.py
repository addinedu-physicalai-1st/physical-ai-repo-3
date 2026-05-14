from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('table_monitor_controller'),
        'config',
        'table_monitor_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='table_monitor_controller',
            executable='table_monitor_controller_node',
            name='table_monitor_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
