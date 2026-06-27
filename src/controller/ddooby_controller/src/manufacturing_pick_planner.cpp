#include "ddooby_controller/manufacturing_pick_planner.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_layout_utils.hpp"
#include "ddooby_controller/manufacturing_pose_utils.hpp"

namespace ddooby_controller::manufacturing_task
{

const task_presets::TcpPosePreset * findPullOutPosePreset(
  task_presets::ManufacturingTarget target,
  task_presets::ArmSide arm)
{
  const auto * preset = task_presets::findStageWaypointPosePreset(
    target,
    arm,
    task_presets::ManufacturingStage::Pick,
    "pull_out");
  if (preset != nullptr) {
    return &preset->pose;
  }
  return nullptr;
}

void applyStageWaypointPosePreset(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget target,
  task_presets::ArmSide arm,
  task_presets::ManufacturingStage stage,
  const char * waypoint,
  geometry_msgs::msg::Pose & pose,
  const PoseAxisReferenceValues & references)
{
  const auto * preset = task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint);
  if (preset == nullptr) {
    return;
  }

  const std::string label =
    std::string(task_presets::stageName(stage)) + "." + waypoint;
  pose = makePoseFromWaypointPreset(logger, *preset, references, label.c_str());
}

bool hasStageWaypointPosePreset(
  task_presets::ManufacturingTarget target,
  task_presets::ArmSide arm,
  task_presets::ManufacturingStage stage,
  const char * waypoint)
{
  return task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint) != nullptr;
}

TargetObject loadTargetObject(
  const std::string & package_share_directory,
  const std::string & layout_path,
  const std::string & target_model)
{
  const std::string layout_text = readTextFile(layout_path);
  const std::string model_block = extractJsonObjectForModel(layout_text, target_model);

  TargetObject object;
  object.name = extractStringValue(model_block, "name");
  object.model_dir = extractStringValue(model_block, "model_dir");
  object.xyz = extractVector3Value(model_block, "xyz");
  object.rpy = extractVector3Value(model_block, "rpy");

  const std::string sdf_path =
    joinPath(joinPath(package_share_directory, "assets"), joinPath(object.model_dir, "model.sdf"));
  const std::vector<CollisionBox> collision_boxes = parseCollisionBoxes(readTextFile(sdf_path));
  if (collision_boxes.empty()) {
    throw std::runtime_error("target model '" + target_model + "' has no supported collision geometry");
  }

  Eigen::Vector3d local_min(
    std::numeric_limits<double>::infinity(),
    std::numeric_limits<double>::infinity(),
    std::numeric_limits<double>::infinity());
  Eigen::Vector3d local_max(
    -std::numeric_limits<double>::infinity(),
    -std::numeric_limits<double>::infinity(),
    -std::numeric_limits<double>::infinity());
  for (const CollisionBox & box : collision_boxes) {
    local_min = local_min.cwiseMin(box.center - box.size * 0.5);
    local_max = local_max.cwiseMax(box.center + box.size * 0.5);
  }

  object.local_center = (local_min + local_max) * 0.5;
  object.size = local_max - local_min;
  return object;
}

TargetObject makeKetchupBodyGraspTarget(const TargetObject & target)
{
  TargetObject body_target = target;

  // The ketchup model includes cap/nozzle collision geometry above the bottle.
  // Grasp pose generation should stay centered on the body cylinder so the
  // gripper does not chase the nozzle-biased overall bounds center.
  body_target.local_center = Eigen::Vector3d(0.0, 0.0, 0.0);
  body_target.size = Eigen::Vector3d(0.050, 0.050, 0.150);
  return body_target;
}

double topDownPlaceThickness(const TargetObject & target)
{
  return std::min({target.size.x(), target.size.y(), target.size.z()});
}

