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

bool HotdogMakingNode::runBreadPick()
{
    const std::string bread_target_model = selectTargetModelOverride(target_model_, "bread1");
    RCLCPP_INFO(
      get_logger(),
      "Hotdog bread pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      bread_target_model.c_str());

    TargetObject target;
    if (!loadTargetForVisionPick(
        ManufacturingTarget::Bread,
        "Bread pick",
        left_arm_group_,
        left_ready_pose_name_,
        left_ready_joints_,
        bread_target_model,
        target))
    {
      return false;
    }

    PickPlan pick_plan =
      makeTopDownPickPlan(
        target,
        pre_grasp_height_,
        lift_height_,
        task_presets::kLeftBreadPickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Bread,
        ArmSide::Left,
        "Bread pick",
        "Hotdog bread pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftBreadPickTuning,
        false,
        true,
        false,
        0.08},
      target,
      pick_plan);
  }

bool HotdogMakingNode::runCasePick()
{
    const std::string case_target_model = selectTargetModelOverride(target_model_, "case");
    RCLCPP_INFO(
      get_logger(),
      "Hotdog case pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      case_target_model.c_str());

    TargetObject target;
    if (!loadManufacturingTarget(case_target_model, target)) {
      return false;
    }
    if (!applyVisionPickTarget(ManufacturingTarget::Case, case_target_model, target)) {
      return false;
    }

    PickPlan pick_plan =
      makeHorizontalPickPlan(
        target,
        Eigen::Vector3d::UnitX(),
        Eigen::Vector3d::UnitY(),
        case_pre_grasp_distance_,
        lift_height_,
        task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
    offsetPickPlanGraspAndLiftWorldZ(pick_plan, task_presets::kRightCaseGraspWorldZOffsetM);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Case,
        ArmSide::Right,
        "Case pick",
        "Hotdog case pick completed",
        right_arm_group_,
        right_gripper_group_,
        right_tcp_link_,
        right_ready_pose_name_,
        right_ready_joints_,
        &task_presets::kRightCasePickTuning,
        true,
        false},
      target,
      pick_plan);
  }

bool HotdogMakingNode::runSausagePick()
{
    const std::string sausage_target_model = selectTargetModelOverride(target_model_, "sausage");
    RCLCPP_INFO(
      get_logger(),
      "Hotdog sausage pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      sausage_target_model.c_str());

    TargetObject target;
    if (!loadTargetForVisionPick(
        ManufacturingTarget::Sausage,
        "Sausage pick",
        left_arm_group_,
        left_ready_pose_name_,
        left_ready_joints_,
        sausage_target_model,
        target))
    {
      return false;
    }

    PickPlan pick_plan =
      makeTopDownPickPlan(
        target,
        pre_grasp_height_,
        lift_height_,
        task_presets::kLeftSausagePickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Sausage,
        ArmSide::Left,
        "Sausage pick",
        "Hotdog sausage pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftSausagePickTuning,
        false,
        true,
        false,
        0.08},
      target,
      pick_plan);
  }


bool HotdogMakingNode::runKetchupPick()
{
    const std::string ketchup_target_model = selectTargetModelOverride(target_model_, "kachup");
    RCLCPP_INFO(
      get_logger(),
      "Hotdog ketchup pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      ketchup_target_model.c_str());

    TargetObject target;
    if (!loadTargetForVisionPick(
        ManufacturingTarget::Ketchup,
        "Ketchup pick",
        left_arm_group_,
        left_ready_pose_name_,
        left_ready_joints_,
        ketchup_target_model,
        target))
    {
      return false;
    }

    const TargetObject grasp_target = makeKetchupBodyGraspTarget(target);
    PickPlan pick_plan =
      makeHorizontalPickPlan(
        grasp_target,
        Eigen::Vector3d::UnitX(),
        Eigen::Vector3d::UnitY(),
        ketchup_pre_grasp_distance_,
        lift_height_,
        task_presets::kLeftKetchupPickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        "Ketchup pick",
        "Hotdog ketchup pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftKetchupPickTuning,
        false,
        false,
        false},
      grasp_target,
      pick_plan);
  }

