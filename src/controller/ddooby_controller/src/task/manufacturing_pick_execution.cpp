#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <memory>
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

#include "ddooby_controller/simulator/manufacturing_layout_utils.hpp"
#include "ddooby_controller/task/manufacturing_pick_planner.hpp"
#include "ddooby_controller/task/manufacturing_place_planner.hpp"
#include "ddooby_controller/task/manufacturing_pose_utils.hpp"
#include "ddooby_controller/control/manufacturing_stage_motion.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"
#include "manufacturing_task_node_private.hpp"
#include "ddooby_controller/control/moveit_task_utils.hpp"
#include "ddooby_controller/control/planning_scene_utils.hpp"
#include "ddooby_controller/vision/vision_pick_adapter.hpp"

namespace ddooby_controller
{
using namespace manufacturing_task;

bool HotdogMakingNode::prepareAndRunPickMotion(
    const PickMotionConfig & config,
    const TargetObject & target,
    PickPlan pick_plan)
{
    if (config.tuning == nullptr) {
      RCLCPP_ERROR(get_logger(), "%s: missing pick tuning preset", config.log_label.c_str());
      return false;
    }

    const auto & tuning = *config.tuning;
    const bool pre_grasp_pose_configured =
      hasStageWaypointPosePreset(config.target, config.arm, ManufacturingStage::Pick, "pre_grasp");
    const bool pick_pose_configured =
      hasStageWaypointPosePreset(config.target, config.arm, ManufacturingStage::Pick, "grasp");
    applyPickStageWaypointPresets(
      get_logger(),
      config.target,
      config.arm,
      target,
      pre_grasp_height_,
      lift_height_,
      pick_plan);

    logPickPlanSummary(get_logger(), config.log_label, target, tuning, pick_plan);

    if (dry_run_) {
      logDryRunPickPlan(get_logger(), config.log_label, pick_plan);
      return true;
    }

    auto self = shared_from_this();
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: constructing arm group '%s'",
      config.log_label.c_str(),
      config.arm_group.c_str());
    moveit::planning_interface::MoveGroupInterface arm(self, config.arm_group);
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: arm group '%s' constructed",
      config.log_label.c_str(),
      config.arm_group.c_str());
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: constructing gripper group '%s'",
      config.log_label.c_str(),
      config.gripper_group.c_str());
    moveit::planning_interface::MoveGroupInterface gripper(self, config.gripper_group);
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: gripper group '%s' constructed",
      config.log_label.c_str(),
      config.gripper_group.c_str());
    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    if (!applyVisionCollisionObjectIfNeeded(planning_scene_interface, target, config.log_label)) {
      return false;
    }

    const bool tcp_set = configureTaskArm(arm, config.tcp_link);
    configureTaskGripper(gripper);
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: planning_frame='%s', eef='%s' (%s)",
      config.log_label.c_str(),
      arm.getPlanningFrame().c_str(),
      arm.getEndEffectorLink().c_str(),
      tcp_set ? "ok" : "failed");
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " initial");

    rememberJointTargetIfConfigured(arm, config.ready_pose_name, config.ready_joints);

    const MotionStepResult home_result = runPickHomeStage(config, arm);
    if (home_result == MotionStepResult::Failed) {
      return false;
    }
    if (home_result == MotionStepResult::Stop) {
      return true;
    }

    bool gripper_opened_for_approach = false;

    PreGraspGoalMode pre_grasp_goal_mode = PreGraspGoalMode::ExactPose;
    geometry_msgs::msg::Pose reached_pre_grasp_pose;
    const MotionStepResult pre_grasp_result = runPickPreGraspStage(
      config,
      tuning,
      pick_plan,
      pre_grasp_pose_configured,
      arm,
      gripper,
      gripper_opened_for_approach,
      pre_grasp_goal_mode,
      reached_pre_grasp_pose);
    if (pre_grasp_result == MotionStepResult::Failed) {
      return false;
    }
    if (pre_grasp_result == MotionStepResult::Stop) {
      return true;
    }

    geometry_msgs::msg::Pose grasp_pose = pick_plan.grasp_pose;
    geometry_msgs::msg::Pose lift_pose = pick_plan.lift_pose;
    limitPickLiftHeight(get_logger(), config.log_label, config.max_lift_height_m, grasp_pose, lift_pose);

    if (shouldRunStage(ManufacturingStage::Pick)) {
      const MotionStepResult alignment_result = runPickTargetAlignment(
        config,
        pick_plan,
        grasp_pose,
        pre_grasp_pose_configured,
        pick_pose_configured,
        arm,
        reached_pre_grasp_pose);
      if (alignment_result == MotionStepResult::Failed) {
        return false;
      }
      if (alignment_result == MotionStepResult::Stop) {
        return true;
      }

      const MotionStepResult grasp_result = runPickGraspAttachAndDirectLift(
        config,
        tuning,
        target,
        planning_scene_interface,
        arm,
        gripper,
        gripper_opened_for_approach,
        grasp_pose,
        lift_pose);
      if (grasp_result == MotionStepResult::Failed) {
        return false;
      }
      if (grasp_result == MotionStepResult::Stop) {
        return true;
      }
    }

    const MotionStepResult pull_out_result = runPickPullOutAndLift(config, pick_plan, arm, lift_pose);
    if (pull_out_result == MotionStepResult::Failed) {
      return false;
    }
    if (pull_out_result == MotionStepResult::Stop) {
      return true;
    }

    if (shouldStopAfter(ManufacturingStage::Pick)) {
      return true;
    }

    if (config.target == ManufacturingTarget::Bread || config.target == ManufacturingTarget::Sausage) {
      RCLCPP_INFO(get_logger(), "%s", config.completed_log.c_str());
      return true;
    }

    for (const auto & optional_stage : {
        OptionalStageWaypoint{ManufacturingStage::Work, "work", "work"},
        OptionalStageWaypoint{ManufacturingStage::Place, "release", "place"},
        OptionalStageWaypoint{ManufacturingStage::ReturnHome, "return_home", "return-home"}})
    {
      const MotionStepResult stage_result = runOptionalStageWaypoint(config, arm, optional_stage);
      if (stage_result == MotionStepResult::Failed) {
        return false;
      }
      if (stage_result == MotionStepResult::Stop) {
        return true;
      }
    }

    RCLCPP_INFO(get_logger(), "%s", config.completed_log.c_str());
    return true;
  }

