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
#include "manufacturing_task_node_private.hpp"
#include "ddooby_controller/manufacturing_task_runner.hpp"
#include "ddooby_controller/moveit_task_utils.hpp"
#include "ddooby_controller/planning_scene_utils.hpp"
#include "ddooby_controller/vision_pick_adapter.hpp"

namespace ddooby_controller
{
using namespace std::chrono_literals;
using namespace manufacturing_task;

MotionStepResult HotdogMakingNode::runKetchupPickStageIfNeeded()
{
    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_play_to_stage.has_value() &&
        stageOrder(requested_play_to_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        play_to_stage_.reset();
      }
      const bool ketchup_pick_ok = runKetchupPick();
      play_to_stage_ = requested_play_to_stage;
      if (!ketchup_pick_ok) {
        return MotionStepResult::Failed;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return MotionStepResult::Stop;
      }
    }
    return MotionStepResult::Continue;
  }

bool HotdogMakingNode::loadKetchupSqueezeTargets(
    std::string & ketchup_target_model,
    TargetObject & sausage_target,
    TargetObject & bread_target,
    TargetObject & case_target,
    TargetObject & ketchup_target)
{
    ketchup_target_model =
      selectTargetModelOverride(target_model_, ketchup_target_model_);
    return loadManufacturingTarget(sausage_target_model_, sausage_target) &&
           loadManufacturingTarget(bread_target_model_, bread_target) &&
           loadManufacturingTarget(case_target_model_, case_target) &&
           loadManufacturingTarget(ketchup_target_model, ketchup_target);
  }

