"""mode_serving.launch.py — 서빙 모드 stack (opennav_docking 정밀 주차).

mode_manager 가 SetMode("serving", {"waypoint": "T01"}) 요청 시 spawn.
Nav2 (moca_navigation, docking_server 포함) 가 별도로 가동되어 있어야 함:
  - NavigateToPose action (home 복귀 + 레거시 nav)
  - DockRobot / UndockRobot action (docking_server, 정밀 주차)

노드 구성:
  - serving_dispatcher (dobi_npc_bringup):
      tables.yaml 로드 → DockRobot(staging+정밀접근) → dwell → UndockRobot → 다음/home
      구독 /serving/goto_table, 발행 /serving/state (1Hz)

launch 인자:
  params_json: SetMode 서비스로 받은 JSON params 그대로 (예: '{"waypoint":"T01"}')
  dwell_sec: 도착 후 대기 시간 (기본 5.0)
  return_home_after_dwell: dwell 후 home_pose 자동 복귀 여부 (기본 true)
  enable_docking: 정밀 주차(DockRobot) 사용 여부 (기본 true). false 면 NavigateToPose 단발 폴백.
  dock_type: docking_server 의 dock_plugins 키 (기본 'cafe_table')
  dock_timeout_sec: dispatcher last-resort 안전망 타임아웃 (기본 180.0)

자세한 명세: docs/cafe_npc_serving_mode.md
"""
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
        description='도착 후 대기 시간 (sec)')
    return_home_arg = DeclareLaunchArgument(
        'return_home_after_dwell', default_value='true',
        description='dwell 후 home_pose 자동 복귀 여부')
    enable_docking_arg = DeclareLaunchArgument(
        'enable_docking', default_value='true',
        description='정밀 주차(DockRobot) 사용 여부. false 면 NavigateToPose 단발 폴백')
    dock_type_arg = DeclareLaunchArgument(
        'dock_type', default_value='cafe_table',
        description='docking_server dock_plugins 키')
    dock_timeout_arg = DeclareLaunchArgument(
        'dock_timeout_sec', default_value='180.0',
        description='dispatcher last-resort 안전망 타임아웃 (sec)')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        dwell_arg,
        return_home_arg,
        enable_docking_arg,
        dock_type_arg,
        dock_timeout_arg,
        Node(
            package='dobi_npc_bringup', executable='serving_dispatcher',
            name='serving_dispatcher', output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                # JSON 문자열을 그대로 받기 위해 value_type=str 강제 (ros2 launch 가
                # `{...}` 보면 dict 자동 파싱 시도 → "Got dict for params_json" 에러).
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'dwell_sec': ParameterValue(
                    LaunchConfiguration('dwell_sec'), value_type=float),
                'return_home_after_dwell': ParameterValue(
                    LaunchConfiguration('return_home_after_dwell'), value_type=bool),
                'enable_docking': ParameterValue(
                    LaunchConfiguration('enable_docking'), value_type=bool),
                'dock_type': ParameterValue(
                    LaunchConfiguration('dock_type'), value_type=str),
                'dock_timeout_sec': ParameterValue(
                    LaunchConfiguration('dock_timeout_sec'), value_type=float),
            }],
        ),
    ])
