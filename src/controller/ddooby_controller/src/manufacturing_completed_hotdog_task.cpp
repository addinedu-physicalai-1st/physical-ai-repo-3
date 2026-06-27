#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <Eigen/Geometry>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/wait_for_message.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/manufacturing_layout_utils.hpp"
#include "ddooby_controller/manufacturing_pick_planner.hpp"
#include "ddooby_controller/manufacturing_place_planner.hpp"
#include "ddooby_controller/manufacturing_pose_utils.hpp"
#include "ddooby_controller/manufacturing_stage_motion.hpp"
#include "ddooby_controller/manufacturing_task_common.hpp"
#include "manufacturing_task_node.hpp"
#include "ddooby_controller/manufacturing_task_runner.hpp"
#include "ddooby_controller/moveit_task_utils.hpp"
#include "ddooby_controller/planning_scene_utils.hpp"
#include "ddooby_controller/vision_pick_adapter.hpp"

namespace ddooby_controller
{
using namespace std::chrono_literals;

MotionStepResult HotdogMakingNode::runCompletedHotdogCarryWaypoints(
    moveit::planning_interface::MoveGroupInterface & right_arm,
    const geometry_msgs::msg::Pose & current_pose,
    const geometry_msgs::msg::Pose & release_pose,
    bool release_pose_preset_configured,
    double carry_min_duration_sec)
{
    bool configured_carry_waypoint_used = false;
    for (const char * waypoint_name : {"move1", "move2"}) {
      const auto * waypoint_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Hotdog,
          ArmSide::Right,
          ManufacturingStage::Place,
          waypoint_name);
      if (waypoint_preset == nullptr) {
        continue;
      }

      configured_carry_waypoint_used = true;
      const geometry_msgs::msg::Pose waypoint_pose = makePoseFromPreset(waypoint_preset->pose);
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog place: MoveIt carry to waypoint %s",
        waypoint_name);
      if (!planAndExecutePoseTarget(
          get_logger(),
          right_arm,
          waypoint_pose,
          right_tcp_link_,
          std::string("completed hotdog pickup ") + waypoint_name,
          task_presets::kDefaultPlanExecuteMaxAttempts,
          carry_min_duration_sec))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup waypoint");
      if (shouldStopAfterWaypoint(ManufacturingStage::Place, waypoint_name)) {
        return MotionStepResult::Stop;
      }
    }

    if (!configured_carry_waypoint_used && release_pose_preset_configured) {
      geometry_msgs::msg::Pose midpoint_pose = current_pose;
      midpoint_pose.position.x =
        current_pose.position.x + (release_pose.position.x - current_pose.position.x) * 0.5;
      midpoint_pose.position.y =
        current_pose.position.y + (release_pose.position.y - current_pose.position.y) * 0.5;
      midpoint_pose.position.z = std::max(current_pose.position.z, release_pose.position.z);

      RCLCPP_INFO(get_logger(), "Completed hotdog place: MoveIt carry through auto midpoint");
      if (!planAndExecutePoseTarget(
          get_logger(),
          right_arm,
          midpoint_pose,
          right_tcp_link_,
          "completed hotdog pickup auto midpoint",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          carry_min_duration_sec))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(
        get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup auto midpoint");
    }

    return MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runCompletedHotdogApproachAndLower(
    moveit::planning_interface::MoveGroupInterface & right_arm,
    const geometry_msgs::msg::Pose & approach_pose,
    const geometry_msgs::msg::Pose & release_pose,
    bool release_pose_preset_configured,
    double carry_velocity_scaling,
    double carry_acceleration_scaling,
    double carry_min_duration_sec)
{
    RCLCPP_INFO(get_logger(), "Completed hotdog place: MoveIt carry to pickup approach");
    if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        approach_pose,
        right_tcp_link_,
        "completed hotdog pickup approach pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        carry_min_duration_sec))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(
      get_logger(),
      right_arm,
      right_tcp_link_,
      "Completed hotdog pickup approach");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "approach")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(
      get_logger(),
      "Completed hotdog place: Cartesian lower to pickup release pose");
    if (!executeCartesian(
        get_logger(),
        right_arm,
        {release_pose},
        "completed hotdog pickup release_pose",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        carry_velocity_scaling,
        carry_acceleration_scaling,
        carry_min_duration_sec))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(
      get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup release_pose");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release_pose")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Completed hotdog place: opening at pickup release pose");
    logCurrentTcpPose(
      get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup pre-release");

    return MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runCompletedHotdogReleaseAndReturn(
    moveit::planning_interface::MoveGroupInterface & right_arm,
    moveit::planning_interface::MoveGroupInterface & right_gripper,
    const geometry_msgs::msg::Pose & approach_pose,
    const geometry_msgs::msg::Pose & release_pose,
    double carry_velocity_scaling,
    double carry_acceleration_scaling,
    double carry_min_duration_sec)
{
    RCLCPP_INFO(get_logger(), "Completed hotdog place: opening right gripper");
    if (!openGripperForPickApproach(
        get_logger(),
        right_gripper,
        "Completed hotdog place",
        task_presets::kRightCasePickTuning,
        gripper_open_target_))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(300ms);
    if (!detachTargetCollisionObject(
        get_logger(),
        right_arm,
        attached_collision_objects_,
        case_target_model_,
        "Completed hotdog place",
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return MotionStepResult::Stop;
    }

    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      RCLCPP_INFO(get_logger(), "Completed hotdog place: Cartesian retreat");
      geometry_msgs::msg::Pose retreat_pose = approach_pose;
      retreat_pose.position.z = std::max(
        retreat_pose.position.z,
        release_pose.position.z + task_presets::kCompletedHotdogPickupApproachHeightM);
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {retreat_pose},
          "completed hotdog pickup retreat",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          carry_velocity_scaling,
          carry_acceleration_scaling,
          carry_min_duration_sec))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup retreat");

      if (!planAndExecuteReturnHome(
          right_arm,
          ManufacturingTarget::Hotdog,
          ArmSide::Right,
          right_tcp_link_,
          "Completed hotdog"))
      {
        return MotionStepResult::Failed;
      }
    }

    return MotionStepResult::Continue;
  }

