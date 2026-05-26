from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.substitutions import TextSubstitution


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'wrist_cam_path',
            default_value='/dev/video6',
            description='wrist camera device path',
        ),
        DeclareLaunchArgument(
            'realsense_serial',
            default_value='943222071539',
            description='RealSense camera serial number',
        ),
        DeclareLaunchArgument(
            'task',
            default_value='pick up cup and place at target zone',
            description='task instruction for SmolVLA inference',
        ),
        DeclareLaunchArgument(
            'vlm_host',
            default_value='http://localhost:11434',
            description='Ollama VLM server address',
        ),
        Node(
            package='single_arm_controller',
            executable='serving',
            name='single_arm_controller',
            output='screen',
            parameters=[{
                'wrist_cam_path':   ParameterValue(LaunchConfiguration('wrist_cam_path'),   value_type=str),
                'realsense_serial': ParameterValue(LaunchConfiguration('realsense_serial'), value_type=str),
                'task':             ParameterValue(LaunchConfiguration('task'),             value_type=str),
                'vlm_host':         ParameterValue(LaunchConfiguration('vlm_host'),         value_type=str),
            }],
        ),
    ])
