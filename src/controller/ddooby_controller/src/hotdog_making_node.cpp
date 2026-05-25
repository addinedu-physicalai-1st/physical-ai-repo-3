#include <chrono>
#include <array>
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
#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_task_presets.hpp"

namespace
{
using namespace std::chrono_literals;
namespace task_presets = ddooby_controller::manufacturing_task_presets;
using ManufacturingStage = task_presets::ManufacturingStage;

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

struct BreadPickPlan
{
  geometry_msgs::msg::Pose pre_grasp_pose;
  geometry_msgs::msg::Pose grasp_pose;
  geometry_msgs::msg::Pose lift_pose;
  Eigen::Vector3d principal_axis{Eigen::Vector3d::UnitY()};
  Eigen::Vector3d closing_axis{Eigen::Vector3d::UnitX()};
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
    case ManufacturingStage::Work:
      return 3;
    case ManufacturingStage::Place:
      return 4;
    case ManufacturingStage::ReturnHome:
      return 5;
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

void applyStagePosePreset(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingStage stage,
  geometry_msgs::msg::Pose & pose)
{
  const auto * preset = task_presets::findLeftBreadPickStagePose(stage);
  if (preset == nullptr) {
    return;
  }

  pose.position.x = preset->pose.x;
  pose.position.y = preset->pose.y;
  pose.position.z = preset->pose.z;
  pose.orientation = makeQuaternion(preset->pose);

  RCLCPP_INFO(
    logger,
    "Stage pose preset applied: %s full_pose=override",
    task_presets::stageName(stage));
}

bool hasStagePosePreset(ManufacturingStage stage)
{
  return task_presets::findLeftBreadPickStagePose(stage) != nullptr;
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

BreadPickPlan makeTopDownPickPlan(
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

  return BreadPickPlan{
    makePose(pre_grasp_position, tcp_orientation),
    makePose(grasp_position, tcp_orientation),
    makePose(lift_position, tcp_orientation),
    principal_axis,
    closing_axis};
}

void setBoundedStartState(moveit::planning_interface::MoveGroupInterface & group)
{
  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    group.setStartStateToCurrentState();
    return;
  }

  current_state->enforceBounds();
  current_state->update();
  group.setStartState(*current_state);
}

bool planAndExecute(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & group,
  const std::string & label,
  int max_attempts = 2)
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
  const task_presets::PickTuningPreset & tuning,
  const std::string & fallback_named_target)
{
  if (tuning.gripper_close.enabled) {
    RCLCPP_INFO(
      logger,
      "Bread pick: closing left gripper to joint position %.3f",
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
    return planAndExecute(logger, gripper, "left bread grasp close");
  }

  RCLCPP_INFO(
    logger,
    "Bread pick: closing left gripper to named target '%s'",
    fallback_named_target.c_str());
  gripper.setNamedTarget(fallback_named_target);
  return planAndExecute(logger, gripper, "left bread grasp close");
}

bool planAndExecuteStagePoseIfConfigured(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  task_presets::ManufacturingStage stage,
  const std::string & tcp_link,
  bool & configured)
{
  configured = false;
  const auto * preset = task_presets::findLeftBreadPickStagePose(stage);
  if (preset == nullptr) {
    return true;
  }

  configured = true;
  geometry_msgs::msg::Pose target_pose = arm.getCurrentPose(tcp_link).pose;
  target_pose.position.x = preset->pose.x;
  target_pose.position.y = preset->pose.y;
  target_pose.position.z = preset->pose.z;
  target_pose.orientation = makeQuaternion(preset->pose);

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);

  const std::string label =
    std::string("stage pose ") + task_presets::stageName(stage);
  return planAndExecute(logger, arm, label, 1);
}

bool executeCartesian(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & group,
  const std::vector<geometry_msgs::msg::Pose> & waypoints,
  const std::string & label,
  double eef_step,
  double min_fraction,
  bool avoid_collisions)
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
  if (planAndExecute(logger, arm, "left bread pre-grasp exact pose", 1)) {
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
    if (planAndExecute(logger, arm, "left bread pre-grasp position only", 1)) {
      used_mode = PreGraspGoalMode::PositionOnly;
      return true;
    }
  }

