"""Compatibility wrapper for the mobility-owned patrol mode stack."""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument('params_json', default_value='')
    image_topic_arg = DeclareLaunchArgument(
        'image_topic', default_value='/camera/image_raw')
    dwell_arg = DeclareLaunchArgument(
        'dwell_per_table_sec', default_value='2.0')
    arrival_timeout_arg = DeclareLaunchArgument(
        'arrival_timeout_sec', default_value='90.0')
    waypoints_arg = DeclareLaunchArgument(
        'waypoints_yaml',
        default_value=os.environ.get('MOCA_WAYPOINTS_YAML', ''))
    scan_map_arg = DeclareLaunchArgument(
        'scan_table_map_json',
        default_value='{"W05": ["T02", "T03"], "W07": ["T04", "T05"]}')
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false')

    mobility_launch = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'launch',
        'mode_patrol.launch.py',
    ])

    return LaunchDescription([
        params_arg,
        image_topic_arg,
        dwell_arg,
        arrival_timeout_arg,
        waypoints_arg,
        scan_map_arg,
        use_sim_time_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(mobility_launch),
            launch_arguments={
                'params_json': LaunchConfiguration('params_json'),
                'image_topic': LaunchConfiguration('image_topic'),
                'dwell_per_table_sec': LaunchConfiguration(
                    'dwell_per_table_sec'),
                'arrival_timeout_sec': LaunchConfiguration(
                    'arrival_timeout_sec'),
                'waypoints_yaml': LaunchConfiguration('waypoints_yaml'),
                'scan_table_map_json': LaunchConfiguration(
                    'scan_table_map_json'),
                'use_sim_time': LaunchConfiguration('use_sim_time'),
            }.items(),
        ),
    ])
