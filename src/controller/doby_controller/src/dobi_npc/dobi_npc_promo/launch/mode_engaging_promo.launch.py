"""mode_engaging_promo.launch.py - promo_viewer 단독 launch.

기존 mode_engaging.launch.py 와 함께 실행. 모객 모드 진입 시 별도 spawn.
google-chrome kiosk 풀스크린으로 assets/promo/promo.html 표시. minigame 시작 시
자동 suspend (chrome 종료), minigame 종료 시 자동 resume (chrome respawn).

사용:
  # engaging 모드 stack
  ros2 launch dobi_npc_bringup mode_engaging.launch.py
  # 별 터미널에서 promo viewer
  ros2 launch dobi_npc_promo mode_engaging_promo.launch.py

자동 suspend/resume:
  /minigame/start  -> chrome kill
  /minigame/result -> chrome respawn
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    browser_arg = DeclareLaunchArgument(
        'browser_cmd',
        default_value=EnvironmentVariable(
            'MOCA_PROMO_BROWSER', default_value='google-chrome'),
        description='kiosk browser 명령 (google-chrome / chromium-browser / firefox)')

    kiosk_arg = DeclareLaunchArgument(
        'kiosk',
        default_value='true',
        description='풀스크린 kiosk 모드 (false 시 일반 윈도우)')

    return LaunchDescription([
        browser_arg,
        kiosk_arg,
        Node(
            package='dobi_npc_promo', executable='promo_viewer',
            name='promo_viewer', output='screen',
            parameters=[{
                'browser_cmd': LaunchConfiguration('browser_cmd'),
                'kiosk': LaunchConfiguration('kiosk'),
            }],
        ),
    ])
