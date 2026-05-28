from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    target = LaunchConfiguration("target")
    arm = LaunchConfiguration("arm")
    target_model = LaunchConfiguration("target_model")
    case_target_model = LaunchConfiguration("case_target_model")
    bread_target_model = LaunchConfiguration("bread_target_model")
    sausage_target_model = LaunchConfiguration("sausage_target_model")
    start_from_stage = LaunchConfiguration("start_from_stage")
    stop_after_stage = LaunchConfiguration("stop_after_stage")
    gripper_grasp_target = LaunchConfiguration("gripper_grasp_target")
    dry_run = LaunchConfiguration("dry_run")
    use_sim_time = LaunchConfiguration("use_sim_time")
    max_pre_grasp_xy_error = LaunchConfiguration("max_pre_grasp_xy_error")
    velocity_scaling = LaunchConfiguration("velocity_scaling")
    acceleration_scaling = LaunchConfiguration("acceleration_scaling")
    gripper_velocity_scaling = LaunchConfiguration("gripper_velocity_scaling")
    gripper_acceleration_scaling = LaunchConfiguration("gripper_acceleration_scaling")
    cartesian_min_duration_sec = LaunchConfiguration("cartesian_min_duration_sec")
    pose_min_duration_sec = LaunchConfiguration("pose_min_duration_sec")

    target_arg = DeclareLaunchArgument(
        "target",
        default_value="bread",
        choices=["bread", "case", "sausage", "hotdog"],
        description="Manufacturing target object.",
    )
    arm_arg = DeclareLaunchArgument(
        "arm",
        default_value="auto",
        choices=["auto", "left", "right"],
        description="Arm side to use. Auto maps bread/sausage to left and case to right.",
    )
    target_model_arg = DeclareLaunchArgument(
        "target_model",
        default_value="auto",
        description="Manufacturing world model name to pick. Use auto for the target default.",
    )
    case_target_model_arg = DeclareLaunchArgument(
        "case_target_model",
        default_value="case",
        description="World model name used for the case step in target:=hotdog.",
    )
    bread_target_model_arg = DeclareLaunchArgument(
        "bread_target_model",
        default_value="bread",
        description="World model name used for the bread step in target:=hotdog.",
    )
    sausage_target_model_arg = DeclareLaunchArgument(
        "sausage_target_model",
        default_value="sausage",
        description="World model name used for the sausage step in target:=hotdog.",
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
    use_sim_time_arg = DeclareLaunchArgument(
        "use_sim_time",
        default_value="true",
        choices=["true", "false"],
        description="Use simulated time. Set false for physical OpenArm hardware.",
    )
    max_pre_grasp_xy_error_arg = DeclareLaunchArgument(
        "max_pre_grasp_xy_error",
        default_value="0.035",
        description="Maximum TCP xy error allowed after pre-grasp before continuing to pick.",
    )
    velocity_scaling_arg = DeclareLaunchArgument(
        "velocity_scaling",
        default_value="0.05",
        description="MoveIt arm trajectory max velocity scaling.",
    )
    acceleration_scaling_arg = DeclareLaunchArgument(
        "acceleration_scaling",
        default_value="0.05",
        description="MoveIt arm trajectory max acceleration scaling.",
    )
    gripper_velocity_scaling_arg = DeclareLaunchArgument(
        "gripper_velocity_scaling",
        default_value="0.12",
        description="MoveIt gripper trajectory max velocity scaling.",
    )
    gripper_acceleration_scaling_arg = DeclareLaunchArgument(
        "gripper_acceleration_scaling",
        default_value="0.12",
        description="MoveIt gripper trajectory max acceleration scaling.",
    )
    cartesian_min_duration_sec_arg = DeclareLaunchArgument(
        "cartesian_min_duration_sec",
        default_value="3.5",
        description="Minimum duration applied to Cartesian trajectories.",
    )
    pose_min_duration_sec_arg = DeclareLaunchArgument(
        "pose_min_duration_sec",
        default_value="3.5",
        description="Minimum duration applied to regular MoveIt pose-target trajectories.",
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
                "use_sim_time": use_sim_time,
                "scenario_only": False,
                "target": target,
                "arm": arm,
                "target_model": target_model,
                "case_target_model": case_target_model,
                "bread_target_model": bread_target_model,
                "sausage_target_model": sausage_target_model,
                "start_from_stage": start_from_stage,
                "stop_after_stage": stop_after_stage,
                "gripper_grasp_target": gripper_grasp_target,
                "dry_run": dry_run,
                "max_pre_grasp_xy_error": max_pre_grasp_xy_error,
                "velocity_scaling": velocity_scaling,
                "acceleration_scaling": acceleration_scaling,
                "gripper_velocity_scaling": gripper_velocity_scaling,
                "gripper_acceleration_scaling": gripper_acceleration_scaling,
                "cartesian_min_duration_sec": cartesian_min_duration_sec,
                "pose_min_duration_sec": pose_min_duration_sec,
            },
        ],
    )

    return LaunchDescription([
        target_arg,
        arm_arg,
        target_model_arg,
        case_target_model_arg,
        bread_target_model_arg,
        sausage_target_model_arg,
        start_from_stage_arg,
        stop_after_stage_arg,
        gripper_grasp_target_arg,
        dry_run_arg,
        use_sim_time_arg,
        max_pre_grasp_xy_error_arg,
        velocity_scaling_arg,
        acceleration_scaling_arg,
        gripper_velocity_scaling_arg,
        gripper_acceleration_scaling_arg,
        cartesian_min_duration_sec_arg,
        pose_min_duration_sec_arg,
        hotdog_making_node,
    ])
