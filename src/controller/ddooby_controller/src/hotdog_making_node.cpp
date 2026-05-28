#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <Eigen/Geometry>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <builtin_interfaces/msg/duration.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit/robot_trajectory/robot_trajectory.hpp>
#include <moveit/trajectory_processing/time_optimal_trajectory_generation.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_task_presets.hpp"

namespace
{
using namespace std::chrono_literals;
namespace task_presets = ddooby_controller::manufacturing_task_presets;
using ManufacturingStage = task_presets::ManufacturingStage;
using ManufacturingTarget = task_presets::ManufacturingTarget;
using ArmSide = task_presets::ArmSide;

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

struct TargetObject
{
  std::string name;
  std::string model_dir;
  Eigen::Vector3d xyz{Eigen::Vector3d::Zero()};
  Eigen::Vector3d rpy{Eigen::Vector3d::Zero()};
  Eigen::Vector3d local_center{Eigen::Vector3d::Zero()};
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
  ManufacturingTarget target;
  ArmSide arm;
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
};

enum class PreGraspGoalMode
{
  ExactPose,
};

std::string normalizeStageName(const std::string & value)
{
  std::string normalized;
  normalized.reserve(value.size());
  for (char character : value) {
    if (character == '_' || character == '-' || character == ' ' ||
      character == '.' || character == '/' || character == ':')
    {
      continue;
    }
    normalized.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(character))));
  }
  return normalized;
}

std::optional<ManufacturingStage> parseStopAfterStage(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized.empty() || normalized == "complete" || normalized == "all" ||
    normalized == "none")
  {
    return std::nullopt;
  }
  if (normalized == "home") {
    return ManufacturingStage::Home;
  }
  if (normalized == "pick") {
    return ManufacturingStage::Pick;
  }
  if (normalized == "work") {
    return ManufacturingStage::Work;
  }
  if (normalized == "place") {
    return ManufacturingStage::Place;
  }
  if (normalized == "returnhome") {
    return ManufacturingStage::ReturnHome;
  }
  if (normalized == "pregrasp" || normalized == "pullout") {
    return ManufacturingStage::Pick;
  }
  throw std::invalid_argument("unsupported stop_after_stage '" + value + "'");
}

ManufacturingTarget parseManufacturingTarget(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized == "bread") {
    return ManufacturingTarget::Bread;
  }
  if (normalized == "case") {
    return ManufacturingTarget::Case;
  }
  if (normalized == "hotdog" || normalized == "newyorkhotdog") {
    return ManufacturingTarget::Hotdog;
  }
  if (normalized == "ketchup" || normalized == "kachup") {
    return ManufacturingTarget::Ketchup;
  }
  if (normalized == "sausage") {
    return ManufacturingTarget::Sausage;
  }
  throw std::invalid_argument("unsupported target '" + value + "'");
}

std::optional<ArmSide> parseArmSide(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized.empty() || normalized == "auto") {
    return std::nullopt;
  }
  if (normalized == "left") {
    return ArmSide::Left;
  }
  if (normalized == "right") {
    return ArmSide::Right;
  }
  throw std::invalid_argument("unsupported arm '" + value + "'");
}

ArmSide defaultArmForTarget(ManufacturingTarget target)
{
  if (target == ManufacturingTarget::Case) {
    return ArmSide::Right;
  }
  return ArmSide::Left;
}

ManufacturingStage parseStartFromStage(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized == "home") {
    return ManufacturingStage::Home;
  }
  if (normalized == "pick") {
    return ManufacturingStage::Pick;
  }
  if (normalized == "work") {
    return ManufacturingStage::Work;
  }
  if (normalized == "place") {
    return ManufacturingStage::Place;
  }
  if (normalized == "returnhome") {
    return ManufacturingStage::ReturnHome;
  }
  if (normalized == "pregrasp" || normalized == "pullout") {
    return ManufacturingStage::Pick;
  }
  throw std::invalid_argument("unsupported start_from_stage '" + value + "'");
}

int stageOrder(ManufacturingStage stage)
{
  switch (stage) {
    case ManufacturingStage::Home:
      return 0;
    case ManufacturingStage::Pick:
      return 1;
    case ManufacturingStage::Work:
      return 2;
    case ManufacturingStage::Place:
      return 3;
    case ManufacturingStage::ReturnHome:
      return 4;
  }
  return 0;
}

std::string readTextFile(const std::string & path)
{
  std::ifstream stream(path);
  if (!stream) {
    throw std::runtime_error("failed to open " + path);
  }
  std::ostringstream buffer;
  buffer << stream.rdbuf();
  return buffer.str();
}

std::string joinPath(const std::string & left, const std::string & right)
{
  if (left.empty() || left.back() == '/') {
    return left + right;
  }
  return left + "/" + right;
}

std::string extractStringValue(const std::string & text, const std::string & key)
{
  const std::string marker = "\"" + key + "\"";
  const auto key_pos = text.find(marker);
  if (key_pos == std::string::npos) {
    throw std::runtime_error("missing string key '" + key + "'");
  }
  const auto colon_pos = text.find(':', key_pos + marker.size());
  const auto first_quote = text.find('"', colon_pos);
  const auto second_quote = text.find('"', first_quote + 1);
  if (colon_pos == std::string::npos || first_quote == std::string::npos ||
    second_quote == std::string::npos)
  {
    throw std::runtime_error("invalid string value for key '" + key + "'");
  }
  return text.substr(first_quote + 1, second_quote - first_quote - 1);
}

std::vector<double> parseDoubles(const std::string & text)
{
  std::string normalized = text;
  for (char & character : normalized) {
    if (character == ',' || character == '\n' || character == '\t') {
      character = ' ';
    }
  }

  std::istringstream stream(normalized);
  std::vector<double> values;
  double value = 0.0;
  while (stream >> value) {
    values.push_back(value);
  }
  return values;
}

Eigen::Vector3d extractVector3Value(const std::string & text, const std::string & key)
{
  const std::string marker = "\"" + key + "\"";
  const auto key_pos = text.find(marker);
  if (key_pos == std::string::npos) {
    throw std::runtime_error("missing vector key '" + key + "'");
  }
  const auto open_bracket = text.find('[', key_pos + marker.size());
  const auto close_bracket = text.find(']', open_bracket);
  if (open_bracket == std::string::npos || close_bracket == std::string::npos) {
    throw std::runtime_error("invalid vector value for key '" + key + "'");
  }
  const auto values = parseDoubles(text.substr(open_bracket + 1, close_bracket - open_bracket - 1));
  if (values.size() != 3) {
    throw std::runtime_error("vector key '" + key + "' does not have three values");
  }
  return Eigen::Vector3d(values[0], values[1], values[2]);
}

std::optional<std::string> extractTagText(const std::string & text, const std::string & tag)
{
  const std::string open_tag = "<" + tag + ">";
  const std::string close_tag = "</" + tag + ">";
  const auto open_pos = text.find(open_tag);
  if (open_pos == std::string::npos) {
    return std::nullopt;
  }
  const auto value_start = open_pos + open_tag.size();
  const auto close_pos = text.find(close_tag, value_start);
  if (close_pos == std::string::npos) {
    return std::nullopt;
  }
  return text.substr(value_start, close_pos - value_start);
}

std::string extractJsonObjectForModel(const std::string & layout_text, const std::string & target_model)
{
  const std::string marker = "\"name\": \"" + target_model + "\"";
  const auto name_pos = layout_text.find(marker);
  if (name_pos == std::string::npos) {
    throw std::runtime_error("target model '" + target_model + "' is missing from layout");
  }

  const auto object_start = layout_text.rfind('{', name_pos);
  if (object_start == std::string::npos) {
    throw std::runtime_error("failed to locate model object for '" + target_model + "'");
  }

  int depth = 0;
  for (size_t i = object_start; i < layout_text.size(); ++i) {
    if (layout_text[i] == '{') {
      ++depth;
    } else if (layout_text[i] == '}') {
      --depth;
      if (depth == 0) {
        return layout_text.substr(object_start, i - object_start + 1);
      }
    }
  }

  throw std::runtime_error("unterminated model object for '" + target_model + "'");
}

Eigen::Matrix3d rotationFromRpy(const Eigen::Vector3d & rpy)
{
  return (
    Eigen::AngleAxisd(rpy.z(), Eigen::Vector3d::UnitZ()) *
    Eigen::AngleAxisd(rpy.y(), Eigen::Vector3d::UnitY()) *
    Eigen::AngleAxisd(rpy.x(), Eigen::Vector3d::UnitX()))
    .toRotationMatrix();
}

geometry_msgs::msg::Pose makePose(
  const Eigen::Vector3d & position,
  const Eigen::Quaterniond & orientation)
{
  geometry_msgs::msg::Pose pose;
  pose.position.x = position.x();
  pose.position.y = position.y();
  pose.position.z = position.z();
  pose.orientation.x = orientation.x();
  pose.orientation.y = orientation.y();
  pose.orientation.z = orientation.z();
  pose.orientation.w = orientation.w();
  return pose;
}

geometry_msgs::msg::Quaternion makeQuaternion(
  const task_presets::TcpPosePreset & preset)
{
  geometry_msgs::msg::Quaternion quaternion;
  quaternion.x = preset.qx;
  quaternion.y = preset.qy;
  quaternion.z = preset.qz;
  quaternion.w = preset.qw;
  return quaternion;
}

geometry_msgs::msg::Pose makePoseFromPreset(const task_presets::TcpPosePreset & preset)
{
  geometry_msgs::msg::Pose pose;
  pose.position.x = preset.x;
  pose.position.y = preset.y;
  pose.position.z = preset.z;
  pose.orientation = makeQuaternion(preset);
  return pose;
}

Eigen::Vector3d posePosition(const geometry_msgs::msg::Pose & pose)
{
  return Eigen::Vector3d(pose.position.x, pose.position.y, pose.position.z);
}

Eigen::Quaterniond poseOrientation(const geometry_msgs::msg::Pose & pose)
{
  Eigen::Quaterniond orientation(
    pose.orientation.w,
    pose.orientation.x,
    pose.orientation.y,
    pose.orientation.z);
  orientation.normalize();
  return orientation;
}

const task_presets::TcpPosePreset * findPullOutPosePreset(
  ManufacturingTarget target,
  ArmSide arm)
{
  const auto * preset = task_presets::findStageWaypointPosePreset(
    target,
    arm,
    ManufacturingStage::Pick,
    "pull_out");
  if (preset != nullptr) {
    return &preset->pose;
  }
  return nullptr;
}

