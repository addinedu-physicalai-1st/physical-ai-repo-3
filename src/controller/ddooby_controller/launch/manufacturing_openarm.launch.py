from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    start_moveit = LaunchConfiguration("start_moveit")
    sync_planning_scene = LaunchConfiguration("sync_planning_scene")
    arm_type = LaunchConfiguration("arm_type")
    use_fake_hardware = LaunchConfiguration("use_fake_hardware")
    right_can_interface = LaunchConfiguration("right_can_interface")
    left_can_interface = LaunchConfiguration("left_can_interface")
    hardware_plugin = LaunchConfiguration("hardware_plugin")
    return_to_zero_on_activate = LaunchConfiguration("return_to_zero_on_activate")
    hold_current_on_activate = LaunchConfiguration("hold_current_on_activate")
    enable_gravity_comp = LaunchConfiguration("enable_gravity_comp")
    enable_coriolis_comp = LaunchConfiguration("enable_coriolis_comp")
    gravity_comp_start_delay_sec = LaunchConfiguration("gravity_comp_start_delay_sec")
    gravity_comp_torque_scale = LaunchConfiguration("gravity_comp_torque_scale")
    gravity_comp_max_abs_torque = LaunchConfiguration("gravity_comp_max_abs_torque")
    gravity_comp_publish_rate_hz = LaunchConfiguration("gravity_comp_publish_rate_hz")
    robot_controller = LaunchConfiguration("robot_controller")
    scene_wait_timeout_sec = LaunchConfiguration("scene_wait_timeout_sec")
    frame_id = LaunchConfiguration("frame_id")

    start_moveit_arg = DeclareLaunchArgument(
        "start_moveit",
        default_value="false",
        choices=["true", "false"],
        description="Start the real OpenArm MoveIt/ros2_control stack. False only syncs the planning scene.",
    )
    sync_planning_scene_arg = DeclareLaunchArgument(
        "sync_planning_scene",
        default_value="true",
        choices=["true", "false"],
        description="Apply manufacturing world collision objects to the active MoveIt planning scene.",
    )
    arm_type_arg = DeclareLaunchArgument(
        "arm_type",
        default_value="v10",
        description="OpenArm type passed to openarm_bimanual_moveit_config demo.launch.py.",
    )
    use_fake_hardware_arg = DeclareLaunchArgument(
        "use_fake_hardware",
        default_value="false",
        choices=["true", "false"],
        description="Use OpenArm fake hardware. For the physical robot use false.",
    )
    right_can_interface_arg = DeclareLaunchArgument(
        "right_can_interface",
        default_value="can0",
        description="SocketCAN interface for the right arm.",
    )
    left_can_interface_arg = DeclareLaunchArgument(
        "left_can_interface",
        default_value="can1",
        description="SocketCAN interface for the left arm.",
    )
    hardware_plugin_arg = DeclareLaunchArgument(
        "hardware_plugin",
        default_value="openarm_hardware/OpenArmHW",
        choices=[
            "openarm_hardware/OpenArm_v10HW",
            "openarm_hardware/OpenArmHW",
        ],
        description="OpenArm ros2_control hardware plugin. Use OpenArmHW for legacy A/B checks.",
    )
    return_to_zero_on_activate_arg = DeclareLaunchArgument(
        "return_to_zero_on_activate",
        default_value="false",
        choices=["true", "false"],
        description="Return physical OpenArm joints to zero when hardware activates.",
    )
    hold_current_on_activate_arg = DeclareLaunchArgument(
        "hold_current_on_activate",
        default_value="true",
        choices=["true", "false"],
        description="Initialize command state from current hardware position on activation.",
    )
    enable_gravity_comp_arg = DeclareLaunchArgument(
        "enable_gravity_comp",
        default_value="true",
        choices=["true", "false"],
        description="Enable KDL gravity compensation in the OpenArm hardware interface.",
    )
    enable_coriolis_comp_arg = DeclareLaunchArgument(
        "enable_coriolis_comp",
        default_value="false",
        choices=["true", "false"],
        description="Enable KDL Coriolis compensation in the OpenArm hardware interface.",
    )
    gravity_comp_start_delay_arg = DeclareLaunchArgument(
        "gravity_comp_start_delay_sec",
        default_value="8.0",
        description="Delay gravity compensation until arm controllers have loaded.",
    )
    gravity_comp_torque_scale_arg = DeclareLaunchArgument(
        "gravity_comp_torque_scale",
        default_value="0.60",
        description="Scale applied to computed gravity feedforward torque.",
    )
    gravity_comp_max_abs_torque_arg = DeclareLaunchArgument(
        "gravity_comp_max_abs_torque",
        default_value="3.0",
        description="Per-joint absolute torque limit for gravity feedforward.",
    )
    gravity_comp_publish_rate_arg = DeclareLaunchArgument(
        "gravity_comp_publish_rate_hz",
        default_value="50.0",
        description="Gravity compensation effort command publish rate.",
    )
    robot_controller_arg = DeclareLaunchArgument(
        "robot_controller",
        default_value="forward_position_controller",
        choices=["joint_trajectory_controller", "forward_position_controller"],
        description="Controller type passed to the OpenArm MoveIt demo launch.",
    )
    scene_wait_timeout_arg = DeclareLaunchArgument(
        "scene_wait_timeout_sec",
        default_value="60.0",
        description="Timeout while waiting for /apply_planning_scene.",
    )
    frame_id_arg = DeclareLaunchArgument(
        "frame_id",
        default_value="world",
        description="Planning frame for manufacturing collision objects.",
    )

    openarm_moveit = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("openarm_bimanual_moveit_config"),
                "launch",
                "demo.launch.py",
            ])
        ),
        launch_arguments={
            "arm_type": arm_type,
            "use_fake_hardware": use_fake_hardware,
            "right_can_interface": right_can_interface,
            "left_can_interface": left_can_interface,
            "hardware_plugin": hardware_plugin,
            "return_to_zero_on_activate": return_to_zero_on_activate,
            "hold_current_on_activate": hold_current_on_activate,
            "enable_gravity_comp": enable_gravity_comp,
            "enable_coriolis_comp": enable_coriolis_comp,
            "gravity_comp_start_delay_sec": gravity_comp_start_delay_sec,
            "robot_controller": robot_controller,
        }.items(),
        condition=IfCondition(start_moveit),
    )

    planning_scene_sync = Node(
        package="ddooby_controller",
        executable="sync_planning_scene_from_layout.py",
        name="planning_scene_layout_sync",
        output="screen",
        parameters=[
            {
                "layout_path": PathJoinSubstitution([
                    FindPackageShare("ddooby_controller"),
                    "assets",
                    "manufacturing_world",
                    "layout.json",
                ]),
                "frame_id": frame_id,
                "include_collections": ["Environment", "Object"],
                "apply_service": "/apply_planning_scene",
                "wait_timeout_sec": scene_wait_timeout_sec,
            }
        ],
    )

    delayed_planning_scene_sync = TimerAction(
        period=10.0,
        actions=[planning_scene_sync],
        condition=IfCondition(sync_planning_scene),
    )

    gravity_condition = IfCondition(PythonExpression([
        "'", start_moveit, "' == 'true' and '", enable_gravity_comp, "' == 'true'"
    ]))
    forward_trajectory_bridge_condition = IfCondition(PythonExpression([
        "'", start_moveit, "' == 'true' and '",
        robot_controller,
        "' == 'forward_position_controller'",
    ]))

    gravity_effort_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "left_forward_effort_controller",
            "right_forward_effort_controller",
            "-c",
            "/controller_manager",
        ],
        condition=gravity_condition,
    )

    gravity_compensation = Node(
        package="ddooby_controller",
        executable="openarm_gravity_compensation_node",
        name="openarm_gravity_compensation",
        output="screen",
        parameters=[
            {
                "enabled": enable_gravity_comp,
                "start_delay_sec": gravity_comp_start_delay_sec,
                "publish_rate_hz": gravity_comp_publish_rate_hz,
                "torque_scale": gravity_comp_torque_scale,
                "max_abs_torque": gravity_comp_max_abs_torque,
                "left_root_link": "openarm_body_link0",
                "left_tip_link": "openarm_left_hand",
                "right_root_link": "openarm_body_link0",
                "right_tip_link": "openarm_right_hand",
                "left_command_topic": "/left_forward_effort_controller/commands",
                "right_command_topic": "/right_forward_effort_controller/commands",
                "robot_description_topic": "/openarm_robot_description",
            }
        ],
        condition=gravity_condition,
    )

    delayed_gravity_effort_spawner = TimerAction(
        period=5.5,
        actions=[gravity_effort_spawner],
        condition=gravity_condition,
    )

    delayed_gravity_compensation = TimerAction(
        period=6.5,
        actions=[gravity_compensation],
        condition=gravity_condition,
    )

    left_forward_trajectory_bridge = Node(
        package="ddooby_controller",
        executable="forward_joint_trajectory_bridge_node",
        name="left_forward_joint_trajectory_bridge",
        output="screen",
        parameters=[
            {
                "controller_name": "left_joint_trajectory_controller",
                "command_topic": "/left_forward_position_controller/commands",
                "joint_states_topic": "/joint_states",
                "joint_names": [
                    "openarm_left_joint1",
                    "openarm_left_joint2",
                    "openarm_left_joint3",
                    "openarm_left_joint4",
                    "openarm_left_joint5",
                    "openarm_left_joint6",
                    "openarm_left_joint7",
                ],
                "publish_rate_hz": 100.0,
                "state_wait_timeout_sec": 5.0,
                "hold_after_goal_sec": 0.2,
                "hold_when_idle": True,
                "idle_hold_publish_rate_hz": 50.0,
                "goal_tolerance_rad": 0.08,
                "goal_settle_timeout_sec": 5.0,
                "goal_settle_required_sec": 0.35,
            }
        ],
        condition=forward_trajectory_bridge_condition,
    )

    right_forward_trajectory_bridge = Node(
        package="ddooby_controller",
        executable="forward_joint_trajectory_bridge_node",
        name="right_forward_joint_trajectory_bridge",
        output="screen",
        parameters=[
            {
                "controller_name": "right_joint_trajectory_controller",
                "command_topic": "/right_forward_position_controller/commands",
                "joint_states_topic": "/joint_states",
                "joint_names": [
                    "openarm_right_joint1",
                    "openarm_right_joint2",
                    "openarm_right_joint3",
                    "openarm_right_joint4",
                    "openarm_right_joint5",
                    "openarm_right_joint6",
                    "openarm_right_joint7",
                ],
                "publish_rate_hz": 100.0,
                "state_wait_timeout_sec": 5.0,
                "hold_after_goal_sec": 0.2,
                "hold_when_idle": True,
                "idle_hold_publish_rate_hz": 50.0,
                "goal_tolerance_rad": 0.08,
                "goal_settle_timeout_sec": 5.0,
                "goal_settle_required_sec": 0.35,
            }
        ],
        condition=forward_trajectory_bridge_condition,
    )

    delayed_forward_trajectory_bridges = TimerAction(
        period=4.5,
        actions=[left_forward_trajectory_bridge, right_forward_trajectory_bridge],
        condition=forward_trajectory_bridge_condition,
    )

    return LaunchDescription([
        start_moveit_arg,
        sync_planning_scene_arg,
        arm_type_arg,
        use_fake_hardware_arg,
        right_can_interface_arg,
        left_can_interface_arg,
        hardware_plugin_arg,
        return_to_zero_on_activate_arg,
        hold_current_on_activate_arg,
        enable_gravity_comp_arg,
        enable_coriolis_comp_arg,
        gravity_comp_start_delay_arg,
        gravity_comp_torque_scale_arg,
        gravity_comp_max_abs_torque_arg,
        gravity_comp_publish_rate_arg,
        robot_controller_arg,
        scene_wait_timeout_arg,
        frame_id_arg,
        openarm_moveit,
        delayed_forward_trajectory_bridges,
        delayed_gravity_effort_spawner,
        delayed_gravity_compensation,
        delayed_planning_scene_sync,
    ])
