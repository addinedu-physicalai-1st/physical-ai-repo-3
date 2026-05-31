from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('mobility_controller'),
        'config',
        'mobility_controller.yaml',
    ])

    return LaunchDescription([
        Node(
            package='mobility_controller',
            executable='mobility_controller_node',
            name='mobility_controller',
            output='screen',
            parameters=[config_file],
        ),
        Node(
            package='mobility_controller',
            executable='nav_map_apply_adapter',
            name='nav_map_apply_adapter',
            output='screen',
        ),
        Node(
            package='mobility_controller',
            executable='approach_controller',
            name='approach_controller_node',
            output='screen',
            parameters=[{
                'linear_speed':    0.15,
                'angular_gain':    1.8,
                'derivative_gain': 0.3,
                'ema_alpha':       0.3,
                'dead_zone':       0.05,
                'close_threshold': 0.999,
                'pose_timeout':    1.0,
            }],
        ),
    ])
