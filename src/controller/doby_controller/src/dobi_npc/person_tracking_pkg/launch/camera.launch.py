"""카메라 + person_tracking_node 실행."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='v4l2_camera',
            executable='v4l2_camera_node',
            name='camera',
            parameters=[{
                'image_size': [1280, 720],
                'camera_frame_id': 'camera_link',
                'video_device': '/dev/video0',
            }],
            remappings=[
                ('image_raw', '/robot_cam/image_raw'),
            ],
        ),
        Node(
            package='person_tracking_pkg',
            executable='person_tracking_node',
            name='person_tracking_node',
            parameters=[{
                'input_topic': '/robot_cam/image_raw',
                'use_compressed': True,
                'publish_visualization': False,
            }],
        ),
    ])
