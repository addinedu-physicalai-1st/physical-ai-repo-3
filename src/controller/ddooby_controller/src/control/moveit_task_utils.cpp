#include "ddooby_controller/control/moveit_task_utils.hpp"

#include <algorithm>
#include <builtin_interfaces/msg/duration.hpp>
#include <chrono>
#include <cmath>
#include <moveit/robot_trajectory/robot_trajectory.hpp>
#include <moveit/trajectory_processing/time_optimal_trajectory_generation.hpp>
#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/task/manufacturing_pose_utils.hpp"

namespace ddooby_controller::manufacturing_task {

void setBoundedStartState(moveit::planning_interface::MoveGroupInterface& group) {
  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    group.setStartStateToCurrentState();
    return;
  }

  const auto* joint_model_group = current_state->getJointModelGroup(group.getName());
  if (joint_model_group != nullptr) {
    current_state->enforceBounds(joint_model_group);
  } else {
    current_state->enforceBounds();
  }
  current_state->update();
  group.setStartState(*current_state);
}

bool configureArmGroupForTask(moveit::planning_interface::MoveGroupInterface& arm,
                              double planning_time_sec, int planning_attempts,
                              double velocity_scaling, double acceleration_scaling,
                              const std::string& tcp_link) {
  arm.setPlanningTime(planning_time_sec);
  arm.setNumPlanningAttempts(planning_attempts);
  arm.setMaxVelocityScalingFactor(velocity_scaling);
  arm.setMaxAccelerationScalingFactor(acceleration_scaling);
  arm.setPoseReferenceFrame(arm.getPlanningFrame());
  if (tcp_link.empty()) {
    return true;
  }
  return arm.setEndEffectorLink(tcp_link);
}

void configureGripperGroupForTask(moveit::planning_interface::MoveGroupInterface& gripper,
                                  double velocity_scaling, double acceleration_scaling) {
  gripper.setMaxVelocityScalingFactor(velocity_scaling);
  gripper.setMaxAccelerationScalingFactor(acceleration_scaling);
}

void rememberJointTargetIfConfigured(moveit::planning_interface::MoveGroupInterface& group,
                                     const std::string& target_name,
                                     const std::vector<double>& joint_values) {
  if (!joint_values.empty()) {
    group.rememberJointValues(target_name, joint_values);
  }
}

double durationToSec(const builtin_interfaces::msg::Duration& duration) {
  return static_cast<double>(duration.sec) + static_cast<double>(duration.nanosec) * 1e-9;
}

builtin_interfaces::msg::Duration durationFromSec(double seconds) {
  builtin_interfaces::msg::Duration duration;
  seconds = std::max(0.0, seconds);
  duration.sec = static_cast<int32_t>(std::floor(seconds));
  duration.nanosec =
      static_cast<uint32_t>(std::round((seconds - static_cast<double>(duration.sec)) * 1e9));
  if (duration.nanosec >= 1000000000U) {
    ++duration.sec;
    duration.nanosec -= 1000000000U;
  }
  return duration;
}

void enforceMinimumTrajectoryDuration(const rclcpp::Logger& logger,
                                      moveit_msgs::msg::RobotTrajectory& trajectory,
                                      const std::string& label, double min_duration_sec) {
  auto& points = trajectory.joint_trajectory.points;
  if (points.empty() || min_duration_sec <= 0.0) {
    return;
  }

  const double original_duration_sec = durationToSec(points.back().time_from_start);
  if (original_duration_sec <= 1e-6 || original_duration_sec >= min_duration_sec) {
    return;
  }

  const double time_scale = min_duration_sec / original_duration_sec;
  for (auto& point : points) {
    point.time_from_start = durationFromSec(durationToSec(point.time_from_start) * time_scale);
    for (double& velocity : point.velocities) {
      velocity /= time_scale;
    }
    for (double& acceleration : point.accelerations) {
      acceleration /= time_scale * time_scale;
    }
  }

  RCLCPP_INFO(logger, "%s Cartesian path stretched: %.3fs -> %.3fs", label.c_str(),
              original_duration_sec, min_duration_sec);
}

