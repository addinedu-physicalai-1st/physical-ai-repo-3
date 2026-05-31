"""Compatibility wrapper for the mobility-owned guiding mode stack."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument('params_json', default_value='')
    persons_topic_arg = DeclareLaunchArgument(
        'persons_topic', default_value='/robot_cam/persons')

    mobility_launch = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'launch',
        'mode_guiding.launch.py',
    ])

    return LaunchDescription([
        params_arg,
        persons_topic_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(mobility_launch),
            launch_arguments={
                'params_json': LaunchConfiguration('params_json'),
                'persons_topic': LaunchConfiguration('persons_topic'),
            }.items(),
        ),
    ])
