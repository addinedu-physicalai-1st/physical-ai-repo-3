"""Compatibility wrapper for the mobility-owned serving mode stack."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument('params_json', default_value='')
    dwell_arg = DeclareLaunchArgument('dwell_sec', default_value='5.0')
    return_home_arg = DeclareLaunchArgument(
        'return_home_after_dwell', default_value='true')

    mobility_launch = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'launch',
        'mode_serving.launch.py',
    ])

    return LaunchDescription([
        params_arg,
        dwell_arg,
        return_home_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(mobility_launch),
            launch_arguments={
                'params_json': LaunchConfiguration('params_json'),
                'dwell_sec': LaunchConfiguration('dwell_sec'),
                'return_home_after_dwell': LaunchConfiguration(
                    'return_home_after_dwell'),
            }.items(),
        ),
    ])
