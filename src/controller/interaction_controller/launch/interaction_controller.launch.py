from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('interaction_controller'),
        'config',
        'interaction_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='interaction_controller',
            executable='interaction_controller_node',
            name='interaction_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