Eigen::Vector3d horizontalOrFallback(
  const Eigen::Vector3d & vector,
  const Eigen::Vector3d & fallback)
{
  Eigen::Vector3d horizontal(vector.x(), vector.y(), 0.0);
  if (horizontal.norm() < 1e-6) {
    horizontal = fallback;
  }
  return horizontal.normalized();
}

PickPlan makeTopDownPickPlan(
  const TargetObject & target,
  double pre_grasp_height,
  double lift_height,
  double grasp_tcp_z_offset_m)
{
  const Eigen::Matrix3d object_rotation = rotationFromRpy(target.rpy);
  const Eigen::Vector3d object_center = target.xyz + object_rotation * target.local_center;

  int principal_index = 0;
  double best_horizontal_span = -1.0;
  for (int index = 0; index < 3; ++index) {
    const Eigen::Vector3d world_axis = object_rotation.col(index);
    const double horizontal_projection =
      Eigen::Vector3d(world_axis.x(), world_axis.y(), 0.0).norm();
    const double horizontal_span = target.size[index] * horizontal_projection;
    if (horizontal_span > best_horizontal_span) {
      best_horizontal_span = horizontal_span;
      principal_index = index;
    }
  }

  Eigen::Vector3d principal_axis =
    horizontalOrFallback(object_rotation.col(principal_index), Eigen::Vector3d::UnitY());
  if (principal_axis.y() < 0.0) {
    principal_axis = -principal_axis;
  }

  Eigen::Vector3d closing_axis(-principal_axis.y(), principal_axis.x(), 0.0);
  if (closing_axis.x() < 0.0) {
    closing_axis = -closing_axis;
  }
  closing_axis.normalize();

  const Eigen::Vector3d tcp_y = closing_axis;
  const Eigen::Vector3d tcp_z = -Eigen::Vector3d::UnitZ();
  const Eigen::Vector3d tcp_x = tcp_y.cross(tcp_z).normalized();
  Eigen::Matrix3d tcp_rotation;
  tcp_rotation.col(0) = tcp_x;
  tcp_rotation.col(1) = tcp_y;
  tcp_rotation.col(2) = tcp_z;
  const Eigen::Quaterniond tcp_orientation(tcp_rotation);

  Eigen::Vector3d grasp_position = object_center;
  grasp_position += tcp_rotation * Eigen::Vector3d(0.0, 0.0, grasp_tcp_z_offset_m);

  Eigen::Vector3d pre_grasp_position = grasp_position;
  pre_grasp_position.z() += pre_grasp_height;

  Eigen::Vector3d lift_position = grasp_position;
  lift_position.z() += lift_height;

  return PickPlan{
    makePose(pre_grasp_position, tcp_orientation),
    makePose(grasp_position, tcp_orientation),
    makePose(lift_position, tcp_orientation),
    principal_axis,
    closing_axis};
}

PickPlan makeHorizontalPickPlan(
  const TargetObject & target,
  const Eigen::Vector3d & approach_axis,
  const Eigen::Vector3d & closing_axis_hint,
  double approach_distance,
  double lift_height,
  double grasp_tcp_z_offset_m)
{
  const Eigen::Matrix3d object_rotation = rotationFromRpy(target.rpy);
  const Eigen::Vector3d object_center = target.xyz + object_rotation * target.local_center;

  Eigen::Vector3d tcp_z = approach_axis;
  if (tcp_z.norm() < 1e-6) {
    tcp_z = Eigen::Vector3d::UnitX();
  }
  tcp_z.normalize();

  Eigen::Vector3d tcp_y = closing_axis_hint - tcp_z * closing_axis_hint.dot(tcp_z);
  if (tcp_y.norm() < 1e-6) {
    tcp_y = Eigen::Vector3d::UnitZ() - tcp_z * Eigen::Vector3d::UnitZ().dot(tcp_z);
  }
  if (tcp_y.norm() < 1e-6) {
    tcp_y = Eigen::Vector3d::UnitY() - tcp_z * Eigen::Vector3d::UnitY().dot(tcp_z);
  }
  tcp_y.normalize();

  const Eigen::Vector3d tcp_x = tcp_y.cross(tcp_z).normalized();
  Eigen::Matrix3d tcp_rotation;
  tcp_rotation.col(0) = tcp_x;
  tcp_rotation.col(1) = tcp_y;
  tcp_rotation.col(2) = tcp_z;
  const Eigen::Quaterniond tcp_orientation(tcp_rotation);

  Eigen::Vector3d grasp_position = object_center;
  grasp_position += tcp_rotation * Eigen::Vector3d(0.0, 0.0, grasp_tcp_z_offset_m);

  Eigen::Vector3d pre_grasp_position = grasp_position;
  pre_grasp_position -= tcp_z * approach_distance;

  Eigen::Vector3d lift_position = grasp_position;
  lift_position.z() += lift_height;

  return PickPlan{
    makePose(pre_grasp_position, tcp_orientation),
    makePose(grasp_position, tcp_orientation),
    makePose(lift_position, tcp_orientation),
    tcp_z,
    tcp_y};
}