bool planAndExecute(const rclcpp::Logger& logger,
                    moveit::planning_interface::MoveGroupInterface& group, const std::string& label,
                    int max_attempts, double min_duration_sec) {
  for (int attempt = 1; attempt <= max_attempts; ++attempt) {
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    if (group.plan(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
      if (attempt < max_attempts) {
        RCLCPP_WARN(logger, "Failed to plan %s on attempt %d/%d; retrying from refreshed state",
                    label.c_str(), attempt, max_attempts);
        rclcpp::sleep_for(std::chrono::milliseconds{300});
        setBoundedStartState(group);
        continue;
      }
      RCLCPP_ERROR(logger, "Failed to plan %s after %d attempt(s)", label.c_str(), max_attempts);
      return false;
    }
    enforceMinimumTrajectoryDuration(logger, plan.trajectory, label, min_duration_sec);

    if (group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
      return true;
    }

    if (attempt < max_attempts) {
      RCLCPP_WARN(logger, "Failed to execute %s on attempt %d/%d; retrying from refreshed state",
                  label.c_str(), attempt, max_attempts);
      rclcpp::sleep_for(std::chrono::milliseconds{500});
      setBoundedStartState(group);
      continue;
    }
    RCLCPP_ERROR(logger, "Failed to execute %s after %d attempt(s)", label.c_str(), max_attempts);
    return false;
  }
  return false;
}

bool planAndExecuteNamedTarget(const rclcpp::Logger& logger,
                               moveit::planning_interface::MoveGroupInterface& group,
                               const std::string& target_name, const std::string& label,
                               int max_attempts, double min_duration_sec) {
  group.clearPoseTargets();
  setBoundedStartState(group);
  group.setNamedTarget(target_name);
  return planAndExecute(logger, group, label, max_attempts, min_duration_sec);
}

bool moveGripperToJointPosition(const rclcpp::Logger& logger,
                                moveit::planning_interface::MoveGroupInterface& gripper,
                                const std::string& log_label, const std::string& action,
                                double joint_position) {
  RCLCPP_INFO(logger, "%s: %s gripper to joint position %.3f", log_label.c_str(), action.c_str(),
              joint_position);
  gripper.clearPoseTargets();
  setBoundedStartState(gripper);
  if (!gripper.setJointValueTarget(std::vector<double>{joint_position})) {
    RCLCPP_ERROR(logger, "Failed to set gripper joint position target %.3f", joint_position);
    return false;
  }
  return planAndExecute(logger, gripper, log_label + " gripper " + action,
                        task_presets::kDefaultPlanExecuteMaxAttempts,
                        task_presets::kDefaultGripperMinDurationSec);
}

bool openGripperForPickApproach(const rclcpp::Logger& logger,
                                moveit::planning_interface::MoveGroupInterface& gripper,
                                const std::string& log_label,
                                const task_presets::PickTuningPreset& tuning,
                                const std::string& fallback_named_target) {
  if (tuning.gripper_pre_open.enabled) {
    return moveGripperToJointPosition(logger, gripper, log_label, "pre-open",
                                      tuning.gripper_pre_open.joint_position);
  }

  RCLCPP_INFO(logger, "%s: opening gripper to named target '%s'", log_label.c_str(),
              fallback_named_target.c_str());
  return planAndExecuteNamedTarget(
      logger, gripper, fallback_named_target, log_label + " gripper open",
      task_presets::kDefaultPlanExecuteMaxAttempts, task_presets::kDefaultGripperMinDurationSec);
}

bool closeGripperForPick(const rclcpp::Logger& logger,
                         moveit::planning_interface::MoveGroupInterface& gripper,
                         const std::string& log_label, const task_presets::PickTuningPreset& tuning,
                         const std::string& fallback_named_target) {
  if (tuning.gripper_close.enabled) {
    return moveGripperToJointPosition(logger, gripper, log_label, "close",
                                      tuning.gripper_close.joint_position);
  }

  RCLCPP_INFO(logger, "%s: closing gripper to named target '%s'", log_label.c_str(),
              fallback_named_target.c_str());
  return planAndExecuteNamedTarget(
      logger, gripper, fallback_named_target, log_label + " grasp close",
      task_presets::kDefaultPlanExecuteMaxAttempts, task_presets::kDefaultGripperMinDurationSec);
}

bool planAndExecutePoseTarget(const rclcpp::Logger& logger,
                              moveit::planning_interface::MoveGroupInterface& arm,
                              const geometry_msgs::msg::Pose& target_pose,
                              const std::string& tcp_link, const std::string& label,
                              int max_attempts, double min_duration_sec) {
  const geometry_msgs::msg::Pose current_pose = arm.getCurrentPose(tcp_link).pose;
  const double position_error = (posePosition(current_pose) - posePosition(target_pose)).norm();
  const double orientation_error = poseOrientationDistanceRad(current_pose, target_pose);
  if (position_error <= task_presets::kDefaultPoseTargetSkipPositionToleranceM &&
      orientation_error <= task_presets::kDefaultPoseTargetSkipOrientationToleranceRad) {
    RCLCPP_INFO(
        logger,
        "%s skipped; current TCP is already near target (pos_error=%.4f m, rot_error=%.4f rad)",
        label.c_str(), position_error, orientation_error);
    return true;
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);
  return planAndExecute(logger, arm, label, max_attempts, min_duration_sec);
}

bool planAndExecutePoseTargetWithScopedScaling(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
    const std::string& label, double current_velocity_scaling, double current_acceleration_scaling,
    double scoped_velocity_scaling, double scoped_acceleration_scaling, int max_attempts,
    double min_duration_sec) {
  arm.setMaxVelocityScalingFactor(scoped_velocity_scaling);
  arm.setMaxAccelerationScalingFactor(scoped_acceleration_scaling);
  RCLCPP_INFO(logger, "%s scoped scaling: velocity=%.3f acceleration=%.3f", label.c_str(),
              scoped_velocity_scaling, scoped_acceleration_scaling);

  const bool ok = planAndExecutePoseTarget(logger, arm, target_pose, tcp_link, label, max_attempts,
                                           min_duration_sec);

  arm.setMaxVelocityScalingFactor(current_velocity_scaling);
  arm.setMaxAccelerationScalingFactor(current_acceleration_scaling);
  return ok;
}

bool ensureTcpNearPose(const rclcpp::Logger& logger,
                       moveit::planning_interface::MoveGroupInterface& arm,
                       const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
                       const std::string& label, bool retry_with_pose_target,
                       double position_tolerance_m, double orientation_tolerance_rad,
                       int max_attempts, double min_duration_sec) {
  const auto current_pose = arm.getCurrentPose(tcp_link).pose;
  const double position_error = (posePosition(current_pose) - posePosition(target_pose)).norm();
  const double orientation_error = poseOrientationDistanceRad(current_pose, target_pose);
  if (position_error <= position_tolerance_m && orientation_error <= orientation_tolerance_rad) {
    return true;
  }

  if (!retry_with_pose_target) {
    RCLCPP_ERROR(logger, "%s TCP is %.3f m / %.3f rad from target after execution", label.c_str(),
                 position_error, orientation_error);
    return false;
  }

  RCLCPP_WARN(logger,
              "%s TCP is %.3f m / %.3f rad from target after execution; retrying exact pose target",
              label.c_str(), position_error, orientation_error);
  if (!planAndExecutePoseTarget(logger, arm, target_pose, tcp_link, label + " retry", max_attempts,
                                min_duration_sec)) {
    return false;
  }

  const auto retry_pose = arm.getCurrentPose(tcp_link).pose;
  const double retry_error = (posePosition(retry_pose) - posePosition(target_pose)).norm();
  const double retry_orientation_error = poseOrientationDistanceRad(retry_pose, target_pose);
  if (retry_error > position_tolerance_m || retry_orientation_error > orientation_tolerance_rad) {
    RCLCPP_ERROR(logger, "%s TCP remains %.3f m / %.3f rad from target after retry", label.c_str(),
                 retry_error, retry_orientation_error);
    return false;
  }
  return true;
}

void alignTrajectoryStartToCurrentState(const rclcpp::Logger& logger,
                                        moveit::planning_interface::MoveGroupInterface& group,
                                        moveit_msgs::msg::RobotTrajectory& trajectory,
                                        const std::string& label) {
  auto& points = trajectory.joint_trajectory.points;
  if (points.empty()) {
    return;
  }

  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    return;
  }

  auto& first_point = points.front();
  double max_delta = 0.0;
  const size_t count =
      std::min(trajectory.joint_trajectory.joint_names.size(), first_point.positions.size());
  for (size_t i = 0; i < count; ++i) {
    const auto& joint_name = trajectory.joint_trajectory.joint_names[i];
    const double current_position = current_state->getVariablePosition(joint_name);
    max_delta = std::max(max_delta, std::abs(first_point.positions[i] - current_position));
    first_point.positions[i] = current_position;
    if (i < first_point.velocities.size()) {
      first_point.velocities[i] = 0.0;
    }
    if (i < first_point.accelerations.size()) {
      first_point.accelerations[i] = 0.0;
    }
  }

  if (max_delta > 1e-4) {
    RCLCPP_INFO(logger,
                "%s Cartesian trajectory start aligned to current state (max_delta=%.6f rad)",
                label.c_str(), max_delta);
  }
}

