"""dock_perception 노드 런치 -- Astra depth -> 테이블 엣지.

config/dock_perception.yaml 파라미터 로드 + config/gimbal_extrinsic.yaml extrinsic
경로 주입. enable 토픽으로 도킹 단계에서만 동작.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('dobi_dock')
    params = os.path.join(share, 'config', 'dock_perception.yaml')
    extrinsic = os.path.join(share, 'config', 'gimbal_extrinsic.yaml')

    side = DeclareLaunchArgument('docking_side', default_value='left',
                                 description='left / right / front')
    enabled = DeclareLaunchArgument('enabled', default_value='true')

    node = Node(
        package='dobi_dock', executable='dock_perception_node',
        name='dock_perception_node', output='screen',
        parameters=[params, {
            'extrinsic_path': extrinsic,
            'docking_side': LaunchConfiguration('docking_side'),
            'enabled': LaunchConfiguration('enabled'),
        }],
    )
    return LaunchDescription([side, enabled, node])
