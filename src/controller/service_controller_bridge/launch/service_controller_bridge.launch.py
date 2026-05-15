from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('service_controller_bridge'),
        'config',
        'service_controller_bridge.yaml',
    ])

    return LaunchDescription([
        Node(
            package='service_controller_bridge',
            executable='service_controller_bridge_node',
            name='service_controller_bridge',
            output='screen',
            parameters=[config_file],
        ),
    ])