bool HotdogMakingNode::runBreadPlace()
{
    RCLCPP_INFO(get_logger(), "Hotdog bread place started: item=%s", item_name_.c_str());
    const std::string bread_target_model = selectTargetModelOverride(target_model_, bread_target_model_);

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool bread_pick_ok = runBreadPick();
      play_to_stage_ = requested_play_to_stage;
      if (!bread_pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Bread place dry run completed after bread pick planning");
      return true;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);

    configureTaskArm(left_arm, left_tcp_link_);
    configureTaskArm(right_arm, right_tcp_link_);
    configureTaskGripper(left_gripper);

    RCLCPP_INFO(
      get_logger(),
      "Bread place MoveIt setup: left_eef='%s'",
      left_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Bread place case reference");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place initial");

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    bool left_work_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Bread place: moving to configured work pose");
      const auto * work_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work");
      if (work_preset != nullptr) {
        left_work_pose_configured = true;
        PoseAxisReferenceValues references;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        const geometry_msgs::msg::Pose work_pose =
          makePoseFromWaypointPreset(get_logger(), *work_preset, references, "Bread place work");
        if (!planAndExecutePoseTarget(
            get_logger(),
            left_arm,
            work_pose,
            left_tcp_link_,
            "bread place work pose",
            task_presets::kDefaultPlanExecuteMaxAttempts,
            cartesian_min_duration_sec_))
        {
          return false;
        }
      }
      if (left_work_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place work");
      } else {
        RCLCPP_INFO(get_logger(), "Bread work pose is disabled; using current left TCP pose");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Bread place completed before place stage");
      return true;
    }

    RCLCPP_INFO(get_logger(), "Bread place: opening left gripper at work pose");
    if (!planAndExecuteNamedTarget(
        get_logger(),
        left_gripper,
        gripper_open_target_,
        "bread place gripper open",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        task_presets::kDefaultGripperMinDurationSec))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);

    if (!detachTargetCollisionObject(
        get_logger(),
        left_arm,
        attached_collision_objects_,
        bread_target_model,
        "Bread place",
        collision_scene_settle_ms_))
    {
      return false;
    }
    if (!removeTargetCollisionObject(
        get_logger(),
        planning_scene_interface,
        bread_target_model,
        "Bread place",
        collision_scene_settle_ms_))
    {
      return false;
    }

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Bread place: release completed without extra retreat");

    bool return_home_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::ReturnHome,
          "return_home",
          left_tcp_link_,
          return_home_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (return_home_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place return-home");
      }
    }

    RCLCPP_INFO(get_logger(), "Hotdog bread place completed");
    return true;
  }

