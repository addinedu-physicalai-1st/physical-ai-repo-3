"""mode_engaging.launch.py — 모객(engaging) 모드 stack.

mode_manager 가 SetMode("engaging") 요청 시 spawn 하는 launch.
공통 always-on 층(dev_common.launch.py)이 먼저 떠있어야 함.

본 파일은 기존 mode_npc.launch.py 의 리네이밍 (2026-05-16 5-state FSM 확장).
내부 노드(bt_executor + minigame_runner)는 그대로 유지 — 호객 BT 로직은
cafe_funnel_v1.xml 그대로 재사용. legacy 진입점 mode_npc.launch.py 는
deprecation wrapper 로 본 파일을 호출 (M3 종료 2026-07-04 후 제거 예정).

구성:
  bt_executor       (cafe_funnel BT — 모객 funnel 6단계 진행)
  minigame_runner   (Phase 3 미니게임 dispatcher — /minigame/start String 수신 시
                     game_id 별 game.py subprocess 실행)
                     registry: rps, speed_counter, cafe_ninja
                     game_camera_index: 카메라 3 (노트북 외장 RPC-20F)

bt_executor 는 다음을 사용:
  - /rapport/event (구독, EmotionMonitor)
  - /battery_state (구독, SafetyCheck)
  - /customer_pose (구독, Approach)
  - /dialog/request (발행, IceBreak/Minigame/Offer/LeadIn)
  - /dialog/utter_done (구독, utter_action_base 동기화)
  - /navigate_to_pose (액션 client, Approach)
  - /minigame/start (발행, std_msgs/String game_type, Minigame phase 2)
  - /minigame/result (구독, MinigameResult, Minigame phase 2)

minigame_runner 는 idle 시 자원 부담 없음 (게임 시작 시 subprocess init).
engaging 모드 stack 에 두는 이유: 다른 모드 (serving/patrol/guiding) 에서는 미사용.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterValue


def generate_launch_description():
    # 카메라 3 (노트북 외장 RPC-20F) 인덱스. /dev/video2 가 일반적이나
    # 환경마다 다르므로 launch arg 로 노출. GEVA 는 카메라 1 (내장, 0).
    # sim 환경 (외장 캠 미연결) 에선 MOCA_GAME_CAMERA_INDEX=0 으로 override.
    game_camera_index_arg = DeclareLaunchArgument(
        'game_camera_index',
        default_value=EnvironmentVariable(
            'MOCA_GAME_CAMERA_INDEX', default_value='2'),
        description='미니게임이 사용할 cv2.VideoCapture 인덱스 (카메라 3, 외장). '
                    'env MOCA_GAME_CAMERA_INDEX 로 default override 가능 (sim=0).')

    return LaunchDescription([
        game_camera_index_arg,
        Node(
            package='dobi_npc_bt', executable='bt_executor',
            name='bt_executor', output='screen',
        ),
        Node(
            package='dobi_npc_minigame', executable='minigame_runner',
            name='minigame_runner', output='screen',
            parameters=[{
                'game_camera_index': ParameterValue(
                    LaunchConfiguration('game_camera_index'),
                    value_type=int),
            }],
        ),
    ])
