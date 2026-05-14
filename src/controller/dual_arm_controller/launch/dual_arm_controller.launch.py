from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('dual_arm_controller'),
        'config',
        'dual_arm_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='dual_arm_controller',
            executable='dual_arm_controller_node',
            name='dual_arm_controller',
            output='screen',
            parameters=[config_file],
        ),
    ])
