"""mode_npc.launch.py — DEPRECATED.

★ 본 launch 는 2026-05-16 5-state FSM 확장으로 deprecated.
   mode_npc → mode_engaging 리네이밍. M3 종료 2026-07-04 후 제거 예정.

mode_manager 가 SetMode("npc") 를 받으면 LEGACY_MODE_ALIAS 에 의해 자동으로
"engaging" 으로 변환되어 mode_engaging.launch.py 가 spawn 된다 (mode_manager_node.py
의 _on_request 참조). 따라서 정상 동작 경로에서는 본 wrapper 가 직접 호출되지
않지만, 외부 도구가 launch 파일명을 직접 호출하는 경우를 대비해 IncludeLaunchDescription
으로 mode_engaging.launch.py 위임.
"""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    engaging_launch = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'),
        'launch',
        'mode_engaging.launch.py',
    ])
    return LaunchDescription([
        LogInfo(msg=(
            'DEPRECATED: mode_npc.launch.py -> mode_engaging.launch.py '
            'forwarding (M3 종료 2026-07-04 까지만 지원)')),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(engaging_launch),
        ),
    ])
