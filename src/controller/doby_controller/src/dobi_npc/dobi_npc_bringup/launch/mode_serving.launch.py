"""mode_serving.launch.py — 서빙 모드 stack (Phase S-A 실 구현).

mode_manager 가 SetMode("serving", {"waypoint": "T01"}) 요청 시 spawn.
Nav2 (vicpinky_navigation) 가 별도로 가동되어 있어야 NavigateToPose action 가 떠 있음.

노드 구성:
  - serving_dispatcher (dobi_npc_bringup):
      tables.yaml 로드 → Nav2 NavigateToPose action 호출 → dwell → home 복귀
      구독 /serving/goto_table (수동/자동 추가 명령), 발행 /serving/state (1Hz)

launch 인자:
  params_json: SetMode 서비스로 받은 JSON params 그대로 (예: '{"waypoint":"T01"}')
              dispatcher 가 진입 시 첫 명령으로 큐 prepend.
  dwell_sec: 도착 후 대기 시간 (기본 5.0). S-D 호객 trigger 시 별 launch 또는 0 으로.
  return_home_after_dwell: dwell 후 home_pose 자동 복귀 여부 (기본 true).

자세한 명세: docs/cafe_npc_serving_mode.md
"""
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
        description='SetMode 서비스로 받은 JSON params (waypoint 필드가 첫 명령)')
    dwell_arg = DeclareLaunchArgument(
        'dwell_sec', default_value='5.0',
        description='도착 후 대기 시간 (sec) — table 단일 주행 경로에만 적용')
    return_home_arg = DeclareLaunchArgument(
        'return_home_after_dwell', default_value='true',
        description='dwell 후 home_pose 자동 복귀 여부 — table 단일 주행 경로에만 적용')
    # mapv6 웨이포인트 + routes(테이블별 outbound/return) yaml 절대경로.
    # 비우면 route 추종 비활성 (기존 tables.yaml 단일 주행만). 상대경로 규약상 env 우선.
    waypoints_arg = DeclareLaunchArgument(
        'waypoints_yaml',
        default_value=os.environ.get('MOCA_WAYPOINTS_YAML', ''),
        description='mapv6 웨이포인트+경로 yaml 절대경로 (NavigateThroughPoses 경로 추종)')
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='시뮬(Gazebo)에서 true — dispatcher 가 /clock 사용 (Nav2 와 시계 정합)')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        dwell_arg,
        return_home_arg,
        waypoints_arg,
        use_sim_time_arg,
        Node(
            package='dobi_npc_bringup', executable='serving_dispatcher',
            name='serving_dispatcher', output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'waypoints_yaml': ParameterValue(
                    LaunchConfiguration('waypoints_yaml'), value_type=str),
                'use_sim_time': ParameterValue(
                    LaunchConfiguration('use_sim_time'), value_type=bool),
                # JSON 문자열을 그대로 받기 위해 value_type=str 강제 (ros2 launch 가
                # `{...}` 보면 dict 자동 파싱 시도 → "Got dict for params_json" 에러).
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'dwell_sec': ParameterValue(
                    LaunchConfiguration('dwell_sec'), value_type=float),
                'return_home_after_dwell': ParameterValue(
                    LaunchConfiguration('return_home_after_dwell'), value_type=bool),
            }],
        ),
    ])
