#include "ddooby_controller/control/manufacturing_motion_primitives.hpp"

#include <algorithm>
#include <string>
#include <utility>
#include <vector>

#include "ddooby_controller/control/moveit_task_utils.hpp"

namespace ddooby_controller::manufacturing_task
{

ManufacturingMotionPrimitives::ManufacturingMotionPrimitives(
  const rclcpp::Logger & logger,
  MotionPrimitiveConfig config)
: logger_(logger),
  config_(std::move(config))
{
}

double ManufacturingMotionPrimitives::poseMinDuration(double override_sec) const
{
  return override_sec >= 0.0 ? override_sec : config_.pose_min_duration_sec;
}

double ManufacturingMotionPrimitives::cartesianMinDuration(double override_sec) const
{
  return override_sec >= 0.0 ? override_sec : config_.cartesian_min_duration_sec;
}

bool ManufacturingMotionPrimitives::moveToNamed(
  moveit::planning_interface::MoveGroupInterface & group,
  const std::string & target_name,
  const std::string & label,
  double min_duration_sec) const
{
  return planAndExecuteNamedTarget(
    logger_,
    group,
    target_name,
    label,
    config_.pose_max_attempts,
    poseMinDuration(min_duration_sec));
}

bool ManufacturingMotionPrimitives::moveToPose(
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & target_pose,
  const std::string & tcp_link,
  const std::string & label,
  double min_duration_sec) const
{
  return planAndExecutePoseTarget(
    logger_,
    arm,
    target_pose,
    tcp_link,
    label,
    config_.pose_max_attempts,
    poseMinDuration(min_duration_sec));
}

bool ManufacturingMotionPrimitives::moveToPoseWithScaling(
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & target_pose,
  const std::string & tcp_link,
  const std::string & label,
  double current_velocity_scaling,
  double current_acceleration_scaling,
  double scoped_velocity_scaling,
  double scoped_acceleration_scaling,
  double min_duration_sec) const
{
  return planAndExecutePoseTargetWithScopedScaling(
    logger_,
    arm,
    target_pose,
    tcp_link,
    label,
    current_velocity_scaling,
    current_acceleration_scaling,
    scoped_velocity_scaling,
    scoped_acceleration_scaling,
    config_.pose_max_attempts,
    poseMinDuration(min_duration_sec));
}

bool ManufacturingMotionPrimitives::cartesianMoveToPose(
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & target_pose,
  const std::string & label,
  bool avoid_collisions,
  double min_duration_sec) const
{
  return cartesianMove(arm, {target_pose}, label, avoid_collisions, min_duration_sec);
}

bool ManufacturingMotionPrimitives::cartesianMove(
  moveit::planning_interface::MoveGroupInterface & arm,
  const std::vector<geometry_msgs::msg::Pose> & waypoints,
  const std::string & label,
  bool avoid_collisions,
  double min_duration_sec) const
{
  return executeCartesian(
    logger_,
    arm,
    waypoints,
    label,
    config_.cartesian_eef_step,
    config_.cartesian_min_fraction,
    avoid_collisions,
    config_.cartesian_velocity_scaling,
    config_.cartesian_acceleration_scaling,
    cartesianMinDuration(min_duration_sec));
}

bool ManufacturingMotionPrimitives::cartesianMoveToPoseWithPlanningFallback(
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & target_pose,
  const std::string & tcp_link,
  const std::string & cartesian_label,
  const std::string & planned_label,
  bool allow_planned_fallback,
  bool avoid_collisions,
  double planned_min_duration_sec) const
{
  return executeCartesianPoseWithPlanningFallback(
    logger_,
    arm,
    target_pose,
    tcp_link,
    cartesian_label,
    planned_label,
    allow_planned_fallback,
    config_.cartesian_eef_step,
    config_.cartesian_min_fraction,
    avoid_collisions,
    config_.cartesian_velocity_scaling,
    config_.cartesian_acceleration_scaling,
    config_.cartesian_min_duration_sec,
    poseMinDuration(planned_min_duration_sec),
    config_.pose_max_attempts);
}

bool ManufacturingMotionPrimitives::clearance(
  moveit::planning_interface::MoveGroupInterface & arm,
  const std::string & tcp_link,
  const std::string & label,
  const Eigen::Vector3d & direction,
  double distance_m,
  bool avoid_collisions,
  double min_duration_sec) const
{
  const double direction_norm = direction.norm();
  if (direction_norm <= 1e-9) {
    RCLCPP_ERROR(logger_, "%s failed: clearance direction is near zero", label.c_str());
    return false;
  }

  // clearance는 파라미터 기반 상대 이동이며, task별 축은 이 함수에 고정하지 않는다.
  auto target_pose = arm.getCurrentPose(tcp_link).pose;
  const Eigen::Vector3d delta = direction.normalized() * distance_m;
  target_pose.position.x += delta.x();
  target_pose.position.y += delta.y();
  target_pose.position.z += delta.z();
  return cartesianMoveToPose(arm, target_pose, label, avoid_collisions, min_duration_sec);
}

bool ManufacturingMotionPrimitives::moveRelative(
  moveit::planning_interface::MoveGroupInterface & arm,
  const std::string & tcp_link,
  const std::string & label,
  const Eigen::Vector3d & direction,
  double distance_m,
  bool avoid_collisions,
  double min_duration_sec) const
{
  const double direction_norm = direction.norm();
  if (direction_norm <= 1e-9) {
    RCLCPP_ERROR(logger_, "%s failed: relative move direction is near zero", label.c_str());
    return false;
  }

  // task 코드가 국소 보정을 조합할 수 있도록 현재 TCP pose를 기준으로 삼는다.
  auto target_pose = arm.getCurrentPose(tcp_link).pose;
  const Eigen::Vector3d delta = direction.normalized() * distance_m;
  target_pose.position.x += delta.x();
  target_pose.position.y += delta.y();
  target_pose.position.z += delta.z();
  return cartesianMoveToPose(arm, target_pose, label, avoid_collisions, min_duration_sec);
}

bool ManufacturingMotionPrimitives::gripperNamedTarget(
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & target_name,
  const std::string & label) const
{
  return moveToNamed(gripper, target_name, label, task_presets::kDefaultGripperMinDurationSec);
}

bool ManufacturingMotionPrimitives::gripperPickAction(
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & label,
  const task_presets::PickTuningPreset & tuning,
  GripperPickAction action) const
{
  switch (action) {
    case GripperPickAction::Open:
      return openGripperForPickApproach(
        logger_,
        gripper,
        label,
        tuning,
        config_.gripper_open_target);
    case GripperPickAction::Close:
      return closeGripperForPick(
        logger_,
        gripper,
        label,
        tuning,
        config_.gripper_grasp_target);
  }
  return false;
}

bool ManufacturingMotionPrimitives::gripperJointPosition(
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & label,
  const std::string & action,
  double joint_position) const
{
  return moveGripperToJointPosition(
    logger_,
    gripper,
    label,
    action,
    joint_position);
}

}  // namespace ddooby_controller::manufacturing_task