void applyStageWaypointPosePreset(
  const rclcpp::Logger & logger,
  ManufacturingTarget target,
  ArmSide arm,
  task_presets::ManufacturingStage stage,
  const char * waypoint,
  geometry_msgs::msg::Pose & pose)
{
  const auto * preset = task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint);
  if (preset == nullptr) {
    return;
  }

  pose = makePoseFromPreset(preset->pose);

  RCLCPP_INFO(
    logger,
    "Stage waypoint pose preset applied: %s.%s full_pose=override",
    task_presets::stageName(stage),
    waypoint);
}

bool hasStageWaypointPosePreset(
  ManufacturingTarget target,
  ArmSide arm,
  ManufacturingStage stage,
  const char * waypoint)
{
  return task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint) != nullptr;
}

std::vector<CollisionBox> parseCollisionBoxes(const std::string & sdf_text)
{
  std::vector<CollisionBox> boxes;
  size_t search_pos = 0;
  while (true) {
    const auto collision_start = sdf_text.find("<collision", search_pos);
    if (collision_start == std::string::npos) {
      break;
    }
    const auto collision_end = sdf_text.find("</collision>", collision_start);
    if (collision_end == std::string::npos) {
      break;
    }
    const auto block =
      sdf_text.substr(collision_start, collision_end + std::string("</collision>").size() - collision_start);
    search_pos = collision_end + std::string("</collision>").size();

    const auto size_text = extractTagText(block, "size");
    if (!size_text.has_value()) {
      continue;
    }
    const auto size_values = parseDoubles(size_text.value());
    if (size_values.size() != 3) {
      continue;
    }

    Eigen::Vector3d center = Eigen::Vector3d::Zero();
    const auto pose_text = extractTagText(block, "pose");
    if (pose_text.has_value()) {
      const auto pose_values = parseDoubles(pose_text.value());
      if (pose_values.size() >= 3) {
        center = Eigen::Vector3d(pose_values[0], pose_values[1], pose_values[2]);
      }
    }

    boxes.push_back(CollisionBox{
      center,
      Eigen::Vector3d(size_values[0], size_values[1], size_values[2])});
  }
  return boxes;
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
    throw std::runtime_error("target model '" + target_model + "' has no box collision geometry");
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

double topDownPlaceThickness(const TargetObject & target)
{
  return std::min({target.size.x(), target.size.y(), target.size.z()});
}

Eigen::Vector3d horizontalOrFallback(const Eigen::Vector3d & vector, const Eigen::Vector3d & fallback)
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

double boundedJointLimitMargin(const moveit::core::VariableBounds & bounds, double requested_margin)
{
  if (!bounds.position_bounded_ || requested_margin <= 0.0) {
    return 0.0;
  }

  const double range = bounds.max_position_ - bounds.min_position_;
  if (range <= 0.0) {
    return 0.0;
  }

  const double max_margin = range * 0.49;
  return requested_margin < max_margin ? requested_margin : max_margin;
}

double clampInsideJointLimitMargin(
  double value,
  const moveit::core::VariableBounds & bounds,
  double requested_margin)
{
  const double margin = boundedJointLimitMargin(bounds, requested_margin);
  if (margin <= 0.0 || !std::isfinite(value)) {
    return value;
  }

  const double lower = bounds.min_position_ + margin;
  const double upper = bounds.max_position_ - margin;
  if (value < lower) {
    return lower;
  }
  if (value > upper) {
    return upper;
  }
  return value;
}

void setBoundedStartState(moveit::planning_interface::MoveGroupInterface & group)
{
  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    group.setStartStateToCurrentState();
    return;
  }

  const auto * joint_model_group = current_state->getJointModelGroup(group.getName());
  if (joint_model_group != nullptr) {
    current_state->enforceBounds(joint_model_group);
    for (const auto & variable_name : joint_model_group->getVariableNames()) {
      const auto & bounds = current_state->getRobotModel()->getVariableBounds(variable_name);
      const double current_value = current_state->getVariablePosition(variable_name);
      const double bounded_value = clampInsideJointLimitMargin(
        current_value,
        bounds,
        task_presets::kDefaultJointLimitSafetyMargin);
      if (bounded_value != current_value) {
        current_state->setVariablePosition(variable_name, bounded_value);
      }
    }
  } else {
    current_state->enforceBounds();
  }
  current_state->update();
  group.setStartState(*current_state);
}

bool planRespectsJointLimitMargin(
  const rclcpp::Logger & logger,
  const moveit::planning_interface::MoveGroupInterface & group,
  const moveit::planning_interface::MoveGroupInterface::Plan & plan,
  double requested_margin)
{
  if (requested_margin <= 0.0) {
    return true;
  }

  const auto robot_model = group.getRobotModel();
  if (!robot_model) {
    return true;
  }

  const auto & trajectory = plan.trajectory.joint_trajectory;
  for (const auto & point : trajectory.points) {
    const size_t count = std::min(trajectory.joint_names.size(), point.positions.size());
    for (size_t i = 0; i < count; ++i) {
      const auto & joint_name = trajectory.joint_names[i];
      const auto & bounds = robot_model->getVariableBounds(joint_name);
      const double margin = boundedJointLimitMargin(bounds, requested_margin);
      if (margin <= 0.0 || !std::isfinite(point.positions[i])) {
        continue;
      }

      const double lower = bounds.min_position_ + margin;
      const double upper = bounds.max_position_ - margin;
      if (point.positions[i] < lower || point.positions[i] > upper) {
        RCLCPP_WARN(
          logger,
          "%s plan rejected: joint '%s' position %.6f is outside safety bounds [%.6f, %.6f]",
          group.getName().c_str(),
          joint_name.c_str(),
          point.positions[i],
          lower,
          upper);
        return false;
      }
    }
  }

  return true;
}

void enforceMinimumTrajectoryDuration(
  const rclcpp::Logger & logger,
  moveit_msgs::msg::RobotTrajectory & trajectory,
  const std::string & label,
  double min_duration_sec);

bool planAndExecute(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & group,
  const std::string & label,
  int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts,
  double min_duration_sec = 0.0)
{
  for (int attempt = 1; attempt <= max_attempts; ++attempt) {
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    if (group.plan(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(
        logger,
        "Failed to plan %s%s",
        label.c_str(),
        attempt < max_attempts ? "; retrying from refreshed state" : "");
      if (attempt < max_attempts) {
        rclcpp::sleep_for(300ms);
        setBoundedStartState(group);
        continue;
      }
      return false;
    }

    if (!planRespectsJointLimitMargin(
        logger,
        group,
        plan,
        task_presets::kDefaultJointLimitSafetyMargin))
    {
      RCLCPP_ERROR(
        logger,
        "%s plan reached joint limit safety margin%s",
        label.c_str(),
        attempt < max_attempts ? "; retrying from refreshed state" : "");
      if (attempt < max_attempts) {
        rclcpp::sleep_for(300ms);
        setBoundedStartState(group);
        continue;
      }
      return false;
    }

    enforceMinimumTrajectoryDuration(logger, plan.trajectory, label, min_duration_sec);

    if (group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
      return true;
    }

    RCLCPP_ERROR(
      logger,
      "Failed to execute %s%s",
      label.c_str(),
      attempt < max_attempts ? "; retrying from refreshed state" : "");
    if (attempt < max_attempts) {
      rclcpp::sleep_for(500ms);
      setBoundedStartState(group);
    }
  }
  return false;
}

bool moveGripperToJointPosition(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & log_label,
  const std::string & action,
  double joint_position)
{
  RCLCPP_INFO(
    logger,
    "%s: %s gripper to joint position %.3f",
    log_label.c_str(),
    action.c_str(),
    joint_position);
  gripper.clearPoseTargets();
  setBoundedStartState(gripper);
  if (!gripper.setJointValueTarget(std::vector<double>{joint_position})) {
    RCLCPP_ERROR(
      logger,
      "Failed to set gripper joint position target %.3f",
      joint_position);
    return false;
  }
  return planAndExecute(logger, gripper, log_label + " gripper " + action);
}

bool openGripperForPickApproach(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & log_label,
  const task_presets::PickTuningPreset & tuning,
  const std::string & fallback_named_target)
{
  if (tuning.gripper_pre_open.enabled) {
    return moveGripperToJointPosition(
      logger,
      gripper,
      log_label,
      "pre-open",
      tuning.gripper_pre_open.joint_position);
  }

  RCLCPP_INFO(
    logger,
    "%s: opening gripper to named target '%s'",
    log_label.c_str(),
    fallback_named_target.c_str());
  gripper.setNamedTarget(fallback_named_target);
  return planAndExecute(logger, gripper, log_label + " gripper open");
}

bool closeGripperForPick(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & log_label,
  const task_presets::PickTuningPreset & tuning,
  const std::string & fallback_named_target)
{
  if (tuning.gripper_close.enabled) {
    return moveGripperToJointPosition(
      logger,
      gripper,
      log_label,
      "close",
      tuning.gripper_close.joint_position);
  }

  RCLCPP_INFO(
    logger,
    "%s: closing gripper to named target '%s'",
    log_label.c_str(),
    fallback_named_target.c_str());
  gripper.setNamedTarget(fallback_named_target);
  return planAndExecute(logger, gripper, log_label + " grasp close");
}

bool planAndExecuteStageWaypointPoseIfConfigured(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  ManufacturingTarget target,
  ArmSide arm_side,
  task_presets::ManufacturingStage stage,
  const char * waypoint,
  const std::string & tcp_link,
  bool & configured,
  double min_duration_sec = 0.0)
{
  configured = false;
  const auto * preset =
    task_presets::findStageWaypointPosePreset(target, arm_side, stage, waypoint);
  if (preset == nullptr) {
    return true;
  }

  configured = true;
  geometry_msgs::msg::Pose target_pose = makePoseFromPreset(preset->pose);

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);

  const std::string label =
    std::string("stage waypoint pose ") + task_presets::stageName(stage) + "." + waypoint;
  return planAndExecute(
    logger,
    arm,
    label,
    task_presets::kDefaultPlanExecuteMaxAttempts,
    min_duration_sec);
}

bool planAndExecutePoseTarget(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & target_pose,
  const std::string & tcp_link,
  const std::string & label,
  int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts,
  double min_duration_sec = 0.0)
{
  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);
  return planAndExecute(logger, arm, label, max_attempts, min_duration_sec);
}

double durationToSec(const builtin_interfaces::msg::Duration & duration)
{
  return static_cast<double>(duration.sec) + static_cast<double>(duration.nanosec) * 1e-9;
}

