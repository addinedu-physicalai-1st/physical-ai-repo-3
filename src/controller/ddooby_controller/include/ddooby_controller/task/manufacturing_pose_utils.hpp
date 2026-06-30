#pragma once

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <geometry_msgs/msg/quaternion.hpp>
#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task {

namespace task_presets = ddooby_controller::manufacturing_task_presets;

Eigen::Matrix3d rotationFromRpy(const Eigen::Vector3d& rpy);

geometry_msgs::msg::Pose makePose(const Eigen::Vector3d& position,
                                  const Eigen::Quaterniond& orientation);

geometry_msgs::msg::Quaternion makeQuaternion(const task_presets::TcpPosePreset& preset);

geometry_msgs::msg::Pose makePoseFromPreset(const task_presets::TcpPosePreset& preset);

const char* poseAxisSourceName(task_presets::PoseAxisSource source);

double resolvePoseAxisValue(const rclcpp::Logger& logger, task_presets::PoseAxisSource source,
                            double preset_value, int axis_index,
                            const PoseAxisReferenceValues& references, const char* label);

geometry_msgs::msg::Pose makePoseFromWaypointPreset(
    const rclcpp::Logger& logger, const task_presets::StageWaypointPosePreset& preset,
    const PoseAxisReferenceValues& references, const char* label);

Eigen::Vector3d posePosition(const geometry_msgs::msg::Pose& pose);

Eigen::Quaterniond poseOrientation(const geometry_msgs::msg::Pose& pose);

void applyLocalTcpZRoll(geometry_msgs::msg::Pose& pose, double roll_deg);

Eigen::Vector3d rpyFromRotation(const Eigen::Matrix3d& rotation);

Eigen::Vector3d objectWorldCenter(const TargetObject& target);

bool poseHasValidOrientation(const geometry_msgs::msg::Pose& pose);

Eigen::Vector3d heldCaseCenterFromTcpPose(const geometry_msgs::msg::Pose& right_tcp_pose);

double poseOrientationDistanceRad(const geometry_msgs::msg::Pose& first,
                                  const geometry_msgs::msg::Pose& second);

}  // namespace ddooby_controller::manufacturing_task
