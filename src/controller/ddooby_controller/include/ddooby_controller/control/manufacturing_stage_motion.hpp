#pragma once

#include <string>

#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

bool planAndExecuteStageWaypointPoseIfConfigured(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  task_presets::ManufacturingTarget target,
  task_presets::ArmSide arm_side,
  task_presets::ManufacturingStage stage,
  const char * waypoint,
  const std::string & tcp_link,
  bool & configured,
  double min_duration_sec = 0.0);

const char * preGraspGoalModeName(PreGraspGoalMode mode);

bool planAndExecutePreGrasp(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & pre_grasp_pose,
  const std::string & tcp_link,
  bool use_clearance_approach,
  double min_duration_sec,
  PreGraspGoalMode & used_mode);

}  // namespace ddooby_controller::manufacturing_task
