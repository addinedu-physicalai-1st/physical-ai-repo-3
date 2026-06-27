#pragma once

#include <string>
#include <optional>
#include <vector>

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <rclcpp/time.hpp>

#include "ddooby_controller/manufacturing_task_presets.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

struct ScenarioStep
{
  std::string name;
  std::string description;
};

struct CollisionBox
{
  Eigen::Vector3d center{Eigen::Vector3d::Zero()};
  Eigen::Vector3d size{Eigen::Vector3d::Zero()};
};

struct CollisionPrimitiveSpec
{
  enum class Type
  {
    Box,
    Cylinder,
  };

  Type type{Type::Box};
  Eigen::Vector3d center{Eigen::Vector3d::Zero()};
  Eigen::Vector3d rpy{Eigen::Vector3d::Zero()};
  Eigen::Vector3d size{Eigen::Vector3d::Zero()};
  double radius{0.0};
  double length{0.0};
};

struct TargetObject
{
  std::string name;
  std::string model_dir;
  Eigen::Vector3d xyz{Eigen::Vector3d::Zero()};
  Eigen::Vector3d rpy{Eigen::Vector3d::Zero()};
  Eigen::Vector3d local_center{Eigen::Vector3d::Zero()};
  Eigen::Vector3d size{Eigen::Vector3d::Zero()};
  bool pose_from_vision{false};
};

struct VisionPickDetection
{
  std::string class_id;
  std::string object_id;
  double score{0.0};
  rclcpp::Time stamp;
  std::string frame_id;
  geometry_msgs::msg::Pose pose;
  Eigen::Vector3d size{Eigen::Vector3d::Zero()};
};

struct PickPlan
{
  geometry_msgs::msg::Pose pre_grasp_pose;
  geometry_msgs::msg::Pose grasp_pose;
  geometry_msgs::msg::Pose lift_pose;
  Eigen::Vector3d principal_axis{Eigen::Vector3d::UnitY()};
  Eigen::Vector3d closing_axis{Eigen::Vector3d::UnitX()};
};

struct PickMotionConfig
{
  task_presets::ManufacturingTarget target;
  task_presets::ArmSide arm;
  std::string log_label;
  std::string completed_log;
  std::string arm_group;
  std::string gripper_group;
  std::string tcp_link;
  std::string ready_pose_name;
  std::vector<double> ready_joints;
  const task_presets::PickTuningPreset * tuning{nullptr};
  bool pull_out_to_pre_grasp_before_lift{false};
  bool allow_planned_grasp_approach_fallback{false};
  bool use_planned_grasp_approach{false};
  double max_lift_height_m{0.0};
};

enum class PreGraspGoalMode
{
  ExactPose,
};

enum class MotionStepResult
{
  Failed,
  Continue,
  Stop,
};

struct PoseAxisReferenceValues
{
  std::optional<Eigen::Vector3d> case_position;
  std::optional<Eigen::Vector3d> target_position;
};

struct OptionalStageWaypoint
{
  task_presets::ManufacturingStage stage;
  const char * waypoint;
  const char * log_suffix;
};

}  // namespace ddooby_controller::manufacturing_task
