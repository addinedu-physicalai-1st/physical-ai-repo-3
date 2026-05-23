from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    ingredient_model = LaunchConfiguration("ingredient_model")
    start_step = LaunchConfiguration("start_step")
    end_step = LaunchConfiguration("end_step")
    reset_world_on_start = LaunchConfiguration("reset_world_on_start")

    ingredient_model_arg = DeclareLaunchArgument(
        "ingredient_model",
        default_value="espresso_cup",
        description="Ingredient cup model handled by the left arm",
    )
    start_step_arg = DeclareLaunchArgument(
        "start_step",
        default_value="",
        description="Optional first primitive step to run",
    )
    end_step_arg = DeclareLaunchArgument(
        "end_step",
        default_value="",
        description="Optional last primitive step to run",
    )
    reset_world_on_start_arg = DeclareLaunchArgument(
        "reset_world_on_start",
        default_value="true",
        description="Reset Gazebo beverage objects to their initial poses before running the task",
    )

    moveit_config = MoveItConfigsBuilder(
        "openarm", package_name="openarm_bimanual_moveit_config"
    ).to_moveit_configs()

    beverage_making_test_node = Node(
        package="ddooby_controller",
        executable="beverage_making_test_node",
        output="screen",
        parameters=[
            moveit_config.to_dict(),
            {
                "use_sim_time": True,
                "water_model": "water_cup",
                "ingredient_model": ingredient_model,
                "mixing_model": "mixing_cup",
                "stir_stick_model": "stir_stick",
                "pickup_model": "pickup_zone",
                "gazebo_pose_topic": "/world/default/pose/info",
                "gazebo_set_pose_service": "/world/default/set_pose",
                "start_step": start_step,
                "end_step": end_step,
                "reset_world_on_start": reset_world_on_start,
                "reset_world_settle_time": 1.0,
                "dual_arm_group": "both_arms",
                "run_water": True,
                "run_ingredient": True,
                "approach_distance": 0.10,
                "cup_grasp_height_offset": 0.0,
                "gripper_center_forward_offset": 0.145,
                "cup_grasp_inward_offset": 0.013,
                "target_pose_timeout": 5.0,
                "planning_time": 5.0,
                "planning_attempts": 5,
                "cartesian_eef_step": 0.005,
                "min_cartesian_fraction": 0.95,
                "min_grasp_approach_fallback_fraction": 0.85,
                "allow_planned_grasp_approach_fallback": True,
                "cartesian_avoid_collisions": False,
                "pick_gripper_target": "half_closed",
                "lift_height": 0.12,
                "mixing_hover_height_offset": 0.16,
                "post_pour_clearance_height_offset": 0.16,
                "place_tcp_backward_offset": 0.0,
                "pour_target_lateral_offset": 0.08,
                "pour_axis": "local_z",
                "pour_angle": 1.05,
                "pour_hold_time": 1.0,
                "pour_waypoint_count": 8,
                "stir_stick_length": 0.18,
                "stir_stick_grasp_inset": 0.02,
                "stir_stick_roll_angle": 1.5708,
                "stir_stick_gripper_target": "closed",
                "vertical_stir_stick": True,
                "vertical_stir_stick_grasp_height_offset": 0.045,
                "stir_stick_grasp_inward_offset": 0.012,
                "stir_hover_height_offset": 0.13,
                "stir_cup_stage_x_offset": 0.0,
                "stir_cup_stage_y": 0.0,
                "stir_cup_stage_height_offset": 0.07,
                "stir_stick_insert_hover_height_offset": 0.25,
                "stir_stick_insert_depth_height_offset": 0.10,
                "stir_transport_retreat_distance": 0.18,
                "stir_transport_extra_height": 0.08,
                "left_stir_entry_guide_joints": [
                    # Guide pose captured from home before entering the stir stick grasp area.
                    0.8466154308640425,
                    -0.5287175219228368,
                    -0.7190660671036047,
                    1.7897609042524751,
                    -0.7588362651435279,
                    -0.4619178272429467,
                    -0.22296615443989146,
                ],
                "left_stir_transport_guide_joints": [
                    # Post-grasp guide pose from the stick holder toward the cup hover route.
                    -0.7685762359402868,
                    -1.3448193569944227,
                    0.07831866078247118,
                    1.5905137729263639,
                    -1.3448119025434657,
                    0.03679057046950725,
                    0.7089027646912903,
                    # Backward-captured guide pose farther from the final hover.
                    -0.8064186428086612,
                    -0.4464642369966606,
                    -0.35497768194757856,
                    1.7741919744717216,
                    -0.5595900006936744,
                    -0.24034509110401606,
                    1.1087779434403462,
                    # Earlier near-hover guide pose, still used only as a waypoint.
                    -0.8129033575960519,
                    -0.12425973153675493,
                    -0.006058583380389701,
                    2.0132328465994993,
                    -1.1009513293634579,
                    -0.28775587946374703,
                    1.3326731778654028,
                ],
                "stir_radius": 0.008,
                "stir_cycles": 3,
                "stir_waypoint_count": 12,
                "right_mixing_pregrasp_lateral_offset": 0.0,
                "pickup_cup_center_height_offset": 0.085,
                "pickup_hover_height_offset": 0.20,
                "pickup_transfer_lift_height": 0.05,
                "pickup_transfer_x": 0.30,
                "pickup_transfer_y": -0.46,
                "pickup_table_size_x": 0.65,
                "pickup_table_size_y": 0.27,
                "pickup_table_edge_margin": 0.025,
                "pickup_release_retreat_distance": 0.05,
                "pickup_release_settle_time": 0.8,
                "pickup_release_vertical_retreat_height": 0.08,
                "dynamic_waypoint_lift": 0.08,
                "right_pickup_transfer_guide_joints": [
                    -0.555188219937722,
                    -0.09579910643882422,
                    -0.39670130769893824,
                    2.2426402875405334,
                    -0.33217787854758923,
                    -0.24242063856806817,
                    -0.19001668159790125,
                    -0.5047840950881101,
                    -0.14126022038551836,
                    -0.4507047243856685,
                    2.3794279424895897,
                    -0.43259693585088727,
                    -0.19531697871579354,
                    -0.3926967615306836,
                    -0.4173204865219352,
                    0.448613345946635,
                    0.7278378223191548,
                    1.9731708019902068,
                    0.7530328851985,
                    0.39313294200863974,
                    -0.3273412336351283,
                    -0.30425027455087655,
                    0.33829001866886566,
                    0.7881220439460236,
                    1.9732486253428532,
                    0.4476396507951277,
                    -0.07317922089421411,
                    -0.38369807761918484,
                ],
                "right_pickup_home_guide_joints": [
                    # Return guide pose 1 after mixing cup pickup-zone place.
                    -0.296315925937607,
                    0.3367366093592461,
                    0.7803555118333939,
                    1.967254123347183,
                    0.4407596491793244,
                    -0.0712574172137413,
                    -0.3814069491795918,
                    # Return guide pose 2.
                    -0.3968735359875611,
                    0.4364343865880974,
                    0.7248071775334173,
                    1.9672697541857365,
                    0.7201869039980553,
                    0.3531684712323731,
                    -0.33052757308926495,
                    # Return guide pose 3.
                    -0.37296086369059284,
                    0.08777545895243423,
                    0.09749356782364337,
                    2.334149441992133,
                    0.10712385402754175,
                    -0.03734559778376582,
                    -0.4087710364371635,
                    # Return guide pose 4.
                    -0.819007494223123,
                    0.03611226380780199,
                    0.09055527565198378,
                    2.2591322421024063,
                    0.08844486582326289,
                    -0.005366144325641918,
                    0.11399343815930257,
                ],
                "final_gripper_target": "closed",
            },
        ],
    )

    return LaunchDescription([
        ingredient_model_arg,
        start_step_arg,
        end_step_arg,
        reset_world_on_start_arg,
        beverage_making_test_node,
    ])
