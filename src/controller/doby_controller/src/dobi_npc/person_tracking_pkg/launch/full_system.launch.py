"""전체 시스템: 카메라 + person_tracking_node + group_approach_node."""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory('person_tracking_pkg')

    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_share, 'launch', 'camera.launch.py')
        )
    )

    group_approach = Node(
        package='person_tracking_pkg',
        executable='group_approach_node',
        name='group_approach_node',
        parameters=[{
            'min_group_size': 2,
        }],
    )

    return LaunchDescription([
        camera_launch,
        group_approach,
    ])
