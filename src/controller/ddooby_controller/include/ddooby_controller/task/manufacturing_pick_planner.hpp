#pragma once

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <rclcpp/logger.hpp>
#include <string>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task {

namespace task_presets = ddooby_controller::manufacturing_task_presets;

const task_presets::TcpPosePreset* findPullOutPosePreset(task_presets::ManufacturingTarget target,
                                                         task_presets::ArmSide arm);

void applyStageWaypointPosePreset(
    const rclcpp::Logger& logger, task_presets::ManufacturingTarget target,
    task_presets::ArmSide arm, task_presets::ManufacturingStage stage, const char* waypoint,
    geometry_msgs::msg::Pose& pose,
    const PoseAxisReferenceValues& references = PoseAxisReferenceValues{});

bool hasStageWaypointPosePreset(task_presets::ManufacturingTarget target, task_presets::ArmSide arm,
                                task_presets::ManufacturingStage stage, const char* waypoint);

TargetObject loadTargetObject(const std::string& package_share_directory,
                              const std::string& layout_path, const std::string& target_model);

TargetObject makeKetchupBodyGraspTarget(const TargetObject& target);

double topDownPlaceThickness(const TargetObject& target);

Eigen::Vector3d horizontalOrFallback(const Eigen::Vector3d& vector,
                                     const Eigen::Vector3d& fallback);

PickPlan makeTopDownPickPlan(const TargetObject& target, double pre_grasp_height,
                             double lift_height, double grasp_tcp_z_offset_m);

PickPlan makeHorizontalPickPlan(const TargetObject& target, const Eigen::Vector3d& approach_axis,
                                const Eigen::Vector3d& closing_axis_hint, double approach_distance,
                                double lift_height, double grasp_tcp_z_offset_m);

void applyPickStageWaypointPresets(const rclcpp::Logger& logger,
                                   task_presets::ManufacturingTarget target_kind,
                                   task_presets::ArmSide arm, const TargetObject& target,
                                   double pre_grasp_height, double lift_height,
                                   PickPlan& pick_plan);

void logPickPlanSummary(const rclcpp::Logger& logger, const std::string& log_label,
                        const TargetObject& target, const task_presets::PickTuningPreset& tuning,
                        const PickPlan& pick_plan);

void limitPickLiftHeight(const rclcpp::Logger& logger, const std::string& log_label,
                         double max_lift_height_m, const geometry_msgs::msg::Pose& grasp_pose,
                         geometry_msgs::msg::Pose& lift_pose);

void offsetPickPlanGraspAndLiftWorldZ(PickPlan& pick_plan, double offset_m);

void logDryRunPickPlan(const rclcpp::Logger& logger, const std::string& log_label,
                       const PickPlan& pick_plan);

}  // namespace ddooby_controller::manufacturing_task
