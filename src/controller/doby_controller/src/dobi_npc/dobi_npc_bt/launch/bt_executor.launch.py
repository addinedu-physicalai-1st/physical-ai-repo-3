"""
bt_executor.launch.py — Phase 1 W2 (Step A)

dobi_npc_bt의 bt_executor 노드를 표준 launch로 실행.
Step A 변경: bt_xml_path / tick_period_ms 파라미터를 cpp 노드로 전달 활성화.

=== 인자 ===
  xml_file        기본 'cafe_funnel_v1.xml'  — bt_xml/ 안의 BT XML 파일명
  tick_period_ms  기본 100  — BT tick 주기 (ms). 100=10Hz
  log_level       기본 'info'  — DEBUG | INFO | WARN | ERROR

=== 사용 예 ===
  # 기본 (10Hz)
  ros2 launch dobi_npc_bt bt_executor.launch.py

  # 다른 BT XML
  ros2 launch dobi_npc_bt bt_executor.launch.py xml_file:=funnel_v2.xml

  # 5Hz tick
  ros2 launch dobi_npc_bt bt_executor.launch.py tick_period_ms:=200

  # 디버그 로그
  ros2 launch dobi_npc_bt bt_executor.launch.py log_level:=debug

=== Phase 진화 ===
  W2 Step B+: Nav2 bringup launch include
  Phase 2: emotion_monitor 노드 + parameter remapping 추가
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # === 인자 선언 ===
    xml_file_arg = DeclareLaunchArgument(
        'xml_file',
        default_value='cafe_funnel_v1.xml',
        description='BT XML 파일명 (bt_xml/ 안의 파일)'
    )
    tick_period_arg = DeclareLaunchArgument(
        'tick_period_ms',
        default_value='100',
        description='BT tick 주기 (ms). 100=10Hz, 200=5Hz'
    )
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='로그 레벨 (debug, info, warn, error)'
    )

    # === XML 절대경로 substitution ===
    xml_path = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bt'),
        'bt_xml',
        LaunchConfiguration('xml_file'),
    ])

    # === bt_executor 노드 ===
    bt_executor_node = Node(
        package='dobi_npc_bt',
        executable='bt_executor',
        name='bt_executor',
        output='screen',
        emulate_tty=True,  # rclcpp 컬러 로그 유지
        arguments=[
            '--ros-args',
            '--log-level', LaunchConfiguration('log_level'),
        ],
        parameters=[{
            'bt_xml_path': xml_path,
            'tick_period_ms': ParameterValue(
                LaunchConfiguration('tick_period_ms'), value_type=int),
        }],
    )

    return LaunchDescription([
        xml_file_arg,
        tick_period_arg,
        log_level_arg,
        bt_executor_node,
    ])