bool HotdogMakingNode::runSausagePlace()
{
    RCLCPP_INFO(get_logger(), "Hotdog sausage place started: item=%s", item_name_.c_str());
    const std::string sausage_target_model =
      selectTargetModelOverride(target_model_, sausage_target_model_);

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool sausage_pick_ok = runSausagePick();
      play_to_stage_ = requested_play_to_stage;
      if (!sausage_pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Sausage place dry run completed after sausage pick planning; live right TCP is required for automatic place pose");
      return true;
    }

    TargetObject sausage_target;
    TargetObject bread_target;
    TargetObject case_target;
    if (!loadManufacturingTarget(sausage_target_model, sausage_target) ||
      !loadManufacturingTarget("bread1", bread_target) ||
      !loadManufacturingTarget("case", case_target))
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

    RCLCPP_INFO(
      get_logger(),
      "Sausage place MoveIt setup: left_eef='%s', right_eef='%s'",
      left_arm.getEndEffectorLink().c_str(),
      right_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Case presentation initial");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place initial");

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    bool right_work_pose_configured = false;
    bool left_work_pose_configured = false;
    std::optional<geometry_msgs::msg::Pose> left_work_pose;
    if (shouldRunStage(ManufacturingStage::Work)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          right_arm,
          ManufacturingTarget::Case,
          ArmSide::Right,
          task_presets::ManufacturingStage::Work,
          "work",
          right_tcp_link_,
          right_work_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (right_work_pose_configured) {
        logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Case presentation work");
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Case presentation work pose is disabled; using current right TCP pose");
      }

      const auto * left_work_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Sausage,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work");
      if (left_work_preset != nullptr) {
        left_work_pose_configured = true;
        PoseAxisReferenceValues references;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        references.target_position = sausage_target.xyz;
        const geometry_msgs::msg::Pose work_pose =
          makePoseFromWaypointPreset(
            get_logger(), *left_work_preset, references, "Sausage place work");
        left_work_pose = work_pose;
        const double previous_velocity_scaling = velocity_scaling_;
        const double previous_acceleration_scaling = acceleration_scaling_;
        const double sausage_transport_velocity_scaling = std::max(previous_velocity_scaling, 0.15);
        const double sausage_transport_acceleration_scaling =
          std::max(previous_acceleration_scaling, 0.10);
        const bool sausage_work_ok = planAndExecutePoseTargetWithScopedScaling(
          get_logger(),
          left_arm,
          work_pose,
          left_tcp_link_,
          "sausage place work pose",
          previous_velocity_scaling,
          previous_acceleration_scaling,
          sausage_transport_velocity_scaling,
          sausage_transport_acceleration_scaling,
          task_presets::kDefaultPlanExecuteMaxAttempts,
          cartesian_min_duration_sec_);
        if (!sausage_work_ok) {
          return false;
        }
      }
      if (left_work_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage pre-place work");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Sausage place completed before place stage");
      return true;
    }

    const geometry_msgs::msg::Pose right_tcp_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const geometry_msgs::msg::Pose left_current_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
    const Eigen::Vector3d case_center = heldCaseCenterFromTcpPose(right_tcp_pose);
    const SausagePlacePlan sausage_place_plan =
      makeSausagePlacePlan(
        get_logger(),
        sausage_target,
        bread_target,
        case_target,
        case_center,
        left_current_pose,
        left_work_pose,
        place_approach_height_,
        case_sausage_place_clearance_);

    if (sausage_place_plan.approach_reuses_completed_work_pose) {
      RCLCPP_INFO(get_logger(), "Sausage place: already at approach pose from work stage");
    } else {
      RCLCPP_INFO(get_logger(), "Sausage place: moving to approach pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          left_arm,
          sausage_place_plan.approach_pose,
          left_tcp_link_,
          "sausage place approach pose"))
      {
        return false;
      }
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place approach pose");

    if (!sausage_place_plan.lower_to_release_pose) {
      RCLCPP_INFO(
        get_logger(),
        "Sausage place lower skipped; work pose is used as release pose");
    } else {
      RCLCPP_INFO(get_logger(), "Sausage place: Cartesian lower to release pose");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {sausage_place_plan.release_pose},
          "sausage place lower",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place release pose");

    RCLCPP_INFO(get_logger(), "Sausage place: opening left gripper");
    if (!planAndExecuteNamedTarget(
        get_logger(),
        left_gripper,
        gripper_open_target_,
        "sausage place gripper open",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        task_presets::kDefaultGripperMinDurationSec))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);

    if (!detachTargetCollisionObject(
        get_logger(),
        left_arm,
        attached_collision_objects_,
        sausage_target_model,
        "Sausage place",
        collision_scene_settle_ms_))
    {
      return false;
    }
    RCLCPP_INFO(
      get_logger(),
      "Sausage place: keeping released sausage collision object in planning scene");

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    bool return_home_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Sausage,
          ArmSide::Left,
          task_presets::ManufacturingStage::ReturnHome,
          "return_home",
          left_tcp_link_,
          return_home_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (return_home_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place return-home");
      }
    }

    RCLCPP_INFO(get_logger(), "Hotdog sausage place completed");
    return true;
  }

}  // namespace ddooby_controller
