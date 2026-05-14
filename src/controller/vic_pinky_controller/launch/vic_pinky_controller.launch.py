from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('vic_pinky_controller'),
        'config',
        'vic_pinky_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='vic_pinky_controller',
            executable='vic_pinky_controller_node',
            name='vic_pinky_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