bool HotdogMakingNode::runKetchupSqueeze()
{
    RCLCPP_INFO(get_logger(), "Hotdog ketchup squeeze started: item=%s", item_name_.c_str());

    const MotionStepResult pick_result = runKetchupPickStageIfNeeded();
    if (pick_result == MotionStepResult::Failed) {
      return false;
    }
    if (pick_result == MotionStepResult::Stop) {
      return true;
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup squeeze dry run completed after ketchup pick planning; live case pose is required for aim/squeeze");
      return true;
    }

    TargetObject sausage_target;
    TargetObject bread_target;
    TargetObject case_target;
    TargetObject ketchup_target;
    std::string ketchup_target_model;
    if (!loadKetchupSqueezeTargets(
        ketchup_target_model,
        sausage_target,
        bread_target,
        case_target,
        ketchup_target))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);

    configureTaskArm(left_arm, left_tcp_link_);
    configureTaskArm(right_arm, right_tcp_link_);
    configureTaskGripper(left_gripper);

    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Ketchup case presentation initial");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup squeeze initial");

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    bool right_case_present_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze: moving right hand to case presentation pose");
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          right_arm,
          ManufacturingTarget::Ketchup,
          ArmSide::Right,
          task_presets::ManufacturingStage::Work,
          "case_present",
          right_tcp_link_,
          right_case_present_configured,
          pose_min_duration_sec_))
      {
        return false;
      }
      if (right_case_present_configured) {
        logCurrentTcpPose(
          get_logger(), right_arm, right_tcp_link_, "Ketchup case presentation pose");
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup case_present waypoint is disabled; using current right TCP pose");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "case_present")) {
        return true;
      }
    }

    const geometry_msgs::msg::Pose right_tcp_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const geometry_msgs::msg::Pose left_current_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
    const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
    const Eigen::Vector3d case_center =
      posePosition(right_tcp_pose) +
      right_tcp_rotation.col(2).normalized() *
      (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
    const KetchupSqueezePlan ketchup_squeeze_plan =
      makeKetchupSqueezePlan(
        get_logger(),
        sausage_target,
        bread_target,
        case_target,
        case_center,
        left_current_pose,
        ketchup_squeeze_height_,
        ketchup_squeeze_length_);
    const geometry_msgs::msg::Pose aim_pose = ketchup_squeeze_plan.aim_pose;
    const geometry_msgs::msg::Pose squeeze_pose = ketchup_squeeze_plan.squeeze_pose;

    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze: moving to aim pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          left_arm,
          aim_pose,
          left_tcp_link_,
          "ketchup aim pose",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup aim pose");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "aim")) {
        return true;
      }

      if (enable_ketchup_squeeze_gripper_) {
        if (!moveGripperToJointPosition(
            get_logger(),
            left_gripper,
            "Ketchup squeeze",
            "squeeze",
            ketchup_squeeze_gripper_position_))
        {
          return false;
        }
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup squeeze gripper adjustment disabled; keeping current grasp width");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "squeeze_start")) {
        return true;
      }

      RCLCPP_INFO(get_logger(), "Ketchup squeeze: Cartesian line over sausage");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {squeeze_pose},
          "ketchup squeeze line",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup squeeze pose");
      if (enable_ketchup_squeeze_gripper_) {
        if (task_presets::kLeftKetchupPickTuning.gripper_close.enabled) {
          if (!moveGripperToJointPosition(
              get_logger(),
              left_gripper,
              "Ketchup squeeze",
              "release squeeze pressure",
              task_presets::kLeftKetchupPickTuning.gripper_close.joint_position))
          {
            return false;
          }
        } else {
          RCLCPP_INFO(
            get_logger(),
            "Ketchup squeeze: reopening gripper to named grasp target '%s'",
            gripper_grasp_target_.c_str());
          if (!planAndExecuteNamedTarget(
              get_logger(),
              left_gripper,
              gripper_grasp_target_,
              "ketchup squeeze release pressure",
              task_presets::kDefaultPlanExecuteMaxAttempts,
              task_presets::kDefaultGripperMinDurationSec))
          {
            return false;
          }
        }
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup squeeze gripper adjustment disabled; keeping grasp width after squeeze");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "squeeze")) {
        return true;
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze completed before ketchup return stage");
      return true;
    }

    const KetchupReturnPlacePlan ketchup_return_plan =
      makeKetchupReturnPlacePlan(
        get_logger(),
        ketchup_target,
        ketchup_pre_grasp_distance_,
        lift_height_);
    const geometry_msgs::msg::Pose return_pose = ketchup_return_plan.return_pose;
    const geometry_msgs::msg::Pose return_lift_pose = ketchup_return_plan.lift_pose;

    const geometry_msgs::msg::Pose squeeze_complete_pose =
      left_arm.getCurrentPose(left_tcp_link_).pose;
    geometry_msgs::msg::Pose post_squeeze_clear_pose = squeeze_complete_pose;
    post_squeeze_clear_pose.position.z = std::max(
      squeeze_complete_pose.position.z + 0.080,
      return_lift_pose.position.z + 0.010);

    RCLCPP_INFO(
      get_logger(),
      "Ketchup place: vertical lift out from squeeze path before returning bottle");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {post_squeeze_clear_pose},
        "ketchup post-squeeze vertical clearance",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup post-squeeze vertical clearance");
    if (!ensureTcpNearPose(
        get_logger(),
        left_arm,
        post_squeeze_clear_pose,
        left_tcp_link_,
        "Ketchup post-squeeze vertical clearance",
        false,
        0.060,
        0.300,
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "aim")) {
      return true;
    }

    bool ketchup_return_guide_configured = false;
    RCLCPP_INFO(
      get_logger(),
      "Ketchup place: checking optional return_guide pose before return lift");
    if (!planAndExecuteStageWaypointPoseIfConfigured(
        get_logger(),
        left_arm,
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        ManufacturingStage::Place,
        "return_guide",
        left_tcp_link_,
        ketchup_return_guide_configured,
        pose_min_duration_sec_))
    {
      return false;
    }
    if (ketchup_return_guide_configured) {
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup post-squeeze return guide pose");
      if (shouldStopAfterWaypoint(ManufacturingStage::Place, "return_guide")) {
        return true;
      }
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup place: no return_guide pose configured; staying at elevated clearance before return lift");
      if (shouldStopAfterWaypoint(ManufacturingStage::Place, "ready")) {
        return true;
      }
    }

    RCLCPP_INFO(
      get_logger(),
      "Ketchup place: MoveIt transfer to return lift pose (height=%.3f)",
      task_presets::kLeftKetchupReturnLiftHeightM);
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        return_lift_pose,
        left_tcp_link_,
        "ketchup return lift pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup return lift");
    if (!ensureTcpNearPose(
        get_logger(),
        left_arm,
        return_lift_pose,
        left_tcp_link_,
        "Ketchup return lift",
        true,
        0.060,
        0.250,
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "lift")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Ketchup place: returning bottle");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {return_pose},
        "ketchup return place pose",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup return place");
    if (!ensureTcpNearPose(
        get_logger(),
        left_arm,
        return_pose,
        left_tcp_link_,
        "Ketchup return place",
        false,
        0.050,
        0.200,
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "return_pose")) {
      return true;
    }

    const auto ketchup_gripper_touch_links = makeGripperTouchLinks(left_gripper, left_tcp_link_);
    const std::vector<std::string> beverage_support_links{"beverage_stand"};
    const auto set_ketchup_beverage_support_collision = [&](bool allow) {
        return applyTargetGripperAllowedCollision(
          shared_from_this(),
          get_logger(),
          planning_scene_interface,
          ketchup_target_model,
          beverage_support_links,
          allow,
          collision_scene_settle_ms_);
      };
    const auto set_ketchup_gripper_collision = [&](bool allow) {
        return applyTargetGripperAllowedCollision(
          shared_from_this(),
          get_logger(),
          planning_scene_interface,
          ketchup_target_model,
          ketchup_gripper_touch_links,
          allow,
          collision_scene_settle_ms_);
      };
    const auto set_beverage_gripper_collision = [&](bool allow) {
        return applyTargetGripperAllowedCollision(
          shared_from_this(),
          get_logger(),
          planning_scene_interface,
          "beverage_stand",
          ketchup_gripper_touch_links,
          allow,
          collision_scene_settle_ms_);
      };
    const auto restore_transient_place_collisions = [&]() {
        const bool gripper_ok = set_ketchup_gripper_collision(false);
        const bool stand_ok = set_beverage_gripper_collision(false);
        return gripper_ok && stand_ok;
      };

    if (!set_ketchup_beverage_support_collision(true) ||
      !set_ketchup_gripper_collision(true) ||
      !set_beverage_gripper_collision(true))
    {
      return false;
    }

    if (!openGripperForPickApproach(
        get_logger(),
        left_gripper,
        "Ketchup place",
        task_presets::kLeftKetchupPickTuning,
        gripper_open_target_))
    {
      restore_transient_place_collisions();
      set_ketchup_beverage_support_collision(false);
      return false;
    }

    if (!detachTargetCollisionObject(
        get_logger(),
        left_arm,
        attached_collision_objects_,
        ketchup_target_model,
        "Ketchup place",
        collision_scene_settle_ms_))
    {
      restore_transient_place_collisions();
      set_ketchup_beverage_support_collision(false);
      return false;
    }
    if (!restoreTargetCollisionObject(
        planning_scene_interface,
        ketchup_target_model,
        "Ketchup place"))
    {
      restore_transient_place_collisions();
      set_ketchup_beverage_support_collision(false);
      return false;
    }

    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      if (!restore_transient_place_collisions()) {
        return false;
      }
      return true;
    }

    const KetchupPostReleaseRetreatPlan post_release_retreat_plan =
      makeKetchupPostReleaseRetreatPlan(return_pose, return_lift_pose);
    RCLCPP_INFO(get_logger(), "Ketchup place: retreating horizontally clear of restored bottle collision");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {post_release_retreat_plan.horizontal_retreat_pose},
        "ketchup horizontal release retreat",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      restore_transient_place_collisions();
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup horizontal release retreat");

    RCLCPP_INFO(get_logger(), "Ketchup place: extra clear retreat before restoring strict collisions");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {post_release_retreat_plan.clear_retreat_pose},
        "ketchup extra clear retreat",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        false,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      restore_transient_place_collisions();
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup extra clear retreat");
    if (!restore_transient_place_collisions()) {
      return false;
    }

    RCLCPP_INFO(get_logger(), "Hotdog ketchup squeeze completed");
    return true;
  }

}  // namespace ddooby_controller