bool HotdogMakingNode::runCompletedHotdogPlace()
{
    RCLCPP_INFO(get_logger(), "Completed hotdog pickup-zone place started");

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog place dry run skipped; live right TCP pose is required");
      return true;
    }

    TargetObject pickup_zone;
    TargetObject case_target;
    if (!loadManufacturingTarget("pickup_zone", pickup_zone) ||
      !loadManufacturingTarget(case_target_model_, case_target))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);
    moveit::planning_interface::MoveGroupInterface right_gripper(self, right_gripper_group_);
    const double carry_velocity_scaling = task_presets::kCompletedHotdogCarryVelocityScaling;
    const double carry_acceleration_scaling = task_presets::kCompletedHotdogCarryAccelerationScaling;
    const double carry_min_duration_sec = task_presets::kCompletedHotdogCarryMinDurationSec;

    configureTaskArm(right_arm, right_tcp_link_, carry_velocity_scaling, carry_acceleration_scaling);
    configureTaskGripper(right_gripper);

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    if (!removeTargetCollisionObject(
        get_logger(),
        planning_scene_interface,
        sausage_target_model_,
        "Completed hotdog place",
        collision_scene_settle_ms_))
    {
      return false;
    }

    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog place initial");

    const geometry_msgs::msg::Pose current_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const CompletedHotdogPlacePlan completed_hotdog_place_plan =
      makeCompletedHotdogPlacePlan(get_logger(), pickup_zone, case_target, current_pose);
    const geometry_msgs::msg::Pose approach_pose = completed_hotdog_place_plan.approach_pose;
    const geometry_msgs::msg::Pose release_pose = completed_hotdog_place_plan.release_pose;
    const bool release_pose_preset_configured =
      completed_hotdog_place_plan.release_pose_preset_configured;

    const MotionStepResult waypoint_result =
      runCompletedHotdogCarryWaypoints(
        right_arm,
        current_pose,
        release_pose,
        release_pose_preset_configured,
        carry_min_duration_sec);
    if (waypoint_result == MotionStepResult::Failed) {
      return false;
    }
    if (waypoint_result == MotionStepResult::Stop) {
      return true;
    }

    const MotionStepResult approach_result =
      runCompletedHotdogApproachAndLower(
        right_arm,
        approach_pose,
        release_pose,
        release_pose_preset_configured,
        carry_velocity_scaling,
        carry_acceleration_scaling,
        carry_min_duration_sec);
    if (approach_result == MotionStepResult::Failed) {
      return false;
    }
    if (approach_result == MotionStepResult::Stop) {
      return true;
    }

    const MotionStepResult release_result =
      runCompletedHotdogReleaseAndReturn(
        right_arm,
        right_gripper,
        approach_pose,
        release_pose,
        carry_velocity_scaling,
        carry_acceleration_scaling,
        carry_min_duration_sec);
    if (release_result == MotionStepResult::Failed) {
      return false;
    }
    if (release_result == MotionStepResult::Stop) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Completed hotdog pickup-zone place completed");
    return true;
  }

}  // namespace ddooby_controller