  if (allow_approximate_pose) {
    RCLCPP_WARN(logger, "Position-only pre-grasp target failed; trying approximate IK target");
    arm.clearPoseTargets();
    setBoundedStartState(arm);
    if (arm.setApproximateJointValueTarget(pre_grasp_pose, tcp_link) &&
      planAndExecute(logger, arm, "left bread pre-grasp approximate pose", 1))
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
    active_step_ = declare_parameter<std::string>("active_step", "bread_pick");
    target_model_ = declare_parameter<std::string>("target_model", "bread");
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
    planning_time_sec_ = declare_parameter<double>("planning_time_sec", 8.0);
    planning_attempts_ = declare_parameter<int>("planning_attempts", 8);
    velocity_scaling_ = declare_parameter<double>("velocity_scaling", 0.15);
    acceleration_scaling_ = declare_parameter<double>("acceleration_scaling", 0.15);
    gripper_velocity_scaling_ = declare_parameter<double>("gripper_velocity_scaling", 0.4);
    gripper_acceleration_scaling_ = declare_parameter<double>("gripper_acceleration_scaling", 0.4);
    pre_grasp_height_ = declare_parameter<double>("pre_grasp_height", 0.12);
    lift_height_ = declare_parameter<double>("lift_height", 0.12);
    cartesian_eef_step_ = declare_parameter<double>("cartesian_eef_step", 0.005);
    min_cartesian_fraction_ = declare_parameter<double>("min_cartesian_fraction", 0.90);
    cartesian_avoid_collisions_ = declare_parameter<bool>("cartesian_avoid_collisions", false);
    gripper_open_target_ = declare_parameter<std::string>("gripper_open_target", "open");
    gripper_grasp_target_ = declare_parameter<std::string>("gripper_grasp_target", "half_closed");
    remove_target_collision_before_grasp_ =
      declare_parameter<bool>("remove_target_collision_before_grasp", true);
    collision_scene_settle_ms_ = declare_parameter<int>("collision_scene_settle_ms", 300);
    allow_approximate_pre_grasp_ = declare_parameter<bool>("allow_approximate_pre_grasp", false);
    allow_position_only_pre_grasp_ = declare_parameter<bool>("allow_position_only_pre_grasp", true);
    adapt_grasp_orientation_to_reached_pre_grasp_ =
      declare_parameter<bool>("adapt_grasp_orientation_to_reached_pre_grasp", true);
    max_pre_grasp_xy_error_ = declare_parameter<double>("max_pre_grasp_xy_error", 0.03);
    dry_run_ = declare_parameter<bool>("dry_run", false);

    try {
      start_from_stage_ = parseStartFromStage(start_from_stage_name_);
      stop_after_stage_ = parseStopAfterStage(stop_after_stage_name_);
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

    if (active_step_ != "bread_pick") {
      RCLCPP_ERROR(
        get_logger(),
        "Unsupported active_step '%s'. First actual motion step supports 'bread_pick' only.",
        active_step_.c_str());
      return false;
    }
    return runBreadPick();
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

  bool runBreadPick()
  {
    RCLCPP_INFO(
      get_logger(),
      "Hotdog bread pick started: item=%s, target_model=%s",
      item_name_.c_str(),
      target_model_.c_str());

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
      target = loadTargetObject(package_share_directory, layout_path, target_model_);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", target_model_.c_str(), error.what());
      return false;
    }

    const auto & bread_pick_tuning = task_presets::kLeftBreadPickTuning;
    BreadPickPlan pick_plan =
      makeTopDownPickPlan(
        target,
        pre_grasp_height_,
        lift_height_,
        bread_pick_tuning.grasp_tcp_z_offset_m);
    const bool pre_grasp_pose_configured = hasStagePosePreset(ManufacturingStage::PreGrasp);
    const bool pick_pose_configured = hasStagePosePreset(ManufacturingStage::Pick);
    if (pre_grasp_pose_configured) {
      applyStagePosePreset(
        get_logger(),
        task_presets::ManufacturingStage::PreGrasp,
        pick_plan.pre_grasp_pose);
    }
    if (pick_pose_configured) {
      applyStagePosePreset(
        get_logger(),
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
      "Bread pick tuning: grasp_tcp_z_offset=%.3f, gripper_joint_position=%s%.3f",
      bread_pick_tuning.grasp_tcp_z_offset_m,
      bread_pick_tuning.gripper_close.enabled ? "" : "disabled fallback ",
      bread_pick_tuning.gripper_close.joint_position);

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Hotdog bread pick dry run completed: pre_grasp=[%.3f %.3f %.3f], grasp=[%.3f %.3f %.3f], lift=[%.3f %.3f %.3f]",
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
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;

    left_arm.setPlanningTime(planning_time_sec_);
    left_arm.setNumPlanningAttempts(planning_attempts_);
    left_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    left_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    left_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    left_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    left_arm.setPoseReferenceFrame(left_arm.getPlanningFrame());
    const bool tcp_set = left_arm.setEndEffectorLink(left_tcp_link_);
    RCLCPP_INFO(
      get_logger(),
      "MoveIt setup: planning_frame='%s', left_eef='%s' (%s)",
      left_arm.getPlanningFrame().c_str(),
      left_arm.getEndEffectorLink().c_str(),
      tcp_set ? "ok" : "failed");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick initial");

    if (!left_ready_joints_.empty()) {
      left_arm.rememberJointValues(left_ready_pose_name_, left_ready_joints_);
    }

    bool home_stage_configured = false;
    if (shouldRunStage(ManufacturingStage::Home)) {
      if (!planAndExecuteStagePoseIfConfigured(
          get_logger(),
          left_arm,
          task_presets::ManufacturingStage::Home,
          left_tcp_link_,
          home_stage_configured))
      {
        return false;
      }

      if (!home_stage_configured) {
        RCLCPP_INFO(get_logger(), "Bread pick: moving left arm to ready pose");
        left_arm.clearPoseTargets();
        setBoundedStartState(left_arm);
        left_arm.setNamedTarget(left_ready_pose_name_);
        if (!planAndExecute(get_logger(), left_arm, "left bread pick ready")) {
          return false;
        }
      } else {
        RCLCPP_INFO(get_logger(), "Bread pick: moved left arm using configured home stage pose");
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick ready");
      if (shouldStopAfter(ManufacturingStage::Home)) {
        return true;
      }
    }

    if (shouldRunStage(ManufacturingStage::PreGrasp) || shouldRunStage(ManufacturingStage::Pick)) {
      RCLCPP_INFO(get_logger(), "Bread pick: opening left gripper");
      left_gripper.setNamedTarget(gripper_open_target_);
      if (!planAndExecute(get_logger(), left_gripper, "left gripper open")) {
        return false;
      }
    }

    bool target_collision_removed = false;

    PreGraspGoalMode pre_grasp_goal_mode = PreGraspGoalMode::ExactPose;
    geometry_msgs::msg::Pose reached_pre_grasp_pose;
    if (shouldRunStage(ManufacturingStage::PreGrasp)) {
      RCLCPP_INFO(get_logger(), "Bread pick: planning to top-down pre-grasp");
      if (!planAndExecutePreGrasp(
          get_logger(),
          left_arm,
          pick_plan.pre_grasp_pose,
          left_tcp_link_,
          allow_approximate_pre_grasp_,
          allow_position_only_pre_grasp_,
          pre_grasp_goal_mode))
      {
        return false;
      }
      RCLCPP_INFO(
        get_logger(),
        "Bread pick: reached pre-grasp using %s goal mode",
        preGraspGoalModeName(pre_grasp_goal_mode));
      reached_pre_grasp_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick pre-grasp");
    } else {
      reached_pre_grasp_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick resume pre-grasp");
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
        "Bread pick: desired pre-grasp xy=[%.3f %.3f], reached tcp xy=[%.3f %.3f], error=%.3f m",
        pick_plan.pre_grasp_pose.position.x,
        pick_plan.pre_grasp_pose.position.y,
        reached_pre_grasp_pose.position.x,
        reached_pre_grasp_pose.position.y,
        pre_grasp_xy_error);
      if (pre_grasp_xy_error > max_pre_grasp_xy_error_) {
        RCLCPP_ERROR(
          get_logger(),
          "Bread pick: rejecting pre-grasp because TCP xy error %.3f m exceeds %.3f m",
          pre_grasp_xy_error,
          max_pre_grasp_xy_error_);
        return false;
      }
      if (shouldStopAfter(ManufacturingStage::PreGrasp)) {
        return true;
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
          "Bread pick: adapted grasp/lift orientation to reached pre-grasp orientation");
      }

      if (remove_target_collision_before_grasp_ && !target_collision_removed) {
        RCLCPP_INFO(
          get_logger(),
          "Bread pick: removing target collision object '%s' before grasp approach",
          target_model_.c_str());
        planning_scene_interface.removeCollisionObjects({target_model_});
        if (collision_scene_settle_ms_ > 0) {
          rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
        }
      }

      RCLCPP_INFO(get_logger(), "Bread pick: Cartesian descent to grasp");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {grasp_pose},
          "left bread grasp descent",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick grasp");

      if (!closeGripperForPick(
          get_logger(),
          left_gripper,
          bread_pick_tuning,
          gripper_grasp_target_))
      {
        return false;
      }
      rclcpp::sleep_for(300ms);

      RCLCPP_INFO(get_logger(), "Bread pick: Cartesian lift");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {lift_pose},
          "left bread lift",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick lift");
      if (shouldStopAfter(ManufacturingStage::Pick)) {
        return true;
      }
    }

    bool optional_stage_configured = false;
    if (!planAndExecuteStagePoseIfConfigured(
        get_logger(),
        left_arm,
        task_presets::ManufacturingStage::Work,
        left_tcp_link_,
        optional_stage_configured))
    {
      return false;
    }
    if (optional_stage_configured) {
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick work");
    }
    if (shouldStopAfter(ManufacturingStage::Work)) {
      return true;
    }

    if (!planAndExecuteStagePoseIfConfigured(
        get_logger(),
        left_arm,
        task_presets::ManufacturingStage::Place,
        left_tcp_link_,
        optional_stage_configured))
    {
      return false;
    }
    if (optional_stage_configured) {
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick place");
    }
    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    if (!planAndExecuteStagePoseIfConfigured(
        get_logger(),
        left_arm,
        task_presets::ManufacturingStage::ReturnHome,
        left_tcp_link_,
        optional_stage_configured))
    {
      return false;
    }
    if (optional_stage_configured) {
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread pick return-home");
    }
    if (shouldStopAfter(ManufacturingStage::ReturnHome)) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Hotdog bread pick completed");
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
  std::string active_step_;
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
  double planning_time_sec_{8.0};
  int planning_attempts_{8};
  double velocity_scaling_{0.15};
  double acceleration_scaling_{0.15};
  double gripper_velocity_scaling_{0.4};
  double gripper_acceleration_scaling_{0.4};
  double pre_grasp_height_{0.12};
  double lift_height_{0.12};
  double cartesian_eef_step_{0.005};
  double min_cartesian_fraction_{0.90};
  bool cartesian_avoid_collisions_{false};
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