bool executeCartesian(const rclcpp::Logger& logger,
                      moveit::planning_interface::MoveGroupInterface& group,
                      const std::vector<geometry_msgs::msg::Pose>& waypoints,
                      const std::string& label, double eef_step, double min_fraction,
                      bool avoid_collisions, double velocity_scaling, double acceleration_scaling,
                      double min_duration_sec) {
  group.clearPoseTargets();
  setBoundedStartState(group);

  moveit_msgs::msg::RobotTrajectory trajectory;
  const double fraction =
      group.computeCartesianPath(waypoints, eef_step, trajectory, avoid_collisions);

  RCLCPP_INFO(logger, "%s Cartesian path fraction: %.3f", label.c_str(), fraction);
  if (fraction < min_fraction) {
    RCLCPP_ERROR(logger, "%s Cartesian path fraction %.3f is below required %.3f", label.c_str(),
                 fraction, min_fraction);
    return false;
  }

  moveit::planning_interface::MoveGroupInterface::Plan plan;
  plan.trajectory = trajectory;
  robot_trajectory::RobotTrajectory robot_trajectory(group.getRobotModel(), group.getName());
  robot_trajectory.setRobotTrajectoryMsg(*group.getCurrentState(), trajectory);
  trajectory_processing::TimeOptimalTrajectoryGeneration time_parameterization;
  if (!time_parameterization.computeTimeStamps(robot_trajectory, velocity_scaling,
                                               acceleration_scaling)) {
    RCLCPP_WARN(logger, "%s Cartesian path time parameterization failed; executing raw path",
                label.c_str());
  } else {
    robot_trajectory.getRobotTrajectoryMsg(plan.trajectory);
    const auto& points = plan.trajectory.joint_trajectory.points;
    if (!points.empty()) {
      RCLCPP_INFO(
          logger,
          "%s Cartesian path retimed: %.3fs with velocity_scale=%.3f acceleration_scale=%.3f",
          label.c_str(), durationToSec(points.back().time_from_start), velocity_scaling,
          acceleration_scaling);
    }
  }
  enforceMinimumTrajectoryDuration(logger, plan.trajectory, label, min_duration_sec);
  alignTrajectoryStartToCurrentState(logger, group, plan.trajectory, label);
  if (group.execute(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
    RCLCPP_ERROR(logger, "Failed to execute %s Cartesian path", label.c_str());
    return false;
  }
  return true;
}

bool executeCartesianPoseWithPlanningFallback(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
    const std::string& cartesian_label, const std::string& planned_label,
    bool allow_planned_fallback, double eef_step, double min_fraction, bool avoid_collisions,
    double velocity_scaling, double acceleration_scaling, double min_duration_sec,
    double planned_min_duration_sec, int max_attempts) {
  if (executeCartesian(logger, arm, {target_pose}, cartesian_label, eef_step, min_fraction,
                       avoid_collisions, velocity_scaling, acceleration_scaling,
                       min_duration_sec)) {
    return true;
  }

  if (!allow_planned_fallback) {
    return false;
  }

  RCLCPP_WARN(logger, "%s failed; trying regular pose planning as '%s'", cartesian_label.c_str(),
              planned_label.c_str());
  return planAndExecutePoseTarget(logger, arm, target_pose, tcp_link, planned_label, max_attempts,
                                  planned_min_duration_sec);
}

void logCurrentTcpPose(const rclcpp::Logger& logger,
                       moveit::planning_interface::MoveGroupInterface& arm,
                       const std::string& tcp_link, const std::string& label) {
  const auto pose = arm.getCurrentPose(tcp_link).pose;
  RCLCPP_INFO(logger, "%s current %s pose: xyz=[%.3f %.3f %.3f], quat_xyzw=[%.4f %.4f %.4f %.4f]",
              label.c_str(), tcp_link.c_str(), pose.position.x, pose.position.y, pose.position.z,
              pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w);
}

}  // namespace ddooby_controller::manufacturing_task
