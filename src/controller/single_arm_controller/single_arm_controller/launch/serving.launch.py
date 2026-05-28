from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_config_path = PathJoinSubstitution([
        FindPackageShare('single_arm_controller'),
        'config',
        'waiter_config.yaml',
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            'config_path',
            default_value=default_config_path,
            description='waiter YAML config path',
        ),
        DeclareLaunchArgument(
            'top_cam_path',
            default_value='',
            description='top camera device path; empty = YAML default',
        ),
        DeclareLaunchArgument(
            'wrist_cam_path',
            default_value='',
            description='wrist camera device path; empty = YAML default',
        ),
        DeclareLaunchArgument(
            'vlm_host',
            default_value='',
            description='Ollama VLM server address; empty = YAML default',
        ),
        Node(
            package='single_arm_controller',
            executable='waiter',
            name='waiter',
            output='screen',
            parameters=[{
                'config_path':      ParameterValue(LaunchConfiguration('config_path'),      value_type=str),
                'top_cam_path':     ParameterValue(LaunchConfiguration('top_cam_path'),     value_type=str),
                'wrist_cam_path':   ParameterValue(LaunchConfiguration('wrist_cam_path'),   value_type=str),
                'vlm_host':         ParameterValue(LaunchConfiguration('vlm_host'),         value_type=str),
            }],
        ),
    ])
