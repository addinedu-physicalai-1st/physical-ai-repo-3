from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    detector_backend = LaunchConfiguration("detector_backend")
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
                "detector_backend",
                default_value="hsv",
                choices=["hsv", "yolo"],
                description="Object detector backend. HSV is recommended for color-coded Gazebo objects.",
            ),
            DeclareLaunchArgument(
                "model_path",
                default_value="yolo11n.pt",
                description="Ultralytics YOLO model path. Used only when detector_backend:=yolo.",
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
                description="Run the vision detector once every N color frames",
            ),
            DeclareLaunchArgument(
                "enable_layout_matching",
                default_value="true",
                choices=["true", "false"],
                description="Match raw vision candidates to known manufacturing layout objects",
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
                        "detector_backend": detector_backend,
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
