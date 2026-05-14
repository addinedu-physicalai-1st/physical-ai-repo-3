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
            executable='single_arm_controller_node',
            name='single_arm_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
