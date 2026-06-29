from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    action_name = LaunchConfiguration("action_name")
    command_timeout_sec = LaunchConfiguration("command_timeout_sec")
    hotdog_use_sim_time = LaunchConfiguration("hotdog_use_sim_time")

    return LaunchDescription([
        DeclareLaunchArgument(
            "action_name",
            default_value="ddooby/manifacture",
            description="Manifacture action name used by moca_service",
        ),
        DeclareLaunchArgument(
            "command_timeout_sec",
            default_value="0.0",
            description="Per manufacture task timeout. 0 disables the timeout.",
        ),
        DeclareLaunchArgument(
            "hotdog_use_sim_time",
            default_value="true",
            description="Use simulated time for hotdog_making.launch.py. Set false for physical OpenArm.",
        ),
        Node(
            package="ddooby_controller",
            executable="manifacture_action_server_node",
            name="ddooby_manifacture_action_server",
            output="screen",
            parameters=[
                {
                    "action_name": action_name,
                    "command_timeout_sec": command_timeout_sec,
                    "hotdog_use_sim_time": hotdog_use_sim_time,
                }
            ],
        ),
    ])
