from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    action_name = LaunchConfiguration("action_name")
    command_timeout_sec = LaunchConfiguration("command_timeout_sec")
    reset_world_on_start = LaunchConfiguration("reset_world_on_start")
    start_step = LaunchConfiguration("start_step")
    end_step = LaunchConfiguration("end_step")

    return LaunchDescription([
        DeclareLaunchArgument(
            "action_name",
            default_value="ddooby/manifacture",
            description="Manifacture action name used by moca_service",
        ),
        DeclareLaunchArgument(
            "command_timeout_sec",
            default_value="0.0",
            description="Per beverage test run timeout. 0 disables the timeout.",
        ),
        DeclareLaunchArgument(
            "reset_world_on_start",
            default_value="true",
            description="Reset Gazebo beverage objects before every beverage test run",
        ),
        DeclareLaunchArgument(
            "start_step",
            default_value="",
            description="Optional first primitive step passed to beverage_making_test.launch.py",
        ),
        DeclareLaunchArgument(
            "end_step",
            default_value="",
            description="Optional last primitive step passed to beverage_making_test.launch.py",
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
                    "reset_world_on_start": reset_world_on_start,
                    "start_step": start_step,
                    "end_step": end_step,
                }
            ],
        ),
    ])
