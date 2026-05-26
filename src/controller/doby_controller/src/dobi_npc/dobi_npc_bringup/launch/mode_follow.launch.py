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

follow_controller 는 RPi mobility_controller.launch.py 로 이관 (2026-05-26).
  /follow/target 을 mobility_controller 의 follow_controller 가 직접 수신.

추종 흐름:
  GEVA → /emotion/state (valence + track_id)
       → target_selector → /follow/target (customer_id)
       → [RPi] follow_controller → /follow/cmd_vel
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([

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
        # follow_controller → RPi mobility_controller.launch.py 로 이관 (2026-05-26)
    ])
