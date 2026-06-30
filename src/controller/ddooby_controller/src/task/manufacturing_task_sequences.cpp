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

#include "ddooby_controller/control/manufacturing_stage_motion.hpp"
#include "ddooby_controller/control/moveit_task_utils.hpp"
#include "ddooby_controller/control/planning_scene_utils.hpp"
#include "ddooby_controller/simulator/manufacturing_layout_utils.hpp"
#include "ddooby_controller/task/manufacturing_pick_planner.hpp"
#include "ddooby_controller/task/manufacturing_place_planner.hpp"
#include "ddooby_controller/task/manufacturing_pose_utils.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"
#include "ddooby_controller/vision/vision_pick_adapter.hpp"
#include "manufacturing_task_node_private.hpp"

namespace ddooby_controller
{

using namespace manufacturing_task;

// ---------------------------------------------------------------------------
// 전체 task 조립부
// ---------------------------------------------------------------------------

bool HotdogMakingNode::runHotdogAssemblyUntil(ManufacturingTarget endpoint)
{
    const int endpoint_order = manufacturing_task::hotdogAssemblyStepOrder(endpoint);
    if (endpoint_order <= 0) {
      RCLCPP_ERROR(get_logger(), "Unsupported hotdog assembly endpoint: %s", task_presets::targetName(endpoint));
      return false;
    }

    if (endpoint == ManufacturingTarget::Hotdog && start_stage_ == ManufacturingStage::Place) {
      RCLCPP_INFO(get_logger(), "New York hotdog assembly starts at completed-hotdog pickup-zone place");
      return runCompletedHotdogPlace();
    }

    if (start_stage_ != ManufacturingStage::Home) {
      RCLCPP_WARN(
        get_logger(),
        "task:=%s runs from the beginning of the manufacturing sequence; start_from_waypoint is only exact for task:=hotdog play_to_stage:=place",
        task_presets::targetName(endpoint));
    }

    const std::string saved_target_model = target_model_;
    const ManufacturingStage saved_start_stage = start_stage_;
    const bool saved_has_play_to_stage = has_play_to_stage_;
    const auto saved_play_to_stage = play_to_stage_;

    auto restore_state = [&]() {
      target_model_ = saved_target_model;
      start_stage_ = saved_start_stage;
      has_play_to_stage_ = saved_has_play_to_stage;
      play_to_stage_ = saved_play_to_stage;
    };

    auto run_endpoint_step = [&](ManufacturingTarget step, const std::string & model, auto && runner) {
      target_model_ = model;
      has_play_to_stage_ = step == endpoint && saved_has_play_to_stage;
      play_to_stage_ = saved_play_to_stage;
      return runner();
    };

    start_stage_ = ManufacturingStage::Home;

    bool success = true;
    RCLCPP_INFO(get_logger(), "New York hotdog assembly started: endpoint=%s", task_presets::targetName(endpoint));

    RCLCPP_INFO(get_logger(), "Hotdog assembly step 1/5: pick and present case (%s)", case_target_model_.c_str());
    if (!run_endpoint_step(ManufacturingTarget::Case, case_target_model_, [&]() {return runCasePick();})) {
      success = false;
    } else if (endpoint_order == manufacturing_task::hotdogAssemblyStepOrder(ManufacturingTarget::Case)) {
      RCLCPP_INFO(get_logger(), "New York hotdog assembly stopped at %s endpoint", task_presets::targetName(ManufacturingTarget::Case));
      restore_state();
      return true;
    }

    if (success) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly step 2/5: pick and place bread (%s)", bread_target_model_.c_str());
      if (!run_endpoint_step(ManufacturingTarget::Bread, bread_target_model_, [&]() {return runBreadPlace();})) {
        success = false;
      } else if (endpoint_order == manufacturing_task::hotdogAssemblyStepOrder(ManufacturingTarget::Bread)) {
        RCLCPP_INFO(get_logger(), "New York hotdog assembly stopped at %s endpoint", task_presets::targetName(ManufacturingTarget::Bread));
        restore_state();
        return true;
      }
    }

