from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('serving_controller'),
        'config',
        'serving_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='serving_controller',
            executable='serving_controller_node',
            name='serving_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
