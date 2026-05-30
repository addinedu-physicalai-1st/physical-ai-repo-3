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
    execution_backend = LaunchConfiguration("execution_backend")
    scenario_step_delay_ms = LaunchConfiguration("scenario_step_delay_ms")
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
        DeclareLaunchArgument(
            "execution_backend",
            default_value="temporary_beverage_test",
            description="temporary_beverage_test keeps the current Gazebo beverage backend; scenario_task_nodes runs the hotdog/drink task-node skeletons",
        ),
        DeclareLaunchArgument(
            "scenario_step_delay_ms",
            default_value="150",
            description="Delay between scenario skeleton steps when task-node backend is used",
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
                    "reset_world_on_start": reset_world_on_start,
                    "start_step": start_step,
                    "end_step": end_step,
                    "execution_backend": execution_backend,
                    "scenario_step_delay_ms": scenario_step_delay_ms,
                    "hotdog_use_sim_time": hotdog_use_sim_time,
                }
            ],
        ),
    ])