    if (success) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly step 3/5: pick and place sausage (%s)", sausage_target_model_.c_str());
      if (!run_endpoint_step(ManufacturingTarget::Sausage, sausage_target_model_, [&]() {return runSausagePlace();})) {
        success = false;
      } else if (endpoint_order == manufacturing_task::hotdogAssemblyStepOrder(ManufacturingTarget::Sausage)) {
        RCLCPP_INFO(get_logger(), "New York hotdog assembly stopped at %s endpoint", task_presets::targetName(ManufacturingTarget::Sausage));
        restore_state();
        return true;
      }
    }

    if (success) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly step 4/5: pick, aim, and squeeze ketchup (%s)", ketchup_target_model_.c_str());
      if (!run_endpoint_step(ManufacturingTarget::Ketchup, ketchup_target_model_, [&]() {return runKetchupSqueeze();})) {
        success = false;
      } else if (endpoint_order == manufacturing_task::hotdogAssemblyStepOrder(ManufacturingTarget::Ketchup)) {
        RCLCPP_INFO(get_logger(), "New York hotdog assembly stopped at %s endpoint", task_presets::targetName(ManufacturingTarget::Ketchup));
        restore_state();
        return true;
      }
    }

    if (success) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly step 5/5: place completed hotdog at pickup zone");
      has_play_to_stage_ = saved_has_play_to_stage;
      play_to_stage_ = saved_play_to_stage;
      if (!runCompletedHotdogPlace()) {
        success = false;
      }
    }

    if (success && !shouldStopAtOrBefore(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly final step: return left arm home");
      success = runSingleArmReturnHome(
        ManufacturingTarget::Hotdog,
        ArmSide::Left,
        left_arm_group_,
        left_tcp_link_,
        "Final left arm");
    }

    if (success) {
      success = validateFinalHotdogPlacement();
    }

    if (success) {
      RCLCPP_INFO(get_logger(), "New York hotdog assembly completed");
    }

    restore_state();
    return success;
}

