#include "ddooby_controller/task/manufacturing_place_planner.hpp"

#include <algorithm>
#include <cmath>

#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/task/manufacturing_pick_planner.hpp"
#include "ddooby_controller/task/manufacturing_pose_utils.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"

namespace ddooby_controller::manufacturing_task
{

SausagePlacePlan makeSausagePlacePlan(
  const rclcpp::Logger & logger,
  const TargetObject & sausage_target,
  const TargetObject & bread_target,
  const TargetObject & case_target,
  const Eigen::Vector3d & held_case_center,
  const geometry_msgs::msg::Pose & left_current_pose,
  bool has_completed_left_work_pose,
  const geometry_msgs::msg::Pose & completed_left_work_pose,
  double place_approach_height_m,
  double case_sausage_place_clearance_m)
{
  const double sausage_thickness = topDownPlaceThickness(sausage_target);
  const double release_z =
    held_case_center.z() +
    case_target.size.z() * 0.5 +
    bread_target.size.z() +
    sausage_thickness * 0.5 +
    case_sausage_place_clearance_m -
    task_presets::kLeftSausagePickTuning.grasp_tcp_z_offset_m;

  SausagePlacePlan plan;
  plan.approach_pose = left_current_pose;
  plan.approach_pose.position.x = held_case_center.x();
  plan.approach_pose.position.y = held_case_center.y();
  plan.approach_pose.position.z = release_z + place_approach_height_m;

  plan.release_pose = plan.approach_pose;
  plan.release_pose.position.z = release_z;

  const auto * work_preset =
    task_presets::findStageWaypointPosePreset(
      task_presets::ManufacturingTarget::Sausage,
      task_presets::ArmSide::Left,
      task_presets::ManufacturingStage::Work,
      "work");
  const auto * place_preset =
    task_presets::findStageWaypointPosePreset(
      task_presets::ManufacturingTarget::Sausage,
      task_presets::ArmSide::Left,
      task_presets::ManufacturingStage::Place,
      "release");

  if (work_preset != nullptr) {
    if (has_completed_left_work_pose) {
      plan.approach_pose = completed_left_work_pose;
      plan.approach_reuses_completed_work_pose = true;
      RCLCPP_INFO(logger, "Sausage place approach reuses completed work pose");
    } else {
      PoseAxisReferenceValues references;
      references.has_case_position = true;
      references.case_position = held_case_center;
      references.has_target_position = true;
      references.target_position = sausage_target.xyz;
      plan.approach_pose =
        makePoseFromWaypointPreset(
          logger, *work_preset, references, "Sausage place approach");
      RCLCPP_INFO(logger, "Sausage place approach pose preset applied");
    }
  } else {
    RCLCPP_INFO(
      logger,
      "Sausage place auto approach pose: xyz=[%.3f %.3f %.3f]",
      plan.approach_pose.position.x,
      plan.approach_pose.position.y,
      plan.approach_pose.position.z);
  }

  if (place_preset != nullptr) {
    PoseAxisReferenceValues references;
    references.has_case_position = true;
    references.case_position = held_case_center;
    references.has_target_position = true;
    references.target_position = sausage_target.xyz;
    plan.release_pose =
      makePoseFromWaypointPreset(logger, *place_preset, references, "Sausage place release");
    RCLCPP_INFO(logger, "Sausage place release pose preset applied");
  } else {
    plan.release_pose.position.x = plan.approach_pose.position.x;
    plan.release_pose.position.y =
      plan.approach_pose.position.y + task_presets::kLeftSausageReleaseYOffsetFromApproachM;
    plan.release_pose.orientation = plan.approach_pose.orientation;
    RCLCPP_INFO(
      logger,
      "Sausage place auto release pose: xyz=[%.3f %.3f %.3f], y_offset_from_approach=%.3f",
      plan.release_pose.position.x,
      plan.release_pose.position.y,
      plan.release_pose.position.z,
      task_presets::kLeftSausageReleaseYOffsetFromApproachM);
  }

  if (has_completed_left_work_pose && place_preset == nullptr) {
    RCLCPP_INFO(
      logger,
      "Sausage place release keeps completed work xy and lowers vertically to computed release height");
  }

  return plan;
}

KetchupSqueezePlan makeKetchupSqueezePlan(
  const rclcpp::Logger & logger,
  const TargetObject & sausage_target,
  const TargetObject & bread_target,
  const TargetObject & case_target,
  const Eigen::Vector3d & held_case_center,
  const geometry_msgs::msg::Pose & left_current_pose,
  double ketchup_squeeze_height_m,
  double ketchup_squeeze_length_m)
{
  const double sausage_thickness = topDownPlaceThickness(sausage_target);
  const double squeeze_z =
    held_case_center.z() +
    case_target.size.z() * 0.5 +
    bread_target.size.z() +
    sausage_thickness +
    ketchup_squeeze_height_m;

  const double squeeze_length = std::max(0.0, ketchup_squeeze_length_m);
  const Eigen::Vector3d squeeze_axis = Eigen::Vector3d::UnitX();
  const Eigen::Vector3d start_position = held_case_center - squeeze_axis * (squeeze_length * 0.5);
  const Eigen::Vector3d end_position = held_case_center + squeeze_axis * (squeeze_length * 0.5);

  KetchupSqueezePlan plan;
  plan.aim_pose = left_current_pose;
  plan.aim_pose.position.x = start_position.x();
  plan.aim_pose.position.y = start_position.y();
  plan.aim_pose.position.z = squeeze_z;

  plan.squeeze_pose = plan.aim_pose;
  plan.squeeze_pose.position.x = end_position.x();
  plan.squeeze_pose.position.y = end_position.y();
  plan.squeeze_pose.position.z = squeeze_z;

  const auto * work_stage_preset =
    task_presets::findStageWaypointPosePreset(
      task_presets::ManufacturingTarget::Ketchup,
      task_presets::ArmSide::Left,
      task_presets::ManufacturingStage::Work,
      "work");
  const auto * aim_preset =
    task_presets::findStageWaypointPosePreset(
      task_presets::ManufacturingTarget::Ketchup,
      task_presets::ArmSide::Left,
      task_presets::ManufacturingStage::Work,
      "aim");
  const auto * squeeze_preset =
    task_presets::findStageWaypointPosePreset(
      task_presets::ManufacturingTarget::Ketchup,
      task_presets::ArmSide::Left,
      task_presets::ManufacturingStage::Work,
      "squeeze");

  if (aim_preset != nullptr) {
    plan.aim_pose = makePoseFromPreset(aim_preset->pose);
    plan.squeeze_pose.orientation = plan.aim_pose.orientation;
    plan.squeeze_pose.position.x = plan.aim_pose.position.x + squeeze_axis.x() * squeeze_length;
    plan.squeeze_pose.position.y = plan.aim_pose.position.y + squeeze_axis.y() * squeeze_length;
    plan.squeeze_pose.position.z = plan.aim_pose.position.z;
    RCLCPP_INFO(logger, "Ketchup work/aim waypoint pose preset applied");
  } else if (work_stage_preset != nullptr) {
    plan.aim_pose = makePoseFromPreset(work_stage_preset->pose);
    plan.squeeze_pose.orientation = plan.aim_pose.orientation;
    plan.squeeze_pose.position.x = plan.aim_pose.position.x + squeeze_axis.x() * squeeze_length;
    plan.squeeze_pose.position.y = plan.aim_pose.position.y + squeeze_axis.y() * squeeze_length;
    plan.squeeze_pose.position.z = plan.aim_pose.position.z;
    RCLCPP_INFO(logger, "Ketchup work/work waypoint pose preset used as aim pose");
  } else {
    RCLCPP_INFO(
      logger,
      "Ketchup auto aim pose: xyz=[%.3f %.3f %.3f]",
      plan.aim_pose.position.x,
      plan.aim_pose.position.y,
      plan.aim_pose.position.z);
  }

  if (squeeze_preset != nullptr) {
    plan.squeeze_pose = makePoseFromPreset(squeeze_preset->pose);
    RCLCPP_INFO(logger, "Ketchup work/squeeze waypoint pose preset applied");
  } else {
    RCLCPP_INFO(
      logger,
      "Ketchup auto squeeze pose: xyz=[%.3f %.3f %.3f]",
      plan.squeeze_pose.position.x,
      plan.squeeze_pose.position.y,
      plan.squeeze_pose.position.z);
  }

  return plan;
}

KetchupReturnPlacePlan makeKetchupReturnPlacePlan(
  const rclcpp::Logger & logger,
  const TargetObject & ketchup_target,
  double ketchup_pre_grasp_distance_m,
  double lift_height_m)
{
  const TargetObject ketchup_grasp_target = makeKetchupBodyGraspTarget(ketchup_target);
  PickPlan pick_plan =
    makeHorizontalPickPlan(
      ketchup_grasp_target,
      Eigen::Vector3d::UnitX(),
      Eigen::Vector3d::UnitY(),
      ketchup_pre_grasp_distance_m,
      lift_height_m,
      task_presets::kLeftKetchupPickTuning.grasp_tcp_z_offset_m);

  KetchupReturnPlacePlan plan;
  plan.return_pose = pick_plan.grasp_pose;

  if (const auto * pick_pre_grasp_preset =
      task_presets::findStageWaypointPosePreset(
        task_presets::ManufacturingTarget::Ketchup,
        task_presets::ArmSide::Left,
        task_presets::ManufacturingStage::Pick,
        "pre_grasp"))
  {
    const geometry_msgs::msg::Pose pick_orientation_pose =
      makePoseFromPreset(pick_pre_grasp_preset->pose);
    plan.return_pose.orientation = pick_orientation_pose.orientation;
    RCLCPP_INFO(logger, "Ketchup return place uses pick pre-grasp orientation");
  }

  plan.lift_pose = plan.return_pose;
  if (std::abs(task_presets::kLeftKetchupPickWristRollDeg) > 1e-9) {
    applyLocalTcpZRoll(plan.return_pose, task_presets::kLeftKetchupPickWristRollDeg);
    applyLocalTcpZRoll(plan.lift_pose, task_presets::kLeftKetchupPickWristRollDeg);
    RCLCPP_INFO(
      logger,
      "Ketchup return place uses pick-equivalent wrist roll correction: %.2f deg",
      task_presets::kLeftKetchupPickWristRollDeg);
  }
  plan.lift_pose.position.z += task_presets::kLeftKetchupReturnLiftHeightM;

  if (const auto * return_preset =
      task_presets::findStageWaypointPosePreset(
        task_presets::ManufacturingTarget::Ketchup,
        task_presets::ArmSide::Left,
        task_presets::ManufacturingStage::Place,
        "return_pose"))
  {
    plan.return_pose = makePoseFromPreset(return_preset->pose);
    plan.lift_pose = plan.return_pose;
    plan.lift_pose.position.z += task_presets::kLeftKetchupReturnLiftHeightM;
    RCLCPP_INFO(logger, "Ketchup return place pose preset applied");
  } else {
    RCLCPP_INFO(
      logger,
      "Ketchup auto return place pose: xyz=[%.3f %.3f %.3f]",
      plan.return_pose.position.x,
      plan.return_pose.position.y,
      plan.return_pose.position.z);
  }

  return plan;
}

KetchupPostReleaseRetreatPlan makeKetchupPostReleaseRetreatPlan(
  const geometry_msgs::msg::Pose & return_pose,
  const geometry_msgs::msg::Pose & return_lift_pose)
{
  KetchupPostReleaseRetreatPlan plan;
  plan.horizontal_retreat_pose = return_pose;
  plan.horizontal_retreat_pose.position.x -= 0.120;
  plan.horizontal_retreat_pose.position.z += 0.010;

  plan.clear_retreat_pose = plan.horizontal_retreat_pose;
  plan.clear_retreat_pose.position.z = return_lift_pose.position.z + 0.060;
  return plan;
}

CompletedHotdogPlacePlan makeCompletedHotdogPlacePlan(
  const rclcpp::Logger & logger,
  const TargetObject & pickup_zone,
  const TargetObject & case_target,
  const geometry_msgs::msg::Pose & current_pose)
{
  const Eigen::Matrix3d tcp_rotation = poseOrientation(current_pose).toRotationMatrix();
  const Eigen::Vector3d tcp_z = tcp_rotation.col(2).normalized();

  const Eigen::Matrix3d pickup_rotation = rotationFromRpy(pickup_zone.rpy);
  const Eigen::Vector3d pickup_center = pickup_zone.xyz + pickup_rotation * pickup_zone.local_center;
  const double pickup_top_z = pickup_center.z() + pickup_zone.size.z() * 0.5;
  const Eigen::Vector3d desired_case_center(
    pickup_center.x(),
    pickup_center.y(),
    pickup_top_z + case_target.size.z() * 0.5 +
    task_presets::kCompletedHotdogPickupPlaceClearanceM);

  CompletedHotdogPlacePlan plan;
  plan.release_pose = current_pose;
  const Eigen::Vector3d release_tcp_position =
    desired_case_center -
    tcp_z * (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
  plan.release_pose.position.x = release_tcp_position.x();
  plan.release_pose.position.y = release_tcp_position.y();
  plan.release_pose.position.z = release_tcp_position.z();

  plan.approach_pose = plan.release_pose;
  plan.approach_pose.position.z += task_presets::kCompletedHotdogPickupApproachHeightM;

  if (const auto * release_pose_preset =
      task_presets::findStageWaypointPosePreset(
        task_presets::ManufacturingTarget::Hotdog,
        task_presets::ArmSide::Right,
        task_presets::ManufacturingStage::Place,
        "release_pose"))
  {
    plan.release_pose_preset_configured = true;
    plan.release_pose = makePoseFromPreset(release_pose_preset->pose);
    plan.approach_pose = plan.release_pose;
    plan.approach_pose.position.z += task_presets::kCompletedHotdogPickupApproachHeightM;
    RCLCPP_INFO(logger, "Completed hotdog place release_pose waypoint pose preset applied");
  } else {
    plan.release_pose.orientation = plan.approach_pose.orientation;
    RCLCPP_INFO(
      logger,
      "Completed hotdog auto approach pose: xyz=[%.3f %.3f %.3f]",
      plan.approach_pose.position.x,
      plan.approach_pose.position.y,
      plan.approach_pose.position.z);
    RCLCPP_INFO(
      logger,
      "Completed hotdog auto release pose: xyz=[%.3f %.3f %.3f]",
      plan.release_pose.position.x,
      plan.release_pose.position.y,
      plan.release_pose.position.z);
  }

  return plan;
}

BeverageHandoffPlan makeBeverageHandoffPlan(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget beverage_target,
  const TargetObject & beverage_target_object,
  const geometry_msgs::msg::Pose & left_current_pose)
{
  BeverageHandoffPlan plan;
  plan.left_handoff_pose = left_current_pose;
  if (const auto * left_handoff_preset =
      task_presets::findStageWaypointPosePreset(
        beverage_target,
        task_presets::ArmSide::Left,
        task_presets::ManufacturingStage::Work,
        "handoff"))
  {
    plan.left_handoff_pose = makePoseFromPreset(left_handoff_preset->pose);
    RCLCPP_INFO(logger, "Beverage left handoff waypoint pose preset applied");
  }

  plan.right_receive_pose = plan.left_handoff_pose;
  plan.right_receive_pose.position.z += task_presets::kBeverageHandoffRightFromLeftZOffsetM;
  PickPlan right_receive_plan =
    makeHorizontalPickPlan(
      TargetObject{
        "beverage_handoff",
        "",
        Eigen::Vector3d(
          plan.right_receive_pose.position.x,
          plan.right_receive_pose.position.y,
          plan.right_receive_pose.position.z),
        Eigen::Vector3d::Zero(),
        Eigen::Vector3d::Zero(),
        beverage_target_object.size},
      -Eigen::Vector3d::UnitY(),
      Eigen::Vector3d::UnitX(),
      0.0,
      0.0,
      task_presets::kRightBeverageCanReceiveTuning.grasp_tcp_z_offset_m);
  plan.right_receive_pose.orientation = right_receive_plan.grasp_pose.orientation;

  plan.right_pre_receive_pose = plan.right_receive_pose;
  if (const auto * right_pre_receive_preset =
      task_presets::findStageWaypointPosePreset(
        beverage_target,
        task_presets::ArmSide::Right,
        task_presets::ManufacturingStage::Work,
        "pre_receive"))
  {
    plan.right_pre_receive_pose = makePoseFromPreset(right_pre_receive_preset->pose);
    plan.right_pre_receive_pose_preset_enabled = true;
    RCLCPP_INFO(logger, "Beverage right pre-receive waypoint pose preset applied");
  }

  if (plan.right_pre_receive_pose_preset_enabled) {
    plan.right_receive_pose = plan.right_pre_receive_pose;
    plan.right_receive_pose.position.x = plan.left_handoff_pose.position.x;
    plan.right_receive_pose.position.y = plan.left_handoff_pose.position.y;
    plan.right_receive_pose.position.z =
      plan.left_handoff_pose.position.z + task_presets::kBeverageHandoffRightFromLeftZOffsetM;
    RCLCPP_INFO(
      logger,
      "Beverage right receive pose centered on handoff can: xyz=[%.3f %.3f %.3f]",
      plan.right_receive_pose.position.x,
      plan.right_receive_pose.position.y,
      plan.right_receive_pose.position.z);
  }

  return plan;
}

BeveragePickupPlacePlan makeBeveragePickupPlacePlan(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget beverage_target,
  const TargetObject & beverage_target_object,
  const TargetObject & pickup_zone,
  const geometry_msgs::msg::Pose & right_current_pose)
{
  const Eigen::Matrix3d pickup_rotation = rotationFromRpy(pickup_zone.rpy);
  const Eigen::Vector3d pickup_center =
    pickup_zone.xyz + pickup_rotation * pickup_zone.local_center;
  const double pickup_top_z = pickup_center.z() + pickup_zone.size.z() * 0.5;

  BeveragePickupPlacePlan plan;
  plan.release_pose = right_current_pose;
  plan.release_pose.position.x = pickup_center.x();
  plan.release_pose.position.y = pickup_center.y() + beveragePickupZoneYOffset(beverage_target);
  plan.release_pose.position.z =
    pickup_top_z +
    beverage_target_object.size.z() * 0.5 +
    task_presets::kBeveragePickupPlaceClearanceM +
    task_presets::kRightBeverageCanReceiveWorldZOffsetM;

  const auto * approach_preset =
    task_presets::findStageWaypointPosePreset(
      beverage_target,
      task_presets::ArmSide::Right,
      task_presets::ManufacturingStage::Place,
      "approach");
  plan.approach_preset_enabled = approach_preset != nullptr && approach_preset->pose.enabled;

  const auto * release_preset =
    task_presets::findStageWaypointPosePreset(
      beverage_target,
      task_presets::ArmSide::Right,
      task_presets::ManufacturingStage::Place,
      "release_pose");
  plan.release_preset_enabled = release_preset != nullptr && release_preset->pose.enabled;

  if (plan.release_preset_enabled) {
    plan.release_pose = makePoseFromPreset(release_preset->pose);
    RCLCPP_INFO(logger, "Beverage pickup release_pose waypoint pose preset applied");
  } else if (plan.approach_preset_enabled) {
    const auto guide_pose = makePoseFromPreset(approach_preset->pose);
    plan.release_pose.position.x = guide_pose.position.x;
    plan.release_pose.position.y = guide_pose.position.y;
    plan.release_pose.orientation = guide_pose.orientation;
    RCLCPP_INFO(
      logger,
      "Beverage pickup release_pose uses approach waypoint xy/orientation with computed z");
  } else {
    PickPlan place_plan =
      makeHorizontalPickPlan(
        TargetObject{
          "beverage_pickup_place",
          "",
          Eigen::Vector3d(
            plan.release_pose.position.x,
            plan.release_pose.position.y,
            plan.release_pose.position.z),
          Eigen::Vector3d::Zero(),
          Eigen::Vector3d::Zero(),
          beverage_target_object.size},
        -Eigen::Vector3d::UnitY(),
        Eigen::Vector3d::UnitX(),
        0.0,
        0.0,
        task_presets::kRightBeverageCanReceiveTuning.grasp_tcp_z_offset_m);
    plan.release_pose.orientation = place_plan.grasp_pose.orientation;
  }

  plan.approach_pose = plan.release_pose;
  plan.approach_pose.position.z += task_presets::kBeveragePickupApproachHeightM;
  if (plan.approach_preset_enabled) {
    plan.approach_pose = makePoseFromPreset(approach_preset->pose);
    RCLCPP_INFO(logger, "Beverage pickup approach waypoint pose preset applied");
  }

  return plan;
}

}  // namespace ddooby_controller::manufacturing_task
