"""mode_follow.launch.py — 팔로우 모드 stack (실 구현).

mode_manager 가 SetMode("follow", {...}) 요청 시 spawn. RPi v4l2_camera_node
(`scripts/run_robot_cam.sh`) 가 별도로 띄워져 있어야 `/robot_cam/image_raw` 가
들어옴. /scan 은 vicpinky_bringup 이 발행.

노드 구성 (2026-05-26 갱신):
  - person_detector        (dobi_npc_emotion):  /robot_cam/image_raw → /robot_cam/persons
  - customer_identity_node (dobi_npc_identity): /robot_cam/image_raw + /person_tracking/tracks
                                                → /customer/registry (customer_id + track_id)
  - target_selector        (dobi_npc_bringup):  /emotion/state + /customer/registry
                                                → /follow/target (customer_id 자동 선택)
  - follow_controller      (dobi_npc_bringup):  /follow/target + /person_tracking/tracks
                                                + /scan + /rapport/event
                                                → /follow/cmd_vel

추종 흐름:
  GEVA → /emotion/state (valence + track_id)
       → target_selector → /follow/target (customer_id)
       → follow_controller → /follow/cmd_vel
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='SetMode 서비스로 받은 JSON params 그대로')

    return LaunchDescription([
        params_arg,

        # 사람 감지 (bbox → /robot_cam/persons)
        Node(
            package='dobi_npc_emotion', executable='person_detector',
            name='person_detector', output='screen',
            parameters=[{
                'input_topic': '/robot_cam/image_raw',
                'use_compressed': True,
                'score_threshold': 0.3,
                'detect_rate_hz': 15.0,
            }],
        ),

        # 얼굴 ReID → customer_id 부여 (/customer/registry)
        Node(
            package='dobi_npc_identity', executable='customer_identity_node',
            name='customer_identity_node', output='screen',
            parameters=[{
                'image_topic': '/robot_cam/image_raw',
                'match_threshold': 0.5,
            }],
        ),

        # 감정 분석 결과 → 추종 대상 customer_id 자동 선택 (/follow/target)
        Node(
            package='dobi_npc_bringup', executable='target_selector',
            name='target_selector_node', output='screen',
            parameters=[{
                # valence 이 값 이상이면 추종 대상 선택
                'valence_threshold': 0.3,
                # 선택 후 lock 시간 (흔들림 방지)
                'lock_duration_sec': 5.0,
            }],
        ),

        # 추종 제어 (/follow/cmd_vel)
        Node(
            package='dobi_npc_bringup', executable='follow_controller',
            name='follow_controller', output='screen',
            parameters=[{
                'target_height_ratio': 0.33,
                'image_width': 640,
                'image_height': 360,
                'scan_stop_dist': 0.30,
                'kp_angular': 0.5,
                'max_angular': 0.6,
                'align_gate': 0.0,
                'angle_smoothing_alpha': 0.4,
                'angle_deadband': 0.15,
                'kp_linear': 0.8,
                'max_linear': 0.4,
                'dist_deadband': 0.02,
                'target_dist': 0.30,
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
            }],
        ),
    ])
