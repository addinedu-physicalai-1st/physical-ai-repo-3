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

bool HotdogMakingNode::runBeverageCanPick(ManufacturingTarget beverage_target)
{
    const std::string beverage_target_model =
      beverageTargetModel(beverage_target, target_model_, coffee_target_model_, coke_target_model_);
    RCLCPP_INFO(
      get_logger(),
      "Beverage can pick started: task=%s, target_model=%s",
      task_presets::targetName(beverage_target),
      beverage_target_model.c_str());

    TargetObject target;
    if (!loadTargetForVisionPick(
        beverage_target,
        "Beverage can pick",
        left_arm_group_,
        left_ready_pose_name_,
        left_ready_joints_,
        beverage_target_model,
        target))
    {
      return false;
    }

    PickPlan pick_plan =
      makeHorizontalPickPlan(
        target,
        Eigen::Vector3d::UnitY(),
        Eigen::Vector3d::UnitX(),
        ketchup_pre_grasp_distance_,
        lift_height_,
        task_presets::kLeftBeverageCanPickTuning.grasp_tcp_z_offset_m);
    offsetPickPlanGraspAndLiftWorldZ(
      pick_plan, task_presets::kLeftBeverageCanGraspWorldZOffsetM);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        beverage_target,
        ArmSide::Left,
        std::string("Beverage ") + task_presets::targetName(beverage_target) + " pick",
        std::string("Beverage ") + task_presets::targetName(beverage_target) + " pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftBeverageCanPickTuning,
        true,
        false,
        false},
      target,
      pick_plan);
  }

MotionStepResult HotdogMakingNode::runBeveragePickStageIfNeeded(ManufacturingTarget beverage_target)
{
    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_play_to_stage.has_value() &&
        stageOrder(requested_play_to_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        play_to_stage_ = ManufacturingStage::Pick;
      }
      const bool pick_ok = runBeverageCanPick(beverage_target);
      play_to_stage_ = requested_play_to_stage;
      if (!pick_ok) {
        return MotionStepResult::Failed;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick) ||
        shouldStopAtOrBeforeWaypointStage(ManufacturingStage::Pick))
      {
        return MotionStepResult::Stop;
      }
    }
    return MotionStepResult::Continue;
  }

bool HotdogMakingNode::loadBeverageServeTargets(
    ManufacturingTarget beverage_target,
    std::string & beverage_target_model,
    TargetObject & beverage_target_object,
    TargetObject & pickup_zone)
{
    beverage_target_model =
      beverageTargetModel(beverage_target, target_model_, coffee_target_model_, coke_target_model_);
    return loadManufacturingTarget(beverage_target_model, beverage_target_object) &&
           loadManufacturingTarget("pickup_zone", pickup_zone);
  }

