"""mobility_controller.launch.py — RPi 주행 제어 스택.

RPi(Vic Pinky)에서 실행. 노트북에서 발행된 토픽을 수신해 cmd_vel 발행.

노드 구성 (2026-05-26):
  mobility_controller_node  (C++): /dobi_controller/status 구독 (상태 모니터링)
  approach_controller_node  (Py):  /customer_pose + /person_tracking/approach_target
                                   → /bt/cmd_vel (그룹 접근 PD제어)
  follow_controller_node    (Py):  /person_tracking/tracks + /customer/registry
                                   + /follow/target + /scan + /rapport/event
                                   → /follow/cmd_vel (1인 추종 reactive 제어)

토픽 흐름 (노트북 → RPi):
  노트북 person_tracking_node  → /person_tracking/tracks, /customer_pose
  노트북 customer_identity_node → /customer/registry
  노트북 target_selector_node   → /follow/target
  노트북 rapport_tracker        → /rapport/event
  RPi   RPLiDAR                → /scan
  RPi   approach_controller    → /bt/cmd_vel      (priority 80 in twist_mux)
  RPi   follow_controller      → /follow/cmd_vel  (priority 50 in twist_mux)

전제조건: ROS_DOMAIN_ID=22, 노트북 dev_common.launch.py 실행 중
"""
from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare('mobility_controller'),
        'config',
        'mobility_controller.yaml',
    ])

    return LaunchDescription([
        # C++ 상태 모니터링 노드
        Node(
            package='mobility_controller',
            executable='mobility_controller_node',
            name='mobility_controller',
            output='screen',
            parameters=[config_file],
        ),

        # 그룹 접근 PD제어 → /bt/cmd_vel (priority 80)
        Node(
            package='mobility_controller',
            executable='approach_controller_node',
            name='approach_controller_node',
            output='screen',
            parameters=[{
                'linear_speed':    0.15,
                'angular_gain':    1.8,   # Kp
                'derivative_gain': 0.3,   # Kd
                'ema_alpha':       0.3,
                'dead_zone':       0.05,
                'close_threshold': 0.999,
                'pose_timeout':    1.0,
            }],
        ),

        # 1인 추종 reactive 제어 → /follow/cmd_vel (priority 50)
        Node(
            package='mobility_controller',
            executable='follow_controller_node',
            name='follow_controller',
            output='screen',
            parameters=[{
                'target_height_ratio': 0.33,
                'image_width':  640,
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
            }],
        ),
    ])
