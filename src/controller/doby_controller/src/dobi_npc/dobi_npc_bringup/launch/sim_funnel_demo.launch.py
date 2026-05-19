"""sim_funnel_demo.launch.py — 노트북 단독 풀 funnel 시뮬 데모.

vicpinky 없이 IceBreak -> Minigame(rotate) -> Offer -> LeadIn(시뮬) 한 cycle
을 영상으로 찍을 수 있는 단일 launch. mode_manager 가 시동 즉시 NPC 모드 stack
(bt_executor + minigame_runner) 을 spawn.

전제:
  - 카메라 1 (노트북 내장, /dev/video0): GEVA 가 점유
  - 카메라 3 (노트북 외장 RPC-20F, 보통 /dev/video2): 미니게임이 점유
  - 인터넷 (edge-tts)
  - 모델 자산: scripts/download_models.sh 1회 실행 (face_landmarker)

흐름 (한 cycle, ~30~50초):
  IdleScan stub                                      <1s
  Approach (Nav2 미연결 → fallback SUCCESS)           <1s
  IceBreak  → minigame_invite phrase 발화             ~3s
  Minigame  → 게임 풀스크린 (cycle 마다 rotate)         ~12~30s
            → minigame_win|minigame_lose phrase 발화  ~3s
  Offer     → offer phrase 발화                       ~3s
  LeadIn    → leadin 발화 + 시뮬 진행 + leadin_arrived ~6+6 = 12s

함정:
  - face_avatar 풀스크린 + 게임 풀스크린이 같은 모니터 점유. 게임 시작 시
    /face_avatar/suspend 보내 검정 양보 → 게임 진행 → resume.
  - GEVA / 게임 카메라 분리 (2026-05-06): 게임 중에도 GEVA 가동되어
    Salichs abort_trigger 정상 작동. 단일 카메라로 회귀할 일이 생기면
    git history 의 /geva/suspend|resume 흐름 (~2026-05-05) 복원.

권장 시동:
  ros2 launch dobi_npc_bringup sim_funnel_demo.launch.py
  (Ctrl-C 로 종료. cycle 끝나도 BT 가 자동 다시 시작 — 한 cycle 데모 후 종료.)
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    fullscreen_arg = DeclareLaunchArgument(
        'fullscreen', default_value='true',
        description='face_avatar/RPS 풀스크린 (시연 기본 true)')
    persona_arg = DeclareLaunchArgument(
        'default_persona', default_value='casual_browser',
        description='persona_manager 기본 페르소나')

    common_launch = os.path.join(
        get_package_share_directory('dobi_npc_bringup'),
        'launch', 'dev_common.launch.py'
    )

    return LaunchDescription([
        fullscreen_arg,
        persona_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(common_launch),
            launch_arguments={
                'fullscreen': LaunchConfiguration('fullscreen'),
                'default_persona': LaunchConfiguration('default_persona'),
                'initial_mode': 'npc',
            }.items(),
        ),
    ])
