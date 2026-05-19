"""opserver.launch.py — moca_opserver 단독 실행.

병행 가동되는 노드 (dev_common.launch.py 의 mode_manager_node 등) 와 동일
ROS_DOMAIN_ID 에서 실행. RPi 라이브 시뮬은 DOMAIN=22, PC 시뮬은 DOMAIN=99.

파라미터는 config/opserver_config.yaml 에서 로드. CLI 로 덮어쓰기 가능:
  ros2 launch moca_opserver opserver.launch.py port:=8801 patrol_enabled:=false

본 launch 는 mode_manager 를 띄우지 않는다 (dev_common 책임). 따라서 단독
실행 시 SetMode 호출이 service unavailable 로 거부될 수 있음 — 정상.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    host_arg = DeclareLaunchArgument(
        'host', default_value='0.0.0.0',
        description='FastAPI bind host')
    port_arg = DeclareLaunchArgument(
        'port', default_value='8800',
        description='FastAPI bind port (REST + WebSocket)')
    config_arg = DeclareLaunchArgument(
        'config_file', default_value=PathJoinSubstitution([
            FindPackageShare('moca_opserver'), 'config', 'opserver_config.yaml']),
        description='opserver config yaml path')

    return LaunchDescription([
        host_arg,
        port_arg,
        config_arg,
        Node(
            package='moca_opserver',
            executable='opserver_node',
            name='moca_opserver',
            output='screen',
            parameters=[
                LaunchConfiguration('config_file'),
                {
                    'host': LaunchConfiguration('host'),
                    'port': LaunchConfiguration('port'),
                },
            ],
        ),
    ])
