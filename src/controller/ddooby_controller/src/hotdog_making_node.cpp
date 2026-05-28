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
};

enum class PreGraspGoalMode
{
  ExactPose,
  ApproximatePose,
  PositionOnly,
};

std::string normalizeStageName(const std::string & value)
{
  std::string normalized;
  normalized.reserve(value.size());
  for (char character : value) {
    if (character == '_' || character == '-' || character == ' ') {
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
  if (normalized == "pregrasp") {
    return ManufacturingStage::PreGrasp;
  }
  if (normalized == "pick") {
    return ManufacturingStage::Pick;
  }
  if (normalized == "pullout") {
    return ManufacturingStage::PullOut;
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
  if (normalized == "pregrasp") {
    return ManufacturingStage::PreGrasp;
  }
  if (normalized == "pick") {
    return ManufacturingStage::Pick;
  }
  if (normalized == "pullout") {
    return ManufacturingStage::PullOut;
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
  throw std::invalid_argument("unsupported start_from_stage '" + value + "'");
}

int stageOrder(ManufacturingStage stage)
{
  switch (stage) {
    case ManufacturingStage::Home:
      return 0;
    case ManufacturingStage::PreGrasp:
      return 1;
    case ManufacturingStage::Pick:
      return 2;
    case ManufacturingStage::PullOut:
      return 3;
    case ManufacturingStage::Work:
      return 4;
    case ManufacturingStage::Place:
      return 5;
    case ManufacturingStage::ReturnHome:
      return 6;
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
  const auto * preset = task_presets::findStagePosePreset(
    target,
    arm,
    ManufacturingStage::PullOut);
  if (preset != nullptr) {
    return &preset->pose;
  }
  return nullptr;
}

void applyStagePosePreset(
  const rclcpp::Logger & logger,
  ManufacturingTarget target,
  ArmSide arm,
  task_presets::ManufacturingStage stage,
  geometry_msgs::msg::Pose & pose)
{
  const auto * preset = task_presets::findStagePosePreset(target, arm, stage);
  if (preset == nullptr) {
    return;
  }

  pose = makePoseFromPreset(preset->pose);

  RCLCPP_INFO(
    logger,
    "Stage pose preset applied: %s full_pose=override",
    task_presets::stageName(stage));
}

bool hasStagePosePreset(
  ManufacturingTarget target,
  ArmSide arm,
  ManufacturingStage stage)
{
  return task_presets::findStagePosePreset(target, arm, stage) != nullptr;
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

  std::array<int, 2> horizontal_indices{0, 1};
  int principal_index = horizontal_indices[0];
  if (target.size[horizontal_indices[1]] > target.size[principal_index]) {
    principal_index = horizontal_indices[1];
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

bool closeGripperForPick(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & log_label,
  const task_presets::PickTuningPreset & tuning,
  const std::string & fallback_named_target)
{
  if (tuning.gripper_close.enabled) {
    RCLCPP_INFO(
      logger,
      "%s: closing gripper to joint position %.3f",
      log_label.c_str(),
      tuning.gripper_close.joint_position);
    gripper.clearPoseTargets();
    setBoundedStartState(gripper);
    if (!gripper.setJointValueTarget(std::vector<double>{tuning.gripper_close.joint_position})) {
      RCLCPP_ERROR(
        logger,
        "Failed to set left gripper joint position target %.3f",
        tuning.gripper_close.joint_position);
      return false;
    }
    return planAndExecute(logger, gripper, log_label + " grasp close");
  }

  RCLCPP_INFO(
    logger,
    "%s: closing gripper to named target '%s'",
    log_label.c_str(),
    fallback_named_target.c_str());
  gripper.setNamedTarget(fallback_named_target);
  return planAndExecute(logger, gripper, log_label + " grasp close");
}

bool planAndExecuteStagePoseIfConfigured(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  ManufacturingTarget target,
  ArmSide arm_side,
  task_presets::ManufacturingStage stage,
  const std::string & tcp_link,
  bool & configured,
  double min_duration_sec = 0.0)
{
  configured = false;
  const auto * preset = task_presets::findStagePosePreset(target, arm_side, stage);
  if (preset == nullptr) {
    return true;
  }

  configured = true;
  geometry_msgs::msg::Pose target_pose = makePoseFromPreset(preset->pose);

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);

  const std::string label =
    std::string("stage pose ") + task_presets::stageName(stage);
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
  int max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts)
{
  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);
  return planAndExecute(logger, arm, label, max_attempts);
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
    case PreGraspGoalMode::ApproximatePose:
      return "approximate_pose";
    case PreGraspGoalMode::PositionOnly:
      return "position_only";
  }
  return "unknown";
}

bool planAndExecutePreGrasp(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  const geometry_msgs::msg::Pose & pre_grasp_pose,
  const std::string & tcp_link,
  bool allow_approximate_pose,
  bool allow_position_only,
  PreGraspGoalMode & used_mode)
{
  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(pre_grasp_pose, tcp_link);
  if (planAndExecute(logger, arm, "pre-grasp exact pose")) {
    used_mode = PreGraspGoalMode::ExactPose;
    return true;
  }

  if (allow_position_only) {
    RCLCPP_WARN(logger, "Exact pre-grasp pose failed; trying position-only target");
    arm.clearPoseTargets();
    setBoundedStartState(arm);
    arm.setPositionTarget(
      pre_grasp_pose.position.x,
      pre_grasp_pose.position.y,
      pre_grasp_pose.position.z,
      tcp_link);
    if (planAndExecute(logger, arm, "pre-grasp position only")) {
      used_mode = PreGraspGoalMode::PositionOnly;
      return true;
    }
  }

  if (allow_approximate_pose) {
    RCLCPP_WARN(logger, "Position-only pre-grasp target failed; trying approximate IK target");
    arm.clearPoseTargets();
    setBoundedStartState(arm);
    if (arm.setApproximateJointValueTarget(pre_grasp_pose, tcp_link) &&
      planAndExecute(logger, arm, "pre-grasp approximate pose"))
    {
      used_mode = PreGraspGoalMode::ApproximatePose;
      return true;
    }
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
    start_from_stage_name_ = declare_parameter<std::string>("start_from_stage", "home");
    stop_after_stage_name_ = declare_parameter<std::string>("stop_after_stage", "complete");
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
    planning_time_sec_ = declare_parameter<double>("planning_time_sec", 8.0);
    planning_attempts_ = declare_parameter<int>("planning_attempts", 8);
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
    pre_grasp_height_ = declare_parameter<double>("pre_grasp_height", 0.12);
    case_pre_grasp_distance_ = declare_parameter<double>("case_pre_grasp_distance", 0.10);
    lift_height_ = declare_parameter<double>("lift_height", 0.12);
    place_approach_height_ = declare_parameter<double>("place_approach_height", 0.08);
    case_bread_place_clearance_ = declare_parameter<double>("case_bread_place_clearance", 0.005);
    cartesian_eef_step_ = declare_parameter<double>("cartesian_eef_step", 0.005);
    min_cartesian_fraction_ = declare_parameter<double>("min_cartesian_fraction", 0.90);
    cartesian_avoid_collisions_ = declare_parameter<bool>("cartesian_avoid_collisions", false);
    cartesian_min_duration_sec_ = declare_parameter<double>("cartesian_min_duration_sec", 3.5);
    gripper_open_target_ = declare_parameter<std::string>("gripper_open_target", "open");
    gripper_grasp_target_ = declare_parameter<std::string>("gripper_grasp_target", "half_closed");
    remove_target_collision_before_grasp_ =
      declare_parameter<bool>("remove_target_collision_before_grasp", true);
    collision_scene_settle_ms_ = declare_parameter<int>("collision_scene_settle_ms", 300);
    allow_approximate_pre_grasp_ = declare_parameter<bool>("allow_approximate_pre_grasp", false);
    allow_position_only_pre_grasp_ = declare_parameter<bool>("allow_position_only_pre_grasp", true);
    adapt_grasp_orientation_to_reached_pre_grasp_ =
      declare_parameter<bool>("adapt_grasp_orientation_to_reached_pre_grasp", true);
    max_pre_grasp_xy_error_ = declare_parameter<double>(
      "max_pre_grasp_xy_error",
      task_presets::kDefaultMaxPreGraspXyError);
    dry_run_ = declare_parameter<bool>("dry_run", false);

    try {
      start_from_stage_ = parseStartFromStage(start_from_stage_name_);
      stop_after_stage_ = parseStopAfterStage(stop_after_stage_name_);
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
    if (target_ == ManufacturingTarget::Bread && arm_ == ArmSide::Left) {
      if (stop_after_stage_.has_value() &&
        stageOrder(stop_after_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runBreadPick();
      }
      return runBreadPlace();
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
      hasStagePosePreset(config.target, config.arm, ManufacturingStage::PreGrasp);
    const bool pick_pose_configured =
      hasStagePosePreset(config.target, config.arm, ManufacturingStage::Pick);
    if (pre_grasp_pose_configured) {
      applyStagePosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::PreGrasp,
        pick_plan.pre_grasp_pose);
    }
    if (pick_pose_configured) {
      applyStagePosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Pick,
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
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Home,
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
        RCLCPP_INFO(get_logger(), "%s: moved arm using configured home stage pose", config.log_label.c_str());
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " ready");
      if (shouldStopAfter(ManufacturingStage::Home)) {
        return true;
      }
    }

    if (shouldRunStage(ManufacturingStage::PreGrasp)) {
      RCLCPP_INFO(get_logger(), "%s: opening gripper", config.log_label.c_str());
      gripper.setNamedTarget(gripper_open_target_);
      if (!planAndExecute(get_logger(), gripper, config.log_label + " gripper open")) {
        return false;
      }
    }

    bool target_collision_removed = false;

    PreGraspGoalMode pre_grasp_goal_mode = PreGraspGoalMode::ExactPose;
    geometry_msgs::msg::Pose reached_pre_grasp_pose;
    if (shouldRunStage(ManufacturingStage::PreGrasp)) {
      RCLCPP_INFO(get_logger(), "%s: planning to pre-grasp", config.log_label.c_str());
      if (!planAndExecutePreGrasp(
          get_logger(),
          arm,
          pick_plan.pre_grasp_pose,
          config.tcp_link,
          allow_approximate_pre_grasp_,
          allow_position_only_pre_grasp_,
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
    } else {
      reached_pre_grasp_pose = arm.getCurrentPose(config.tcp_link).pose;
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " resume pre-grasp");
    }

    geometry_msgs::msg::Pose grasp_pose = pick_plan.grasp_pose;
    geometry_msgs::msg::Pose lift_pose = pick_plan.lift_pose;
    if (adapt_grasp_orientation_to_reached_pre_grasp_ &&
      pre_grasp_goal_mode != PreGraspGoalMode::ExactPose)
    {
      grasp_pose.orientation = reached_pre_grasp_pose.orientation;
      lift_pose.orientation = reached_pre_grasp_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "%s: adapted grasp/lift orientation to reached pre-grasp orientation",
        config.log_label.c_str());
    }

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
      if (shouldStopAfter(ManufacturingStage::PreGrasp)) {
        return true;
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
        return false;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp");

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

      if (shouldStopAfter(ManufacturingStage::Pick)) {
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
      }
    }

    if (config.pull_out_to_pre_grasp_before_lift && shouldRunStage(ManufacturingStage::PullOut)) {
      geometry_msgs::msg::Pose pull_out_pose = arm.getCurrentPose(config.tcp_link).pose;
      const auto * pull_out_preset = findPullOutPosePreset(config.target, config.arm);
      if (pull_out_preset != nullptr) {
        pull_out_pose = makePoseFromPreset(*pull_out_preset);
        RCLCPP_INFO(get_logger(), "%s: pull-out stage pose preset applied", config.log_label.c_str());
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
      if (shouldStopAfter(ManufacturingStage::PullOut)) {
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
    }

    bool optional_stage_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Work,
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
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::Place,
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
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          arm,
          config.target,
          config.arm,
          task_presets::ManufacturingStage::ReturnHome,
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
        false},
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
        true},
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
        "Bread place dry run completed after bread pick planning; live right TCP is required for automatic place pose");
      return true;
    }

    TargetObject bread_target;
    TargetObject case_target;
    if (!loadManufacturingTarget("bread", bread_target) ||
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
      "Bread place MoveIt setup: left_eef='%s', right_eef='%s'",
      left_arm.getEndEffectorLink().c_str(),
      right_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Case presentation initial");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place initial");

    if (!right_ready_joints_.empty()) {
      right_arm.rememberJointValues(right_ready_pose_name_, right_ready_joints_);
    }

    bool right_work_pose_configured = false;
    bool left_work_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          right_arm,
          ManufacturingTarget::Case,
          ArmSide::Right,
          task_presets::ManufacturingStage::Work,
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

      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          left_tcp_link_,
          left_work_pose_configured,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (left_work_pose_configured) {
        logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pre-place work");
      }
      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Bread place completed before place stage");
      return true;
    }

    const geometry_msgs::msg::Pose right_tcp_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const geometry_msgs::msg::Pose left_current_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
    const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
    const Eigen::Vector3d case_center =
      posePosition(right_tcp_pose) +
      right_tcp_rotation.col(2).normalized() *
      (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);

    geometry_msgs::msg::Pose auto_release_pose = left_current_pose;
    auto_release_pose.position.x = case_center.x();
    auto_release_pose.position.y = case_center.y();
    auto_release_pose.position.z =
      case_center.z() +
      case_target.size.z() * 0.5 +
      bread_target.size.z() * 0.5 +
      case_bread_place_clearance_ +
      place_approach_height_;

    const auto * work_preset =
      task_presets::findStagePosePreset(
        ManufacturingTarget::Bread,
        ArmSide::Left,
        ManufacturingStage::Work);
    const auto * place_preset =
      task_presets::findStagePosePreset(
        ManufacturingTarget::Bread,
        ArmSide::Left,
        ManufacturingStage::Place);

    geometry_msgs::msg::Pose release_pose = auto_release_pose;
    geometry_msgs::msg::Pose retreat_pose = auto_release_pose;
    bool move_to_release_pose = true;
    bool retreat_after_release = false;

    if (place_preset != nullptr) {
      release_pose = makePoseFromPreset(place_preset->pose);
      RCLCPP_INFO(get_logger(), "Bread place release pose preset applied");
      if (work_preset != nullptr) {
        retreat_pose = makePoseFromPreset(work_preset->pose);
        retreat_after_release = true;
      } else {
        retreat_pose = release_pose;
        retreat_pose.position.z += place_approach_height_;
        retreat_after_release = true;
      }
    } else if (work_preset != nullptr) {
      release_pose = makePoseFromPreset(work_preset->pose);
      retreat_pose = release_pose;
      move_to_release_pose = false;
      RCLCPP_INFO(get_logger(), "Bread place uses work pose as drop/release pose");
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Bread place auto drop pose: xyz=[%.3f %.3f %.3f]",
        release_pose.position.x,
        release_pose.position.y,
        release_pose.position.z);
    }

    if (move_to_release_pose) {
      RCLCPP_INFO(get_logger(), "Bread place: moving to release pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          left_arm,
          release_pose,
          left_tcp_link_,
          "bread place release pose"))
      {
        return false;
      }
    } else {
      RCLCPP_INFO(get_logger(), "Bread place: release pose is current work pose; opening gripper in place");
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place release pose");

    RCLCPP_INFO(get_logger(), "Bread place: opening left gripper");
    left_gripper.setNamedTarget(gripper_open_target_);
    if (!planAndExecute(get_logger(), left_gripper, "bread place gripper open")) {
      return false;
    }
    rclcpp::sleep_for(300ms);

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    if (retreat_after_release) {
      RCLCPP_INFO(get_logger(), "Bread place: Cartesian retreat");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {retreat_pose},
          "bread place retreat",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place retreat");
    } else {
      RCLCPP_INFO(get_logger(), "Bread place: release completed without retreat");
    }

    bool return_home_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          left_arm,
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::ReturnHome,
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
  std::string start_from_stage_name_;
  ManufacturingStage start_from_stage_{ManufacturingStage::Home};
  std::string stop_after_stage_name_;
  std::optional<ManufacturingStage> stop_after_stage_;
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
  double planning_time_sec_{8.0};
  int planning_attempts_{8};
  double velocity_scaling_{task_presets::kDefaultMotionScaling.arm_velocity_scaling};
  double acceleration_scaling_{task_presets::kDefaultMotionScaling.arm_acceleration_scaling};
  double gripper_velocity_scaling_{task_presets::kDefaultMotionScaling.gripper_velocity_scaling};
  double gripper_acceleration_scaling_{task_presets::kDefaultMotionScaling.gripper_acceleration_scaling};
  double pre_grasp_height_{0.12};
  double case_pre_grasp_distance_{0.10};
  double lift_height_{0.12};
  double place_approach_height_{0.08};
  double case_bread_place_clearance_{0.005};
  double cartesian_eef_step_{0.005};
  double min_cartesian_fraction_{0.90};
  bool cartesian_avoid_collisions_{false};
  double cartesian_min_duration_sec_{3.5};
  std::string gripper_open_target_;
  std::string gripper_grasp_target_;
  bool remove_target_collision_before_grasp_{true};
  int collision_scene_settle_ms_{300};
  bool allow_approximate_pre_grasp_{false};
  bool allow_position_only_pre_grasp_{true};
  bool adapt_grasp_orientation_to_reached_pre_grasp_{true};
  double max_pre_grasp_xy_error_{0.03};
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