bool HotdogMakingNode::runBeverageCanServe(ManufacturingTarget beverage_target)
{
    RCLCPP_INFO(get_logger(), "Beverage can serving started: task=%s", task_presets::targetName(beverage_target));

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
    if (!loadBeverageServeTargets(beverage_target, beverage_target_model, beverage_target_object, pickup_zone)) {
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

    manufacturing_task::logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left initial");
    manufacturing_task::logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right initial");

    // 음료 task의 전체 흐름은 pick -> handoff -> place -> validate 순서로 조립한다.
    const MotionStepResult handoff_result = runBeverageHandoffStage(
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

    const MotionStepResult place_result = runBeveragePlaceStage(
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

    RCLCPP_INFO(get_logger(), "Beverage %s serving completed", task_presets::targetName(beverage_target));
  return true;
}

// ---------------------------------------------------------------------------
// 핫도그 재료 pick/place 호출부
// ---------------------------------------------------------------------------

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
      const bool requested_has_play_to_stage = has_play_to_stage_;
      const auto requested_play_to_stage = play_to_stage_;
      has_play_to_stage_ = true;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool bread_pick_ok = runBreadPick();
      has_play_to_stage_ = requested_has_play_to_stage;
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
    const auto motions = makeMotionPrimitives();

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
        references.has_case_position = true;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        const geometry_msgs::msg::Pose work_pose =
          makePoseFromWaypointPreset(get_logger(), *work_preset, references, "Bread place work");
        if (!motions.moveToPose(left_arm, work_pose, left_tcp_link_, "bread place work pose", cartesian_min_duration_sec_))
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
    if (!motions.gripperNamedTarget(left_gripper, gripper_open_target_, "bread place gripper open"))
    {
      return false;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});

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
      const bool requested_has_play_to_stage = has_play_to_stage_;
      const auto requested_play_to_stage = play_to_stage_;
      has_play_to_stage_ = true;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool sausage_pick_ok = runSausagePick();
      has_play_to_stage_ = requested_has_play_to_stage;
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
    const auto motions = makeMotionPrimitives();

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
    geometry_msgs::msg::Pose left_work_pose;
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
        references.has_case_position = true;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        references.has_target_position = true;
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
        const bool sausage_work_ok = motions.moveToPoseWithScaling(left_arm, work_pose, left_tcp_link_, "sausage place work pose", previous_velocity_scaling, previous_acceleration_scaling, sausage_transport_velocity_scaling, sausage_transport_acceleration_scaling, cartesian_min_duration_sec_);
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
        left_work_pose_configured,
        left_work_pose,
        place_approach_height_,
        case_sausage_place_clearance_);

    if (sausage_place_plan.approach_reuses_completed_work_pose) {
      RCLCPP_INFO(get_logger(), "Sausage place: already at approach pose from work stage");
    } else {
      RCLCPP_INFO(get_logger(), "Sausage place: moving to approach pose");
      if (!motions.moveToPose(left_arm, sausage_place_plan.approach_pose, left_tcp_link_, "sausage place approach pose", 0.0))
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
      if (!motions.cartesianMoveToPose(left_arm, sausage_place_plan.release_pose, "sausage place lower", cartesian_avoid_collisions_))
      {
        return false;
      }
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place release pose");

    RCLCPP_INFO(get_logger(), "Sausage place: opening left gripper");
    if (!motions.gripperNamedTarget(left_gripper, gripper_open_target_, "sausage place gripper open"))
    {
      return false;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});

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

    RCLCPP_INFO(get_logger(), "Sausage place: vertical retreat before any home/ready motion");
    if (!motions.cartesianMoveToPose(left_arm, sausage_place_plan.approach_pose, "sausage place vertical retreat", false))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place vertical retreat");

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

// ---------------------------------------------------------------------------
// 케첩 도포 호출부
// ---------------------------------------------------------------------------

MotionStepResult HotdogMakingNode::runKetchupPickStageIfNeeded()
{
    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const bool requested_has_play_to_stage = has_play_to_stage_;
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_has_play_to_stage &&
        stageOrder(requested_play_to_stage) > stageOrder(ManufacturingStage::Pick))
      {
        has_play_to_stage_ = false;
      }
      const bool ketchup_pick_ok = runKetchupPick();
      has_play_to_stage_ = requested_has_play_to_stage;
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
    const auto motions = makeMotionPrimitives();

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
      if (!motions.moveToPose(left_arm, aim_pose, left_tcp_link_, "ketchup aim pose"))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup aim pose");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "aim")) {
        return true;
      }

      if (enable_ketchup_squeeze_gripper_) {
        if (!motions.gripperJointPosition(left_gripper, "Ketchup squeeze", "squeeze", ketchup_squeeze_gripper_position_))
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
      if (!motions.cartesianMoveToPose(left_arm, squeeze_pose, "ketchup squeeze line", cartesian_avoid_collisions_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup squeeze pose");
      if (enable_ketchup_squeeze_gripper_) {
        if (task_presets::kLeftKetchupPickTuning.gripper_close.enabled) {
          if (!motions.gripperJointPosition(left_gripper, "Ketchup squeeze", "release squeeze pressure", task_presets::kLeftKetchupPickTuning.gripper_close.joint_position))
          {
            return false;
          }
        } else {
          RCLCPP_INFO(
            get_logger(),
            "Ketchup squeeze: reopening gripper to named grasp target '%s'",
            gripper_grasp_target_.c_str());
          if (!motions.gripperNamedTarget(left_gripper, gripper_grasp_target_, "ketchup squeeze release pressure"))
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
    if (!motions.cartesianMoveToPose(left_arm, post_squeeze_clear_pose, "ketchup post-squeeze vertical clearance", cartesian_avoid_collisions_))
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
    if (!motions.moveToPose(left_arm, return_lift_pose, left_tcp_link_, "ketchup return lift pose"))
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
    if (!motions.cartesianMoveToPose(left_arm, return_pose, "ketchup return place pose", cartesian_avoid_collisions_))
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

    if (!motions.gripperPickAction(left_gripper, "Ketchup place", task_presets::kLeftKetchupPickTuning, GripperPickAction::Open))
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
    if (!motions.cartesianMoveToPose(left_arm, post_release_retreat_plan.horizontal_retreat_pose, "ketchup horizontal release retreat", cartesian_avoid_collisions_))
    {
      restore_transient_place_collisions();
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup horizontal release retreat");

    RCLCPP_INFO(get_logger(), "Ketchup place: extra clear retreat before restoring strict collisions");
    if (!motions.cartesianMoveToPose(left_arm, post_release_retreat_plan.clear_retreat_pose, "ketchup extra clear retreat", false))
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

// ---------------------------------------------------------------------------
// 완성 핫도그 pickup zone 배치 호출부
// ---------------------------------------------------------------------------

MotionStepResult HotdogMakingNode::runCompletedHotdogCarryWaypoints(
    moveit::planning_interface::MoveGroupInterface & right_arm,
    const geometry_msgs::msg::Pose & current_pose,
    const geometry_msgs::msg::Pose & release_pose,
    bool release_pose_preset_configured,
    double carry_min_duration_sec)
{
    const auto motions = makeMotionPrimitives();

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
      if (!motions.moveToPose(right_arm, waypoint_pose, right_tcp_link_, std::string("completed hotdog pickup ") + waypoint_name, carry_min_duration_sec))
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
      if (!motions.moveToPose(right_arm, midpoint_pose, right_tcp_link_, "completed hotdog pickup auto midpoint", carry_min_duration_sec))
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
    const auto motions = makeMotionPrimitives();

    RCLCPP_INFO(get_logger(), "Completed hotdog place: MoveIt carry to pickup approach");
    if (!motions.moveToPose(right_arm, approach_pose, right_tcp_link_, "completed hotdog pickup approach pose", carry_min_duration_sec))
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
    if (!motions.cartesianMoveToPose(right_arm, release_pose, "completed hotdog pickup release_pose", cartesian_avoid_collisions_, carry_min_duration_sec))
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
    const auto motions = makeMotionPrimitives();

    RCLCPP_INFO(get_logger(), "Completed hotdog place: opening right gripper");
    if (!motions.gripperPickAction(right_gripper, "Completed hotdog place", task_presets::kRightCasePickTuning, GripperPickAction::Open))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});
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
      if (!motions.cartesianMoveToPose(right_arm, retreat_pose, "completed hotdog pickup retreat", cartesian_avoid_collisions_, carry_min_duration_sec))
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

// ---------------------------------------------------------------------------
// 음료 제공 호출부
// ---------------------------------------------------------------------------

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
      const bool requested_has_play_to_stage = has_play_to_stage_;
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_has_play_to_stage &&
        stageOrder(requested_play_to_stage) > stageOrder(ManufacturingStage::Pick))
      {
        has_play_to_stage_ = true;
        play_to_stage_ = ManufacturingStage::Pick;
      }
      const bool pick_ok = runBeverageCanPick(beverage_target);
      has_play_to_stage_ = requested_has_play_to_stage;
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
    const auto motions = makeMotionPrimitives();

    const BeverageHandoffPlan handoff_plan =
      makeBeverageHandoffPlan(
        get_logger(),
        beverage_target,
        beverage_target_object,
        left_arm.getCurrentPose(left_tcp_link_).pose);

    rememberJointTargetIfConfigured(left_arm, left_ready_pose_name_, left_ready_joints_);
    RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm to ready pose before handoff");
    if (!motions.moveToNamed(left_arm, left_ready_pose_name_, "beverage left ready before handoff"))
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
    if (!motions.moveToPose(left_arm, handoff_plan.left_handoff_pose, left_tcp_link_, "beverage left handoff pose"))
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
    if (!motions.moveToNamed(right_arm, right_ready_pose_name_, "beverage right ready before receive"))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right ready");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "right_ready")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to pre-receive pose");
    if (!motions.moveToPose(right_arm, handoff_plan.right_pre_receive_pose, right_tcp_link_, "beverage right pre-receive pose"))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right pre-receive");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "pre_receive")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper before receive");
    if (!motions.gripperPickAction(right_gripper, "Beverage receive", task_presets::kRightBeverageCanReceiveTuning, GripperPickAction::Open))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive_open")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: planning right arm to receive grasp pose");
    if (!motions.moveToPose(right_arm, handoff_plan.right_receive_pose, right_tcp_link_, "beverage right receive pose"))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right receive");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive")) {
      return MotionStepResult::Stop;
    }

    if (!motions.gripperPickAction(right_gripper, "Beverage receive", task_presets::kRightBeverageCanReceiveTuning, GripperPickAction::Close))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});
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
    if (!motions.gripperPickAction(left_gripper, "Beverage handoff release", task_presets::kLeftBeverageCanPickTuning, GripperPickAction::Open))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});

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
    if (!motions.cartesianMoveToPose(left_arm, left_pull_out_pose, "beverage left handoff pull-out", cartesian_avoid_collisions_))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left pull-out");
    if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_pull_out")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm away after handoff");
    rememberJointTargetIfConfigured(left_arm, left_ready_pose_name_, left_ready_joints_);
    if (!motions.moveToNamed(left_arm, left_ready_pose_name_, "beverage left retreat after handoff"))
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
    const auto motions = makeMotionPrimitives();

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
    if (!motions.moveToPose(right_arm, approach_pose, right_tcp_link_, "beverage pickup approach"))
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
      if (!motions.cartesianMoveToPose(right_arm, release_pose, "beverage pickup release", cartesian_avoid_collisions_))
      {
        return MotionStepResult::Failed;
      }
    } else if (!motions.moveToPose(right_arm, release_pose, right_tcp_link_, "beverage pickup release"))
    {
      return MotionStepResult::Failed;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage pickup release");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release_pose")) {
      return MotionStepResult::Stop;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper");
    if (!motions.gripperPickAction(right_gripper, "Beverage place", task_presets::kRightBeverageCanReceiveTuning, GripperPickAction::Open))
    {
      return MotionStepResult::Failed;
    }
    rclcpp::sleep_for(std::chrono::milliseconds{300});
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
      if (!motions.cartesianMoveToPose(right_arm, approach_pose, "beverage pickup retreat", cartesian_avoid_collisions_))
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

}  // namespace ddooby_controller