void applyPickStageWaypointPresets(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget target_kind,
  task_presets::ArmSide arm,
  const TargetObject & target,
  double pre_grasp_height,
  double lift_height,
  PickPlan & pick_plan)
{
  const bool pre_grasp_pose_configured =
    hasStageWaypointPosePreset(target_kind, arm, task_presets::ManufacturingStage::Pick, "pre_grasp");
  const bool pick_pose_configured =
    hasStageWaypointPosePreset(target_kind, arm, task_presets::ManufacturingStage::Pick, "grasp");

  PoseAxisReferenceValues pick_axis_references;
  pick_axis_references.target_position = objectWorldCenter(target);
  if (pre_grasp_pose_configured) {
    applyStageWaypointPosePreset(
      logger,
      target_kind,
      arm,
      task_presets::ManufacturingStage::Pick,
      "pre_grasp",
      pick_plan.pre_grasp_pose,
      pick_axis_references);
  }
  if (pick_pose_configured) {
    applyStageWaypointPosePreset(
      logger,
      target_kind,
      arm,
      task_presets::ManufacturingStage::Pick,
      "grasp",
      pick_plan.grasp_pose,
      pick_axis_references);
  }
  if (!pre_grasp_pose_configured && pick_pose_configured) {
    pick_plan.pre_grasp_pose.position = pick_plan.grasp_pose.position;
    pick_plan.pre_grasp_pose.position.z += pre_grasp_height;
    pick_plan.pre_grasp_pose.orientation = pick_plan.grasp_pose.orientation;
    RCLCPP_INFO(logger, "Stage pose preset linked: pre_grasp derived from pick pose");
  }
  if (pre_grasp_pose_configured && !pick_pose_configured) {
    pick_plan.grasp_pose.orientation = pick_plan.pre_grasp_pose.orientation;
    RCLCPP_INFO(logger, "Stage pose preset linked: pick auto position uses pre_grasp orientation");
    if (target_kind == task_presets::ManufacturingTarget::Sausage) {
      pick_plan.grasp_pose.position.x = pick_plan.pre_grasp_pose.position.x;
      pick_plan.grasp_pose.position.y = pick_plan.pre_grasp_pose.position.y;
      pick_plan.lift_pose.position.x = pick_plan.pre_grasp_pose.position.x;
      pick_plan.lift_pose.position.y = pick_plan.pre_grasp_pose.position.y;
      RCLCPP_INFO(
        logger,
        "Sausage pick: reusing pre-grasp xy for grasp/lift to avoid extra lateral correction");
    }
  }
  if (pick_pose_configured) {
    pick_plan.lift_pose.position = pick_plan.grasp_pose.position;
    pick_plan.lift_pose.position.z += lift_height;
  }
  pick_plan.lift_pose.orientation = pick_plan.grasp_pose.orientation;

  if (
    target_kind == task_presets::ManufacturingTarget::Ketchup &&
    arm == task_presets::ArmSide::Left &&
    std::abs(task_presets::kLeftKetchupPickWristRollDeg) > 1e-9)
  {
    applyLocalTcpZRoll(pick_plan.pre_grasp_pose, task_presets::kLeftKetchupPickWristRollDeg);
    applyLocalTcpZRoll(pick_plan.grasp_pose, task_presets::kLeftKetchupPickWristRollDeg);
    applyLocalTcpZRoll(pick_plan.lift_pose, task_presets::kLeftKetchupPickWristRollDeg);
    RCLCPP_INFO(
      logger,
      "Ketchup pick final pose wrist roll correction applied: %.2f deg",
      task_presets::kLeftKetchupPickWristRollDeg);
  }
}

