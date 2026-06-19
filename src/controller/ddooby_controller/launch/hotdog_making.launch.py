from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    task = LaunchConfiguration("task")
    arm = LaunchConfiguration("arm")
    target_model = LaunchConfiguration("target_model")
    case_target_model = LaunchConfiguration("case_target_model")
    bread_target_model = LaunchConfiguration("bread_target_model")
    sausage_target_model = LaunchConfiguration("sausage_target_model")
    ketchup_target_model = LaunchConfiguration("ketchup_target_model")
    coke_target_model = LaunchConfiguration("coke_target_model")
    coffee_target_model = LaunchConfiguration("coffee_target_model")
    play_to_stage = LaunchConfiguration("play_to_stage")
    start_from_waypoint = LaunchConfiguration("start_from_waypoint")
    play_to_waypoint = LaunchConfiguration("play_to_waypoint")
    gripper_grasp_target = LaunchConfiguration("gripper_grasp_target")
    dry_run = LaunchConfiguration("dry_run")
    enable_vision_pick = LaunchConfiguration("enable_vision_pick")
    vision_detections_topic = LaunchConfiguration("vision_detections_topic")
    vision_pick_timeout_sec = LaunchConfiguration("vision_pick_timeout_sec")
    vision_pick_max_age_sec = LaunchConfiguration("vision_pick_max_age_sec")
    vision_pick_max_distance_m = LaunchConfiguration("vision_pick_max_distance_m")
    vision_pick_min_score = LaunchConfiguration("vision_pick_min_score")
    vision_pick_required = LaunchConfiguration("vision_pick_required")
    vision_pick_use_orientation = LaunchConfiguration("vision_pick_use_orientation")
    vision_pick_min_orientation_extent_ratio = LaunchConfiguration("vision_pick_min_orientation_extent_ratio")
    vision_pick_use_size = LaunchConfiguration("vision_pick_use_size")
    use_sim_time = LaunchConfiguration("use_sim_time")

    task_arg = DeclareLaunchArgument(
        "task",
        default_value="bread",
        choices=["bread", "case", "sausage", "ketchup", "hotdog", "coke", "coffee"],
        description="Manufacturing task to run.",
    )
    arm_arg = DeclareLaunchArgument(
        "arm",
        default_value="auto",
        choices=["auto", "left", "right"],
        description="Deprecated compatibility option. Manufacturing tasks now determine the required arm sequence from task.",
    )
    target_model_arg = DeclareLaunchArgument(
        "target_model",
        default_value="auto",
        description="Manufacturing world model name to pick. Use auto for the task default model.",
    )
    case_target_model_arg = DeclareLaunchArgument(
        "case_target_model",
        default_value="case",
        description="World model name used for the case step in task:=hotdog.",
    )
    bread_target_model_arg = DeclareLaunchArgument(
        "bread_target_model",
        default_value="bread1",
        description="World model name used for the bread step in task:=hotdog.",
    )
    sausage_target_model_arg = DeclareLaunchArgument(
        "sausage_target_model",
        default_value="sausage",
        description="World model name used for the sausage step in task:=hotdog.",
    )
    ketchup_target_model_arg = DeclareLaunchArgument(
        "ketchup_target_model",
        default_value="kachup",
        description="World model name used for the ketchup step in task:=hotdog.",
    )
    coke_target_model_arg = DeclareLaunchArgument(
        "coke_target_model",
        default_value="can_coke",
        description="World model name used for task:=coke.",
    )
    coffee_target_model_arg = DeclareLaunchArgument(
        "coffee_target_model",
        default_value="can_coffee",
        description="World model name used for task:=coffee.",
    )
    play_to_stage_arg = DeclareLaunchArgument(
        "play_to_stage",
        default_value="complete",
        choices=["complete", "home", "pick", "work", "place", "return_home"],
        description="Run until this manufacturing stage. Use complete to run the full task.",
    )
    start_from_waypoint_arg = DeclareLaunchArgument(
        "start_from_waypoint",
        default_value="",
        description="Optional waypoint-style start hint. Stage endpoint names map to the matching stage.",
    )
    play_to_waypoint_arg = DeclareLaunchArgument(
        "play_to_waypoint",
        default_value="",
        description="Optional task-specific waypoint to run until, such as pre_grasp, pull_out, aim, or squeeze.",
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
    enable_vision_pick_arg = DeclareLaunchArgument(
        "enable_vision_pick",
        default_value="false",
        choices=["true", "false"],
        description="Update pick target positions from manufacturing vision detections.",
    )
    vision_detections_topic_arg = DeclareLaunchArgument(
        "vision_detections_topic",
        default_value="/manufacturing_vision/detections",
        description="vision_msgs/Detection3DArray topic used for vision-based pick target updates.",
    )
    vision_pick_timeout_sec_arg = DeclareLaunchArgument(
        "vision_pick_timeout_sec",
        default_value="2.0",
        description="Seconds to wait for a matching vision detection before pick planning.",
    )
    vision_pick_max_age_sec_arg = DeclareLaunchArgument(
        "vision_pick_max_age_sec",
        default_value="2.0",
        description="Maximum accepted age in seconds for vision detections.",
    )
    vision_pick_max_distance_m_arg = DeclareLaunchArgument(
        "vision_pick_max_distance_m",
        default_value="0.15",
        description="Maximum distance from the layout target center for accepting a vision detection. Use <=0 to disable.",
    )
    vision_pick_min_score_arg = DeclareLaunchArgument(
        "vision_pick_min_score",
        default_value="0.25",
        description="Minimum detection confidence for vision-based pick target updates.",
    )
    vision_pick_required_arg = DeclareLaunchArgument(
        "vision_pick_required",
        default_value="false",
        choices=["true", "false"],
        description="Fail the task when no matching vision detection is available.",
    )
    vision_pick_use_orientation_arg = DeclareLaunchArgument(
        "vision_pick_use_orientation",
        default_value="true",
        choices=["true", "false"],
        description="Use detected object principal-axis yaw for pick target orientation when the PCA axis is reliable.",
    )
    vision_pick_min_orientation_extent_ratio_arg = DeclareLaunchArgument(
        "vision_pick_min_orientation_extent_ratio",
        default_value="1.35",
        description="Minimum PCA primary/secondary extent ratio required before applying vision yaw to pick targets.",
    )
    vision_pick_use_size_arg = DeclareLaunchArgument(
        "vision_pick_use_size",
        default_value="false",
        choices=["true", "false"],
        description="Use detected 3D box size for pick target geometry.",
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
                "task": task,
                "arm": arm,
                "target_model": target_model,
                "case_target_model": case_target_model,
                "bread_target_model": bread_target_model,
                "sausage_target_model": sausage_target_model,
                "ketchup_target_model": ketchup_target_model,
                "coke_target_model": coke_target_model,
                "coffee_target_model": coffee_target_model,
                "play_to_stage": play_to_stage,
                "start_from_waypoint": start_from_waypoint,
                "play_to_waypoint": play_to_waypoint,
                "gripper_grasp_target": gripper_grasp_target,
                "dry_run": dry_run,
                "enable_vision_pick": enable_vision_pick,
                "vision_detections_topic": vision_detections_topic,
                "vision_pick_timeout_sec": vision_pick_timeout_sec,
                "vision_pick_max_age_sec": vision_pick_max_age_sec,
                "vision_pick_max_distance_m": vision_pick_max_distance_m,
                "vision_pick_min_score": vision_pick_min_score,
                "vision_pick_required": vision_pick_required,
                "vision_pick_use_orientation": vision_pick_use_orientation,
                "vision_pick_min_orientation_extent_ratio": vision_pick_min_orientation_extent_ratio,
                "vision_pick_use_size": vision_pick_use_size,
                "enable_ketchup_squeeze_gripper": PythonExpression(
                    ["'true' if '", use_sim_time, "' == 'false' else 'false'"]
                ),
            },
        ],
    )

    return LaunchDescription([
        task_arg,
        arm_arg,
        target_model_arg,
        case_target_model_arg,
        bread_target_model_arg,
        sausage_target_model_arg,
        ketchup_target_model_arg,
        coke_target_model_arg,
        coffee_target_model_arg,
        play_to_stage_arg,
        start_from_waypoint_arg,
        play_to_waypoint_arg,
        gripper_grasp_target_arg,
        dry_run_arg,
        enable_vision_pick_arg,
        vision_detections_topic_arg,
        vision_pick_timeout_sec_arg,
        vision_pick_max_age_sec_arg,
        vision_pick_max_distance_m_arg,
        vision_pick_min_score_arg,
        vision_pick_required_arg,
        vision_pick_use_orientation_arg,
        vision_pick_min_orientation_extent_ratio_arg,
        vision_pick_use_size_arg,
        use_sim_time_arg,
        hotdog_making_node,
    ])
