from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('tubi_controller'),
        'config',
        'tubi_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='tubi_controller',
            executable='tubi_controller_node',
            name='tubi_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
