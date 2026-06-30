#pragma once

#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <rclcpp/logger.hpp>
#include <string>
#include <vector>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"

namespace ddooby_controller::manufacturing_task {

namespace task_presets = ddooby_controller::manufacturing_task_presets;

void setBoundedStartState(moveit::planning_interface::MoveGroupInterface& group);

bool configureArmGroupForTask(moveit::planning_interface::MoveGroupInterface& arm,
                              double planning_time_sec, int planning_attempts,
                              double velocity_scaling, double acceleration_scaling,
                              const std::string& tcp_link = "");

void configureGripperGroupForTask(moveit::planning_interface::MoveGroupInterface& gripper,
                                  double velocity_scaling, double acceleration_scaling);

void rememberJointTargetIfConfigured(moveit::planning_interface::MoveGroupInterface& group,
                                     const std::string& target_name,
                                     const std::vector<double>& joint_values);

void enforceMinimumTrajectoryDuration(const rclcpp::Logger& logger,
                                      moveit_msgs::msg::RobotTrajectory& trajectory,
                                      const std::string& label, double min_duration_sec);

bool planAndExecute(const rclcpp::Logger& logger,
                    moveit::planning_interface::MoveGroupInterface& group, const std::string& label,
                    int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts,
                    double min_duration_sec = 0.0);

bool planAndExecuteNamedTarget(const rclcpp::Logger& logger,
                               moveit::planning_interface::MoveGroupInterface& group,
                               const std::string& target_name, const std::string& label,
                               int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts,
                               double min_duration_sec = 0.0);

bool moveGripperToJointPosition(const rclcpp::Logger& logger,
                                moveit::planning_interface::MoveGroupInterface& gripper,
                                const std::string& log_label, const std::string& action,
                                double joint_position);

bool openGripperForPickApproach(const rclcpp::Logger& logger,
                                moveit::planning_interface::MoveGroupInterface& gripper,
                                const std::string& log_label,
                                const task_presets::PickTuningPreset& tuning,
                                const std::string& fallback_named_target);

bool closeGripperForPick(const rclcpp::Logger& logger,
                         moveit::planning_interface::MoveGroupInterface& gripper,
                         const std::string& log_label, const task_presets::PickTuningPreset& tuning,
                         const std::string& fallback_named_target);

bool planAndExecutePoseTarget(const rclcpp::Logger& logger,
                              moveit::planning_interface::MoveGroupInterface& arm,
                              const geometry_msgs::msg::Pose& target_pose,
                              const std::string& tcp_link, const std::string& label,
                              int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts,
                              double min_duration_sec = 0.0);

bool planAndExecutePoseTargetWithScopedScaling(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
    const std::string& label, double current_velocity_scaling, double current_acceleration_scaling,
    double scoped_velocity_scaling, double scoped_acceleration_scaling,
    int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts, double min_duration_sec = 0.0);

bool ensureTcpNearPose(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
    const std::string& label, bool retry_with_pose_target = true,
    double position_tolerance_m = 0.070,
    double orientation_tolerance_rad = task_presets::kDefaultPoseTargetSkipOrientationToleranceRad,
    int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts, double min_duration_sec = 0.0);

bool executeCartesian(const rclcpp::Logger& logger,
                      moveit::planning_interface::MoveGroupInterface& group,
                      const std::vector<geometry_msgs::msg::Pose>& waypoints,
                      const std::string& label, double eef_step, double min_fraction,
                      bool avoid_collisions, double velocity_scaling, double acceleration_scaling,
                      double min_duration_sec);

bool executeCartesianPoseWithPlanningFallback(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    const geometry_msgs::msg::Pose& target_pose, const std::string& tcp_link,
    const std::string& cartesian_label, const std::string& planned_label,
    bool allow_planned_fallback, double eef_step, double min_fraction, bool avoid_collisions,
    double velocity_scaling, double acceleration_scaling, double min_duration_sec,
    double planned_min_duration_sec,
    int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts);

void logCurrentTcpPose(const rclcpp::Logger& logger,
                       moveit::planning_interface::MoveGroupInterface& arm,
                       const std::string& tcp_link, const std::string& label);

}  // namespace ddooby_controller::manufacturing_task
