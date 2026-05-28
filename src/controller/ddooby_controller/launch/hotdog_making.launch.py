from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    target = LaunchConfiguration("target")
    arm = LaunchConfiguration("arm")
    target_model = LaunchConfiguration("target_model")
    case_target_model = LaunchConfiguration("case_target_model")
    bread_target_model = LaunchConfiguration("bread_target_model")
    sausage_target_model = LaunchConfiguration("sausage_target_model")
    ketchup_target_model = LaunchConfiguration("ketchup_target_model")
    start_from_stage = LaunchConfiguration("start_from_stage")
    stop_after_stage = LaunchConfiguration("stop_after_stage")
    stop_after_waypoint = LaunchConfiguration("stop_after_waypoint")
    gripper_grasp_target = LaunchConfiguration("gripper_grasp_target")
    dry_run = LaunchConfiguration("dry_run")
    use_sim_time = LaunchConfiguration("use_sim_time")

    target_arg = DeclareLaunchArgument(
        "target",
        default_value="bread",
        choices=["bread", "case", "sausage", "ketchup", "hotdog"],
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
    ketchup_target_model_arg = DeclareLaunchArgument(
        "ketchup_target_model",
        default_value="kachup",
        description="World model name used for the ketchup step in target:=hotdog.",
    )
    start_from_stage_arg = DeclareLaunchArgument(
        "start_from_stage",
        default_value="home",
        choices=["home", "pick", "work", "place", "return_home"],
        description="Start execution from this manufacturing stage.",
    )
    stop_after_stage_arg = DeclareLaunchArgument(
        "stop_after_stage",
        default_value="complete",
        choices=["complete", "home", "pick", "work", "place", "return_home"],
        description="Stop after this manufacturing stage. Use complete to run the full task.",
    )
    stop_after_waypoint_arg = DeclareLaunchArgument(
        "stop_after_waypoint",
        default_value="",
        description="Optional task-specific waypoint to stop after, such as pre_grasp, pull_out, aim, or squeeze.",
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
                "ketchup_target_model": ketchup_target_model,
                "start_from_stage": start_from_stage,
                "stop_after_stage": stop_after_stage,
                "stop_after_waypoint": stop_after_waypoint,
                "gripper_grasp_target": gripper_grasp_target,
                "dry_run": dry_run,
                "enable_ketchup_squeeze_gripper": PythonExpression(
                    ["'true' if '", use_sim_time, "' == 'false' else 'false'"]
                ),
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
        ketchup_target_model_arg,
        start_from_stage_arg,
        stop_after_stage_arg,
        stop_after_waypoint_arg,
        gripper_grasp_target_arg,
        dry_run_arg,
        use_sim_time_arg,
        hotdog_making_node,
    ])