void logPickPlanSummary(
  const rclcpp::Logger & logger,
  const std::string & log_label,
  const TargetObject & target,
  const task_presets::PickTuningPreset & tuning,
  const PickPlan & pick_plan)
{
  RCLCPP_INFO(
    logger,
    "Target '%s': xyz=[%.3f %.3f %.3f], size=[%.3f %.3f %.3f], principal=[%.3f %.3f %.3f], closing=[%.3f %.3f %.3f]",
    target.name.c_str(),
    target.xyz.x(),
    target.xyz.y(),
    target.xyz.z(),
    target.size.x(),
    target.size.y(),
    target.size.z(),
    pick_plan.principal_axis.x(),
    pick_plan.principal_axis.y(),
    pick_plan.principal_axis.z(),
    pick_plan.closing_axis.x(),
    pick_plan.closing_axis.y(),
    pick_plan.closing_axis.z());
  RCLCPP_INFO(
    logger,
    "%s tuning: grasp_tcp_z_offset=%.3f, gripper_joint_position=%s%.3f",
    log_label.c_str(),
    tuning.grasp_tcp_z_offset_m,
    tuning.gripper_close.enabled ? "" : "disabled fallback ",
    tuning.gripper_close.joint_position);
}

void limitPickLiftHeight(
  const rclcpp::Logger & logger,
  const std::string & log_label,
  double max_lift_height_m,
  const geometry_msgs::msg::Pose & grasp_pose,
  geometry_msgs::msg::Pose & lift_pose)
{
  if (max_lift_height_m <= 0.0) {
    return;
  }

  const double requested_lift = lift_pose.position.z - grasp_pose.position.z;
  if (requested_lift <= max_lift_height_m) {
    return;
  }

  lift_pose.position.z = grasp_pose.position.z + max_lift_height_m;
  RCLCPP_INFO(
    logger,
    "%s: limiting pick lift height %.3f -> %.3f m",
    log_label.c_str(),
    requested_lift,
    max_lift_height_m);
}

void offsetPickPlanGraspAndLiftWorldZ(PickPlan & pick_plan, double offset_m)
{
  pick_plan.grasp_pose.position.z += offset_m;
  pick_plan.lift_pose.position.z += offset_m;
}

void logDryRunPickPlan(
  const rclcpp::Logger & logger,
  const std::string & log_label,
  const PickPlan & pick_plan)
{
  RCLCPP_INFO(
    logger,
    "%s dry run completed: pre_grasp=[%.3f %.3f %.3f], grasp=[%.3f %.3f %.3f], lift=[%.3f %.3f %.3f]",
    log_label.c_str(),
    pick_plan.pre_grasp_pose.position.x,
    pick_plan.pre_grasp_pose.position.y,
    pick_plan.pre_grasp_pose.position.z,
    pick_plan.grasp_pose.position.x,
    pick_plan.grasp_pose.position.y,
    pick_plan.grasp_pose.position.z,
    pick_plan.lift_pose.position.x,
    pick_plan.lift_pose.position.y,
    pick_plan.lift_pose.position.z);
}

}  // namespace ddooby_controller::manufacturing_task
