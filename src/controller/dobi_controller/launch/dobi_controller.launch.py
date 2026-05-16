from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('dobi_controller'),
        'config',
        'dobi_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='dobi_controller',
            executable='dobi_controller_node',
            name='dobi_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
