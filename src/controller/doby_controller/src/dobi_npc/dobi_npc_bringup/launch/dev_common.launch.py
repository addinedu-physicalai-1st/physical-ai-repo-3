"""dev_common.launch.py — 공통 always-on 층 (B 단계).

mode_manager 가 모드별 stack 을 spawn/kill 할 때 살아있어야 하는 노드들.
모드와 무관하게 항상 켜져 있는 인지/표현/오케스트레이션 10 노드.

구성:
  geva_node                 (웹캠 → /emotion/state)
  rapport_tracker           (/emotion/state → /rapport/event)
  persona_manager           (/dialog/request → /dialog/router_in)
  dialog_router             (/dialog/router_in → /dialog/utter)
  face_avatar               (/face_avatar/expression → 풀스크린/윈도우 GIF 표시)
  tts_node                  (/dialog/utter → 음성 출력)
  mode_manager              (/mode/request, /mode/state, mode stack spawn/kill)
  person_tracking_node      (/robot_cam/image_raw → /person_tracking/tracks)
  group_approach_node       (/person_tracking/tracks → /person_tracking/approach_target)
  approach_controller_node  (/person_tracking/approach_target → /cmd_vel, bbox 기반 PD 제어)

person_tracking_node 전제: run_robot_cam.sh 로 /robot_cam/image_raw 가 발행 중이어야 함.

mode_manager 가 spawn 하는 모드별 stack 은 별도 launch:
  mode_npc.launch.py       (bt_executor)
  mode_serving.launch.py   (stub)
  mode_guiding.launch.py   (Nav2 + guiding_controller, M1 임시 follow stack 재사용)
  mode_follow.launch.py    (follow_controller — LiDAR 거리 기반)

launch 인자:
  fullscreen:=true|false   face_avatar 풀스크린 (기본 false)
  default_persona:=...     persona_manager 기본 페르소나 (기본 casual_browser)
  initial_mode:=idle|serving|patrol|guiding|engaging|follow   mode_manager 초기 모드 (기본 idle)
                                                              legacy npc 도 자동 변환 지원 (M3 종료까지)

검증 시동: ros2 launch dobi_npc_bringup dev_common.launch.py
운영자 패널: bash scripts/run_operator_ui.sh (워크스페이스 루트에서, 별 터미널)
모드 전환: 운영자 패널 또는 ros2 service call /mode/request
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    fullscreen_arg = DeclareLaunchArgument(
        'fullscreen', default_value='false',
        description='face_avatar 풀스크린 여부 (검증엔 false 권장)')
    persona_arg = DeclareLaunchArgument(
        'default_persona', default_value='casual_browser',
        description='persona_manager 기본 페르소나')
    initial_mode_arg = DeclareLaunchArgument(
        'initial_mode', default_value='idle',
        description='mode_manager 초기 모드 (idle|serving|patrol|guiding|engaging|follow)')

    return LaunchDescription([
        fullscreen_arg,
        persona_arg,
        initial_mode_arg,

        Node(
            package='dobi_npc_emotion', executable='geva_node',
            name='geva_node', output='screen',
        ),
        Node(
            package='dobi_npc_emotion', executable='rapport_tracker',
            name='rapport_tracker_node', output='screen',
        ),
        Node(
            package='dobi_npc_dialog', executable='persona_manager',
            name='persona_manager', output='screen',
            parameters=[{'default_persona': LaunchConfiguration('default_persona')}],
        ),
        Node(
            package='dobi_npc_dialog', executable='dialog_router',
            name='dialog_router', output='screen',
        ),
        Node(
            package='dobi_npc_dialog', executable='face_avatar',
            name='face_avatar_node', output='screen',
            parameters=[{
                'fullscreen': LaunchConfiguration('fullscreen'),
                'window_width': 800,
                'window_height': 600,
            }],
        ),
        Node(
            package='dobi_npc_dialog', executable='tts_node',
            name='tts_node', output='screen',
        ),
        Node(
            package='dobi_npc_bringup', executable='mode_manager',
            name='mode_manager', output='screen',
            parameters=[{'initial_mode': LaunchConfiguration('initial_mode')}],
        ),
        Node(
            package='person_tracking_pkg', executable='person_tracking_node',
            name='person_tracking_node', output='screen',
            parameters=[{
                'input_topic': '/robot_cam/image_raw',
                'use_compressed': True,
                'publish_visualization': True,
                'dbscan_eps': 50.0,   # [멀티그룹 테스트용] 프린트 분리 — 실물 시 450.0으로 원복
            }],
        ),
        Node(
            package='person_tracking_pkg', executable='group_approach_node',
            name='group_approach_node', output='screen',
            parameters=[{
                'min_group_size': 1,
            }],
        ),
        Node(
            package='person_tracking_pkg', executable='approach_controller_node',
            name='approach_controller_node', output='screen',
            parameters=[{
                'linear_speed':    0.15,
                'angular_gain':    1.8,   # Kp
                'derivative_gain': 0.3,   # Kd
                'ema_alpha':       0.3,   # D항 노이즈 필터 (작을수록 강한 필터)
                'dead_zone':       0.05,
                'close_threshold': 0.999,  # bbox 높이 비율 기준 (0~1, 클수록 가까움)
                'pose_timeout':    1.0,
            }],
        ),
    ])
