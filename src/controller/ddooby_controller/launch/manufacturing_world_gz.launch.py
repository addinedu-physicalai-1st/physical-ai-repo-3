import json
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def load_layout():
    package_share = Path(get_package_share_directory("ddooby_controller"))
    manifest_path = package_share / "assets" / "manufacturing_world" / "layout.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path}; manufacturing world assets are missing"
        )
    return package_share, json.loads(manifest_path.read_text(encoding="utf-8"))


def spawn_model(package_share, model):
    model_path = package_share / "assets" / model["model_dir"] / "model.sdf"
    x, y, z = model["xyz"]
    roll, pitch, yaw = model["rpy"]

    return TimerAction(
        period=float(model["spawn_delay_sec"]),
        actions=[
            ExecuteProcess(
                cmd=[
                    "ros2", "run", "ros_gz_sim", "create",
                    "-file", str(model_path),
                    "-name", model["name"],
                    "-x", str(x),
                    "-y", str(y),
                    "-z", str(z),
                    "-R", str(roll),
                    "-P", str(pitch),
                    "-Y", str(yaw),
                ],
                output="screen",
            )
        ],
    )


def generate_launch_description():
    # Manufacturing world entrypoint backed by exported runtime assets.
    package_share, layout = load_layout()
    with_moveit = LaunchConfiguration("with_moveit")
    with_rviz = LaunchConfiguration("with_rviz")
    moveit_or_rviz = PythonExpression([
        "'",
        with_moveit,
        "' == 'true' or '",
        with_rviz,
        "' == 'true'",
    ])

    with_moveit_arg = DeclareLaunchArgument(
        "with_moveit",
        default_value="false",
        choices=["true", "false"],
        description="Launch MoveGroup with the Gazebo manufacturing world",
    )
    with_rviz_arg = DeclareLaunchArgument(
        "with_rviz",
        default_value="false",
        choices=["true", "false"],
        description="Launch MoveGroup and RViz with the Gazebo manufacturing world",
    )

    set_pose_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="manufacturing_set_pose_bridge",
        arguments=[
            "/world/default/set_pose@ros_gz_interfaces/srv/SetEntityPose@gz.msgs.Pose@gz.msgs.Boolean",
        ],
        output="screen",
    )
    move_group = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("openarm_gazebo"),
                "launch",
                "move_group_gz.launch.py",
            ])
        ),
        condition=IfCondition(moveit_or_rviz),
    )
    rviz = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("openarm_gazebo"),
                "launch",
                "moveit_rviz_gz.launch.py",
            ])
        ),
        condition=IfCondition(with_rviz),
    )
    planning_scene_sync = Node(
        package="ddooby_controller",
        executable="sync_planning_scene_from_layout.py",
        name="planning_scene_layout_sync",
        output="screen",
        parameters=[
            {
                "layout_path": str(package_share / "assets" / "manufacturing_world" / "layout.json"),
                "frame_id": "world",
                "include_collections": ["Environment", "Object"],
                "apply_service": "/apply_planning_scene",
                "wait_timeout_sec": 60.0,
            }
        ],
        condition=IfCondition(moveit_or_rviz),
    )

    return LaunchDescription([
        with_moveit_arg,
        with_rviz_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    FindPackageShare("openarm_gazebo"),
                    "launch",
                    "openarm_bimanual_gz.launch.py",
                ])
            )
        ),
        TimerAction(period=2.0, actions=[set_pose_bridge]),
        TimerAction(period=6.0, actions=[move_group]),
        TimerAction(period=8.0, actions=[rviz]),
        TimerAction(period=10.0, actions=[planning_scene_sync]),
        *[spawn_model(package_share, model) for model in layout["models"]],
    ])
