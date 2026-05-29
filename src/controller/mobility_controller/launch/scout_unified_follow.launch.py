"""scout_unified_follow — person_tracking(@scout 영상) + scout_follow_controller.

scout 스택(scout_cam+scout_servo+call_detector)은 ~/scout_reactor 별 터미널.
person_tracking_pkg(doby_controller) + 본 패키지 모두 source 필요. 동일 ROS_DOMAIN_ID.

토픽 일원화 (방향 (나)): scout_reactor 는 /scout_cam/image_raw 그대로 사용(lock-on 무손상)
하고, scout_image_relay 가 /robot_cam/image_raw[/compressed] 로 미러 → person_tracking 은
팀 표준 토픽명을 구독한다. 통합 모드(팀이 /robot_cam/image_raw 직접 발행)에서는
relay_scout_image:=false 로 relay 를 끈다(이중 발행 방지).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    scout_image = DeclareLaunchArgument(
        'scout_image_topic', default_value='/robot_cam/image_raw',
        description='person_tracking 입력 — 팀 표준 /robot_cam/image_raw 로 통일')
    scout_src_topic = DeclareLaunchArgument(
        'scout_src_topic', default_value='/scout_cam/image_raw',
        description='relay 입력 — scout_reactor 가 발행하는 원본 토픽')
    relay_scout_image = DeclareLaunchArgument(
        'relay_scout_image', default_value='true',
        description='scout→robot_cam relay 가동 여부. 통합 모드(팀이 직접 발행)면 false')
    use_compressed = DeclareLaunchArgument('use_compressed', default_value='true')
    angular_sign = DeclareLaunchArgument(
        'angular_sign', default_value='1',
        description='차체 회전 부호 — 라이브 1회 검증 후 확정')

    scout_relay = Node(
        package='mobility_controller', executable='scout_image_relay',
        name='scout_image_relay', output='screen',
        parameters=[{
            'in_topic': LaunchConfiguration('scout_src_topic'),
            'out_topic': '/robot_cam/image_raw',
        }],
        condition=IfCondition(LaunchConfiguration('relay_scout_image')),
    )

    person_tracking = Node(
        package='person_tracking_pkg', executable='person_tracking_node',
        name='person_tracking_node', output='screen',
        parameters=[{
            'input_topic': LaunchConfiguration('scout_image_topic'),
            'use_compressed': LaunchConfiguration('use_compressed'),
            'publish_visualization': True,
        }],
    )
    controller = Node(
        package='mobility_controller', executable='scout_follow_controller',
        name='scout_follow_controller', output='screen',
        parameters=[{
            'image_width': 640,
            'image_height': 480,
            'angular_sign': LaunchConfiguration('angular_sign'),
            'max_linear': 0.22,           # 직진 속도↑
            'kp_linear': 1.3,             # 좁은 bh 범위에서 전진 반응↑
            'max_angular': 0.3,           # 회전 속도↓ (지그재그 완화)
            'kp_angular': 0.25,           # 회전 게인↓
            'angular_deadband_px': 60.0,  # 중앙 ±60px 는 회전 안 함 → 직진 유지
            'ema_alpha': 0.35,            # 스무딩↑ (cx jitter 완화)
            'target_bh': 0.85,   # ≈2.4m 유지 (scout 세로FOV 실측: 2m=bh1.0, 3m=bh0.77)
            'bh_stop': 0.95,     # bh≥0.95(≈2m 미만) = 너무 가까움 → 전진 0
            'handoff_base_w': 0.0,       # 핸드오프 base 회전 제거(반대회전 방지) — FOLLOW cx 제어가 회전 담당
            'handoff_timeout_sec': 0.5,  # 핸드오프 즉시 통과 → FOLLOW
        }],
    )
    return LaunchDescription([scout_image, scout_src_topic, relay_scout_image,
                              use_compressed, angular_sign,
                              scout_relay, person_tracking, controller])