MotionStepResult HotdogMakingNode::runPickHomeStage(
    const PickMotionConfig & config,
    moveit::planning_interface::MoveGroupInterface & arm)
{
    const auto motions = makeMotionPrimitives();

    if (!shouldRunStage(ManufacturingStage::Home)) {
      return MotionStepResult::Continue;
    }

    bool home_stage_configured = false;
    if (!planAndExecuteStageWaypointPoseIfConfigured(
        get_logger(),
        arm,
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Home,
        "ready",
        config.tcp_link,
        home_stage_configured,
        cartesian_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }

    if (!home_stage_configured) {
      RCLCPP_INFO(get_logger(), "%s: moving arm to ready pose", config.log_label.c_str());
      if (!motions.moveToNamed(arm, config.ready_pose_name, config.log_label + " ready", 0.0))
      {
        return MotionStepResult::Failed;
      }
    } else {
      RCLCPP_INFO(
        get_logger(),
        "%s: moved arm using configured home/ready waypoint pose",
        config.log_label.c_str());
    }

    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " ready");
    return shouldStopAfter(ManufacturingStage::Home) ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runOptionalStageWaypoint(
    const PickMotionConfig & config,
    moveit::planning_interface::MoveGroupInterface & arm,
    const OptionalStageWaypoint & stage_waypoint)
{
    if (!shouldRunStage(stage_waypoint.stage)) {
      return MotionStepResult::Continue;
    }

    bool configured = false;
    if (!planAndExecuteStageWaypointPoseIfConfigured(
        get_logger(),
        arm,
        config.target,
        config.arm,
        stage_waypoint.stage,
        stage_waypoint.waypoint,
        config.tcp_link,
        configured,
        cartesian_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }

    if (configured) {
      logCurrentTcpPose(
        get_logger(),
        arm,
        config.tcp_link,
        config.log_label + " " + stage_waypoint.log_suffix);
    }

    return shouldStopAfter(stage_waypoint.stage) ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runPickPreGraspStage(
    const PickMotionConfig & config,
    const task_presets::PickTuningPreset & tuning,
    const PickPlan & pick_plan,
    bool pre_grasp_pose_configured,
    moveit::planning_interface::MoveGroupInterface & arm,
    moveit::planning_interface::MoveGroupInterface & gripper,
    bool & gripper_opened_for_approach,
    PreGraspGoalMode & pre_grasp_goal_mode,
    geometry_msgs::msg::Pose & reached_pre_grasp_pose)
{
    const auto motions = makeMotionPrimitives();

    if (!shouldRunStage(ManufacturingStage::Pick)) {
      reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " resume pre-grasp");
      return MotionStepResult::Continue;
    }

    if (config.target == ManufacturingTarget::Case) {
      RCLCPP_INFO(
        get_logger(),
        "%s: opening gripper at ready pose before case approach",
        config.log_label.c_str());
      if (!motions.gripperPickAction(gripper, config.log_label, tuning, GripperPickAction::Open))
      {
        return MotionStepResult::Failed;
      }
      gripper_opened_for_approach = true;
    }

    RCLCPP_INFO(get_logger(), "%s: planning to pre-grasp", config.log_label.c_str());
    const bool use_pre_grasp_clearance =
      pre_grasp_pose_configured &&
      (config.target == ManufacturingTarget::Bread ||
      config.target == ManufacturingTarget::Sausage ||
      config.target == ManufacturingTarget::Ketchup);
    if (!planAndExecutePreGrasp(
        get_logger(),
        arm,
        pick_plan.pre_grasp_pose,
        config.tcp_link,
        use_pre_grasp_clearance,
        pose_min_duration_sec_,
        pre_grasp_goal_mode))
    {
      return MotionStepResult::Failed;
    }

    RCLCPP_INFO(
      get_logger(),
      "%s: reached pre-grasp using %s goal mode",
      config.log_label.c_str(),
      preGraspGoalModeName(pre_grasp_goal_mode));
    reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " pre-grasp");
    return shouldStopAfterWaypoint(ManufacturingStage::Pick, "pre_grasp") ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runPickGraspAttachAndDirectLift(
    const PickMotionConfig & config,
    const task_presets::PickTuningPreset & tuning,
    const TargetObject & target,
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    moveit::planning_interface::MoveGroupInterface & arm,
    moveit::planning_interface::MoveGroupInterface & gripper,
    bool gripper_opened_for_approach,
    const geometry_msgs::msg::Pose & grasp_pose,
    const geometry_msgs::msg::Pose & lift_pose)
{
    const auto motions = makeMotionPrimitives();

    bool target_gripper_collision_allowed = false;
    std::vector<std::string> gripper_touch_links;
    auto restore_target_gripper_collision = [&]() {
      if (!target_gripper_collision_allowed) {
        return true;
      }
      const bool restored = applyTargetGripperAllowedCollision(
        shared_from_this(),
        get_logger(),
        planning_scene_interface,
        target.name,
        gripper_touch_links,
        false,
        collision_scene_settle_ms_);
      target_gripper_collision_allowed = false;
      return restored;
    };

    if (!gripper_opened_for_approach) {
      RCLCPP_INFO(get_logger(), "%s: opening gripper after target alignment", config.log_label.c_str());
      if (!motions.gripperPickAction(gripper, config.log_label, tuning, GripperPickAction::Open))
      {
        return MotionStepResult::Failed;
      }
    }

    if (allow_gripper_target_collision_for_grasp_) {
      gripper_touch_links = makeGripperTouchLinks(gripper, config.tcp_link);
      if (!applyTargetGripperAllowedCollision(
          shared_from_this(),
          get_logger(),
          planning_scene_interface,
          target.name,
          gripper_touch_links,
          true,
          collision_scene_settle_ms_))
      {
        return MotionStepResult::Failed;
      }
      target_gripper_collision_allowed = true;
    }

    if (config.use_planned_grasp_approach) {
      RCLCPP_INFO(get_logger(), "%s: planned approach to grasp", config.log_label.c_str());
      if (!motions.moveToPose(arm, grasp_pose, config.tcp_link, config.log_label + " planned grasp approach"))
      {
        restore_target_gripper_collision();
        return MotionStepResult::Failed;
      }
    } else {
      RCLCPP_INFO(get_logger(), "%s: Cartesian approach to grasp", config.log_label.c_str());
      if (!motions.cartesianMoveToPoseWithPlanningFallback(arm, grasp_pose, config.tcp_link, config.log_label + " grasp approach", config.log_label + " planned grasp approach", config.allow_planned_grasp_approach_fallback, cartesian_avoid_collisions_))
      {
        restore_target_gripper_collision();
        return MotionStepResult::Failed;
      }
    }
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp");
    if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "grasp")) {
      restore_target_gripper_collision();
      return MotionStepResult::Stop;
    }

    if (!motions.gripperPickAction(gripper, config.log_label, tuning, GripperPickAction::Close))
    {
      restore_target_gripper_collision();
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});
    if (gripper_touch_links.empty()) {
      gripper_touch_links = makeGripperTouchLinks(gripper, config.tcp_link);
    }
    if (!attachTargetCollisionObject(
        get_logger(),
        arm,
        attached_collision_objects_,
        target.name,
        config.tcp_link,
        gripper_touch_links,
        config.log_label,
        collision_scene_settle_ms_))
    {
      restore_target_gripper_collision();
      return MotionStepResult::Failed;
    }
    if (!restore_target_gripper_collision()) {
      return MotionStepResult::Failed;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "close")) {
      return MotionStepResult::Stop;
    }

    if (config.pull_out_to_pre_grasp_before_lift) {
      return MotionStepResult::Continue;
    }

    RCLCPP_INFO(get_logger(), "%s: Cartesian lift", config.log_label.c_str());
    if (!motions.cartesianMoveToPoseWithPlanningFallback(arm, lift_pose, config.tcp_link, config.log_label + " lift", config.log_label + " planned lift", true, cartesian_avoid_collisions_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
    return shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift") ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runPickPullOutAndLift(
    const PickMotionConfig & config,
    const PickPlan & pick_plan,
    moveit::planning_interface::MoveGroupInterface & arm,
    geometry_msgs::msg::Pose & lift_pose)
{
    const auto motions = makeMotionPrimitives();

    if (!config.pull_out_to_pre_grasp_before_lift || !shouldRunStage(ManufacturingStage::Pick)) {
      return MotionStepResult::Continue;
    }

    geometry_msgs::msg::Pose pull_out_pose = arm.getCurrentPose(config.tcp_link).pose;
    const auto * pull_out_preset = findPullOutPosePreset(config.target, config.arm);
    if (pull_out_preset != nullptr) {
      pull_out_pose = makePoseFromPreset(*pull_out_preset);
      RCLCPP_INFO(get_logger(), "%s: pull-out waypoint pose preset applied", config.log_label.c_str());
    } else {
      pull_out_pose.position.x = pick_plan.pre_grasp_pose.position.x;
      pull_out_pose.position.y = pick_plan.pre_grasp_pose.position.y;
    }

    RCLCPP_INFO(get_logger(), "%s: Cartesian pull-out", config.log_label.c_str());
    if (!motions.cartesianMoveToPose(arm, pull_out_pose, config.log_label + " pull-out", cartesian_avoid_collisions_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " pull-out");
    if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "pull_out")) {
      return MotionStepResult::Stop;
    }

    lift_pose.position.x = pull_out_pose.position.x;
    lift_pose.position.y = pull_out_pose.position.y;
    lift_pose.position.z = pull_out_pose.position.z + lift_height_;
    lift_pose.orientation = pull_out_pose.orientation;

    RCLCPP_INFO(get_logger(), "%s: Cartesian lift", config.log_label.c_str());
    if (!motions.cartesianMoveToPoseWithPlanningFallback(arm, lift_pose, config.tcp_link, config.log_label + " lift", config.log_label + " planned lift", true, cartesian_avoid_collisions_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
    return shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift") ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runPickTargetAlignment(
    const PickMotionConfig & config,
    const PickPlan & pick_plan,
    const geometry_msgs::msg::Pose & grasp_pose,
    bool pre_grasp_pose_configured,
    bool pick_pose_configured,
    moveit::planning_interface::MoveGroupInterface & arm,
    geometry_msgs::msg::Pose & reached_pre_grasp_pose)
{
    const auto motions = makeMotionPrimitives();

    const double pre_grasp_dx =
      reached_pre_grasp_pose.position.x - pick_plan.pre_grasp_pose.position.x;
    const double pre_grasp_dy =
      reached_pre_grasp_pose.position.y - pick_plan.pre_grasp_pose.position.y;
    const double pre_grasp_xy_error =
      std::sqrt(pre_grasp_dx * pre_grasp_dx + pre_grasp_dy * pre_grasp_dy);
    RCLCPP_INFO(
      get_logger(),
      "%s: desired pre-grasp xy=[%.3f %.3f], reached tcp xy=[%.3f %.3f], error=%.3f m",
      config.log_label.c_str(),
      pick_plan.pre_grasp_pose.position.x,
      pick_plan.pre_grasp_pose.position.y,
      reached_pre_grasp_pose.position.x,
      reached_pre_grasp_pose.position.y,
      pre_grasp_xy_error);

    const bool has_target_alignment_after_pre_grasp =
      pre_grasp_pose_configured && !pick_pose_configured &&
      (config.target == ManufacturingTarget::Case ||
      config.target == ManufacturingTarget::Bread ||
      config.target == ManufacturingTarget::Sausage ||
      config.target == ManufacturingTarget::Ketchup);
    if (pre_grasp_xy_error > max_pre_grasp_xy_error_ &&
      !has_target_alignment_after_pre_grasp)
    {
      RCLCPP_ERROR(
        get_logger(),
        "%s: rejecting pre-grasp because TCP xy error %.3f m exceeds %.3f m",
        config.log_label.c_str(),
        pre_grasp_xy_error,
        max_pre_grasp_xy_error_);
      return MotionStepResult::Failed;
    }

    if (pre_grasp_xy_error > max_pre_grasp_xy_error_) {
      RCLCPP_WARN(
        get_logger(),
        "%s: pre-grasp TCP xy error %.3f m exceeds %.3f m; continuing to explicit target-alignment step",
        config.log_label.c_str(),
        pre_grasp_xy_error,
        max_pre_grasp_xy_error_);
    }

    if (config.target == ManufacturingTarget::Ketchup && pre_grasp_xy_error > 0.015) {
      if (pre_grasp_xy_error > max_pre_grasp_xy_error_) {
        RCLCPP_WARN(
          get_logger(),
          "%s: pre-grasp TCP xy error %.3f m exceeds %.3f m; applying bottle-aligned correction",
          config.log_label.c_str(),
          pre_grasp_xy_error,
          max_pre_grasp_xy_error_);
      }
      geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = pick_plan.pre_grasp_pose;
      target_aligned_pre_grasp_pose.orientation = grasp_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "%s: re-aligning TCP to bottle y before straight horizontal grasp approach",
        config.log_label.c_str());
      if (!motions.moveToPose(arm, target_aligned_pre_grasp_pose, config.tcp_link, config.log_label + " bottle-y-aligned pre-grasp"))
      {
        return MotionStepResult::Failed;
      }
      reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
      logCurrentTcpPose(
        get_logger(),
        arm,
        config.tcp_link,
        config.log_label + " bottle-y-aligned pre-grasp");
      return shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align") ?
             MotionStepResult::Stop :
             MotionStepResult::Continue;
    }

    if (!pre_grasp_pose_configured || pick_pose_configured) {
      return MotionStepResult::Continue;
    }

    if (config.target == ManufacturingTarget::Case) {
      const Eigen::Vector3d approach_axis = pick_plan.principal_axis.normalized();
      const Eigen::Vector3d reached_position = posePosition(reached_pre_grasp_pose);
      const Eigen::Vector3d grasp_position = posePosition(grasp_pose);
      const Eigen::Vector3d aligned_position =
        grasp_position + approach_axis * ((reached_position - grasp_position).dot(approach_axis));

      geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = grasp_pose;
      target_aligned_pre_grasp_pose.position.x = aligned_position.x();
      target_aligned_pre_grasp_pose.position.y = aligned_position.y();
      target_aligned_pre_grasp_pose.position.z =
        aligned_position.z() + task_presets::kRightCaseTargetAlignZOffsetM;
      RCLCPP_INFO(
        get_logger(),
        "%s: moving beside selected target before horizontal grasp approach (z_offset=%.3f)",
        config.log_label.c_str(),
        task_presets::kRightCaseTargetAlignZOffsetM);
      if (!motions.moveToPose(arm, target_aligned_pre_grasp_pose, config.tcp_link, config.log_label + " target-aligned horizontal pre-grasp"))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(
        get_logger(),
        arm,
        config.tcp_link,
        config.log_label + " target-aligned horizontal pre-grasp");
      return shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align") ?
             MotionStepResult::Stop :
             MotionStepResult::Continue;
    }

    if (config.target == ManufacturingTarget::Ketchup) {
      geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = pick_plan.pre_grasp_pose;
      target_aligned_pre_grasp_pose.orientation = grasp_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "%s: moving to bottle-axis-aligned pre-grasp before straight horizontal approach",
        config.log_label.c_str());
      if (!motions.moveToPose(arm, target_aligned_pre_grasp_pose, config.tcp_link, config.log_label + " bottle-axis-aligned horizontal pre-grasp"))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(
        get_logger(),
        arm,
        config.tcp_link,
        config.log_label + " bottle-axis-aligned horizontal pre-grasp");
      return shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align") ?
             MotionStepResult::Stop :
             MotionStepResult::Continue;
    }

    if (config.target == ManufacturingTarget::Sausage ||
      config.target == ManufacturingTarget::Coke ||
      config.target == ManufacturingTarget::Coffee)
    {
      RCLCPP_INFO(
        get_logger(),
        "%s: skipping forced target alignment; target uses planned grasp approach",
        config.log_label.c_str());
      return MotionStepResult::Continue;
    }

    constexpr double kMinGraspClearanceAboveTarget = 0.05;
    const double clearance_z = std::max({
      reached_pre_grasp_pose.position.z,
      pick_plan.pre_grasp_pose.position.z,
      grasp_pose.position.z + kMinGraspClearanceAboveTarget});

    geometry_msgs::msg::Pose clearance_pose = reached_pre_grasp_pose;
    clearance_pose.position.z = clearance_z;
    clearance_pose.orientation = grasp_pose.orientation;

    if (std::abs(clearance_pose.position.z - reached_pre_grasp_pose.position.z) > 0.005) {
      RCLCPP_INFO(
        get_logger(),
        "%s: moving to grasp clearance z=%.3f before lateral target alignment",
        config.log_label.c_str(),
        clearance_z);
      if (!motions.moveToPose(arm, clearance_pose, config.tcp_link, config.log_label + " grasp clearance"))
      {
        return MotionStepResult::Failed;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp clearance");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "clearance")) {
        return MotionStepResult::Stop;
      }
    }

    geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = grasp_pose;
    target_aligned_pre_grasp_pose.position.z = clearance_z;
    if (config.target == ManufacturingTarget::Sausage) {
      constexpr double kSausageTargetAlignExtraZ = 0.04;
      target_aligned_pre_grasp_pose.position.x = pick_plan.pre_grasp_pose.position.x;
      target_aligned_pre_grasp_pose.position.y = pick_plan.pre_grasp_pose.position.y;
      target_aligned_pre_grasp_pose.position.z =
        std::max(target_aligned_pre_grasp_pose.position.z, grasp_pose.position.z + 0.09) +
        kSausageTargetAlignExtraZ;
      target_aligned_pre_grasp_pose.orientation = pick_plan.pre_grasp_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "%s: moving to elevated sausage pre-grasp alignment before vertical descent",
        config.log_label.c_str());
    } else {
      RCLCPP_INFO(
        get_logger(),
        "%s: moving above selected target before vertical grasp descent",
        config.log_label.c_str());
    }
    if (!motions.moveToPose(arm, target_aligned_pre_grasp_pose, config.tcp_link, config.log_label + " target-aligned pre-grasp"))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(
      get_logger(),
      arm,
      config.tcp_link,
      config.log_label + " target-aligned pre-grasp");
    return shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align") ?
           MotionStepResult::Stop :
           MotionStepResult::Continue;
  }

}  // namespace ddooby_controller