builtin_interfaces::msg::Duration durationFromSec(double seconds)
{
  builtin_interfaces::msg::Duration duration;
  seconds = std::max(0.0, seconds);
  duration.sec = static_cast<int32_t>(std::floor(seconds));
  duration.nanosec = static_cast<uint32_t>(
    std::round((seconds - static_cast<double>(duration.sec)) * 1e9));
  if (duration.nanosec >= 1000000000U) {
    ++duration.sec;
    duration.nanosec -= 1000000000U;
  }
  return duration;
}

void enforceMinimumTrajectoryDuration(
  const rclcpp::Logger & logger,
  moveit_msgs::msg::RobotTrajectory & trajectory,
  const std::string & label,
  double min_duration_sec)
{
  auto & points = trajectory.joint_trajectory.points;
  if (points.empty() || min_duration_sec <= 0.0) {
    return;
  }

  const double original_duration_sec = durationToSec(points.back().time_from_start);
  if (original_duration_sec <= 1e-6 || original_duration_sec >= min_duration_sec) {
    return;
  }

  const double time_scale = min_duration_sec / original_duration_sec;
  for (auto & point : points) {
    point.time_from_start = durationFromSec(durationToSec(point.time_from_start) * time_scale);
    for (double & velocity : point.velocities) {
      velocity /= time_scale;
    }
    for (double & acceleration : point.accelerations) {
      acceleration /= time_scale * time_scale;
    }
  }

  RCLCPP_INFO(
    logger,
    "%s Cartesian path stretched: %.3fs -> %.3fs",
    label.c_str(),
    original_duration_sec,
    min_duration_sec);
}

