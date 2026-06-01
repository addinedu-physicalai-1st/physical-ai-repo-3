"""mode_serving.launch.py - serving mode mobility stack."""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='SetMode params JSON. waypoint becomes the first command')
    dwell_arg = DeclareLaunchArgument(
        'dwell_sec', default_value='5.0',
        description='Dwell time for legacy single-table navigation')
    return_home_arg = DeclareLaunchArgument(
        'return_home_after_dwell', default_value='true',
        description='Return home after legacy single-table dwell')
    waypoints_arg = DeclareLaunchArgument(
        'waypoints_yaml',
        default_value=os.environ.get('MOCA_WAYPOINTS_YAML', ''),
        description='mapv6 waypoint/routes yaml. Empty disables route mode')
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Use /clock in Gazebo simulation')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        dwell_arg,
        return_home_arg,
        waypoints_arg,
        use_sim_time_arg,
        Node(
            package='mobility_controller',
            executable='serving_dispatcher',
            name='serving_dispatcher',
            output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'waypoints_yaml': ParameterValue(
                    LaunchConfiguration('waypoints_yaml'), value_type=str),
                'use_sim_time': ParameterValue(
                    LaunchConfiguration('use_sim_time'), value_type=bool),
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'dwell_sec': ParameterValue(
                    LaunchConfiguration('dwell_sec'), value_type=float),
                'return_home_after_dwell': ParameterValue(
                    LaunchConfiguration('return_home_after_dwell'),
                    value_type=bool),
            }],
        ),
    ])
