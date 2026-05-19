"""mode_patrol.launch.py — 순회(patrol) 모드 stack (M2 실 구현).

mode_manager 가 SetMode("patrol", params) 요청 시 spawn.
Nav2 (moca_navigation/vicpinky_navigation) 는 별도 가동 가정 (RPi 또는 시뮬).

설계 SoT: docs/moca_patrol_design.md §4.

노드 구성:
  - table_occupancy_detector (먼저, 서비스 ready 보장):
      /camera/image_raw 구독 + /table_occupancy/scan 서비스
      YOLO ultralytics 가 미설치면 unknown 응답 모드 (degrade gracefully).

  - patrol_scheduler (실제 mobility):
      tables.yaml load → sweep_order 순회 → Nav2 NavigateToPose → dwell 2s
      → ScanTable 호출 → TableReport 발행. 사이클 종료 후 home 복귀 + DONE.

launch 인자:
  params_json: SetMode 가 전달한 JSON params (예: '{"sweep_mode":"all"}')
               sweep_order override 도 지원 ('{"sweep_order":["T03","T01"]}')
  image_topic: detector 가 구독할 카메라 토픽 (기본 /camera/image_raw)
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
        description='SetMode 가 전달한 JSON params (sweep_mode / sweep_order)')
    image_topic_arg = DeclareLaunchArgument(
        'image_topic', default_value='/camera/image_raw',
        description='detector 가 구독할 RGB 카메라 토픽')
    dwell_arg = DeclareLaunchArgument(
        'dwell_per_table_sec', default_value='2.0',
        description='각 테이블 도착 후 분석 대기 시간 (sec)')
    arrival_timeout_arg = DeclareLaunchArgument(
        'arrival_timeout_sec', default_value='30.0',
        description='Nav2 단일 goal 타임아웃 (sec)')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        image_topic_arg,
        dwell_arg,
        arrival_timeout_arg,
        # 1) detector 먼저 spawn — patrol_scheduler 가 서비스 wait_for_service 시점 보장
        Node(
            package='dobi_npc_bringup',
            executable='table_occupancy_detector',
            name='table_occupancy_detector',
            output='screen',
            parameters=[{
                # yolo_weights_path 는 노드 default 가 workspace 추정 (env MOCA_YOLO_WEIGHTS
                # 또는 models/yolo/yolov8n.pt). 명시 override 필요 시 여기서 추가.
                'confidence_threshold': 0.5,
                'person_class_id': 0,
                'image_topic': LaunchConfiguration('image_topic'),
                'dishes_enabled': False,
                'frame_stale_sec': 2.0,
                'scan_service_name': '/table_occupancy/scan',
            }],
        ),
        # 2) scheduler
        Node(
            package='dobi_npc_bringup',
            executable='patrol_scheduler',
            name='patrol_scheduler',
            output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                # sweep_order: tables.yaml 의 T01~T05 (params_json 으로 override 가능)
                'sweep_order': ['T01', 'T02', 'T03', 'T04', 'T05'],
                'dwell_per_table_sec': ParameterValue(
                    LaunchConfiguration('dwell_per_table_sec'),
                    value_type=float),
                'arrival_timeout_sec': ParameterValue(
                    LaunchConfiguration('arrival_timeout_sec'),
                    value_type=float),
                'inter_table_timeout_sec': 60.0,
                'return_home_after_cycle': True,
                'report_to_opserver': True,
                'scan_service_name': '/table_occupancy/scan',
                'nav_action_name': '/navigate_to_pose',
            }],
        ),
    ])
