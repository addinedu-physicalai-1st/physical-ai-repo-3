from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    device = LaunchConfiguration("device")
    profile = LaunchConfiguration("profile")
    width = LaunchConfiguration("width")
    height = LaunchConfiguration("height")
    fps = LaunchConfiguration("fps")
    show_debug_view = LaunchConfiguration("show_debug_view")
    publish_debug_image = LaunchConfiguration("publish_debug_image")
    process_every_n = LaunchConfiguration("process_every_n")
    max_window_width = LaunchConfiguration("max_window_width")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "device",
                default_value="auto",
                description="RealSense RGB V4L device. Use auto, /dev/video6, or /dev/v4l/by-id/...video-index0.",
            ),
            DeclareLaunchArgument(
                "profile",
                default_value="realsense",
                choices=["realsense", "gazebo"],
                description="HSV threshold profile.",
            ),
            DeclareLaunchArgument("width", default_value="1280"),
            DeclareLaunchArgument("height", default_value="720"),
            DeclareLaunchArgument("fps", default_value="30"),
            DeclareLaunchArgument(
                "show_debug_view",
                default_value="true",
                choices=["true", "false"],
                description="Open the OpenCV annotated camera view.",
            ),
            DeclareLaunchArgument(
                "publish_debug_image",
                default_value="true",
                choices=["true", "false"],
                description="Publish the annotated image on /manufacturing_vision/debug_image.",
            ),
            DeclareLaunchArgument(
                "process_every_n",
                default_value="1",
                description="Run detection once every N frames.",
            ),
            DeclareLaunchArgument(
                "max_window_width",
                default_value="1280",
                description="Resize only the displayed OpenCV window when it is wider than this.",
            ),
            Node(
                package="ddooby_controller",
                executable="realsense_hsv_preview.py",
                name="realsense_hsv_preview",
                output="screen",
                parameters=[
                    {
                        "device": device,
                        "profile": profile,
                        "width": width,
                        "height": height,
                        "fps": fps,
                        "show_debug_view": show_debug_view,
                        "publish_debug_image": publish_debug_image,
                        "process_every_n": process_every_n,
                        "max_window_width": max_window_width,
                    }
                ],
            ),
        ]
    )