MotionStepResult HotdogMakingNode::runBeverageHandoffStage(
    ManufacturingTarget beverage_target,
    const std::string & beverage_target_model,
    const TargetObject & beverage_target_object,
    moveit::planning_interface::MoveGroupInterface & left_arm,
    moveit::planning_interface::MoveGroupInterface & left_gripper,
    moveit::planning_interface::MoveGroupInterface & right_arm,
    moveit::planning_interface::MoveGroupInterface & right_gripper)
{
    if (!shouldRunStage(ManufacturingStage::Work)) {
      return MotionStepResult::Continue;
    }

    const BeverageHandoffPlan handoff_plan =
      makeBeverageHandoffPlan(
        get_logger(),
        beverage_target,
        beverage_target_object,
        left_arm.getCurrentPose(left_tcp_link_).pose);

    rememberJointTargetIfConfigured(left_arm, left_ready_pose_name_, left_ready_joints_);
    RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm to ready pose before handoff");
    if (!planAndExecuteNamedTarget(
        get_logger(),
        left_arm,
        left_ready_pose_name_,
        "beverage left ready before handoff",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left ready");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_ready")) {
      return MotionStepResult::Stop;
    }

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    std::vector<std::string> left_handoff_case_collision_names = left_arm.getLinkNames();
    const auto left_gripper_touch_links = makeGripperTouchLinks(left_gripper, left_tcp_link_);
    left_handoff_case_collision_names.insert(
      left_handoff_case_collision_names.end(),
      left_gripper_touch_links.begin(),
      left_gripper_touch_links.end());
    left_handoff_case_collision_names.push_back(beverage_target_model);
    std::sort(
      left_handoff_case_collision_names.begin(),
      left_handoff_case_collision_names.end());
    left_handoff_case_collision_names.erase(
      std::unique(
        left_handoff_case_collision_names.begin(),
        left_handoff_case_collision_names.end()),
      left_handoff_case_collision_names.end());

    if (!applyTargetGripperAllowedCollision(
        shared_from_this(),
        get_logger(),
        planning_scene_interface,
        case_target_model_,
        left_handoff_case_collision_names,
        true,
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm to handoff pose");
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        handoff_plan.left_handoff_pose,
        left_tcp_link_,
        "beverage left handoff pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      applyTargetGripperAllowedCollision(
        shared_from_this(),
        get_logger(),
        planning_scene_interface,
        case_target_model_,
        left_handoff_case_collision_names,
        false,
        collision_scene_settle_ms_);
      return MotionStepResult::Failed;
    }
    if (!applyTargetGripperAllowedCollision(
        shared_from_this(),
        get_logger(),
        planning_scene_interface,
        case_target_model_,
        left_handoff_case_collision_names,
        false,
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left handoff");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "handoff")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(
      get_logger(),
      "Beverage serving: using current right gripper opening for handoff receive");

    rememberJointTargetIfConfigured(right_arm, right_ready_pose_name_, right_ready_joints_);
    RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to ready pose before receive");
    if (!planAndExecuteNamedTarget(
        get_logger(),
        right_arm,
        right_ready_pose_name_,
        "beverage right ready before receive",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right ready");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "right_ready")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to pre-receive pose");
    if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        handoff_plan.right_pre_receive_pose,
        right_tcp_link_,
        "beverage right pre-receive pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right pre-receive");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "pre_receive")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper before receive");
    if (!openGripperForPickApproach(
        get_logger(),
        right_gripper,
        "Beverage receive",
        task_presets::kRightBeverageCanReceiveTuning,
        gripper_open_target_))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(300ms);
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive_open")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: planning right arm to receive grasp pose");
    if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        handoff_plan.right_receive_pose,
        right_tcp_link_,
        "beverage right receive pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right receive");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive")) {
      return MotionStepResult::Stop;
    }

    if (!closeGripperForPick(
        get_logger(),
        right_gripper,
        "Beverage receive",
        task_presets::kRightBeverageCanReceiveTuning,
        gripper_grasp_target_))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(300ms);
    if (!detachTargetCollisionObject(
        get_logger(),
        left_arm,
        attached_collision_objects_,
        beverage_target_model,
        "Beverage handoff",
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }
    if (!attachTargetCollisionObject(
        get_logger(),
        right_arm,
        attached_collision_objects_,
        beverage_target_model,
        right_tcp_link_,
        makeGripperTouchLinks(right_gripper, right_tcp_link_),
        "Beverage receive",
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive_close")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: releasing left gripper after handoff");
    if (!openGripperForPickApproach(
        get_logger(),
        left_gripper,
        "Beverage handoff release",
        task_presets::kLeftBeverageCanPickTuning,
        gripper_open_target_))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(300ms);

    const auto * left_pull_out_preset =
      task_presets::findStageWaypointPosePreset(
        beverage_target,
        ArmSide::Left,
        ManufacturingStage::Work,
        "left_pull_out");
    if (left_pull_out_preset == nullptr || !left_pull_out_preset->pose.enabled) {
      RCLCPP_ERROR(
        get_logger(),
        "Beverage left_pull_out waypoint pose preset is disabled; "
        "set work.left_pull_out before running past receive_close");
      return MotionStepResult::Failed;
    }

    const auto left_pull_out_pose = makePoseFromPreset(left_pull_out_preset->pose);
    RCLCPP_INFO(get_logger(), "Beverage left pull-out waypoint pose preset applied");
    RCLCPP_INFO(get_logger(), "Beverage serving: Cartesian left-arm pull-out after handoff");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {left_pull_out_pose},
        "beverage left handoff pull-out",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left pull-out");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_pull_out")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm away after handoff");
    rememberJointTargetIfConfigured(left_arm, left_ready_pose_name_, left_ready_joints_);
    if (!planAndExecuteNamedTarget(
        get_logger(),
        left_arm,
        left_ready_pose_name_,
        "beverage left retreat after handoff",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left retreat");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_retreat") ||
      shouldStopAfter(ManufacturingStage::Work))
    {
      return MotionStepResult::Stop;
    }

    return MotionStepResult::Continue;
  }

