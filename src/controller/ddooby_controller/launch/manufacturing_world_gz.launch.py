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
    with_vision = LaunchConfiguration("with_vision")
    vision_detector_backend = LaunchConfiguration("vision_detector_backend")
    vision_model_path = LaunchConfiguration("vision_model_path")
    show_vision_view = LaunchConfiguration("show_vision_view")
    vision_process_every_n = LaunchConfiguration("vision_process_every_n")
    vision_enable_layout_matching = LaunchConfiguration("vision_enable_layout_matching")
    vision_layout_match_max_distance = LaunchConfiguration("vision_layout_match_max_distance")
    vision_layout_pose_weight = LaunchConfiguration("vision_layout_pose_weight")
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
    with_vision_arg = DeclareLaunchArgument(
        "with_vision",
        default_value="false",
        choices=["true", "false"],
        description="Launch Gazebo D435 image bridges and manufacturing vision pose estimation",
    )
    vision_detector_backend_arg = DeclareLaunchArgument(
        "vision_detector_backend",
        default_value="hsv",
        choices=["hsv", "yolo"],
        description="Object detector backend for Gazebo vision. Use hsv for color-coded Gazebo objects.",
    )
    vision_model_path_arg = DeclareLaunchArgument(
        "vision_model_path",
        default_value="yolo11n.pt",
        description="Ultralytics YOLO model path. Used only when vision_detector_backend:=yolo.",
    )
    show_vision_view_arg = DeclareLaunchArgument(
        "show_vision_view",
        default_value="true",
        choices=["true", "false"],
        description="Open the OpenCV annotated camera view for Gazebo vision",
    )
    vision_process_every_n_arg = DeclareLaunchArgument(
        "vision_process_every_n",
        default_value="1",
        description="Run the vision detector once every N color frames",
    )
    vision_enable_layout_matching_arg = DeclareLaunchArgument(
        "vision_enable_layout_matching",
        default_value="true",
        choices=["true", "false"],
        description="Match raw vision detections to known manufacturing layout object classes and positions",
    )
    vision_layout_match_max_distance_arg = DeclareLaunchArgument(
        "vision_layout_match_max_distance",
        default_value="0.18",
        description="Maximum distance in meters between a vision candidate and a layout object for matching",
    )
    vision_layout_pose_weight_arg = DeclareLaunchArgument(
        "vision_layout_pose_weight",
        default_value="0.85",
        description="Blend weight for the known layout pose after a vision candidate is matched",
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
    camera_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="manufacturing_d435_bridge",
        arguments=[
            "/realsense_d435/image@sensor_msgs/msg/Image[gz.msgs.Image",
            "/realsense_d435/depth_image@sensor_msgs/msg/Image[gz.msgs.Image",
            "/realsense_d435/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo",
        ],
        output="screen",
        condition=IfCondition(with_vision),
    )
    vision_node = Node(
        package="ddooby_controller",
        executable="gazebo_yolo_pose_node.py",
        name="gazebo_yolo_pose",
        output="screen",
        parameters=[
            {
                "detector_backend": vision_detector_backend,
                "model_path": vision_model_path,
                "target_frame": "world",
                "show_debug_view": show_vision_view,
                "process_every_n": vision_process_every_n,
                "layout_path": str(package_share / "assets" / "manufacturing_world" / "layout.json"),
                "enable_layout_matching": vision_enable_layout_matching,
                "layout_match_max_distance_m": vision_layout_match_max_distance,
                "layout_pose_weight": vision_layout_pose_weight,
            }
        ],
        condition=IfCondition(with_vision),
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
        with_vision_arg,
        vision_detector_backend_arg,
        vision_model_path_arg,
        show_vision_view_arg,
        vision_process_every_n_arg,
        vision_enable_layout_matching_arg,
        vision_layout_match_max_distance_arg,
        vision_layout_pose_weight_arg,
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
        TimerAction(period=4.0, actions=[camera_bridge]),
        TimerAction(period=6.0, actions=[move_group]),
        TimerAction(period=8.0, actions=[rviz]),
        TimerAction(period=9.0, actions=[vision_node]),
        TimerAction(period=10.0, actions=[planning_scene_sync]),
        *[spawn_model(package_share, model) for model in layout["models"]],
    ])
