"""mode_follow.launch.py — 팔로우 모드 stack (실 구현).

mode_manager 가 SetMode("follow", {...}) 요청 시 spawn. RPi v4l2_camera_node
(`scripts/run_robot_cam.sh`) 가 별도로 띄워져 있어야 `/robot_cam/image_raw` 가
들어옴. /scan 은 vicpinky_bringup 이 발행.

노드 구성:
  - person_detector   (dobi_npc_emotion):  /robot_cam/image_raw → /robot_cam/persons
  - follow_controller (mobility_controller):  /robot_cam/persons + /scan + /rapport/event
                                            → /cmd_vel

launch 인자:
  params_json: SetMode 서비스로 전달받은 JSON params 그대로 (예: '{"target":"owner"}').
               현 구현은 가장 큰 person bbox 추적이라 target 식별자 미사용. face id
               등으로 확장 시 follow_controller 파라미터로 매핑 (후속).
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

    # JSON 문자열을 그대로 받기 위해 value_type=str 강제 (ros2 launch 가
    # `{...}` 보면 dict 자동 파싱 시도 → "Got dict for params_json" 에러).
    return LaunchDescription([
        params_arg,
        Node(
            package='dobi_npc_emotion', executable='person_detector',
            name='person_detector', output='screen',
            parameters=[{
                # 2026-05-09: input_topic /image_raw 로 변경 (usb_cam 통합 운영).
                # run_teleop_ui.sh 의 usb_cam 이 /image_raw 발행 → v4l2 device 충돌 회피.
                'input_topic': '/image_raw',
                # 카메라 320x240 @ 10fps + Wi-Fi compressed drop 환경에서
                # 검출 빈도 ↑ 위해 score 낮추고 detect_rate 카메라보다 약간 높게.
                'score_threshold': 0.3,
                'detect_rate_hz': 15.0,
            }],
        ),
        Node(
            package='mobility_controller', executable='follow_controller',
            name='follow_controller', output='screen',
            parameters=[{
                # 2026-05-09: 0.9m follow (사용자 결정). STOP zone 0.7m 와 충돌 회피.
                # 0.3 ≈ 1m / 0.5 ≈ 50cm 회고 기반 → 0.33 ≈ 0.9m. 라이브 튜닝 미세 조정 가능.
                'target_height_ratio': 0.33,
                # 카메라 image 사이즈와 일치 필수. 안 맞으면 err_angle/err_dist
                # 부호/스케일 모두 깨짐 → 직진 차단.
                # 2026-05-07: abko FHD1080p 지원 사이즈 (640x360, 640x480, 1024x768,
                # 1152x864, 1280x720, 1280x1024, 1920x1080). 320x240 미지원 →
                # v4l2 fallback. 5G AP 이동 후 bandwidth ↓ 위해 640x360 으로 ↓
                # (Wi-Fi 부담 25% 절감 + abko 지원 사이즈).
                'image_width': 640,
                'image_height': 360,
                # vicpinky 섀시 마스킹 0.25 + 마진 0.05. 0.45 는 라이다 jitter
                # 와 너무 빠듯해 매 tick 자주 trigger. follow 가드 빈도 ↓.
                'scan_stop_dist': 0.30,
                # 2026-05-18 라이브 튜닝:
                # - kp_angular 1.2→0.5 (흔들림 감소), align_gate 0.10→0.0 (회전+전진 동시)
                # - angle_smoothing_alpha 0.2→0.4, angle_deadband 0.10→0.15
                # - dist_deadband 0.05→0.02 (EMA 리셋 후 빠른 수렴)
                'kp_angular': 0.5,
                'max_angular': 0.6,
                'align_gate': 0.0,
                'angle_smoothing_alpha': 0.4,
                'angle_deadband': 0.15,
                # 2026-05-18: 라이다 거리 기반 제어로 변경.
                # err_dist = scan_front - target_dist → 양수=전진, 음수=후진. kp_linear 양수.
                'kp_linear': 0.8,
                'max_linear': 0.4,
                'dist_deadband': 0.02,
                'target_dist': 0.30,  # 유지할 거리 (m), 라이브 튜닝 가능
                # mode_manager가 던진 JSON은 현 구현에 미사용 — 단순 reflect 위해 보관.
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
            }],
        ),
    ])
