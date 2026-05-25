from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    active_step = LaunchConfiguration("active_step")
    target_model = LaunchConfiguration("target_model")
    start_from_stage = LaunchConfiguration("start_from_stage")
    stop_after_stage = LaunchConfiguration("stop_after_stage")
    gripper_grasp_target = LaunchConfiguration("gripper_grasp_target")
    dry_run = LaunchConfiguration("dry_run")

    active_step_arg = DeclareLaunchArgument(
        "active_step",
        default_value="bread_pick",
        choices=["case_pick", "bread_pick"],
        description="Hotdog task step to execute.",
    )
    target_model_arg = DeclareLaunchArgument(
        "target_model",
        default_value="auto",
        description="Manufacturing world model name to pick. Use auto for the active step default.",
    )
    start_from_stage_arg = DeclareLaunchArgument(
        "start_from_stage",
        default_value="home",
        choices=["home", "pre_grasp", "pick", "pull_out", "work", "place", "return_home"],
        description="Start execution from this manufacturing stage.",
    )
    stop_after_stage_arg = DeclareLaunchArgument(
        "stop_after_stage",
        default_value="complete",
        choices=["complete", "home", "pre_grasp", "pick", "pull_out", "work", "place", "return_home"],
        description="Stop after this manufacturing stage. Use complete to run the full task.",
    )
    gripper_grasp_target_arg = DeclareLaunchArgument(
        "gripper_grasp_target",
        default_value="half_closed",
        choices=["half_closed", "closed"],
        description="Fallback named gripper target used when the task preset does not set a joint position.",
    )
    dry_run_arg = DeclareLaunchArgument(
        "dry_run",
        default_value="false",
        choices=["true", "false"],
        description="Compute the target grasp plan without constructing MoveIt interfaces.",
    )

    moveit_config = MoveItConfigsBuilder(
        "openarm", package_name="openarm_bimanual_moveit_config"
    ).to_moveit_configs()

    hotdog_making_node = Node(
        package="ddooby_controller",
        executable="hotdog_making_node",
        name="ddooby_hotdog_making",
        output="screen",
        parameters=[
            moveit_config.to_dict(),
            {
                "use_sim_time": True,
                "scenario_only": False,
                "active_step": active_step,
                "target_model": target_model,
                "start_from_stage": start_from_stage,
                "stop_after_stage": stop_after_stage,
                "gripper_grasp_target": gripper_grasp_target,
                "dry_run": dry_run,
            },
        ],
    )

    return LaunchDescription([
        active_step_arg,
        target_model_arg,
        start_from_stage_arg,
        stop_after_stage_arg,
        gripper_grasp_target_arg,
        dry_run_arg,
        hotdog_making_node,
    ])
