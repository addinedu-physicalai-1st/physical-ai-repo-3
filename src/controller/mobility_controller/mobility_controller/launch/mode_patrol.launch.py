"""mode_patrol.launch.py - patrol mode mobility stack."""

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
        description='SetMode params JSON. sweep_order overrides are supported')
    image_topic_arg = DeclareLaunchArgument(
        'image_topic', default_value='/camera/image_raw',
        description='RGB camera topic for table occupancy detection')
    dwell_arg = DeclareLaunchArgument(
        'dwell_per_table_sec', default_value='2.0',
        description='Dwell time at scan stops')
    arrival_timeout_arg = DeclareLaunchArgument(
        'arrival_timeout_sec', default_value='90.0',
        description='Nav2 per-goal timeout')
    waypoints_arg = DeclareLaunchArgument(
        'waypoints_yaml',
        default_value=os.environ.get('MOCA_WAYPOINTS_YAML', ''),
        description='mapv6 waypoint yaml. Empty falls back to tables.yaml')
    scan_map_arg = DeclareLaunchArgument(
        'scan_table_map_json',
        default_value='{"W05": ["T02", "T03"], "W07": ["T04", "T05"]}',
        description='Waypoint to table scan mapping')
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Use /clock in Gazebo simulation')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        image_topic_arg,
        dwell_arg,
        arrival_timeout_arg,
        waypoints_arg,
        scan_map_arg,
        use_sim_time_arg,
        Node(
            package='mobility_controller',
            executable='table_occupancy_detector',
            name='table_occupancy_detector',
            output='screen',
            parameters=[{
                'confidence_threshold': 0.5,
                'person_class_id': 0,
                'image_topic': LaunchConfiguration('image_topic'),
                'dishes_enabled': False,
                'frame_stale_sec': 2.0,
                'scan_service_name': '/table_occupancy/scan',
                'use_sim_time': ParameterValue(
                    LaunchConfiguration('use_sim_time'), value_type=bool),
            }],
        ),
        Node(
            package='mobility_controller',
            executable='patrol_scheduler',
            name='patrol_scheduler',
            output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'waypoints_yaml': ParameterValue(
                    LaunchConfiguration('waypoints_yaml'), value_type=str),
                'scan_table_map_json': ParameterValue(
                    LaunchConfiguration('scan_table_map_json'), value_type=str),
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'sweep_order': ['W01', 'W02', 'W03', 'W04', 'W05', 'W06',
                                'W07', 'W08', 'W09', 'W10', 'W11', 'W12'],
                'dwell_per_table_sec': ParameterValue(
                    LaunchConfiguration('dwell_per_table_sec'),
                    value_type=float),
                'arrival_timeout_sec': ParameterValue(
                    LaunchConfiguration('arrival_timeout_sec'),
                    value_type=float),
                'inter_table_timeout_sec': 60.0,
                'return_home_after_cycle': True,
                'report_to_orchestrator': True,
                'scan_service_name': '/table_occupancy/scan',
                'nav_action_name': '/navigate_to_pose',
                'use_sim_time': ParameterValue(
                    LaunchConfiguration('use_sim_time'), value_type=bool),
            }],
        ),
    ])
