import os

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, SetEnvironmentVariable, TimerAction
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    gz_ros2_control_lib = os.path.join(get_package_prefix("gz_ros2_control"), "lib")
    openarm_description_share_parent = os.path.dirname(
        get_package_share_directory("openarm_description")
    )
    gz_system_plugin_path = os.pathsep.join(
        filter(
            None,
            [
                gz_ros2_control_lib,
                os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
            ],
        )
    )
    gz_resource_path = os.pathsep.join(
        filter(
            None,
            [
                openarm_description_share_parent,
                get_package_share_directory("openarm_description"),
                os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
            ],
        )
    )

    xacro_file = PathJoinSubstitution(
        [
            FindPackageShare("openarm_gazebo"),
            "urdf",
            "openarm_bimanual_gz.urdf.xacro",
        ]
    )
    world_file = PathJoinSubstitution(
        [
            FindPackageShare("openarm_gazebo"),
            "worlds",
            "empty_no_gravity.sdf",
        ]
    )

    robot_description = {
        "robot_description": Command(
            [
                FindExecutable(name="xacro"),
                " ",
                xacro_file,
                " ",
                "bimanual:=true",
                " ",
                "ros2_control:=false",
            ]
        )
    }

    gz_sim = ExecuteProcess(
        cmd=["gz", "sim", "-r", world_file],
        output="screen",
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        parameters=[robot_description],
        output="screen",
    )

    spawn_robot = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=[
            "-name",
            "openarm_bimanual",
            "-topic",
            "robot_description",
            "-x",
            "0",
            "-y",
            "0",
            "-z",
            "0.0",
        ],
        output="screen",
    )

    clock_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"],
        output="screen",
    )

    spawn_joint_state_broadcaster = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_left_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["left_joint_trajectory_controller", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_right_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["right_joint_trajectory_controller", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_left_gripper_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["left_gripper_controller", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_right_gripper_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["right_gripper_controller", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_left_finger_mimic_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["left_finger_mimic_controller", "-c", "/controller_manager"],
        output="screen",
    )

    spawn_right_finger_mimic_controller = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["right_finger_mimic_controller", "-c", "/controller_manager"],
        output="screen",
    )

    gripper_mimic_follower = Node(
        package="openarm_gazebo",
        executable="gripper_mimic_follower.py",
        output="screen",
    )

    return LaunchDescription(
        [
            SetEnvironmentVariable(
                name="GZ_SIM_SYSTEM_PLUGIN_PATH",
                value=gz_system_plugin_path,
            ),
            SetEnvironmentVariable(
                name="GZ_SIM_RESOURCE_PATH",
                value=gz_resource_path,
            ),
            SetEnvironmentVariable(
                name="IGN_GAZEBO_RESOURCE_PATH",
                value=gz_resource_path,
            ),
            SetEnvironmentVariable(
                name="SDF_PATH",
                value=gz_resource_path,
            ),
            gz_sim,
            clock_bridge,
            robot_state_publisher,
            TimerAction(period=3.0, actions=[spawn_robot]),
            TimerAction(period=6.0, actions=[spawn_joint_state_broadcaster]),
            TimerAction(period=7.0, actions=[spawn_left_controller]),
            TimerAction(period=8.0, actions=[spawn_right_controller]),
            TimerAction(period=9.0, actions=[spawn_left_gripper_controller]),
            TimerAction(period=10.0, actions=[spawn_right_gripper_controller]),
            TimerAction(period=11.0, actions=[spawn_left_finger_mimic_controller]),
            TimerAction(period=12.0, actions=[spawn_right_finger_mimic_controller]),
            TimerAction(period=13.0, actions=[gripper_mimic_follower]),
        ]
    )
