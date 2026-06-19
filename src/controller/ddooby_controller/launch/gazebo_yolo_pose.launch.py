from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node


def default_model_path():
    return str(
        Path(get_package_share_directory("ddooby_controller"))
        / "assets"
        / "vision_models"
        / "gazebo_moca_yolov8n_seg.pt"
    )


def generate_launch_description():
    model_path = LaunchConfiguration("model_path")
    target_frame = LaunchConfiguration("target_frame")
    show_debug_view = LaunchConfiguration("show_debug_view")
    process_every_n = LaunchConfiguration("process_every_n")
    enable_layout_matching = LaunchConfiguration("enable_layout_matching")
    layout_match_max_distance = LaunchConfiguration("layout_match_max_distance")
    layout_pose_weight = LaunchConfiguration("layout_pose_weight")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "model_path",
                default_value=default_model_path(),
                description="Ultralytics YOLO-seg model path for Gazebo manufacturing object segmentation.",
            ),
            DeclareLaunchArgument(
                "target_frame",
                default_value="world",
                description="Frame used for published object and grasp-entry poses",
            ),
            DeclareLaunchArgument(
                "show_debug_view",
                default_value="true",
                choices=["true", "false"],
                description="Open an OpenCV window with the annotated camera view",
            ),
            DeclareLaunchArgument(
                "process_every_n",
                default_value="1",
                description="Run YOLO-seg once every N color frames",
            ),
            DeclareLaunchArgument(
                "enable_layout_matching",
                default_value="true",
                choices=["true", "false"],
                description="Match YOLO-seg candidates to known manufacturing layout objects",
            ),
            DeclareLaunchArgument(
                "layout_match_max_distance",
                default_value="0.18",
                description="Maximum candidate-to-layout distance in meters for matching",
            ),
            DeclareLaunchArgument(
                "layout_pose_weight",
                default_value="0.85",
                description="Blend weight for the known layout pose after a candidate is matched",
            ),
            Node(
                package="ddooby_controller",
                executable="gazebo_yolo_pose_node.py",
                name="gazebo_yolo_pose",
                output="screen",
                parameters=[
                    {
                        "model_path": model_path,
                        "target_frame": target_frame,
                        "show_debug_view": show_debug_view,
                        "process_every_n": process_every_n,
                        "enable_layout_matching": enable_layout_matching,
                        "layout_match_max_distance_m": layout_match_max_distance,
                        "layout_pose_weight": layout_pose_weight,
                    }
                ],
            ),
        ]
    )
