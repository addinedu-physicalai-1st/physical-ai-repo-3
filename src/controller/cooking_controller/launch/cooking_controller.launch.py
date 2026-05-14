from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('cooking_controller'),
        'config',
        'cooking_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='cooking_controller',
            executable='cooking_controller_node',
            name='cooking_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