MotionStepResult HotdogMakingNode::runBeveragePlaceStage(
    ManufacturingTarget beverage_target,
    const std::string & beverage_target_model,
    const TargetObject & beverage_target_object,
    const TargetObject & pickup_zone,
    moveit::planning_interface::MoveGroupInterface & left_arm,
    moveit::planning_interface::MoveGroupInterface & right_arm,
    moveit::planning_interface::MoveGroupInterface & right_gripper)
{
    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Beverage serving completed before place stage");
      return MotionStepResult::Stop;
    }

    const BeveragePickupPlacePlan pickup_place_plan =
      makeBeveragePickupPlacePlan(
        get_logger(),
        beverage_target,
        beverage_target_object,
        pickup_zone,
        right_arm.getCurrentPose(right_tcp_link_).pose);
    const geometry_msgs::msg::Pose approach_pose = pickup_place_plan.approach_pose;
    const geometry_msgs::msg::Pose release_pose = pickup_place_plan.release_pose;

    RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to pickup approach");
    if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        approach_pose,
        right_tcp_link_,
        "beverage pickup approach",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage pickup approach");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "approach")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(
      get_logger(),
      "Beverage serving: moving right arm to pickup release xyz=[%.3f %.3f %.3f]",
      release_pose.position.x,
      release_pose.position.y,
      release_pose.position.z);
    if (pickup_place_plan.approach_preset_enabled && !pickup_place_plan.release_preset_enabled) {
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {release_pose},
          "beverage pickup release",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return MotionStepResult::Failed;
      }
    } else if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        release_pose,
        right_tcp_link_,
        "beverage pickup release",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage pickup release");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release_pose")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper");
    if (!openGripperForPickApproach(
        get_logger(),
        right_gripper,
        "Beverage place",
        task_presets::kRightBeverageCanReceiveTuning,
        gripper_open_target_))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(300ms);
    if (!detachTargetCollisionObject(
        get_logger(),
        right_arm,
        attached_collision_objects_,
        beverage_target_model,
        "Beverage place",
        collision_scene_settle_ms_))
    {
      return MotionStepResult::Failed;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return MotionStepResult::Stop;
    }

    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      RCLCPP_INFO(get_logger(), "Beverage serving: Cartesian right-arm retreat");
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {approach_pose},
          "beverage pickup retreat",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return MotionStepResult::Failed;
      }
      if (!planAndExecuteReturnHome(
          right_arm,
          beverage_target,
          ArmSide::Right,
          right_tcp_link_,
          "Beverage right arm"))
      {
        return MotionStepResult::Failed;
      }
      if (!planAndExecuteReturnHome(
          left_arm,
          beverage_target,
          ArmSide::Left,
          left_tcp_link_,
          "Beverage left arm"))
      {
        return MotionStepResult::Failed;
      }
    }

    return MotionStepResult::Continue;
  }

bool HotdogMakingNode::runBeverageCanServe(ManufacturingTarget beverage_target)
{
    RCLCPP_INFO(
      get_logger(),
      "Beverage can serving started: task=%s",
      task_presets::targetName(beverage_target));

    const MotionStepResult pick_result = runBeveragePickStageIfNeeded(beverage_target);
    if (pick_result == MotionStepResult::Failed) {
      return false;
    }
    if (pick_result == MotionStepResult::Stop) {
      return true;
    }

    if (dry_run_) {
      RCLCPP_INFO(get_logger(), "Beverage serving dry run completed after pick planning");
      return true;
    }

    std::string beverage_target_model;
    TargetObject beverage_target_object;
    TargetObject pickup_zone;
    if (!loadBeverageServeTargets(
        beverage_target,
        beverage_target_model,
        beverage_target_object,
        pickup_zone))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);
    moveit::planning_interface::MoveGroupInterface right_gripper(self, right_gripper_group_);

    configureTaskArm(left_arm, left_tcp_link_);
    configureTaskArm(right_arm, right_tcp_link_);
    configureTaskGripper(left_gripper);
    configureTaskGripper(right_gripper);

    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left initial");
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right initial");

    const MotionStepResult handoff_result =
      runBeverageHandoffStage(
        beverage_target,
        beverage_target_model,
        beverage_target_object,
        left_arm,
        left_gripper,
        right_arm,
        right_gripper);
    if (handoff_result == MotionStepResult::Failed) {
      return false;
    }
    if (handoff_result == MotionStepResult::Stop) {
      return true;
    }

    const MotionStepResult place_result =
      runBeveragePlaceStage(
        beverage_target,
        beverage_target_model,
        beverage_target_object,
        pickup_zone,
        left_arm,
        right_arm,
        right_gripper);
    if (place_result == MotionStepResult::Failed) {
      return false;
    }

    if (!validateFinalBeveragePlacement(beverage_target)) {
      return false;
    }

    RCLCPP_INFO(
      get_logger(),
      "Beverage %s serving completed",
      task_presets::targetName(beverage_target));
    return true;
  }

}  // namespace ddooby_controller
