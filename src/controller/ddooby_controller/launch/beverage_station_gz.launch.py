from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def spawn_model(name, model_dir, x, y, z, delay, roll=0.0, pitch=0.0, yaw=0.0):
    model_path = PathJoinSubstitution([
        FindPackageShare("ddooby_controller"),
        "models",
        model_dir,
        "model.sdf",
    ])
    return TimerAction(
        period=delay,
        actions=[
            ExecuteProcess(
                cmd=[
                    "ros2", "run", "ros_gz_sim", "create",
                    "-file", model_path,
                    "-name", name,
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
    openarm_gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare("openarm_gazebo"),
            "/launch/openarm_bimanual_gz.launch.py",
        ])
    )

    set_pose_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "/world/default/set_pose@ros_gz_interfaces/srv/SetEntityPose",
        ],
        output="screen",
    )

    return LaunchDescription([
        openarm_gazebo,
        TimerAction(period=2.0, actions=[set_pose_bridge]),
        spawn_model("beverage_table", "table", 0.57, 0.00, 0.00, 4.0),
        spawn_model("espresso_cup", "cup", 0.38, 0.21, 0.425, 5.0),
        spawn_model("ade_cup", "cup", 0.38, 0.07, 0.425, 5.5),
        spawn_model("mixing_cup", "mixing_cup_open", 0.38, -0.08, 0.425, 6.0),
        spawn_model("water_cup", "cup", 0.38, -0.22, 0.425, 6.5),
        spawn_model("stir_stick_holder", "stir_stick_holder", 0.38, 0.36, 0.37, 6.8),
        spawn_model("stir_stick", "stir_stick", 0.38, 0.36, 0.48, 7.0),
        spawn_model("pickup_zone", "pickup_zone", 0.025, -0.50, 0.35, 7.5),
    ])