bool executeCartesian(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & group,
  const std::vector<geometry_msgs::msg::Pose> & waypoints,
  const std::string & label,
  double eef_step,
  double min_fraction,
  bool avoid_collisions,
  double velocity_scaling,
  double acceleration_scaling,
  double min_duration_sec)
{
  group.clearPoseTargets();
  setBoundedStartState(group);

  moveit_msgs::msg::RobotTrajectory trajectory;
  const double fraction = group.computeCartesianPath(
    waypoints,
    eef_step,
    trajectory,
    avoid_collisions);

  RCLCPP_INFO(logger, "%s Cartesian path fraction: %.3f", label.c_str(), fraction);
  if (fraction < min_fraction) {
    RCLCPP_ERROR(
      logger,
      "%s Cartesian path fraction %.3f is below required %.3f",
      label.c_str(),
      fraction,
      min_fraction);
    return false;
  }

  moveit::planning_interface::MoveGroupInterface::Plan plan;
  plan.trajectory = trajectory;
  robot_trajectory::RobotTrajectory robot_trajectory(group.getRobotModel(), group.getName());
  robot_trajectory.setRobotTrajectoryMsg(*group.getCurrentState(), trajectory);
  trajectory_processing::TimeOptimalTrajectoryGeneration time_parameterization;
  if (!time_parameterization.computeTimeStamps(
      robot_trajectory,
      velocity_scaling,
      acceleration_scaling))
  {
    RCLCPP_WARN(logger, "%s Cartesian path time parameterization failed; executing raw path", label.c_str());
  } else {
    robot_trajectory.getRobotTrajectoryMsg(plan.trajectory);
    const auto & points = plan.trajectory.joint_trajectory.points;
    if (!points.empty()) {
      RCLCPP_INFO(
        logger,
        "%s Cartesian path retimed: %.3fs with velocity_scale=%.3f acceleration_scale=%.3f",
        label.c_str(),
        durationToSec(points.back().time_from_start),
        velocity_scaling,
        acceleration_scaling);
    }
  }
  enforceMinimumTrajectoryDuration(logger, plan.trajectory, label, min_duration_sec);
  if (!planRespectsJointLimitMargin(
      logger,
      group,
      plan,
      0.0))
  {
    RCLCPP_ERROR(logger, "%s Cartesian path reached joint limit safety margin", label.c_str());
    return false;
  }
  if (group.execute(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
    RCLCPP_ERROR(logger, "Failed to execute %s Cartesian path", label.c_str());
    return false;
  }
  return true;
}

void logCurrentTcpPose(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  const std::string & tcp_link,
  const std::string & label)
{
  const auto pose = arm.getCurrentPose(tcp_link).pose;
  RCLCPP_INFO(
    logger,
    "%s current %s pose: xyz=[%.3f %.3f %.3f], quat_xyzw=[%.4f %.4f %.4f %.4f]",
    label.c_str(),
    tcp_link.c_str(),
    pose.position.x,
    pose.position.y,
    pose.position.z,
    pose.orientation.x,
    pose.orientation.y,
    pose.orientation.z,
    pose.orientation.w);
}

const char * preGraspGoalModeName(PreGraspGoalMode mode)
{
  switch (mode) {
    case PreGraspGoalMode::ExactPose:
      return "exact_pose";
  }
  return "unknown";
}

bool planAndExecutePreGrasp(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & pre_grasp_pose,
  const std::string & tcp_link,
  bool use_clearance_approach,
  double min_duration_sec,
  PreGraspGoalMode & used_mode)
{
  if (use_clearance_approach) {
    constexpr double kPreGraspClearanceHeight = 0.03;
    geometry_msgs::msg::Pose approach_pose = pre_grasp_pose;
    approach_pose.position.z += kPreGraspClearanceHeight;

    RCLCPP_INFO(
      logger,
      "Moving to pre-grasp clearance pose at z=%.3f before descending to pre-grasp",
      approach_pose.position.z);
    if (!planAndExecutePoseTarget(
        logger,
        arm,
        approach_pose,
        tcp_link,
        "pre-grasp clearance pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        min_duration_sec))
    {
      RCLCPP_WARN(logger, "Pre-grasp clearance pose failed; trying direct pre-grasp target");
    }
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(pre_grasp_pose, tcp_link);
  if (planAndExecute(logger, arm, "pre-grasp exact pose", task_presets::kDefaultPlanExecuteMaxAttempts, min_duration_sec)) {
    used_mode = PreGraspGoalMode::ExactPose;
    return true;
  }

  return false;
}

class HotdogMakingNode : public rclcpp::Node
{
public:
  HotdogMakingNode()
  : Node("ddooby_hotdog_making_node")
  {
    item_name_ = declare_parameter<std::string>("item_name", "new_york_hotdog");
    scenario_only_ = declare_parameter<bool>("scenario_only", true);
    step_delay_ms_ = declare_parameter<int>("step_delay_ms", 150);
    target_name_ = declare_parameter<std::string>("target", "bread");
    arm_name_ = declare_parameter<std::string>("arm", "auto");
    target_model_ = declare_parameter<std::string>("target_model", "auto");
    case_target_model_ = declare_parameter<std::string>("case_target_model", "case");
    bread_target_model_ = declare_parameter<std::string>("bread_target_model", "bread");
    sausage_target_model_ = declare_parameter<std::string>("sausage_target_model", "sausage");
    ketchup_target_model_ = declare_parameter<std::string>("ketchup_target_model", "kachup");
    start_from_stage_name_ = declare_parameter<std::string>("start_from_stage", "home");
    stop_after_stage_name_ = declare_parameter<std::string>("stop_after_stage", "complete");
    stop_after_waypoint_name_ = declare_parameter<std::string>("stop_after_waypoint", "");
    layout_path_ = declare_parameter<std::string>("layout_path", "");
    left_arm_group_ = declare_parameter<std::string>("left_arm_group", "left_arm");
    left_gripper_group_ = declare_parameter<std::string>("left_gripper_group", "left_gripper");
    left_tcp_link_ = declare_parameter<std::string>("left_tcp_link", "openarm_left_hand_tcp");
    left_ready_pose_name_ = declare_parameter<std::string>("left_ready_pose_name", "left_bread_pick_ready");
    left_ready_joints_ = declare_parameter<std::vector<double>>(
      "left_ready_joints",
      {
        1.239329032213002,
        0.0010114715451901488,
        -0.0009259087954886816,
        1.718774510702148,
        0.0010237185554880786,
        -0.0010588666577850028,
        -1.0783557656423297});
    right_arm_group_ = declare_parameter<std::string>("right_arm_group", "right_arm");
    right_gripper_group_ = declare_parameter<std::string>("right_gripper_group", "right_gripper");
    right_tcp_link_ = declare_parameter<std::string>("right_tcp_link", "openarm_right_hand_tcp");
    right_ready_pose_name_ = declare_parameter<std::string>("right_ready_pose_name", "right_case_pick_ready");
    right_ready_joints_ = declare_parameter<std::vector<double>>(
      "right_ready_joints",
      {
        -1.239329032213002,
        0.0010114715451901488,
        0.0009259087954886816,
        1.718774510702148,
        -0.0010237185554880786,
        -0.0010588666577850028,
        1.0783557656423297});
    planning_time_sec_ = declare_parameter<double>(
      "planning_time_sec",
      task_presets::kDefaultPlanning.planning_time_sec);
    planning_attempts_ = declare_parameter<int>(
      "planning_attempts",
      task_presets::kDefaultPlanning.planning_attempts);
    velocity_scaling_ = declare_parameter<double>(
      "velocity_scaling",
      task_presets::kDefaultMotionScaling.arm_velocity_scaling);
    acceleration_scaling_ = declare_parameter<double>(
      "acceleration_scaling",
      task_presets::kDefaultMotionScaling.arm_acceleration_scaling);
    gripper_velocity_scaling_ = declare_parameter<double>(
      "gripper_velocity_scaling",
      task_presets::kDefaultMotionScaling.gripper_velocity_scaling);
    gripper_acceleration_scaling_ = declare_parameter<double>(
      "gripper_acceleration_scaling",
      task_presets::kDefaultMotionScaling.gripper_acceleration_scaling);
    pre_grasp_height_ = declare_parameter<double>(
      "pre_grasp_height",
      task_presets::kDefaultPickGeometry.pre_grasp_height_m);
    case_pre_grasp_distance_ = declare_parameter<double>(
      "case_pre_grasp_distance",
      task_presets::kDefaultPickGeometry.case_pre_grasp_distance_m);
    ketchup_pre_grasp_distance_ = declare_parameter<double>(
      "ketchup_pre_grasp_distance",
      task_presets::kDefaultPickGeometry.ketchup_pre_grasp_distance_m);
    lift_height_ = declare_parameter<double>(
      "lift_height",
      task_presets::kDefaultPickGeometry.lift_height_m);
    place_approach_height_ = declare_parameter<double>(
      "place_approach_height",
      task_presets::kDefaultPlaceGeometry.approach_height_m);
    case_bread_place_clearance_ = declare_parameter<double>(
      "case_bread_place_clearance",
      task_presets::kDefaultPlaceGeometry.case_bread_clearance_m);
    case_sausage_place_clearance_ = declare_parameter<double>(
      "case_sausage_place_clearance",
      task_presets::kDefaultPlaceGeometry.case_sausage_clearance_m);
    cartesian_eef_step_ = declare_parameter<double>(
      "cartesian_eef_step",
      task_presets::kDefaultCartesian.eef_step_m);
    min_cartesian_fraction_ = declare_parameter<double>(
      "min_cartesian_fraction",
      task_presets::kDefaultCartesian.min_fraction);
    cartesian_avoid_collisions_ = declare_parameter<bool>(
      "cartesian_avoid_collisions",
      task_presets::kDefaultCartesian.avoid_collisions);
    cartesian_min_duration_sec_ = declare_parameter<double>(
      "cartesian_min_duration_sec",
      task_presets::kDefaultCartesian.min_duration_sec);
    pose_min_duration_sec_ = declare_parameter<double>(
      "pose_min_duration_sec",
      task_presets::kDefaultPlanning.pose_min_duration_sec);
    ketchup_squeeze_length_ = declare_parameter<double>(
      "ketchup_squeeze_length",
      task_presets::kDefaultKetchupSqueeze.length_m);
    ketchup_squeeze_height_ = declare_parameter<double>(
      "ketchup_squeeze_height",
      task_presets::kDefaultKetchupSqueeze.height_m);
    ketchup_squeeze_gripper_position_ =
      declare_parameter<double>(
      "ketchup_squeeze_gripper_position",
      task_presets::kDefaultKetchupSqueeze.gripper_joint_position);
    enable_ketchup_squeeze_gripper_ =
      declare_parameter<bool>("enable_ketchup_squeeze_gripper", false);
    gripper_open_target_ = declare_parameter<std::string>("gripper_open_target", "open");
    gripper_grasp_target_ = declare_parameter<std::string>("gripper_grasp_target", "half_closed");
    remove_target_collision_before_grasp_ =
      declare_parameter<bool>(
      "remove_target_collision_before_grasp",
      task_presets::kDefaultPlanningScene.remove_target_collision_before_grasp);
    collision_scene_settle_ms_ = declare_parameter<int>(
      "collision_scene_settle_ms",
      task_presets::kDefaultPlanningScene.collision_scene_settle_ms);
    max_pre_grasp_xy_error_ = declare_parameter<double>(
      "max_pre_grasp_xy_error",
      task_presets::kDefaultMaxPreGraspXyError);
    dry_run_ = declare_parameter<bool>("dry_run", false);

    try {
      start_from_stage_ = parseStartFromStage(start_from_stage_name_);
      stop_after_stage_ = parseStopAfterStage(stop_after_stage_name_);
      stop_after_waypoint_ = normalizeStageName(stop_after_waypoint_name_);
      if (stop_after_waypoint_ == "complete" || stop_after_waypoint_ == "all" ||
        stop_after_waypoint_ == "none")
      {
        stop_after_waypoint_.clear();
      }
      target_ = parseManufacturingTarget(target_name_);
      arm_ = parseArmSide(arm_name_).value_or(defaultArmForTarget(target_));
      if (stop_after_stage_.has_value() &&
        stageOrder(stop_after_stage_.value()) < stageOrder(start_from_stage_))
      {
        throw std::invalid_argument(
                "stop_after_stage must be the same as or later than start_from_stage");
      }
    } catch (const std::exception & error) {
      stop_after_stage_valid_ = false;
      RCLCPP_ERROR(get_logger(), "%s", error.what());
    }
  }

  bool run()
  {
    if (!stop_after_stage_valid_) {
      return false;
    }

    if (scenario_only_) {
      return runScenario();
    }

    RCLCPP_INFO(
      get_logger(),
      "Manufacturing request: target=%s, arm=%s, start_stage=%s, stop_stage=%s",
      task_presets::targetName(target_),
      task_presets::armName(arm_),
      task_presets::stageName(start_from_stage_),
      stop_after_stage_.has_value() ? task_presets::stageName(stop_after_stage_.value()) : "complete");

    if (target_ == ManufacturingTarget::Case && arm_ == ArmSide::Right) {
      return runCasePick();
    }
    if (target_ == ManufacturingTarget::Hotdog) {
      return runHotdogAssembly();
    }
    if (target_ == ManufacturingTarget::Bread && arm_ == ArmSide::Left) {
      if (stop_after_stage_.has_value() &&
        stageOrder(stop_after_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runBreadPick();
      }
      return runBreadPlace();
    }
    if (target_ == ManufacturingTarget::Sausage && arm_ == ArmSide::Left) {
      if (stop_after_stage_.has_value() &&
        stageOrder(stop_after_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runSausagePick();
      }
      return runSausagePlace();
    }
    if (target_ == ManufacturingTarget::Ketchup && arm_ == ArmSide::Left) {
      if (stop_after_stage_.has_value() &&
        stageOrder(stop_after_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runKetchupPick();
      }
      return runKetchupSqueeze();
    }

    RCLCPP_ERROR(
      get_logger(),
      "Unsupported target/arm combination: target=%s, arm=%s",
      task_presets::targetName(target_),
      task_presets::armName(arm_));
    return false;
  }

private:
  bool runScenario()
  {
    RCLCPP_INFO(
      get_logger(),
      "Hotdog making task accepted: item=%s, scenario_only=%s",
      item_name_.c_str(),
      scenario_only_ ? "true" : "false");

    const std::vector<ScenarioStep> steps{
      {"case_pull", "right arm pulls the New York hotdog case horizontally from the right-side stack"},
      {"bread_pick", "right arm keeps holding the case while left arm picks bread from the handled bread tray"},
      {"bread_place", "left arm lowers bread from above and places it into the case"},
      {"sausage_pick", "left arm picks sausage from the handled sausage tray"},
      {"sausage_place", "left arm lowers sausage from above and places it on the bread"},
      {"ketchup_pick", "left arm picks the ketchup bottle from the right-side condiment area"},
      {"ketchup_aim", "left arm orients the ketchup nozzle toward the sausage over the case"},
      {"ketchup_squeeze", "left gripper slightly closes and moves horizontally along the sausage length"},
      {"pickup_place", "right arm places the completed New York hotdog at the pickup zone"},
    };

    for (size_t i = 0; i < steps.size(); ++i) {
      if (!rclcpp::ok()) {
        RCLCPP_WARN(get_logger(), "Hotdog task interrupted before step %zu", i + 1);
        return false;
      }
      RCLCPP_INFO(
        get_logger(),
        "Hotdog scenario step %zu/%zu [%s]: %s",
        i + 1,
        steps.size(),
        steps[i].name.c_str(),
        steps[i].description.c_str());
      sleepStep();
    }

    RCLCPP_INFO(get_logger(), "Hotdog task scenario completed");
    return true;
  }

  bool runHotdogAssembly()
  {
    if (start_from_stage_ != ManufacturingStage::Home || stop_after_stage_.has_value()) {
      RCLCPP_WARN(
        get_logger(),
        "target:=hotdog currently runs the implemented full sequence and ignores start/stop stage slicing");
    }

    RCLCPP_INFO(get_logger(), "New York hotdog assembly started");

    const std::string saved_target_model = target_model_;
    const ManufacturingStage saved_start_from_stage = start_from_stage_;
    const auto saved_stop_after_stage = stop_after_stage_;

    auto restore_state = [&]() {
      target_model_ = saved_target_model;
      start_from_stage_ = saved_start_from_stage;
      stop_after_stage_ = saved_stop_after_stage;
    };

    start_from_stage_ = ManufacturingStage::Home;
    stop_after_stage_.reset();

    target_model_ = case_target_model_;
    RCLCPP_INFO(get_logger(), "Hotdog assembly step 1/5: pick and present case (%s)", target_model_.c_str());
    if (!runCasePick()) {
      restore_state();
      return false;
    }

    target_model_ = bread_target_model_;
    RCLCPP_INFO(get_logger(), "Hotdog assembly step 2/5: pick and place bread (%s)", target_model_.c_str());
    if (!runBreadPlace()) {
      restore_state();
      return false;
    }

    target_model_ = sausage_target_model_;
    RCLCPP_INFO(get_logger(), "Hotdog assembly step 3/5: pick and place sausage (%s)", target_model_.c_str());
    if (!runSausagePlace()) {
      restore_state();
      return false;
    }

    target_model_ = ketchup_target_model_;
    RCLCPP_INFO(get_logger(), "Hotdog assembly step 4/5: pick, aim, and squeeze ketchup (%s)", target_model_.c_str());
    if (!runKetchupSqueeze()) {
      restore_state();
      return false;
    }

    RCLCPP_WARN(
      get_logger(),
      "Hotdog assembly step 5/5 completed-hotdog pickup-zone place is not implemented yet");

    restore_state();
    RCLCPP_INFO(get_logger(), "New York hotdog assembly completed through ketchup squeeze");
    return true;
  }

  bool shouldStopAfter(ManufacturingStage stage) const
  {
    if (!stop_after_stage_.has_value() || stop_after_stage_.value() != stage) {
      return false;
    }

    RCLCPP_INFO(
      get_logger(),
      "Stopping after manufacturing stage: %s",
      task_presets::stageName(stage));
    return true;
  }

  bool shouldStopAfterWaypoint(ManufacturingStage stage, const std::string & waypoint) const
  {
    if (stop_after_waypoint_.empty()) {
      return false;
    }

    const std::string normalized_waypoint = normalizeStageName(waypoint);
    const std::string normalized_stage_waypoint =
      normalizeStageName(std::string(task_presets::stageName(stage)) + waypoint);
    if (stop_after_waypoint_ != normalized_waypoint &&
      stop_after_waypoint_ != normalized_stage_waypoint)
    {
      return false;
    }

    RCLCPP_INFO(
      get_logger(),
      "Stopping after manufacturing waypoint: %s.%s",
      task_presets::stageName(stage),
      waypoint.c_str());
    return true;
  }

  bool shouldRunStage(ManufacturingStage stage) const
  {
    return stageOrder(stage) >= stageOrder(start_from_stage_);
  }

  bool shouldStopAtOrBefore(ManufacturingStage stage) const
  {
    return stop_after_stage_.has_value() &&
           stageOrder(stop_after_stage_.value()) <= stageOrder(stage);
  }

  bool prepareAndRunPickMotion(
    const PickMotionConfig & config,
    const TargetObject & target,
    PickPlan pick_plan)
  {
    if (config.tuning == nullptr) {
      RCLCPP_ERROR(get_logger(), "%s: missing pick tuning preset", config.log_label.c_str());
      return false;
    }

    const auto & tuning = *config.tuning;
    const bool pre_grasp_pose_configured =
      hasStageWaypointPosePreset(config.target, config.arm, ManufacturingStage::Pick, "pre_grasp");
    const bool pick_pose_configured =
      hasStageWaypointPosePreset(config.target, config.arm, ManufacturingStage::Pick, "grasp");
    if (pre_grasp_pose_configured) {
      applyStageWaypointPosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Pick,
        "pre_grasp",
        pick_plan.pre_grasp_pose);
    }
    if (pick_pose_configured) {
      applyStageWaypointPosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Pick,
        "grasp",
        pick_plan.grasp_pose);
    }
    if (!pre_grasp_pose_configured && pick_pose_configured) {
      pick_plan.pre_grasp_pose.position = pick_plan.grasp_pose.position;
      pick_plan.pre_grasp_pose.position.z += pre_grasp_height_;
      pick_plan.pre_grasp_pose.orientation = pick_plan.grasp_pose.orientation;
      RCLCPP_INFO(get_logger(), "Stage pose preset linked: pre_grasp derived from pick pose");
    }
    if (pre_grasp_pose_configured && !pick_pose_configured) {
      pick_plan.grasp_pose.orientation = pick_plan.pre_grasp_pose.orientation;
      RCLCPP_INFO(get_logger(), "Stage pose preset linked: pick auto position uses pre_grasp orientation");
    }
    if (pick_pose_configured) {
      pick_plan.lift_pose.position = pick_plan.grasp_pose.position;
      pick_plan.lift_pose.position.z += lift_height_;
    }
    pick_plan.lift_pose.orientation = pick_plan.grasp_pose.orientation;

    RCLCPP_INFO(
      get_logger(),
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
      get_logger(),
      "%s tuning: grasp_tcp_z_offset=%.3f, gripper_joint_position=%s%.3f",
      config.log_label.c_str(),
      tuning.grasp_tcp_z_offset_m,
      tuning.gripper_close.enabled ? "" : "disabled fallback ",
      tuning.gripper_close.joint_position);

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "%s dry run completed: pre_grasp=[%.3f %.3f %.3f], grasp=[%.3f %.3f %.3f], lift=[%.3f %.3f %.3f]",
        config.log_label.c_str(),
        pick_plan.pre_grasp_pose.position.x,
        pick_plan.pre_grasp_pose.position.y,
        pick_plan.pre_grasp_pose.position.z,
        pick_plan.grasp_pose.position.x,
        pick_plan.grasp_pose.position.y,
        pick_plan.grasp_pose.position.z,
        pick_plan.lift_pose.position.x,
        pick_plan.lift_pose.position.y,
        pick_plan.lift_pose.position.z);
      return true;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface arm(self, config.arm_group);
    moveit::planning_interface::MoveGroupInterface gripper(self, config.gripper_group);
    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;

    arm.setPlanningTime(planning_time_sec_);
    arm.setNumPlanningAttempts(planning_attempts_);
    arm.setMaxVelocityScalingFactor(velocity_scaling_);
    arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    arm.setPoseReferenceFrame(arm.getPlanningFrame());
    const bool tcp_set = arm.setEndEffectorLink(config.tcp_link);
    RCLCPP_INFO(
      get_logger(),
      "%s MoveIt setup: planning_frame='%s', eef='%s' (%s)",
      config.log_label.c_str(),
      arm.getPlanningFrame().c_str(),
      arm.getEndEffectorLink().c_str(),
      tcp_set ? "ok" : "failed");
    logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " initial");

    if (!config.ready_joints.empty()) {
      arm.rememberJointValues(config.ready_pose_name, config.ready_joints);
    }

    bool home_stage_configured = false;
    if (shouldRunStage(ManufacturingStage::Home)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Home,
          "ready",
          config.tcp_link,
          home_stage_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }

      if (!home_stage_configured) {
        RCLCPP_INFO(get_logger(), "%s: moving arm to ready pose", config.log_label.c_str());
        arm.clearPoseTargets();
        setBoundedStartState(arm);
        arm.setNamedTarget(config.ready_pose_name);
        if (!planAndExecute(get_logger(), arm, config.log_label + " ready")) {
          return false;
        }
      } else {
        RCLCPP_INFO(
          get_logger(),
          "%s: moved arm using configured home/ready waypoint pose",
          config.log_label.c_str());
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " ready");
      if (shouldStopAfter(ManufacturingStage::Home)) {
        return true;
      }
    }

    bool target_collision_removed = false;

    PreGraspGoalMode pre_grasp_goal_mode = PreGraspGoalMode::ExactPose;
    geometry_msgs::msg::Pose reached_pre_grasp_pose;
    if (shouldRunStage(ManufacturingStage::Pick)) {
      RCLCPP_INFO(get_logger(), "%s: planning to pre-grasp", config.log_label.c_str());
      const bool use_pre_grasp_clearance =
        pre_grasp_pose_configured &&
        config.target == ManufacturingTarget::Sausage;
      if (!planAndExecutePreGrasp(
          get_logger(),
          arm,
          pick_plan.pre_grasp_pose,
          config.tcp_link,
          use_pre_grasp_clearance,
          pose_min_duration_sec_,
          pre_grasp_goal_mode))
      {
        return false;
      }
      RCLCPP_INFO(
        get_logger(),
        "%s: reached pre-grasp using %s goal mode",
        config.log_label.c_str(),
        preGraspGoalModeName(pre_grasp_goal_mode));
      reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " pre-grasp");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "pre_grasp")) {
        return true;
      }
    } else {
      reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " resume pre-grasp");
    }

    geometry_msgs::msg::Pose grasp_pose = pick_plan.grasp_pose;
    geometry_msgs::msg::Pose lift_pose = pick_plan.lift_pose;

    if (shouldRunStage(ManufacturingStage::Pick)) {
      const double pre_grasp_dx =
        reached_pre_grasp_pose.position.x - pick_plan.pre_grasp_pose.position.x;
      const double pre_grasp_dy =
        reached_pre_grasp_pose.position.y - pick_plan.pre_grasp_pose.position.y;
      const double pre_grasp_xy_error =
        std::sqrt(pre_grasp_dx * pre_grasp_dx + pre_grasp_dy * pre_grasp_dy);
      RCLCPP_INFO(
        get_logger(),
        "%s: desired pre-grasp xy=[%.3f %.3f], reached tcp xy=[%.3f %.3f], error=%.3f m",
        config.log_label.c_str(),
        pick_plan.pre_grasp_pose.position.x,
        pick_plan.pre_grasp_pose.position.y,
        reached_pre_grasp_pose.position.x,
        reached_pre_grasp_pose.position.y,
        pre_grasp_xy_error);
      if (pre_grasp_xy_error > max_pre_grasp_xy_error_) {
        RCLCPP_ERROR(
          get_logger(),
          "%s: rejecting pre-grasp because TCP xy error %.3f m exceeds %.3f m",
          config.log_label.c_str(),
          pre_grasp_xy_error,
          max_pre_grasp_xy_error_);
        return false;
      }
      if (pre_grasp_pose_configured && !pick_pose_configured) {
        if (config.target == ManufacturingTarget::Case) {
          const Eigen::Vector3d approach_axis = pick_plan.principal_axis.normalized();
          const Eigen::Vector3d reached_position = posePosition(reached_pre_grasp_pose);
          const Eigen::Vector3d grasp_position = posePosition(grasp_pose);
          const Eigen::Vector3d aligned_position =
            grasp_position + approach_axis * ((reached_position - grasp_position).dot(approach_axis));

          geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = grasp_pose;
          target_aligned_pre_grasp_pose.position.x = aligned_position.x();
          target_aligned_pre_grasp_pose.position.y = aligned_position.y();
          target_aligned_pre_grasp_pose.position.z =
            aligned_position.z() + task_presets::kRightCaseTargetAlignZOffsetM;
          RCLCPP_INFO(
            get_logger(),
            "%s: moving beside selected target before horizontal grasp approach (z_offset=%.3f)",
            config.log_label.c_str(),
            task_presets::kRightCaseTargetAlignZOffsetM);
          if (!planAndExecutePoseTarget(
              get_logger(),
              arm,
              target_aligned_pre_grasp_pose,
              config.tcp_link,
              config.log_label + " target-aligned horizontal pre-grasp",
              task_presets::kDefaultPlanExecuteMaxAttempts,
              pose_min_duration_sec_))
          {
            return false;
          }
          logCurrentTcpPose(
            get_logger(),
            arm,
            config.tcp_link,
            config.log_label + " target-aligned horizontal pre-grasp");
          if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align")) {
            return true;
          }
        } else if (config.target == ManufacturingTarget::Ketchup) {
          RCLCPP_INFO(
            get_logger(),
            "%s: skipping forced target alignment; cylindrical target uses planned grasp approach",
            config.log_label.c_str());
        } else {
          constexpr double kMinGraspClearanceAboveTarget = 0.05;
          const double clearance_z = std::max({
            reached_pre_grasp_pose.position.z,
            pick_plan.pre_grasp_pose.position.z,
            grasp_pose.position.z + kMinGraspClearanceAboveTarget});

          geometry_msgs::msg::Pose clearance_pose = reached_pre_grasp_pose;
          clearance_pose.position.z = clearance_z;
          clearance_pose.orientation = grasp_pose.orientation;

          if (std::abs(clearance_pose.position.z - reached_pre_grasp_pose.position.z) > 0.005) {
            RCLCPP_INFO(
              get_logger(),
              "%s: moving to grasp clearance z=%.3f before lateral target alignment",
              config.log_label.c_str(),
              clearance_z);
            if (!planAndExecutePoseTarget(
                get_logger(),
                arm,
                clearance_pose,
                config.tcp_link,
                config.log_label + " grasp clearance",
                task_presets::kDefaultPlanExecuteMaxAttempts,
                pose_min_duration_sec_))
            {
              return false;
            }
            logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp clearance");
            if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "clearance")) {
              return true;
            }
          }

          geometry_msgs::msg::Pose target_aligned_pre_grasp_pose = grasp_pose;
          target_aligned_pre_grasp_pose.position.z = clearance_z;
          RCLCPP_INFO(
            get_logger(),
            "%s: moving above selected target before vertical grasp descent",
            config.log_label.c_str());
          if (!planAndExecutePoseTarget(
              get_logger(),
              arm,
              target_aligned_pre_grasp_pose,
              config.tcp_link,
              config.log_label + " target-aligned pre-grasp",
              task_presets::kDefaultPlanExecuteMaxAttempts,
              pose_min_duration_sec_))
          {
            return false;
          }
          logCurrentTcpPose(
            get_logger(),
            arm,
            config.tcp_link,
            config.log_label + " target-aligned pre-grasp");
          if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "target_align")) {
            return true;
          }
        }
      }

      RCLCPP_INFO(get_logger(), "%s: opening gripper after target alignment", config.log_label.c_str());
      if (!openGripperForPickApproach(
          get_logger(),
          gripper,
          config.log_label,
          tuning,
          gripper_open_target_))
      {
        return false;
      }

      if (remove_target_collision_before_grasp_ && !target_collision_removed) {
        RCLCPP_INFO(
          get_logger(),
          "%s: removing target collision object '%s' before grasp approach",
          config.log_label.c_str(),
          target.name.c_str());
        planning_scene_interface.removeCollisionObjects({target.name});
        target_collision_removed = true;
        if (collision_scene_settle_ms_ > 0) {
          rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
        }
      }

      if (config.use_planned_grasp_approach) {
        RCLCPP_INFO(get_logger(), "%s: planned approach to grasp", config.log_label.c_str());
        if (!planAndExecutePoseTarget(
            get_logger(),
            arm,
            grasp_pose,
            config.tcp_link,
            config.log_label + " planned grasp approach",
            task_presets::kDefaultPlanExecuteMaxAttempts,
            pose_min_duration_sec_))
        {
          return false;
        }
      } else {
        RCLCPP_INFO(get_logger(), "%s: Cartesian approach to grasp", config.log_label.c_str());
        if (!executeCartesian(
            get_logger(),
            arm,
            {grasp_pose},
            config.log_label + " grasp approach",
            cartesian_eef_step_,
            min_cartesian_fraction_,
            cartesian_avoid_collisions_,
            velocity_scaling_,
            acceleration_scaling_,
            cartesian_min_duration_sec_))
        {
          if (!config.allow_planned_grasp_approach_fallback) {
            return false;
          }

          RCLCPP_WARN(
            get_logger(),
            "%s: Cartesian grasp approach failed; trying regular pose planning to grasp",
            config.log_label.c_str());
          if (!planAndExecutePoseTarget(
              get_logger(),
              arm,
              grasp_pose,
              config.tcp_link,
              config.log_label + " planned grasp approach",
              task_presets::kDefaultPlanExecuteMaxAttempts,
              pose_min_duration_sec_))
          {
            return false;
          }
        }
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "grasp")) {
        return true;
      }

      if (!closeGripperForPick(
          get_logger(),
          gripper,
          config.log_label,
          tuning,
          gripper_grasp_target_))
      {
        return false;
      }
      rclcpp::sleep_for(300ms);
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "close")) {
        return true;
      }

      if (!config.pull_out_to_pre_grasp_before_lift) {
        RCLCPP_INFO(get_logger(), "%s: Cartesian lift", config.log_label.c_str());
        if (!executeCartesian(
            get_logger(),
            arm,
            {lift_pose},
            config.log_label + " lift",
            cartesian_eef_step_,
            min_cartesian_fraction_,
            cartesian_avoid_collisions_,
            velocity_scaling_,
            acceleration_scaling_,
            cartesian_min_duration_sec_))
        {
          return false;
        }
        logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
        if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift")) {
          return true;
        }
      }
    }

    if (config.pull_out_to_pre_grasp_before_lift && shouldRunStage(ManufacturingStage::Pick)) {
      geometry_msgs::msg::Pose pull_out_pose = arm.getCurrentPose(config.tcp_link).pose;
      const auto * pull_out_preset = findPullOutPosePreset(config.target, config.arm);
      if (pull_out_preset != nullptr) {
        pull_out_pose = makePoseFromPreset(*pull_out_preset);
        RCLCPP_INFO(get_logger(), "%s: pull-out waypoint pose preset applied", config.log_label.c_str());
      } else {
        pull_out_pose.position.x = pick_plan.pre_grasp_pose.position.x;
        pull_out_pose.position.y = pick_plan.pre_grasp_pose.position.y;
      }

      RCLCPP_INFO(get_logger(), "%s: Cartesian pull-out", config.log_label.c_str());
      if (!executeCartesian(
          get_logger(),
          arm,
          {pull_out_pose},
          config.log_label + " pull-out",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " pull-out");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "pull_out")) {
        return true;
      }
      lift_pose.position.x = pull_out_pose.position.x;
      lift_pose.position.y = pull_out_pose.position.y;
      lift_pose.position.z = pull_out_pose.position.z + lift_height_;
      lift_pose.orientation = pull_out_pose.orientation;

      RCLCPP_INFO(get_logger(), "%s: Cartesian lift", config.log_label.c_str());
      if (!executeCartesian(
          get_logger(),
          arm,
          {lift_pose},
          config.log_label + " lift",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift")) {
        return true;
      }
    }

    if (shouldStopAfter(ManufacturingStage::Pick)) {
      return true;
    }

    bool optional_stage_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Work,
          "work",
          config.tcp_link,
          optional_stage_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (optional_stage_configured) {
        logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " work");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (shouldRunStage(ManufacturingStage::Place)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Place,
          "release",
          config.tcp_link,
          optional_stage_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (optional_stage_configured) {
        logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " place");
      }
      if (shouldStopAfter(ManufacturingStage::Place)) {
        return true;
      }
    }

    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::ReturnHome,
          "return_home",
          config.tcp_link,
          optional_stage_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (optional_stage_configured) {
        logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " return-home");
      }
      if (shouldStopAfter(ManufacturingStage::ReturnHome)) {
        return true;
      }
    }

    RCLCPP_INFO(get_logger(), "%s", config.completed_log.c_str());
    return true;
  }

  bool runBreadPick()
  {
    const std::string bread_target_model =
      target_model_.empty() || target_model_ == "auto" ? "bread" : target_model_;
    RCLCPP_INFO(
      get_logger(),
      "Hotdog bread pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      bread_target_model.c_str());

    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }

    const std::string layout_path = layout_path_.empty() ?
      joinPath(package_share_directory, "assets/manufacturing_world/layout.json") :
      layout_path_;

    TargetObject target;
    try {
      target = loadTargetObject(package_share_directory, layout_path, bread_target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", bread_target_model.c_str(), error.what());
      return false;
    }

    PickPlan pick_plan =
      makeTopDownPickPlan(
        target,
        pre_grasp_height_,
        lift_height_,
        task_presets::kLeftBreadPickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Bread,
        ArmSide::Left,
        "Bread pick",
        "Hotdog bread pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftBreadPickTuning,
        false,
        true},
      target,
      pick_plan);
  }

  bool loadManufacturingTarget(const std::string & target_model, TargetObject & target)
  {
    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }

    const std::string layout_path = layout_path_.empty() ?
      joinPath(package_share_directory, "assets/manufacturing_world/layout.json") :
      layout_path_;

    try {
      target = loadTargetObject(package_share_directory, layout_path, target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", target_model.c_str(), error.what());
      return false;
    }
    return true;
  }

  bool runCasePick()
  {
    const std::string case_target_model =
      target_model_.empty() || target_model_ == "auto" ? "case" : target_model_;
    RCLCPP_INFO(
      get_logger(),
      "Hotdog case pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      case_target_model.c_str());

    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }

    const std::string layout_path = layout_path_.empty() ?
      joinPath(package_share_directory, "assets/manufacturing_world/layout.json") :
      layout_path_;

    TargetObject target;
    try {
      target = loadTargetObject(package_share_directory, layout_path, case_target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", case_target_model.c_str(), error.what());
      return false;
    }

    PickPlan pick_plan =
      makeHorizontalPickPlan(
        target,
        Eigen::Vector3d::UnitX(),
        Eigen::Vector3d::UnitY(),
        case_pre_grasp_distance_,
        lift_height_,
        task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Case,
        ArmSide::Right,
        "Case pick",
        "Hotdog case pick completed",
        right_arm_group_,
        right_gripper_group_,
        right_tcp_link_,
        right_ready_pose_name_,
        right_ready_joints_,
        &task_presets::kRightCasePickTuning,
        true,
        false},
      target,
      pick_plan);
  }

  bool runSausagePick()
  {
    const std::string sausage_target_model =
      target_model_.empty() || target_model_ == "auto" ? "sausage" : target_model_;
    RCLCPP_INFO(
      get_logger(),
      "Hotdog sausage pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      sausage_target_model.c_str());

    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }

    const std::string layout_path = layout_path_.empty() ?
      joinPath(package_share_directory, "assets/manufacturing_world/layout.json") :
      layout_path_;

    TargetObject target;
    try {
      target = loadTargetObject(package_share_directory, layout_path, sausage_target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", sausage_target_model.c_str(), error.what());
      return false;
    }

    PickPlan pick_plan =
      makeTopDownPickPlan(
        target,
        pre_grasp_height_,
        lift_height_,
        task_presets::kLeftSausagePickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Sausage,
        ArmSide::Left,
        "Sausage pick",
        "Hotdog sausage pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftSausagePickTuning,
        false,
        true},
      target,
      pick_plan);
  }

  bool runKetchupPick()
  {
    const std::string ketchup_target_model =
      target_model_.empty() || target_model_ == "auto" ? "kachup" : target_model_;
    RCLCPP_INFO(
      get_logger(),
      "Hotdog ketchup pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      ketchup_target_model.c_str());

    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }

    const std::string layout_path = layout_path_.empty() ?
      joinPath(package_share_directory, "assets/manufacturing_world/layout.json") :
      layout_path_;

    TargetObject target;
    try {
      target = loadTargetObject(package_share_directory, layout_path, ketchup_target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", ketchup_target_model.c_str(), error.what());
      return false;
    }

    PickPlan pick_plan =
      makeHorizontalPickPlan(
        target,
        Eigen::Vector3d::UnitY(),
        Eigen::Vector3d::UnitX(),
        ketchup_pre_grasp_distance_,
        lift_height_,
        task_presets::kLeftKetchupPickTuning.grasp_tcp_z_offset_m);

    return prepareAndRunPickMotion(
      PickMotionConfig{
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        "Ketchup pick",
        "Hotdog ketchup pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftKetchupPickTuning,
        false,
        false,
        false},
      target,
      pick_plan);
  }

  bool runBreadPlace()
  {
    RCLCPP_INFO(get_logger(), "Hotdog bread place started: item=%s", item_name_.c_str());

    if (stageOrder(start_from_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_stop_after_stage = stop_after_stage_;
      if (requested_stop_after_stage.has_value() &&
        stageOrder(requested_stop_after_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        stop_after_stage_.reset();
      }
      const bool bread_pick_ok = runBreadPick();
      stop_after_stage_ = requested_stop_after_stage;
      if (!bread_pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Bread place dry run completed after bread pick planning");
      return true;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);

    left_arm.setPlanningTime(planning_time_sec_);
    left_arm.setNumPlanningAttempts(planning_attempts_);
    left_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    left_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    left_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    left_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    left_arm.setPoseReferenceFrame(left_arm.getPlanningFrame());
    left_arm.setEndEffectorLink(left_tcp_link_);

    RCLCPP_INFO(
      get_logger(),
      "Bread place MoveIt setup: left_eef='%s'",
      left_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place initial");

    bool left_work_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Bread place: moving to configured work pose");
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work",
          left_tcp_link_,
          left_work_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (left_work_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place work");
      } else {
        RCLCPP_INFO(get_logger(), "Bread work pose is disabled; using current left TCP pose");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Bread place completed before place stage");
      return true;
    }

    RCLCPP_INFO(get_logger(), "Bread place: opening left gripper at work pose");
    left_gripper.setNamedTarget(gripper_open_target_);
    if (!planAndExecute(get_logger(), left_gripper, "bread place gripper open")) {
      return false;
    }
    rclcpp::sleep_for(300ms);

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Bread place: release completed without extra retreat");

    bool return_home_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::ReturnHome,
          "return_home",
          left_tcp_link_,
          return_home_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (return_home_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place return-home");
      }
    }

    RCLCPP_INFO(get_logger(), "Hotdog bread place completed");
    return true;
  }

  bool runSausagePlace()
  {
    RCLCPP_INFO(get_logger(), "Hotdog sausage place started: item=%s", item_name_.c_str());

    if (stageOrder(start_from_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_stop_after_stage = stop_after_stage_;
      if (requested_stop_after_stage.has_value() &&
        stageOrder(requested_stop_after_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        stop_after_stage_.reset();
      }
      const bool sausage_pick_ok = runSausagePick();
      stop_after_stage_ = requested_stop_after_stage;
      if (!sausage_pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Sausage place dry run completed after sausage pick planning; live right TCP is required for automatic place pose");
      return true;
    }

    TargetObject sausage_target;
    TargetObject bread_target;
    TargetObject case_target;
    if (!loadManufacturingTarget("sausage", sausage_target) ||
      !loadManufacturingTarget("bread", bread_target) ||
      !loadManufacturingTarget("case", case_target))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);

    left_arm.setPlanningTime(planning_time_sec_);
    left_arm.setNumPlanningAttempts(planning_attempts_);
    left_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    left_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    right_arm.setPlanningTime(planning_time_sec_);
    right_arm.setNumPlanningAttempts(planning_attempts_);
    right_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    right_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    left_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    left_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    left_arm.setPoseReferenceFrame(left_arm.getPlanningFrame());
    right_arm.setPoseReferenceFrame(right_arm.getPlanningFrame());
    left_arm.setEndEffectorLink(left_tcp_link_);
    right_arm.setEndEffectorLink(right_tcp_link_);

    RCLCPP_INFO(
      get_logger(),
      "Sausage place MoveIt setup: left_eef='%s', right_eef='%s'",
      left_arm.getEndEffectorLink().c_str(),
      right_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Case presentation initial");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place initial");

    bool right_work_pose_configured = false;
    bool left_work_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          right_arm,
          ManufacturingTarget::Case,
          ArmSide::Right,
          task_presets::ManufacturingStage::Work,
          "work",
          right_tcp_link_,
          right_work_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (right_work_pose_configured) {
        logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Case presentation work");
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Case presentation work pose is disabled; using current right TCP pose");
      }

      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Sausage,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work",
          left_tcp_link_,
          left_work_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (left_work_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage pre-place work");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Sausage place completed before place stage");
      return true;
    }

    const geometry_msgs::msg::Pose right_tcp_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const geometry_msgs::msg::Pose left_current_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
    const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
    const Eigen::Vector3d case_center =
      posePosition(right_tcp_pose) +
      right_tcp_rotation.col(2).normalized() *
      (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);

    const double sausage_thickness = topDownPlaceThickness(sausage_target);
    const double release_z =
      case_center.z() +
      case_target.size.z() * 0.5 +
      bread_target.size.z() +
      sausage_thickness * 0.5 +
      case_sausage_place_clearance_;

    geometry_msgs::msg::Pose approach_pose = left_current_pose;
    approach_pose.position.x = case_center.x();
    approach_pose.position.y = case_center.y();
    approach_pose.position.z = release_z + place_approach_height_;

    geometry_msgs::msg::Pose release_pose = approach_pose;
    release_pose.position.z = release_z;

    const auto * work_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Sausage,
        ArmSide::Left,
        ManufacturingStage::Work,
        "work");
    const auto * place_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Sausage,
        ArmSide::Left,
        ManufacturingStage::Place,
        "release");

    if (work_preset != nullptr) {
      approach_pose = makePoseFromPreset(work_preset->pose);
      RCLCPP_INFO(get_logger(), "Sausage place approach pose preset applied");
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Sausage place auto approach pose: xyz=[%.3f %.3f %.3f]",
        approach_pose.position.x,
        approach_pose.position.y,
        approach_pose.position.z);
    }

    if (place_preset != nullptr) {
      release_pose = makePoseFromPreset(place_preset->pose);
      RCLCPP_INFO(get_logger(), "Sausage place release pose preset applied");
    } else {
      release_pose.orientation = approach_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "Sausage place auto release pose: xyz=[%.3f %.3f %.3f]",
        release_pose.position.x,
        release_pose.position.y,
        release_pose.position.z);
    }

    RCLCPP_INFO(get_logger(), "Sausage place: moving to approach pose");
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        approach_pose,
        left_tcp_link_,
        "sausage place approach pose"))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place approach pose");

    RCLCPP_INFO(get_logger(), "Sausage place: Cartesian lower to release pose");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {release_pose},
        "sausage place lower",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place release pose");

    RCLCPP_INFO(get_logger(), "Sausage place: opening left gripper");
    left_gripper.setNamedTarget(gripper_open_target_);
    if (!planAndExecute(get_logger(), left_gripper, "sausage place gripper open")) {
      return false;
    }
    rclcpp::sleep_for(300ms);

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Sausage place: Cartesian retreat");
    if (!executeCartesian(
        get_logger(),
        left_arm,
        {approach_pose},
        "sausage place retreat",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place retreat");

    bool return_home_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Sausage,
          ArmSide::Left,
          task_presets::ManufacturingStage::ReturnHome,
          "return_home",
          left_tcp_link_,
          return_home_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (return_home_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place return-home");
      }
    }

    RCLCPP_INFO(get_logger(), "Hotdog sausage place completed");
    return true;
  }

  bool runKetchupSqueeze()
  {
    RCLCPP_INFO(get_logger(), "Hotdog ketchup squeeze started: item=%s", item_name_.c_str());

    if (stageOrder(start_from_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_stop_after_stage = stop_after_stage_;
      if (requested_stop_after_stage.has_value() &&
        stageOrder(requested_stop_after_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        stop_after_stage_.reset();
      }
      const bool ketchup_pick_ok = runKetchupPick();
      stop_after_stage_ = requested_stop_after_stage;
      if (!ketchup_pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick)) {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup squeeze dry run completed after ketchup pick planning; live case pose is required for aim/squeeze");
      return true;
    }

    TargetObject sausage_target;
    TargetObject bread_target;
    TargetObject case_target;
    TargetObject ketchup_target;
    const std::string ketchup_target_model =
      target_model_.empty() || target_model_ == "auto" ? ketchup_target_model_ : target_model_;
    if (!loadManufacturingTarget(sausage_target_model_, sausage_target) ||
      !loadManufacturingTarget(bread_target_model_, bread_target) ||
      !loadManufacturingTarget(case_target_model_, case_target) ||
      !loadManufacturingTarget(ketchup_target_model, ketchup_target))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);

    left_arm.setPlanningTime(planning_time_sec_);
    left_arm.setNumPlanningAttempts(planning_attempts_);
    left_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    left_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    right_arm.setPlanningTime(planning_time_sec_);
    right_arm.setNumPlanningAttempts(planning_attempts_);
    right_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    right_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    left_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    left_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    left_arm.setPoseReferenceFrame(left_arm.getPlanningFrame());
    right_arm.setPoseReferenceFrame(right_arm.getPlanningFrame());
    left_arm.setEndEffectorLink(left_tcp_link_);
    right_arm.setEndEffectorLink(right_tcp_link_);

    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Ketchup case presentation initial");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup squeeze initial");

    bool right_case_present_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze: moving right hand to case presentation pose");
      if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(),
          right_arm,
          ManufacturingTarget::Ketchup,
          ArmSide::Right,
          task_presets::ManufacturingStage::Work,
          "case_present",
          right_tcp_link_,
          right_case_present_configured,
          pose_min_duration_sec_))
      {
        return false;
      }
      if (right_case_present_configured) {
        logCurrentTcpPose(
          get_logger(), right_arm, right_tcp_link_, "Ketchup case presentation pose");
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup case_present waypoint is disabled; using current right TCP pose");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "case_present")) {
        return true;
      }
    }

    const geometry_msgs::msg::Pose right_tcp_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const geometry_msgs::msg::Pose left_current_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
    const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
    const Eigen::Vector3d case_center =
      posePosition(right_tcp_pose) +
      right_tcp_rotation.col(2).normalized() *
      (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);

    const double sausage_thickness = topDownPlaceThickness(sausage_target);
    const double squeeze_z =
      case_center.z() +
      case_target.size.z() * 0.5 +
      bread_target.size.z() +
      sausage_thickness +
      ketchup_squeeze_height_;

    const double squeeze_length = std::max(0.0, ketchup_squeeze_length_);
    const Eigen::Vector3d squeeze_axis = Eigen::Vector3d::UnitX();
    const Eigen::Vector3d start_position = case_center - squeeze_axis * (squeeze_length * 0.5);
    const Eigen::Vector3d end_position = case_center + squeeze_axis * (squeeze_length * 0.5);

    geometry_msgs::msg::Pose aim_pose = left_current_pose;
    aim_pose.position.x = start_position.x();
    aim_pose.position.y = start_position.y();
    aim_pose.position.z = squeeze_z;

    geometry_msgs::msg::Pose squeeze_pose = aim_pose;
    squeeze_pose.position.x = end_position.x();
    squeeze_pose.position.y = end_position.y();
    squeeze_pose.position.z = squeeze_z;

    const auto * work_stage_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        ManufacturingStage::Work,
        "work");
    const auto * aim_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        ManufacturingStage::Work,
        "aim");
    const auto * squeeze_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        ManufacturingStage::Work,
        "squeeze");
    const auto * return_preset =
      task_presets::findStageWaypointPosePreset(
        ManufacturingTarget::Ketchup,
        ArmSide::Left,
        ManufacturingStage::Place,
        "return_pose");

    if (aim_preset != nullptr) {
      aim_pose = makePoseFromPreset(aim_preset->pose);
      squeeze_pose.orientation = aim_pose.orientation;
      squeeze_pose.position.x = aim_pose.position.x + squeeze_axis.x() * squeeze_length;
      squeeze_pose.position.y = aim_pose.position.y + squeeze_axis.y() * squeeze_length;
      squeeze_pose.position.z = aim_pose.position.z;
      RCLCPP_INFO(get_logger(), "Ketchup work/aim waypoint pose preset applied");
    } else if (work_stage_preset != nullptr) {
      aim_pose = makePoseFromPreset(work_stage_preset->pose);
      squeeze_pose.orientation = aim_pose.orientation;
      squeeze_pose.position.x = aim_pose.position.x + squeeze_axis.x() * squeeze_length;
      squeeze_pose.position.y = aim_pose.position.y + squeeze_axis.y() * squeeze_length;
      squeeze_pose.position.z = aim_pose.position.z;
      RCLCPP_INFO(get_logger(), "Ketchup work/work waypoint pose preset used as aim pose");
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup auto aim pose: xyz=[%.3f %.3f %.3f]",
        aim_pose.position.x,
        aim_pose.position.y,
        aim_pose.position.z);
    }

    if (squeeze_preset != nullptr) {
      squeeze_pose = makePoseFromPreset(squeeze_preset->pose);
      RCLCPP_INFO(get_logger(), "Ketchup work/squeeze waypoint pose preset applied");
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup auto squeeze pose: xyz=[%.3f %.3f %.3f]",
        squeeze_pose.position.x,
        squeeze_pose.position.y,
        squeeze_pose.position.z);
    }

    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze: moving to aim pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          left_arm,
          aim_pose,
          left_tcp_link_,
          "ketchup aim pose",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup aim pose");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "aim")) {
        return true;
      }

      if (enable_ketchup_squeeze_gripper_) {
        if (!moveGripperToJointPosition(
            get_logger(),
            left_gripper,
            "Ketchup squeeze",
            "squeeze",
            ketchup_squeeze_gripper_position_))
        {
          return false;
        }
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup squeeze gripper adjustment disabled; keeping current grasp width");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "squeeze_start")) {
        return true;
      }

      RCLCPP_INFO(get_logger(), "Ketchup squeeze: Cartesian line over sausage");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {squeeze_pose},
          "ketchup squeeze line",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup squeeze pose");
      if (enable_ketchup_squeeze_gripper_) {
        if (task_presets::kLeftKetchupPickTuning.gripper_close.enabled) {
          if (!moveGripperToJointPosition(
              get_logger(),
              left_gripper,
              "Ketchup squeeze",
              "release squeeze pressure",
              task_presets::kLeftKetchupPickTuning.gripper_close.joint_position))
          {
            return false;
          }
        } else {
          RCLCPP_INFO(
            get_logger(),
            "Ketchup squeeze: reopening gripper to named grasp target '%s'",
            gripper_grasp_target_.c_str());
          left_gripper.setNamedTarget(gripper_grasp_target_);
          if (!planAndExecute(get_logger(), left_gripper, "ketchup squeeze release pressure")) {
            return false;
          }
        }
      } else {
        RCLCPP_INFO(
          get_logger(),
          "Ketchup squeeze gripper adjustment disabled; keeping grasp width after squeeze");
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "squeeze")) {
        return true;
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Ketchup squeeze completed before ketchup return stage");
      return true;
    }

    PickPlan return_plan =
      makeHorizontalPickPlan(
        ketchup_target,
        Eigen::Vector3d::UnitY(),
        Eigen::Vector3d::UnitX(),
        ketchup_pre_grasp_distance_,
        lift_height_,
        task_presets::kLeftKetchupPickTuning.grasp_tcp_z_offset_m);
    geometry_msgs::msg::Pose return_pre_grasp_pose = return_plan.pre_grasp_pose;
    if (const auto * pick_pre_grasp_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Ketchup,
          ArmSide::Left,
          ManufacturingStage::Pick,
          "pre_grasp"))
    {
      return_pre_grasp_pose = makePoseFromPreset(pick_pre_grasp_preset->pose);
      RCLCPP_INFO(get_logger(), "Ketchup return pre-grasp uses pick.pre_grasp waypoint pose");
    }
    geometry_msgs::msg::Pose return_pose = return_plan.grasp_pose;
    return_pose.orientation = return_pre_grasp_pose.orientation;
    geometry_msgs::msg::Pose return_lift_pose = return_pose;
    return_lift_pose.position.z += task_presets::kLeftKetchupReturnLiftHeightM;

    RCLCPP_INFO(get_logger(), "Ketchup place: retreating back to aim pose");
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        aim_pose,
        left_tcp_link_,
        "ketchup place aim retreat pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup place aim retreat");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "aim")) {
      return true;
    }

    if (return_preset != nullptr) {
      return_pose = makePoseFromPreset(return_preset->pose);
      return_lift_pose = return_pose;
      return_lift_pose.position.z += task_presets::kLeftKetchupReturnLiftHeightM;
      RCLCPP_INFO(get_logger(), "Ketchup return place pose preset applied");
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Ketchup auto return place pose: xyz=[%.3f %.3f %.3f]",
        return_pose.position.x,
        return_pose.position.y,
        return_pose.position.z);
    }

    RCLCPP_INFO(
      get_logger(),
      "Ketchup place: moving through return lift pose (height=%.3f)",
      task_presets::kLeftKetchupReturnLiftHeightM);
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        return_lift_pose,
        left_tcp_link_,
        "ketchup return lift pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup return lift");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "lift")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Ketchup place: returning bottle");
    if (!planAndExecutePoseTarget(
        get_logger(),
        left_arm,
        return_pose,
        left_tcp_link_,
        "ketchup return place pose",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Ketchup return place");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "return_pose")) {
      return true;
    }

    if (!openGripperForPickApproach(
        get_logger(),
        left_gripper,
        "Ketchup place",
        task_presets::kLeftKetchupPickTuning,
        gripper_open_target_))
    {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Hotdog ketchup squeeze completed");
    return true;
  }

  void sleepStep() const
  {
    if (step_delay_ms_ > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(step_delay_ms_));
    }
  }

  std::string item_name_;
  bool scenario_only_{true};
  int step_delay_ms_{150};
  std::string target_name_;
  std::string arm_name_;
  ManufacturingTarget target_{ManufacturingTarget::Bread};
  ArmSide arm_{ArmSide::Left};
  std::string target_model_;
  std::string case_target_model_;
  std::string bread_target_model_;
  std::string sausage_target_model_;
  std::string ketchup_target_model_;
  std::string start_from_stage_name_;
  ManufacturingStage start_from_stage_{ManufacturingStage::Home};
  std::string stop_after_stage_name_;
  std::optional<ManufacturingStage> stop_after_stage_;
  std::string stop_after_waypoint_name_;
  std::string stop_after_waypoint_;
  bool stop_after_stage_valid_{true};
  std::string layout_path_;
  std::string left_arm_group_;
  std::string left_gripper_group_;
  std::string left_tcp_link_;
  std::string left_ready_pose_name_;
  std::vector<double> left_ready_joints_;
  std::string right_arm_group_;
  std::string right_gripper_group_;
  std::string right_tcp_link_;
  std::string right_ready_pose_name_;
  std::vector<double> right_ready_joints_;
  double planning_time_sec_{task_presets::kDefaultPlanning.planning_time_sec};
  int planning_attempts_{task_presets::kDefaultPlanning.planning_attempts};
  double velocity_scaling_{task_presets::kDefaultMotionScaling.arm_velocity_scaling};
  double acceleration_scaling_{task_presets::kDefaultMotionScaling.arm_acceleration_scaling};
  double gripper_velocity_scaling_{task_presets::kDefaultMotionScaling.gripper_velocity_scaling};
  double gripper_acceleration_scaling_{task_presets::kDefaultMotionScaling.gripper_acceleration_scaling};
  double pre_grasp_height_{task_presets::kDefaultPickGeometry.pre_grasp_height_m};
  double case_pre_grasp_distance_{task_presets::kDefaultPickGeometry.case_pre_grasp_distance_m};
  double ketchup_pre_grasp_distance_{task_presets::kDefaultPickGeometry.ketchup_pre_grasp_distance_m};
  double lift_height_{task_presets::kDefaultPickGeometry.lift_height_m};
  double place_approach_height_{task_presets::kDefaultPlaceGeometry.approach_height_m};
  double case_bread_place_clearance_{task_presets::kDefaultPlaceGeometry.case_bread_clearance_m};
  double case_sausage_place_clearance_{task_presets::kDefaultPlaceGeometry.case_sausage_clearance_m};
  double cartesian_eef_step_{task_presets::kDefaultCartesian.eef_step_m};
  double min_cartesian_fraction_{task_presets::kDefaultCartesian.min_fraction};
  bool cartesian_avoid_collisions_{task_presets::kDefaultCartesian.avoid_collisions};
  double cartesian_min_duration_sec_{task_presets::kDefaultCartesian.min_duration_sec};
  double pose_min_duration_sec_{task_presets::kDefaultPlanning.pose_min_duration_sec};
  double ketchup_squeeze_length_{task_presets::kDefaultKetchupSqueeze.length_m};
  double ketchup_squeeze_height_{task_presets::kDefaultKetchupSqueeze.height_m};
  double ketchup_squeeze_gripper_position_{task_presets::kDefaultKetchupSqueeze.gripper_joint_position};
  bool enable_ketchup_squeeze_gripper_{false};
  std::string gripper_open_target_;
  std::string gripper_grasp_target_;
  bool remove_target_collision_before_grasp_{
    task_presets::kDefaultPlanningScene.remove_target_collision_before_grasp};
  int collision_scene_settle_ms_{task_presets::kDefaultPlanningScene.collision_scene_settle_ms};
  double max_pre_grasp_xy_error_{task_presets::kDefaultMaxPreGraspXyError};
  bool dry_run_{false};
};
}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<HotdogMakingNode>();

  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  const bool success = node->run();
  rclcpp::shutdown();
  if (spinner.joinable()) {
    spinner.join();
  }
  return success ? 0 : 1;
}
