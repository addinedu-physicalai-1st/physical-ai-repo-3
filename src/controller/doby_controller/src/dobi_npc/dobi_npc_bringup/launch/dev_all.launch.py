"""dev_all.launch.py — backward-compat alias.

B 단계에서 dev_common.launch.py(공통 always-on 7 노드) + mode_*.launch.py
(모드별 stack)로 분리됨. 본 파일은 기존 명령(`ros2 launch dobi_npc_bringup
dev_all.launch.py`)을 그대로 쓰던 사용자/스크립트 호환을 위해 dev_common 을
include + 호환 alias 로 유지.

권장:
  - 통합 시동: `ros2 launch dobi_npc_bringup dev_common.launch.py`
                 (mode_manager 가 모드별 stack 을 spawn/kill 하므로 충분)
  - 모드 stack 직접 시동(검증/디버깅): `ros2 launch dobi_npc_bringup mode_npc.launch.py`

A2 시점의 dev_all 은 bt_executor 까지 같이 띄웠으나 B 부터는 mode_manager
가 모드 전환 시 자동 spawn 하므로 공통층만 시동하는 게 정상 운영 흐름.
검증 단계에서 NPC 모드 노드를 즉시 띄우고 싶으면 launch 인자
`initial_mode:=npc` 로 mode_manager 가 시동 시 자동 spawn.
"""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    common_launch = os.path.join(
        get_package_share_directory('dobi_npc_bringup'),
        'launch', 'dev_common.launch.py'
    )
    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(common_launch)),
    ])
