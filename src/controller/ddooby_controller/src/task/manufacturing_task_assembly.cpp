#include "manufacturing_task_node_private.hpp"

#include <optional>
#include <string>

#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/task/manufacturing_task_common.hpp"
#include "ddooby_controller/task/manufacturing_task_sequence_runner.hpp"
#include "ddooby_controller/control/moveit_task_utils.hpp"

namespace ddooby_controller
{

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
    const auto saved_play_to_stage = play_to_stage_;

    auto restore_state = [&]() {
      target_model_ = saved_target_model;
      start_stage_ = saved_start_stage;
      play_to_stage_ = saved_play_to_stage;
    };

    auto run_endpoint_step = [&](ManufacturingTarget step, const std::string & model, auto && runner) {
      target_model_ = model;
      play_to_stage_ = step == endpoint ? saved_play_to_stage : std::optional<ManufacturingStage>{};
      return runner();
    };

    start_stage_ = ManufacturingStage::Home;

    // 전체 핫도그 제조 흐름은 여기에서만 조립한다.
    manufacturing_task::TaskSequenceRunner sequence_runner(get_logger());
    const bool success = sequence_runner.runHotdogAssembly(
      endpoint,
      {
        manufacturing_task::HotdogAssemblyStep{
          ManufacturingTarget::Case,
          case_target_model_,
          "pick and present case",
          [&]() {return run_endpoint_step(ManufacturingTarget::Case, case_target_model_, [&]() {return runCasePick();});}},
        manufacturing_task::HotdogAssemblyStep{
          ManufacturingTarget::Bread,
          bread_target_model_,
          "pick and place bread",
          [&]() {return run_endpoint_step(ManufacturingTarget::Bread, bread_target_model_, [&]() {return runBreadPlace();});}},
        manufacturing_task::HotdogAssemblyStep{
          ManufacturingTarget::Sausage,
          sausage_target_model_,
          "pick and place sausage",
          [&]() {return run_endpoint_step(ManufacturingTarget::Sausage, sausage_target_model_, [&]() {return runSausagePlace();});}},
        manufacturing_task::HotdogAssemblyStep{
          ManufacturingTarget::Ketchup,
          ketchup_target_model_,
          "pick, aim, and squeeze ketchup",
          [&]() {return run_endpoint_step(ManufacturingTarget::Ketchup, ketchup_target_model_, [&]() {return runKetchupSqueeze();});}},
      },
      [&]() {
        play_to_stage_ = saved_play_to_stage;
        return runCompletedHotdogPlace();
      },
      [&]() {
        if (shouldStopAtOrBefore(ManufacturingStage::Place)) {
          return true;
        }
        RCLCPP_INFO(get_logger(), "Hotdog assembly final step: return left arm home");
        return runSingleArmReturnHome(
          ManufacturingTarget::Hotdog,
          ArmSide::Left,
          left_arm_group_,
          left_tcp_link_,
          "Final left arm");
      },
      [&]() {return validateFinalHotdogPlacement();});

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

}  // namespace ddooby_controller
