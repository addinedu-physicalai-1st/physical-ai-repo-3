#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cmath>
#include <fstream>
#include <future>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
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
#include <moveit_msgs/msg/allowed_collision_entry.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <moveit_msgs/msg/planning_scene.hpp>
#include <moveit_msgs/msg/planning_scene_components.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <moveit_msgs/srv/get_planning_scene.hpp>
#include <rclcpp/rclcpp.hpp>
#include <shape_msgs/msg/solid_primitive.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

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

std::optional<ManufacturingStage> parsePlayToStage(const std::string & value)
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
  throw std::invalid_argument("unsupported play_to_stage '" + value + "'");
}

ManufacturingTarget parseManufacturingTask(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized == "bread") {
    return ManufacturingTarget::Bread;
  }
  if (normalized == "case") {
    return ManufacturingTarget::Case;
  }
  if (normalized == "coffee" || normalized == "cancoffee") {
    return ManufacturingTarget::Coffee;
  }
  if (normalized == "coke" || normalized == "cola" || normalized == "cancoke") {
    return ManufacturingTarget::Coke;
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
  throw std::invalid_argument("unsupported task '" + value + "'");
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

std::optional<ManufacturingStage> stageEndpointFromWaypointName(const std::string & value)
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
  return std::nullopt;
}

std::optional<ManufacturingStage> stageHintFromWaypointName(const std::string & value)
{
  if (const auto stage_endpoint = stageEndpointFromWaypointName(value)) {
    return stage_endpoint;
  }

  const std::string normalized = normalizeStageName(value);
  if (normalized == "pregrasp" || normalized == "targetalign" || normalized == "clearance" ||
    normalized == "grasp" || normalized == "close" || normalized == "pullout" ||
    normalized == "lift")
  {
    return ManufacturingStage::Pick;
  }
  if (normalized == "casepresent" || normalized == "aim" || normalized == "squeezestart" ||
    normalized == "squeeze" || normalized == "handoff" || normalized == "prereceive" ||
    normalized == "receiveopen" || normalized == "receive" || normalized == "receiveclose" ||
    normalized == "leftpullout" || normalized == "leftretreat")
  {
    return ManufacturingStage::Work;
  }
  if (normalized == "move1" || normalized == "move2" || normalized == "approach" ||
    normalized == "returnpose" || normalized == "releasepose" || normalized == "release")
  {
    return ManufacturingStage::Place;
  }
  return std::nullopt;
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

struct PoseAxisReferenceValues
{
  std::optional<Eigen::Vector3d> case_position;
  std::optional<Eigen::Vector3d> target_position;
};

const char * poseAxisSourceName(task_presets::PoseAxisSource source)
{
  switch (source) {
    case task_presets::PoseAxisSource::Preset:
      return "preset";
    case task_presets::PoseAxisSource::CaseTcp:
      return "case_tcp";
    case task_presets::PoseAxisSource::TargetObject:
      return "target_object";
  }
  return "unknown";
}

double resolvePoseAxisValue(
  const rclcpp::Logger & logger,
  task_presets::PoseAxisSource source,
  double preset_value,
  int axis_index,
  const PoseAxisReferenceValues & references,
  const char * label)
{
  if (source == task_presets::PoseAxisSource::CaseTcp) {
    if (references.case_position.has_value()) {
      return references.case_position.value()[axis_index];
    }
    RCLCPP_WARN(
      logger,
      "%s requested case_tcp axis source, but case reference is unavailable; using preset value",
      label);
    return preset_value;
  }

  if (source == task_presets::PoseAxisSource::TargetObject) {
    if (references.target_position.has_value()) {
      return references.target_position.value()[axis_index];
    }
    RCLCPP_WARN(
      logger,
      "%s requested target_object axis source, but target reference is unavailable; using preset value",
      label);
    return preset_value;
  }

  return preset_value;
}

geometry_msgs::msg::Pose makePoseFromWaypointPreset(
  const rclcpp::Logger & logger,
  const task_presets::StageWaypointPosePreset & preset,
  const PoseAxisReferenceValues & references,
  const char * label)
{
  geometry_msgs::msg::Pose pose = makePoseFromPreset(preset.pose);
  pose.position.x = resolvePoseAxisValue(
    logger, preset.x_source, preset.pose.x, 0, references, label) + preset.x_offset;
  pose.position.y = resolvePoseAxisValue(
    logger, preset.y_source, preset.pose.y, 1, references, label) + preset.y_offset;
  pose.position.z = resolvePoseAxisValue(
    logger, preset.z_source, preset.pose.z, 2, references, label) + preset.z_offset;

  RCLCPP_INFO(
    logger,
    "%s waypoint axis sources: x=%s y=%s z=%s, offsets=[%.3f %.3f %.3f] -> xyz=[%.3f %.3f %.3f]",
    label,
    poseAxisSourceName(preset.x_source),
    poseAxisSourceName(preset.y_source),
    poseAxisSourceName(preset.z_source),
    preset.x_offset,
    preset.y_offset,
    preset.z_offset,
    pose.position.x,
    pose.position.y,
    pose.position.z);
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

Eigen::Vector3d rpyFromRotation(const Eigen::Matrix3d & rotation)
{
  const double pitch = std::asin(std::clamp(-rotation(2, 0), -1.0, 1.0));
  const double cos_pitch = std::cos(pitch);
  double roll = 0.0;
  double yaw = 0.0;
  if (std::abs(cos_pitch) > 1e-6) {
    roll = std::atan2(rotation(2, 1), rotation(2, 2));
    yaw = std::atan2(rotation(1, 0), rotation(0, 0));
  } else {
    roll = std::atan2(-rotation(1, 2), rotation(1, 1));
    yaw = 0.0;
  }
  return Eigen::Vector3d(roll, pitch, yaw);
}

Eigen::Vector3d objectWorldCenter(const TargetObject & target)
{
  return target.xyz + rotationFromRpy(target.rpy) * target.local_center;
}

std::vector<std::string> visionClassAliases(
  ManufacturingTarget target,
  const std::string & target_model)
{
  std::vector<std::string> aliases{
    normalizeStageName(target_model),
    normalizeStageName(task_presets::targetName(target)),
  };

  switch (target) {
    case ManufacturingTarget::Bread:
      aliases.insert(aliases.end(), {"bread", "bun", "hotdogbun"});
      break;
    case ManufacturingTarget::Case:
      aliases.insert(aliases.end(), {"case", "tray", "box", "hotdogcase"});
      break;
    case ManufacturingTarget::Coffee:
      aliases.insert(aliases.end(), {"coffee", "can", "cancoffee", "cup"});
      break;
    case ManufacturingTarget::Coke:
      aliases.insert(aliases.end(), {"coke", "cola", "can", "cancoke"});
      break;
    case ManufacturingTarget::Ketchup:
      aliases.insert(aliases.end(), {"ketchup", "kachup", "bottle"});
      break;
    case ManufacturingTarget::Sausage:
      aliases.insert(aliases.end(), {"sausage", "hotdogsausage"});
      break;
    case ManufacturingTarget::Hotdog:
      aliases.insert(aliases.end(), {"hotdog", "newyorkhotdog"});
      break;
  }

  std::sort(aliases.begin(), aliases.end());
  aliases.erase(std::remove_if(
      aliases.begin(),
      aliases.end(),
      [](const std::string & alias) {return alias.empty();}),
    aliases.end());
  aliases.erase(std::unique(aliases.begin(), aliases.end()), aliases.end());
  return aliases;
}

bool visionClassMatches(
  const std::string & class_id,
  ManufacturingTarget target,
  const std::string & target_model)
{
  const std::string normalized_class = normalizeStageName(class_id);
  for (const std::string & alias : visionClassAliases(target, target_model)) {
    if (normalized_class == alias) {
      return true;
    }
  }
  return false;
}

bool poseHasValidOrientation(const geometry_msgs::msg::Pose & pose)
{
  const double norm_squared =
    pose.orientation.x * pose.orientation.x +
    pose.orientation.y * pose.orientation.y +
    pose.orientation.z * pose.orientation.z +
    pose.orientation.w * pose.orientation.w;
  return norm_squared > 1e-8;
}

Eigen::Vector3d heldCaseCenterFromTcpPose(const geometry_msgs::msg::Pose & right_tcp_pose)
{
  const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
  return posePosition(right_tcp_pose) +
         right_tcp_rotation.col(2).normalized() *
         (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
}

double poseOrientationDistanceRad(
  const geometry_msgs::msg::Pose & first,
  const geometry_msgs::msg::Pose & second)
{
  const Eigen::Quaterniond first_orientation = poseOrientation(first);
  const Eigen::Quaterniond second_orientation = poseOrientation(second);
  const double dot = std::abs(first_orientation.dot(second_orientation));
  return 2.0 * std::acos(std::clamp(dot, -1.0, 1.0));
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
  geometry_msgs::msg::Pose & pose,
  const PoseAxisReferenceValues & references = PoseAxisReferenceValues{})
{
  const auto * preset = task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint);
  if (preset == nullptr) {
    return;
  }

  const std::string label =
    std::string(task_presets::stageName(stage)) + "." + waypoint;
  pose = makePoseFromWaypointPreset(logger, *preset, references, label.c_str());
}

bool hasStageWaypointPosePreset(
  ManufacturingTarget target,
  ArmSide arm,
  ManufacturingStage stage,
  const char * waypoint)
{
  return task_presets::findStageWaypointPosePreset(target, arm, stage, waypoint) != nullptr;
}

std::vector<CollisionPrimitiveSpec> parseCollisionPrimitives(const std::string & sdf_text)
{
  std::vector<CollisionPrimitiveSpec> primitives;
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

    CollisionPrimitiveSpec primitive;
    bool has_geometry = false;
    if (const auto size_text = extractTagText(block, "size")) {
      const auto size_values = parseDoubles(size_text.value());
      if (size_values.size() == 3) {
        primitive.type = CollisionPrimitiveSpec::Type::Box;
        primitive.size = Eigen::Vector3d(size_values[0], size_values[1], size_values[2]);
        has_geometry = true;
      }
    } else {
      const auto radius_text = extractTagText(block, "radius");
      const auto length_text = extractTagText(block, "length");
      if (radius_text.has_value() && length_text.has_value()) {
        const auto radius_values = parseDoubles(radius_text.value());
        const auto length_values = parseDoubles(length_text.value());
        if (radius_values.size() == 1 && length_values.size() == 1) {
          const double diameter = radius_values[0] * 2.0;
          primitive.type = CollisionPrimitiveSpec::Type::Cylinder;
          primitive.radius = radius_values[0];
          primitive.length = length_values[0];
          primitive.size = Eigen::Vector3d(diameter, diameter, length_values[0]);
          has_geometry = true;
        }
      }
    }
    if (!has_geometry) {
      continue;
    }

    const auto pose_text = extractTagText(block, "pose");
    if (pose_text.has_value()) {
      const auto pose_values = parseDoubles(pose_text.value());
      if (pose_values.size() >= 3) {
        primitive.center = Eigen::Vector3d(pose_values[0], pose_values[1], pose_values[2]);
      }
      if (pose_values.size() >= 6) {
        primitive.rpy = Eigen::Vector3d(pose_values[3], pose_values[4], pose_values[5]);
      }
    }

    primitives.push_back(primitive);
  }
  return primitives;
}

std::vector<CollisionBox> parseCollisionBoxes(const std::string & sdf_text)
{
  std::vector<CollisionBox> boxes;
  for (const CollisionPrimitiveSpec & primitive : parseCollisionPrimitives(sdf_text)) {
    boxes.push_back(CollisionBox{primitive.center, primitive.size});
  }
  return boxes;
}

moveit_msgs::msg::CollisionObject makeCollisionObjectFromSdf(
  const std::string & package_share_directory,
  const std::string & layout_path,
  const std::string & target_model,
  const std::string & frame_id)
{
  const std::string layout_text = readTextFile(layout_path);
  const std::string model_block = extractJsonObjectForModel(layout_text, target_model);

  const std::string model_name = extractStringValue(model_block, "name");
  const std::string model_dir = extractStringValue(model_block, "model_dir");
  const Eigen::Vector3d model_xyz = extractVector3Value(model_block, "xyz");
  const Eigen::Vector3d model_rpy = extractVector3Value(model_block, "rpy");
  const Eigen::Matrix3d model_rotation = rotationFromRpy(model_rpy);

  const std::string sdf_path =
    joinPath(joinPath(package_share_directory, "assets"), joinPath(model_dir, "model.sdf"));
  const std::vector<CollisionPrimitiveSpec> primitives =
    parseCollisionPrimitives(readTextFile(sdf_path));
  if (primitives.empty()) {
    throw std::runtime_error("target model '" + target_model + "' has no supported collision geometry");
  }

  moveit_msgs::msg::CollisionObject object;
  object.header.frame_id = frame_id;
  object.id = model_name;
  object.operation = moveit_msgs::msg::CollisionObject::ADD;

  for (const CollisionPrimitiveSpec & primitive_spec : primitives) {
    shape_msgs::msg::SolidPrimitive primitive;
    if (primitive_spec.type == CollisionPrimitiveSpec::Type::Cylinder) {
      primitive.type = shape_msgs::msg::SolidPrimitive::CYLINDER;
      primitive.dimensions.resize(2);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_HEIGHT] =
        primitive_spec.length;
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_RADIUS] =
        primitive_spec.radius;
    } else {
      primitive.type = shape_msgs::msg::SolidPrimitive::BOX;
      primitive.dimensions.resize(3);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_X] = primitive_spec.size.x();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Y] = primitive_spec.size.y();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Z] = primitive_spec.size.z();
    }

    const Eigen::Vector3d global_center =
      model_xyz + model_rotation * primitive_spec.center;
    const Eigen::Matrix3d global_rotation =
      model_rotation * rotationFromRpy(primitive_spec.rpy);

    object.primitives.push_back(primitive);
    object.primitive_poses.push_back(makePose(global_center, Eigen::Quaterniond(global_rotation)));
  }

  return object;
}

moveit_msgs::msg::CollisionObject makeCollisionObjectFromTargetObject(
  const std::string & package_share_directory,
  const TargetObject & target,
  const std::string & frame_id)
{
  const std::string sdf_path =
    joinPath(joinPath(package_share_directory, "assets"), joinPath(target.model_dir, "model.sdf"));
  const std::vector<CollisionPrimitiveSpec> primitives =
    parseCollisionPrimitives(readTextFile(sdf_path));
  if (primitives.empty()) {
    throw std::runtime_error("target model '" + target.name + "' has no supported collision geometry");
  }

  const Eigen::Matrix3d model_rotation = rotationFromRpy(target.rpy);

  moveit_msgs::msg::CollisionObject object;
  object.header.frame_id = frame_id;
  object.id = target.name;
  object.operation = moveit_msgs::msg::CollisionObject::ADD;

  for (const CollisionPrimitiveSpec & primitive_spec : primitives) {
    shape_msgs::msg::SolidPrimitive primitive;
    if (primitive_spec.type == CollisionPrimitiveSpec::Type::Cylinder) {
      primitive.type = shape_msgs::msg::SolidPrimitive::CYLINDER;
      primitive.dimensions.resize(2);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_HEIGHT] =
        primitive_spec.length;
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_RADIUS] =
        primitive_spec.radius;
    } else {
      primitive.type = shape_msgs::msg::SolidPrimitive::BOX;
      primitive.dimensions.resize(3);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_X] = primitive_spec.size.x();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Y] = primitive_spec.size.y();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Z] = primitive_spec.size.z();
    }

    const Eigen::Vector3d global_center =
      target.xyz + model_rotation * primitive_spec.center;
    const Eigen::Matrix3d global_rotation =
      model_rotation * rotationFromRpy(primitive_spec.rpy);

    object.primitives.push_back(primitive);
    object.primitive_poses.push_back(makePose(global_center, Eigen::Quaterniond(global_rotation)));
  }

  return object;
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
    throw std::runtime_error("target model '" + target_model + "' has no supported collision geometry");
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

TargetObject makeKetchupBodyGraspTarget(const TargetObject & target)
{
  TargetObject body_target = target;

  // The ketchup model includes cap/nozzle collision geometry above the bottle.
  // Grasp pose generation should stay centered on the body cylinder so the
  // gripper does not chase the nozzle-biased overall bounds center.
  body_target.local_center = Eigen::Vector3d(0.0, 0.0, 0.0);
  body_target.size = Eigen::Vector3d(0.050, 0.050, 0.150);
  return body_target;
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
  return planAndExecute(
    logger,
    gripper,
    log_label + " gripper " + action,
    task_presets::kDefaultPlanExecuteMaxAttempts,
    task_presets::kDefaultGripperMinDurationSec);
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
  return planAndExecute(
    logger,
    gripper,
    log_label + " gripper open",
    task_presets::kDefaultPlanExecuteMaxAttempts,
    task_presets::kDefaultGripperMinDurationSec);
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
  return planAndExecute(
    logger,
    gripper,
    log_label + " grasp close",
    task_presets::kDefaultPlanExecuteMaxAttempts,
    task_presets::kDefaultGripperMinDurationSec);
}

std::vector<std::string> makeGripperTouchLinks(
  const moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & tcp_link)
{
  std::vector<std::string> touch_links = gripper.getLinkNames();
  touch_links.push_back(tcp_link);

  constexpr std::string_view kHandTcpSuffix = "_hand_tcp";
  if (tcp_link.size() > kHandTcpSuffix.size() &&
    tcp_link.compare(
      tcp_link.size() - kHandTcpSuffix.size(),
      kHandTcpSuffix.size(),
      kHandTcpSuffix) == 0)
  {
    const std::string arm_prefix = tcp_link.substr(0, tcp_link.size() - kHandTcpSuffix.size());
    touch_links.push_back(arm_prefix + "_hand");
    touch_links.push_back(arm_prefix + "_hand_tcp");
    touch_links.push_back(arm_prefix + "_left_finger");
    touch_links.push_back(arm_prefix + "_right_finger");
  }

  std::sort(touch_links.begin(), touch_links.end());
  touch_links.erase(std::unique(touch_links.begin(), touch_links.end()), touch_links.end());
  return touch_links;
}

bool applyTargetGripperAllowedCollision(
  const rclcpp::Node::SharedPtr & node,
  const rclcpp::Logger & logger,
  moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
  const std::string & target_object,
  const std::vector<std::string> & touch_links,
  bool allow,
  int settle_ms)
{
  if (target_object.empty() || touch_links.empty()) {
    return true;
  }

  auto client = node->create_client<moveit_msgs::srv::GetPlanningScene>("get_planning_scene");
  if (!client->wait_for_service(2s)) {
    RCLCPP_ERROR(logger, "MoveIt get_planning_scene service is not available");
    return false;
  }

  auto request = std::make_shared<moveit_msgs::srv::GetPlanningScene::Request>();
  request->components.components =
    moveit_msgs::msg::PlanningSceneComponents::ALLOWED_COLLISION_MATRIX;
  auto future = client->async_send_request(request);
  if (future.wait_for(2s) != std::future_status::ready) {
    RCLCPP_ERROR(logger, "Timed out while reading MoveIt allowed collision matrix");
    return false;
  }

  auto acm = future.get()->scene.allowed_collision_matrix;
  auto ensure_entry = [&acm](const std::string & name) {
      const auto found = std::find(acm.entry_names.begin(), acm.entry_names.end(), name);
      if (found != acm.entry_names.end()) {
        return static_cast<std::size_t>(std::distance(acm.entry_names.begin(), found));
      }

      const std::size_t new_size = acm.entry_names.size() + 1;
      acm.entry_names.push_back(name);
      for (auto & entry : acm.entry_values) {
        entry.enabled.resize(new_size, false);
      }
      moveit_msgs::msg::AllowedCollisionEntry entry;
      entry.enabled.assign(new_size, false);
      acm.entry_values.push_back(entry);
      return new_size - 1;
    };

  const std::size_t target_index = ensure_entry(target_object);
  for (const auto & link : touch_links) {
    const std::size_t link_index = ensure_entry(link);
    acm.entry_values[target_index].enabled[link_index] = allow;
    acm.entry_values[link_index].enabled[target_index] = allow;
  }

  moveit_msgs::msg::PlanningScene scene;
  scene.is_diff = true;
  scene.allowed_collision_matrix = acm;

  RCLCPP_INFO(
    logger,
    "%s target/gripper collision between '%s' and %zu touch links",
    allow ? "Allowing" : "Restoring",
    target_object.c_str(),
    touch_links.size());
  if (!planning_scene_interface.applyPlanningScene(scene)) {
    RCLCPP_ERROR(
      logger,
      "Failed to apply allowed collision update for target '%s'",
      target_object.c_str());
    return false;
  }
  if (settle_ms > 0) {
    rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
  }
  return true;
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

  const std::string label =
    std::string("stage waypoint pose ") + task_presets::stageName(stage) + "." + waypoint;
  const geometry_msgs::msg::Pose current_pose = arm.getCurrentPose(tcp_link).pose;
  const double position_error = (posePosition(current_pose) - posePosition(target_pose)).norm();
  const double orientation_error = poseOrientationDistanceRad(current_pose, target_pose);
  if (position_error <= task_presets::kDefaultPoseTargetSkipPositionToleranceM &&
    orientation_error <= task_presets::kDefaultPoseTargetSkipOrientationToleranceRad)
  {
    RCLCPP_INFO(
      logger,
      "%s skipped; current TCP is already near target (pos_error=%.4f m, rot_error=%.4f rad)",
      label.c_str(),
      position_error,
      orientation_error);
    return true;
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);

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
  const geometry_msgs::msg::Pose current_pose = arm.getCurrentPose(tcp_link).pose;
  const double position_error = (posePosition(current_pose) - posePosition(target_pose)).norm();
  const double orientation_error = poseOrientationDistanceRad(current_pose, target_pose);
  if (position_error <= task_presets::kDefaultPoseTargetSkipPositionToleranceM &&
    orientation_error <= task_presets::kDefaultPoseTargetSkipOrientationToleranceRad)
  {
    RCLCPP_INFO(
      logger,
      "%s skipped; current TCP is already near target (pos_error=%.4f m, rot_error=%.4f rad)",
      label.c_str(),
      position_error,
      orientation_error);
    return true;
  }

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

void alignTrajectoryStartToCurrentState(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & group,
  moveit_msgs::msg::RobotTrajectory & trajectory,
  const std::string & label)
{
  auto & points = trajectory.joint_trajectory.points;
  if (points.empty()) {
    return;
  }

  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    return;
  }

  auto & first_point = points.front();
  double max_delta = 0.0;
  const size_t count =
    std::min(trajectory.joint_trajectory.joint_names.size(), first_point.positions.size());
  for (size_t i = 0; i < count; ++i) {
    const auto & joint_name = trajectory.joint_trajectory.joint_names[i];
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
    RCLCPP_INFO(
      logger,
      "%s Cartesian trajectory start aligned to current state (max_delta=%.6f rad)",
      label.c_str(),
      max_delta);
  }
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
  alignTrajectoryStartToCurrentState(logger, group, plan.trajectory, label);
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
    task_name_ = declare_parameter<std::string>("task", "bread");
    arm_name_ = declare_parameter<std::string>("arm", "auto");
    target_model_ = declare_parameter<std::string>("target_model", "auto");
    case_target_model_ = declare_parameter<std::string>("case_target_model", "case");
    bread_target_model_ = declare_parameter<std::string>("bread_target_model", "bread1");
    sausage_target_model_ = declare_parameter<std::string>("sausage_target_model", "sausage");
    ketchup_target_model_ = declare_parameter<std::string>("ketchup_target_model", "kachup");
    coke_target_model_ = declare_parameter<std::string>("coke_target_model", "can_coke");
    coffee_target_model_ = declare_parameter<std::string>("coffee_target_model", "can_coffee");
    play_to_stage_name_ = declare_parameter<std::string>("play_to_stage", "complete");
    start_from_waypoint_name_ = declare_parameter<std::string>("start_from_waypoint", "");
    play_to_waypoint_name_ = declare_parameter<std::string>("play_to_waypoint", "");
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
    allow_gripper_target_collision_for_grasp_ =
      declare_parameter<bool>(
      "allow_gripper_target_collision_for_grasp",
      task_presets::kDefaultPlanningScene.allow_gripper_target_collision_for_grasp);
    collision_scene_settle_ms_ = declare_parameter<int>(
      "collision_scene_settle_ms",
      task_presets::kDefaultPlanningScene.collision_scene_settle_ms);
    max_pre_grasp_xy_error_ = declare_parameter<double>(
      "max_pre_grasp_xy_error",
      task_presets::kDefaultMaxPreGraspXyError);
    dry_run_ = declare_parameter<bool>("dry_run", false);
    enable_vision_pick_ = declare_parameter<bool>("enable_vision_pick", false);
    vision_detections_topic_ =
      declare_parameter<std::string>("vision_detections_topic", "/manufacturing_vision/detections");
    vision_pick_timeout_sec_ = declare_parameter<double>("vision_pick_timeout_sec", 2.0);
    vision_pick_max_age_sec_ = declare_parameter<double>("vision_pick_max_age_sec", 2.0);
    vision_pick_max_distance_m_ = declare_parameter<double>("vision_pick_max_distance_m", 0.15);
    vision_pick_min_score_ = declare_parameter<double>("vision_pick_min_score", 0.25);
    vision_pick_required_ = declare_parameter<bool>("vision_pick_required", false);
    vision_pick_use_orientation_ = declare_parameter<bool>("vision_pick_use_orientation", false);
    vision_pick_use_size_ = declare_parameter<bool>("vision_pick_use_size", false);

    if (enable_vision_pick_) {
      vision_detection_sub_ =
        create_subscription<vision_msgs::msg::Detection3DArray>(
        vision_detections_topic_,
        rclcpp::QoS(10),
        [this](vision_msgs::msg::Detection3DArray::SharedPtr msg) {
          handleVisionDetections(msg);
        });
      RCLCPP_INFO(
        get_logger(),
        "Vision pick enabled: topic=%s timeout=%.2fs max_age=%.2fs max_distance=%.3fm min_score=%.2f required=%s",
        vision_detections_topic_.c_str(),
        vision_pick_timeout_sec_,
        vision_pick_max_age_sec_,
        vision_pick_max_distance_m_,
        vision_pick_min_score_,
        vision_pick_required_ ? "true" : "false");
    }

    try {
      start_stage_ = ManufacturingStage::Home;
      if (!normalizeStageName(start_from_waypoint_name_).empty()) {
        if (const auto start_stage = stageHintFromWaypointName(start_from_waypoint_name_)) {
          start_stage_ = start_stage.value();
          if (!stageEndpointFromWaypointName(start_from_waypoint_name_)) {
            RCLCPP_WARN(
              get_logger(),
              "start_from_waypoint='%s' starts from containing stage '%s'; "
              "intra-stage waypoint resume is not exact yet",
              start_from_waypoint_name_.c_str(),
              task_presets::stageName(start_stage_));
          }
        } else {
          throw std::invalid_argument(
                  "unsupported start_from_waypoint '" + start_from_waypoint_name_ + "'");
        }
      }

      play_to_stage_ = parsePlayToStage(play_to_stage_name_);

      play_to_waypoint_ = normalizeStageName(play_to_waypoint_name_);
      if (const auto waypoint_stage_endpoint =
          stageEndpointFromWaypointName(play_to_waypoint_name_))
      {
        play_to_stage_ = waypoint_stage_endpoint;
        play_to_waypoint_.clear();
      }
      if (play_to_waypoint_ == "complete" || play_to_waypoint_ == "all" ||
        play_to_waypoint_ == "none")
      {
        play_to_waypoint_.clear();
      }
      target_ = parseManufacturingTask(task_name_);
      arm_ = parseArmSide(arm_name_).value_or(defaultArmForTarget(target_));
      if (play_to_stage_.has_value() &&
        stageOrder(play_to_stage_.value()) < stageOrder(start_stage_))
      {
        throw std::invalid_argument(
                "play_to_stage must be the same as or later than start_from_waypoint");
      }
    } catch (const std::exception & error) {
      play_range_valid_ = false;
      RCLCPP_ERROR(get_logger(), "%s", error.what());
    }
  }

  bool run()
  {
    if (!play_range_valid_) {
      return false;
    }

    if (scenario_only_) {
      return runScenario();
    }

    RCLCPP_INFO(
      get_logger(),
      "Manufacturing request: task=%s, arm=%s, start_stage=%s, play_to_stage=%s",
      task_presets::targetName(target_),
      task_presets::armName(arm_),
      task_presets::stageName(start_stage_),
      play_to_stage_.has_value() ? task_presets::stageName(play_to_stage_.value()) : "complete");

    if (target_ == ManufacturingTarget::Case && arm_ == ArmSide::Right) {
      return runCasePick();
    }
    if (target_ == ManufacturingTarget::Hotdog) {
      return runHotdogAssembly();
    }
    if (target_ == ManufacturingTarget::Bread && arm_ == ArmSide::Left) {
      if (play_to_stage_.has_value() &&
        stageOrder(play_to_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runBreadPick();
      }
      return runBreadPlace();
    }
    if (target_ == ManufacturingTarget::Sausage && arm_ == ArmSide::Left) {
      if (play_to_stage_.has_value() &&
        stageOrder(play_to_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runSausagePick();
      }
      return runSausagePlace();
    }
    if (target_ == ManufacturingTarget::Ketchup && arm_ == ArmSide::Left) {
      if (play_to_stage_.has_value() &&
        stageOrder(play_to_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runKetchupPick();
      }
      return runKetchupSqueeze();
    }
    if ((target_ == ManufacturingTarget::Coke || target_ == ManufacturingTarget::Coffee) &&
      arm_ == ArmSide::Left)
    {
      if (play_to_stage_.has_value() &&
        stageOrder(play_to_stage_.value()) <= stageOrder(ManufacturingStage::Pick))
      {
        return runBeverageCanPick(target_);
      }
      return runBeverageCanServe(target_);
    }

    RCLCPP_ERROR(
      get_logger(),
      "Unsupported task/arm combination: task=%s, arm=%s",
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
    if (start_stage_ == ManufacturingStage::Place) {
      RCLCPP_INFO(
        get_logger(),
        "New York hotdog assembly starts at completed-hotdog pickup-zone place");
      return runCompletedHotdogPlace();
    }

    if (start_stage_ != ManufacturingStage::Home ||
      (play_to_stage_.has_value() &&
      play_to_stage_.value() != ManufacturingStage::Place))
    {
      RCLCPP_WARN(
        get_logger(),
        "task:=hotdog currently runs the implemented full sequence and ignores waypoint slicing");
    }

    RCLCPP_INFO(get_logger(), "New York hotdog assembly started");

    const std::string saved_target_model = target_model_;
    const ManufacturingStage saved_start_stage = start_stage_;
    const auto saved_play_to_stage = play_to_stage_;

    auto restore_state = [&]() {
      target_model_ = saved_target_model;
      start_stage_ = saved_start_stage;
      play_to_stage_ = saved_play_to_stage;
    };

    start_stage_ = ManufacturingStage::Home;
    play_to_stage_.reset();

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

    play_to_stage_ = saved_play_to_stage;
    RCLCPP_INFO(get_logger(), "Hotdog assembly step 5/5: place completed hotdog at pickup zone");
    if (!runCompletedHotdogPlace()) {
      restore_state();
      return false;
    }
    if (!shouldStopAtOrBefore(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Hotdog assembly final step: return left arm home");
      if (!runSingleArmReturnHome(
          ManufacturingTarget::Hotdog,
          ArmSide::Left,
          left_arm_group_,
          left_tcp_link_,
          "Final left arm"))
      {
        restore_state();
        return false;
      }
    }

    restore_state();
    RCLCPP_INFO(get_logger(), "New York hotdog assembly completed");
    return true;
  }

  bool shouldStopAfter(ManufacturingStage stage) const
  {
    if (!play_to_stage_.has_value() || play_to_stage_.value() != stage) {
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
    if (play_to_waypoint_.empty()) {
      return false;
    }

    const std::string normalized_waypoint = normalizeStageName(waypoint);
    const std::string normalized_stage_waypoint =
      normalizeStageName(std::string(task_presets::stageName(stage)) + waypoint);
    if (play_to_waypoint_ != normalized_waypoint &&
      play_to_waypoint_ != normalized_stage_waypoint)
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
    return stageOrder(stage) >= stageOrder(start_stage_);
  }

  bool shouldStopAtOrBefore(ManufacturingStage stage) const
  {
    return play_to_stage_.has_value() &&
           stageOrder(play_to_stage_.value()) <= stageOrder(stage);
  }

  bool shouldStopAtOrBeforeWaypointStage(ManufacturingStage stage) const
  {
    if (play_to_waypoint_.empty()) {
      return false;
    }

    if (const auto waypoint_stage = stageHintFromWaypointName(play_to_waypoint_)) {
      return stageOrder(waypoint_stage.value()) <= stageOrder(stage);
    }

    for (const auto candidate_stage : {
        ManufacturingStage::Home,
        ManufacturingStage::Pick,
        ManufacturingStage::Work,
        ManufacturingStage::Place,
        ManufacturingStage::ReturnHome})
    {
      const std::string prefix = normalizeStageName(task_presets::stageName(candidate_stage));
      if (play_to_waypoint_.rfind(prefix, 0) == 0) {
        return stageOrder(candidate_stage) <= stageOrder(stage);
      }
    }

    return false;
  }

  bool planAndExecuteReturnHome(
    moveit::planning_interface::MoveGroupInterface & arm,
    ManufacturingTarget target,
    ArmSide arm_side,
    const std::string & tcp_link,
    const std::string & label)
  {
    bool return_home_pose_configured = false;
    if (!planAndExecuteStageWaypointPoseIfConfigured(
        get_logger(),
        arm,
        target,
        arm_side,
        task_presets::ManufacturingStage::ReturnHome,
        "return_home",
        tcp_link,
        return_home_pose_configured,
        pose_min_duration_sec_))
    {
      return false;
    }

    if (return_home_pose_configured) {
      logCurrentTcpPose(get_logger(), arm, tcp_link, label + " return-home waypoint");
      return true;
    }

    RCLCPP_INFO(get_logger(), "%s: moving arm to home pose", label.c_str());
    arm.clearPoseTargets();
    setBoundedStartState(arm);
    arm.setNamedTarget("home");
    if (!planAndExecute(
        get_logger(),
        arm,
        label + " home",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }

    logCurrentTcpPose(get_logger(), arm, tcp_link, label + " home");
    return true;
  }

  bool runSingleArmReturnHome(
    ManufacturingTarget target,
    ArmSide arm_side,
    const std::string & arm_group,
    const std::string & tcp_link,
    const std::string & label)
  {
    if (!shouldRunStage(ManufacturingStage::ReturnHome)) {
      return true;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface arm(self, arm_group);
    arm.setPlanningTime(planning_time_sec_);
    arm.setNumPlanningAttempts(planning_attempts_);
    arm.setMaxVelocityScalingFactor(velocity_scaling_);
    arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    arm.setPoseReferenceFrame(arm.getPlanningFrame());
    arm.setEndEffectorLink(tcp_link);

    return planAndExecuteReturnHome(arm, target, arm_side, tcp_link, label);
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
    PoseAxisReferenceValues pick_axis_references;
    pick_axis_references.target_position = objectWorldCenter(target);
    if (pre_grasp_pose_configured) {
      applyStageWaypointPosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Pick,
        "pre_grasp",
        pick_plan.pre_grasp_pose,
        pick_axis_references);
    }
    if (pick_pose_configured) {
      applyStageWaypointPosePreset(
        get_logger(),
        config.target,
        config.arm,
        task_presets::ManufacturingStage::Pick,
        "grasp",
        pick_plan.grasp_pose,
        pick_axis_references);
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
    if (!applyVisionCollisionObjectIfNeeded(planning_scene_interface, target, config.log_label)) {
      return false;
    }

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

    bool gripper_opened_for_approach = false;
    bool target_gripper_collision_allowed = false;
    std::vector<std::string> gripper_touch_links;
    auto restore_target_gripper_collision = [&]() {
      if (!target_gripper_collision_allowed) {
        return true;
      }
      const bool restored = applyTargetGripperAllowedCollision(
        self,
        get_logger(),
        planning_scene_interface,
        target.name,
        gripper_touch_links,
        false,
        collision_scene_settle_ms_);
      target_gripper_collision_allowed = false;
      return restored;
    };

    PreGraspGoalMode pre_grasp_goal_mode = PreGraspGoalMode::ExactPose;
    geometry_msgs::msg::Pose reached_pre_grasp_pose;
    if (shouldRunStage(ManufacturingStage::Pick)) {
      if (config.target == ManufacturingTarget::Case) {
        RCLCPP_INFO(
          get_logger(),
          "%s: opening gripper at ready pose before case approach",
          config.log_label.c_str());
        if (!openGripperForPickApproach(
            get_logger(),
            gripper,
            config.log_label,
            tuning,
            gripper_open_target_))
        {
          return false;
        }
        gripper_opened_for_approach = true;
      }

      RCLCPP_INFO(get_logger(), "%s: planning to pre-grasp", config.log_label.c_str());
      const bool use_pre_grasp_clearance =
        pre_grasp_pose_configured &&
        (config.target == ManufacturingTarget::Bread ||
        config.target == ManufacturingTarget::Sausage);
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
        } else if (
          config.target == ManufacturingTarget::Ketchup ||
          config.target == ManufacturingTarget::Coke ||
          config.target == ManufacturingTarget::Coffee)
        {
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

      if (!gripper_opened_for_approach) {
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
      }

      if (allow_gripper_target_collision_for_grasp_) {
        gripper_touch_links = makeGripperTouchLinks(gripper, config.tcp_link);
        if (!applyTargetGripperAllowedCollision(
            self,
            get_logger(),
            planning_scene_interface,
            target.name,
            gripper_touch_links,
            true,
            collision_scene_settle_ms_))
        {
          return false;
        }
        target_gripper_collision_allowed = true;
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
          restore_target_gripper_collision();
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
            restore_target_gripper_collision();
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
            restore_target_gripper_collision();
            return false;
          }
        }
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " grasp");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "grasp")) {
        restore_target_gripper_collision();
        return true;
      }

      if (!closeGripperForPick(
          get_logger(),
          gripper,
          config.log_label,
          tuning,
          gripper_grasp_target_))
      {
        restore_target_gripper_collision();
        return false;
      }
      rclcpp::sleep_for(300ms);
      if (gripper_touch_links.empty()) {
        gripper_touch_links = makeGripperTouchLinks(gripper, config.tcp_link);
      }
      if (!attachTargetCollisionObject(
          arm,
          target.name,
          config.tcp_link,
          gripper_touch_links,
          config.log_label))
      {
        restore_target_gripper_collision();
        return false;
      }
      if (!restore_target_gripper_collision()) {
        return false;
      }
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
          restore_target_gripper_collision();
          return false;
        }
        logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
        if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift")) {
          restore_target_gripper_collision();
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
        restore_target_gripper_collision();
        return false;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " pull-out");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "pull_out")) {
        restore_target_gripper_collision();
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
        restore_target_gripper_collision();
        return false;
      }
      logCurrentTcpPose(get_logger(), arm, config.tcp_link, config.log_label + " lift");
      if (shouldStopAfterWaypoint(ManufacturingStage::Pick, "lift")) {
        restore_target_gripper_collision();
        return true;
      }
    }

    if (!restore_target_gripper_collision()) {
      return false;
    }

    if (shouldStopAfter(ManufacturingStage::Pick)) {
      return true;
    }

    if (config.target == ManufacturingTarget::Bread || config.target == ManufacturingTarget::Sausage) {
      RCLCPP_INFO(get_logger(), "%s", config.completed_log.c_str());
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
      target_model_.empty() || target_model_ == "auto" ? "bread1" : target_model_;
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
    if (!applyVisionPickTarget(ManufacturingTarget::Bread, bread_target_model, target)) {
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

  void handleVisionDetections(const vision_msgs::msg::Detection3DArray::SharedPtr msg)
  {
    std::vector<VisionPickDetection> detections;
    detections.reserve(msg->detections.size());

    rclcpp::Time stamp(msg->header.stamp);
    if (stamp.nanoseconds() == 0) {
      stamp = get_clock()->now();
    }

    for (const auto & detection : msg->detections) {
      if (detection.results.empty()) {
        continue;
      }

      const auto best_result = std::max_element(
        detection.results.begin(),
        detection.results.end(),
        [](const auto & left, const auto & right) {
          return left.hypothesis.score < right.hypothesis.score;
        });
      if (best_result == detection.results.end()) {
        continue;
      }

      VisionPickDetection stored_detection;
      stored_detection.class_id = best_result->hypothesis.class_id;
      stored_detection.score = best_result->hypothesis.score;
      stored_detection.stamp = stamp;
      stored_detection.frame_id = msg->header.frame_id;
      stored_detection.pose = detection.bbox.center;
      stored_detection.size =
        Eigen::Vector3d(detection.bbox.size.x, detection.bbox.size.y, detection.bbox.size.z);
      detections.push_back(stored_detection);
    }

    {
      std::lock_guard<std::mutex> lock(vision_detections_mutex_);
      latest_vision_detections_ = std::move(detections);
      latest_vision_detection_stamp_ = stamp;
    }
  }

  std::optional<VisionPickDetection> findVisionPickDetection(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target)
  {
    std::vector<VisionPickDetection> detections;
    {
      std::lock_guard<std::mutex> lock(vision_detections_mutex_);
      detections = latest_vision_detections_;
    }

    if (detections.empty()) {
      return std::nullopt;
    }

    const rclcpp::Time now = get_clock()->now();
    const Eigen::Vector3d expected_center = objectWorldCenter(target);
    double best_distance = std::numeric_limits<double>::infinity();
    std::optional<VisionPickDetection> best_detection;

    for (const auto & detection : detections) {
      if (detection.score < vision_pick_min_score_) {
        continue;
      }
      if (!detection.frame_id.empty() && detection.frame_id != "world") {
        RCLCPP_WARN_THROTTLE(
          get_logger(),
          *get_clock(),
          2000,
          "Vision pick ignores detection '%s' in frame '%s'; expected world frame",
          detection.class_id.c_str(),
          detection.frame_id.c_str());
        continue;
      }
      if (!visionClassMatches(detection.class_id, target_kind, target_model)) {
        continue;
      }

      const double age_sec = (now - detection.stamp).seconds();
      if (std::isfinite(age_sec) && std::abs(age_sec) > vision_pick_max_age_sec_) {
        continue;
      }

      const Eigen::Vector3d detection_center = posePosition(detection.pose);
      const double distance = (detection_center - expected_center).norm();
      if (vision_pick_max_distance_m_ > 0.0 && distance > vision_pick_max_distance_m_) {
        continue;
      }
      if (distance < best_distance) {
        best_distance = distance;
        best_detection = detection;
      }
    }

    return best_detection;
  }

  std::optional<VisionPickDetection> waitForVisionPickDetection(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target)
  {
    const rclcpp::Time deadline =
      get_clock()->now() + rclcpp::Duration::from_seconds(vision_pick_timeout_sec_);

    while (rclcpp::ok() && get_clock()->now() < deadline) {
      if (const auto detection = findVisionPickDetection(target_kind, target_model, target)) {
        return detection;
      }
      rclcpp::sleep_for(100ms);
    }

    return findVisionPickDetection(target_kind, target_model, target);
  }

  bool applyVisionPickTarget(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    TargetObject & target)
  {
    if (!enable_vision_pick_ || !shouldRunStage(ManufacturingStage::Pick)) {
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "Vision pick: waiting up to %.2fs for %s/%s detection",
      vision_pick_timeout_sec_,
      task_presets::targetName(target_kind),
      target_model.c_str());
    const auto detection = waitForVisionPickDetection(target_kind, target_model, target);
    if (!detection.has_value()) {
      if (vision_pick_required_) {
        const std::string message =
          "Vision pick: no matching detection for " +
          std::string(task_presets::targetName(target_kind)) +
          "/" + target_model + "; aborting";
        RCLCPP_ERROR(get_logger(), "%s", message.c_str());
        return false;
      }
      const std::string message =
        "Vision pick: no matching detection for " +
        std::string(task_presets::targetName(target_kind)) +
        "/" + target_model + "; using layout target";
      RCLCPP_WARN(get_logger(), "%s", message.c_str());
      return true;
    }

    const Eigen::Vector3d previous_center = objectWorldCenter(target);
    const Eigen::Vector3d detection_center = posePosition(detection->pose);

    if (vision_pick_use_orientation_ && poseHasValidOrientation(detection->pose)) {
      const Eigen::Matrix3d detection_rotation = poseOrientation(detection->pose).toRotationMatrix();
      const Eigen::Vector3d horizontal_x(
        detection_rotation(0, 0),
        detection_rotation(1, 0),
        0.0);
      if (horizontal_x.norm() > 1e-6) {
        target.rpy.z() = std::atan2(horizontal_x.y(), horizontal_x.x());
      }
    }

    if (vision_pick_use_size_ &&
      detection->size.x() > 0.005 &&
      detection->size.y() > 0.005 &&
      detection->size.z() > 0.005)
    {
      target.size = detection->size;
    }

    target.xyz = detection_center - rotationFromRpy(target.rpy) * target.local_center;
    target.pose_from_vision = true;

    RCLCPP_INFO(
      get_logger(),
      "Vision pick target '%s': class=%s score=%.3f center [%.3f %.3f %.3f] -> [%.3f %.3f %.3f], xyz=[%.3f %.3f %.3f]",
      target.name.c_str(),
      detection->class_id.c_str(),
      detection->score,
      previous_center.x(),
      previous_center.y(),
      previous_center.z(),
      detection_center.x(),
      detection_center.y(),
      detection_center.z(),
      target.xyz.x(),
      target.xyz.y(),
      target.xyz.z());
    return true;
  }

  bool applyVisionCollisionObjectIfNeeded(
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    const TargetObject & target,
    const std::string & log_label)
  {
    if (!target.pose_from_vision) {
      return true;
    }

    std::string package_share_directory;
    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
      auto collision_object =
        makeCollisionObjectFromTargetObject(package_share_directory, target, "world");
      RCLCPP_INFO(
        get_logger(),
        "%s: updating collision object '%s' from vision target with %zu primitive(s)",
        log_label.c_str(),
        collision_object.id.c_str(),
        collision_object.primitives.size());
      planning_scene_interface.applyCollisionObject(collision_object);
      if (collision_scene_settle_ms_ > 0) {
        rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
      }
    } catch (const std::exception & error) {
      RCLCPP_ERROR(
        get_logger(),
        "%s: failed to update vision collision object '%s': %s",
        log_label.c_str(),
        target.name.c_str(),
        error.what());
      return false;
    }

    return true;
  }

  bool restoreTargetCollisionObject(
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    const std::string & target_model,
    const std::string & log_label)
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
      auto collision_object =
        makeCollisionObjectFromSdf(package_share_directory, layout_path, target_model, "world");
      RCLCPP_INFO(
        get_logger(),
        "%s: restoring collision object '%s' with %zu primitive(s)",
        log_label.c_str(),
        collision_object.id.c_str(),
        collision_object.primitives.size());
      planning_scene_interface.applyCollisionObject(collision_object);
      if (collision_scene_settle_ms_ > 0) {
        rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
      }
    } catch (const std::exception & error) {
      RCLCPP_ERROR(
        get_logger(),
        "%s: failed to restore collision object for '%s': %s",
        log_label.c_str(),
        target_model.c_str(),
        error.what());
      return false;
    }

    return true;
  }

  bool attachTargetCollisionObject(
    moveit::planning_interface::MoveGroupInterface & arm,
    const std::string & target_model,
    const std::string & attach_link,
    const std::vector<std::string> & touch_links,
    const std::string & log_label)
  {
    if (target_model.empty()) {
      return true;
    }
    if (attached_collision_objects_.find(target_model) != attached_collision_objects_.end()) {
      RCLCPP_INFO(
        get_logger(),
        "%s: collision object '%s' is already attached",
        log_label.c_str(),
        target_model.c_str());
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "%s: attaching collision object '%s' to '%s' with %zu touch links",
      log_label.c_str(),
      target_model.c_str(),
      attach_link.c_str(),
      touch_links.size());
    if (!arm.attachObject(target_model, attach_link, touch_links)) {
      RCLCPP_ERROR(
        get_logger(),
        "%s: failed to attach collision object '%s'",
        log_label.c_str(),
        target_model.c_str());
      return false;
    }

    attached_collision_objects_.insert(target_model);
    if (collision_scene_settle_ms_ > 0) {
      rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
    }
    return true;
  }

  bool detachTargetCollisionObject(
    moveit::planning_interface::MoveGroupInterface & arm,
    const std::string & target_model,
    const std::string & log_label)
  {
    if (target_model.empty()) {
      return true;
    }
    if (attached_collision_objects_.find(target_model) == attached_collision_objects_.end()) {
      RCLCPP_INFO(
        get_logger(),
        "%s: collision object '%s' is not attached; skipping detach",
        log_label.c_str(),
        target_model.c_str());
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "%s: detaching collision object '%s'",
      log_label.c_str(),
      target_model.c_str());
    if (!arm.detachObject(target_model)) {
      RCLCPP_ERROR(
        get_logger(),
        "%s: failed to detach collision object '%s'",
        log_label.c_str(),
        target_model.c_str());
      return false;
    }

    attached_collision_objects_.erase(target_model);
    if (collision_scene_settle_ms_ > 0) {
      rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
    }
    return true;
  }

  bool removeTargetCollisionObject(
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    const std::string & target_model,
    const std::string & log_label)
  {
    if (target_model.empty()) {
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "%s: removing world collision object '%s'",
      log_label.c_str(),
      target_model.c_str());
    planning_scene_interface.removeCollisionObjects({target_model});
    if (collision_scene_settle_ms_ > 0) {
      rclcpp::sleep_for(std::chrono::milliseconds(collision_scene_settle_ms_));
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
    if (!applyVisionPickTarget(ManufacturingTarget::Case, case_target_model, target)) {
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
    pick_plan.grasp_pose.position.z += task_presets::kRightCaseGraspWorldZOffsetM;
    pick_plan.lift_pose.position.z += task_presets::kRightCaseGraspWorldZOffsetM;

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
    if (!applyVisionPickTarget(ManufacturingTarget::Sausage, sausage_target_model, target)) {
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

  std::string beverageTargetModel(ManufacturingTarget beverage_target) const
  {
    if (!target_model_.empty() && target_model_ != "auto") {
      return target_model_;
    }
    if (beverage_target == ManufacturingTarget::Coffee) {
      return coffee_target_model_;
    }
    return coke_target_model_;
  }

  double beveragePickupZoneYOffset(ManufacturingTarget beverage_target) const
  {
    if (beverage_target == ManufacturingTarget::Coffee) {
      return task_presets::kCoffeePickupZoneYOffsetM;
    }
    return task_presets::kCokePickupZoneYOffsetM;
  }

  bool runBeverageCanPick(ManufacturingTarget beverage_target)
  {
    const std::string beverage_target_model = beverageTargetModel(beverage_target);
    RCLCPP_INFO(
      get_logger(),
      "Beverage can pick started: task=%s, target_model=%s",
      task_presets::targetName(beverage_target),
      beverage_target_model.c_str());

    TargetObject target;
    if (!loadManufacturingTarget(beverage_target_model, target)) {
      return false;
    }
    if (!applyVisionPickTarget(beverage_target, beverage_target_model, target)) {
      return false;
    }

    PickPlan pick_plan =
      makeHorizontalPickPlan(
        target,
        Eigen::Vector3d::UnitY(),
        Eigen::Vector3d::UnitX(),
        ketchup_pre_grasp_distance_,
        lift_height_,
        task_presets::kLeftBeverageCanPickTuning.grasp_tcp_z_offset_m);
    pick_plan.grasp_pose.position.z += task_presets::kLeftBeverageCanGraspWorldZOffsetM;
    pick_plan.lift_pose.position.z += task_presets::kLeftBeverageCanGraspWorldZOffsetM;

    return prepareAndRunPickMotion(
      PickMotionConfig{
        beverage_target,
        ArmSide::Left,
        std::string("Beverage ") + task_presets::targetName(beverage_target) + " pick",
        std::string("Beverage ") + task_presets::targetName(beverage_target) + " pick completed",
        left_arm_group_,
        left_gripper_group_,
        left_tcp_link_,
        left_ready_pose_name_,
        left_ready_joints_,
        &task_presets::kLeftBeverageCanPickTuning,
        true,
        false,
        false},
      target,
      pick_plan);
  }

  bool runBeverageCanServe(ManufacturingTarget beverage_target)
  {
    RCLCPP_INFO(
      get_logger(),
      "Beverage can serving started: task=%s",
      task_presets::targetName(beverage_target));

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_play_to_stage.has_value() &&
        stageOrder(requested_play_to_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        play_to_stage_ = ManufacturingStage::Pick;
      }
      const bool pick_ok = runBeverageCanPick(beverage_target);
      play_to_stage_ = requested_play_to_stage;
      if (!pick_ok) {
        return false;
      }
      if (shouldStopAtOrBefore(ManufacturingStage::Pick) ||
        shouldStopAtOrBeforeWaypointStage(ManufacturingStage::Pick))
      {
        return true;
      }
    }

    if (dry_run_) {
      RCLCPP_INFO(get_logger(), "Beverage serving dry run completed after pick planning");
      return true;
    }

    const std::string beverage_target_model = beverageTargetModel(beverage_target);
    TargetObject beverage_target_object;
    TargetObject pickup_zone;
    if (!loadManufacturingTarget(beverage_target_model, beverage_target_object) ||
      !loadManufacturingTarget("pickup_zone", pickup_zone))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface left_arm(self, left_arm_group_);
    moveit::planning_interface::MoveGroupInterface left_gripper(self, left_gripper_group_);
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);
    moveit::planning_interface::MoveGroupInterface right_gripper(self, right_gripper_group_);

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
    right_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    right_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    left_arm.setPoseReferenceFrame(left_arm.getPlanningFrame());
    right_arm.setPoseReferenceFrame(right_arm.getPlanningFrame());
    left_arm.setEndEffectorLink(left_tcp_link_);
    right_arm.setEndEffectorLink(right_tcp_link_);

    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left initial");
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right initial");

    if (shouldRunStage(ManufacturingStage::Work)) {
      geometry_msgs::msg::Pose left_handoff_pose = left_arm.getCurrentPose(left_tcp_link_).pose;
      if (const auto * left_handoff_preset =
          task_presets::findStageWaypointPosePreset(
            beverage_target,
            ArmSide::Left,
            ManufacturingStage::Work,
            "handoff"))
      {
        left_handoff_pose = makePoseFromPreset(left_handoff_preset->pose);
        RCLCPP_INFO(get_logger(), "Beverage left handoff waypoint pose preset applied");
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm to handoff pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          left_arm,
          left_handoff_pose,
          left_tcp_link_,
          "beverage left handoff pose",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left handoff");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "handoff")) {
        return true;
      }

      RCLCPP_INFO(
        get_logger(),
        "Beverage serving: using current right gripper opening for handoff receive");

      if (!right_ready_joints_.empty()) {
        right_arm.rememberJointValues(right_ready_pose_name_, right_ready_joints_);
      }
      RCLCPP_INFO(
        get_logger(),
        "Beverage serving: moving right arm to ready pose before receive");
      right_arm.clearPoseTargets();
      setBoundedStartState(right_arm);
      right_arm.setNamedTarget(right_ready_pose_name_);
      if (!planAndExecute(
          get_logger(),
          right_arm,
          "beverage right ready before receive",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right ready");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "right_ready")) {
        return true;
      }

      geometry_msgs::msg::Pose right_receive_pose = left_handoff_pose;
      right_receive_pose.position.z += task_presets::kBeverageHandoffRightFromLeftZOffsetM;
      PickPlan right_receive_plan =
        makeHorizontalPickPlan(
          TargetObject{
            "beverage_handoff",
            "",
            Eigen::Vector3d(
              right_receive_pose.position.x,
              right_receive_pose.position.y,
              right_receive_pose.position.z),
            Eigen::Vector3d::Zero(),
            Eigen::Vector3d::Zero(),
            beverage_target_object.size},
          -Eigen::Vector3d::UnitY(),
          Eigen::Vector3d::UnitX(),
          0.0,
          0.0,
          task_presets::kRightBeverageCanReceiveTuning.grasp_tcp_z_offset_m);
      right_receive_pose.orientation = right_receive_plan.grasp_pose.orientation;

      geometry_msgs::msg::Pose right_pre_receive_pose = right_receive_pose;
      bool right_pre_receive_pose_preset_enabled = false;
      if (const auto * right_pre_receive_preset =
          task_presets::findStageWaypointPosePreset(
            beverage_target,
            ArmSide::Right,
            ManufacturingStage::Work,
            "pre_receive"))
      {
        right_pre_receive_pose = makePoseFromPreset(right_pre_receive_preset->pose);
        right_pre_receive_pose_preset_enabled = true;
        RCLCPP_INFO(get_logger(), "Beverage right pre-receive waypoint pose preset applied");
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to pre-receive pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          right_arm,
          right_pre_receive_pose,
          right_tcp_link_,
          "beverage right pre-receive pose",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right pre-receive");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "pre_receive")) {
        return true;
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper before receive");
      if (!openGripperForPickApproach(
          get_logger(),
          right_gripper,
          "Beverage receive",
          task_presets::kRightBeverageCanReceiveTuning,
          gripper_open_target_))
      {
        return false;
      }
      rclcpp::sleep_for(300ms);
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive_open")) {
        return true;
      }

      if (right_pre_receive_pose_preset_enabled) {
        right_receive_pose = right_pre_receive_pose;
        right_receive_pose.position.x = left_handoff_pose.position.x;
        right_receive_pose.position.y = left_handoff_pose.position.y;
        right_receive_pose.position.z =
          left_handoff_pose.position.z + task_presets::kBeverageHandoffRightFromLeftZOffsetM;
        RCLCPP_INFO(
          get_logger(),
          "Beverage right receive pose centered on handoff can: xyz=[%.3f %.3f %.3f]",
          right_receive_pose.position.x,
          right_receive_pose.position.y,
          right_receive_pose.position.z);
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: planning right arm to receive grasp pose");
      if (!planAndExecutePoseTarget(
          get_logger(),
          right_arm,
          right_receive_pose,
          right_tcp_link_,
          "beverage right receive pose",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage right receive");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive")) {
        return true;
      }

      if (!closeGripperForPick(
          get_logger(),
          right_gripper,
          "Beverage receive",
          task_presets::kRightBeverageCanReceiveTuning,
          gripper_grasp_target_))
      {
        return false;
      }
      rclcpp::sleep_for(300ms);
      if (!detachTargetCollisionObject(left_arm, beverage_target_model, "Beverage handoff")) {
        return false;
      }
      if (!attachTargetCollisionObject(
          right_arm,
          beverage_target_model,
          right_tcp_link_,
          makeGripperTouchLinks(right_gripper, right_tcp_link_),
          "Beverage receive"))
      {
        return false;
      }
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "receive_close")) {
        return true;
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: releasing left gripper after handoff");
      if (!openGripperForPickApproach(
          get_logger(),
          left_gripper,
          "Beverage handoff release",
          task_presets::kLeftBeverageCanPickTuning,
          gripper_open_target_))
      {
        return false;
      }
      rclcpp::sleep_for(300ms);

      const auto * left_pull_out_preset =
        task_presets::findStageWaypointPosePreset(
          beverage_target,
          ArmSide::Left,
          ManufacturingStage::Work,
          "left_pull_out");
      if (left_pull_out_preset == nullptr || !left_pull_out_preset->pose.enabled) {
        RCLCPP_ERROR(
          get_logger(),
          "Beverage left_pull_out waypoint pose preset is disabled; "
          "set work.left_pull_out before running past receive_close");
        return false;
      }

      const auto left_pull_out_pose = makePoseFromPreset(left_pull_out_preset->pose);
      RCLCPP_INFO(get_logger(), "Beverage left pull-out waypoint pose preset applied");
      RCLCPP_INFO(get_logger(), "Beverage serving: Cartesian left-arm pull-out after handoff");
      if (!executeCartesian(
          get_logger(),
          left_arm,
          {left_pull_out_pose},
          "beverage left handoff pull-out",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left pull-out");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_pull_out")) {
        return true;
      }

      RCLCPP_INFO(get_logger(), "Beverage serving: moving left arm away after handoff");
      if (!left_ready_joints_.empty()) {
        left_arm.rememberJointValues(left_ready_pose_name_, left_ready_joints_);
      }
      left_arm.clearPoseTargets();
      setBoundedStartState(left_arm);
      left_arm.setNamedTarget(left_ready_pose_name_);
      if (!planAndExecute(
          get_logger(),
          left_arm,
          "beverage left retreat after handoff",
          task_presets::kDefaultPlanExecuteMaxAttempts,
          pose_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Beverage left retreat");
      if (shouldStopAfterWaypoint(ManufacturingStage::Work, "left_retreat")) {
        return true;
      }

      if (shouldStopAfter(ManufacturingStage::Work)) {
        return true;
      }
    }

    if (!shouldRunStage(ManufacturingStage::Place)) {
      RCLCPP_INFO(get_logger(), "Beverage serving completed before place stage");
      return true;
    }

    const Eigen::Matrix3d pickup_rotation = rotationFromRpy(pickup_zone.rpy);
    const Eigen::Vector3d pickup_center =
      pickup_zone.xyz + pickup_rotation * pickup_zone.local_center;
    const double pickup_top_z = pickup_center.z() + pickup_zone.size.z() * 0.5;

    geometry_msgs::msg::Pose release_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    release_pose.position.x = pickup_center.x();
    release_pose.position.y = pickup_center.y() + beveragePickupZoneYOffset(beverage_target);
    release_pose.position.z =
      pickup_top_z +
      beverage_target_object.size.z() * 0.5 +
      task_presets::kBeveragePickupPlaceClearanceM +
      task_presets::kRightBeverageCanReceiveWorldZOffsetM;

    const auto * approach_preset =
      task_presets::findStageWaypointPosePreset(
        beverage_target,
        ArmSide::Right,
        ManufacturingStage::Place,
        "approach");
    const bool approach_preset_enabled =
      approach_preset != nullptr && approach_preset->pose.enabled;

    const auto * release_preset =
      task_presets::findStageWaypointPosePreset(
        beverage_target,
        ArmSide::Right,
        ManufacturingStage::Place,
        "release_pose");
    const bool release_preset_enabled =
      release_preset != nullptr && release_preset->pose.enabled;
    if (release_preset_enabled)
    {
      release_pose = makePoseFromPreset(release_preset->pose);
      RCLCPP_INFO(get_logger(), "Beverage pickup release_pose waypoint pose preset applied");
    } else if (approach_preset_enabled) {
      const auto guide_pose = makePoseFromPreset(approach_preset->pose);
      release_pose.position.x = guide_pose.position.x;
      release_pose.position.y = guide_pose.position.y;
      release_pose.orientation = guide_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "Beverage pickup release_pose uses approach waypoint xy/orientation with computed z");
    } else {
      PickPlan place_plan =
        makeHorizontalPickPlan(
          TargetObject{
            "beverage_pickup_place",
            "",
            Eigen::Vector3d(
              release_pose.position.x,
              release_pose.position.y,
              release_pose.position.z),
            Eigen::Vector3d::Zero(),
            Eigen::Vector3d::Zero(),
            beverage_target_object.size},
          -Eigen::Vector3d::UnitY(),
          Eigen::Vector3d::UnitX(),
          0.0,
          0.0,
          task_presets::kRightBeverageCanReceiveTuning.grasp_tcp_z_offset_m);
      release_pose.orientation = place_plan.grasp_pose.orientation;
    }

    geometry_msgs::msg::Pose approach_pose = release_pose;
    approach_pose.position.z += task_presets::kBeveragePickupApproachHeightM;
    if (approach_preset_enabled)
    {
      approach_pose = makePoseFromPreset(approach_preset->pose);
      RCLCPP_INFO(get_logger(), "Beverage pickup approach waypoint pose preset applied");
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: moving right arm to pickup approach");
    if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        approach_pose,
        right_tcp_link_,
        "beverage pickup approach",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage pickup approach");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "approach")) {
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "Beverage serving: moving right arm to pickup release xyz=[%.3f %.3f %.3f]",
      release_pose.position.x,
      release_pose.position.y,
      release_pose.position.z);
    if (approach_preset_enabled && !release_preset_enabled) {
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {release_pose},
          "beverage pickup release",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
    } else if (!planAndExecutePoseTarget(
        get_logger(),
        right_arm,
        release_pose,
        right_tcp_link_,
        "beverage pickup release",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        pose_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Beverage pickup release");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release_pose")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Beverage serving: opening right gripper");
    if (!openGripperForPickApproach(
        get_logger(),
        right_gripper,
        "Beverage place",
        task_presets::kRightBeverageCanReceiveTuning,
        gripper_open_target_))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);
    if (!detachTargetCollisionObject(right_arm, beverage_target_model, "Beverage place")) {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return true;
    }

    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      RCLCPP_INFO(get_logger(), "Beverage serving: Cartesian right-arm retreat");
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {approach_pose},
          "beverage pickup retreat",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      if (!planAndExecuteReturnHome(
          right_arm,
          beverage_target,
          ArmSide::Right,
          right_tcp_link_,
          "Beverage right arm"))
      {
        return false;
      }
      if (!planAndExecuteReturnHome(
          left_arm,
          beverage_target,
          ArmSide::Left,
          left_tcp_link_,
          "Beverage left arm"))
      {
        return false;
      }
    }

    RCLCPP_INFO(
      get_logger(),
      "Beverage %s serving completed",
      task_presets::targetName(beverage_target));
    return true;
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
    if (!applyVisionPickTarget(ManufacturingTarget::Ketchup, ketchup_target_model, target)) {
      return false;
    }

    const TargetObject grasp_target = makeKetchupBodyGraspTarget(target);
    PickPlan pick_plan =
      makeHorizontalPickPlan(
        grasp_target,
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
      grasp_target,
      pick_plan);
  }

  bool runBreadPlace()
  {
    RCLCPP_INFO(get_logger(), "Hotdog bread place started: item=%s", item_name_.c_str());
    const std::string bread_target_model =
      target_model_.empty() || target_model_ == "auto" ? bread_target_model_ : target_model_;

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool bread_pick_ok = runBreadPick();
      play_to_stage_ = requested_play_to_stage;
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
      "Bread place MoveIt setup: left_eef='%s'",
      left_arm.getEndEffectorLink().c_str());
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Bread place case reference");
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Bread place initial");

    bool left_work_pose_configured = false;
    if (shouldRunStage(ManufacturingStage::Work)) {
      RCLCPP_INFO(get_logger(), "Bread place: moving to configured work pose");
      const auto * work_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Bread,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work");
      if (work_preset != nullptr) {
        left_work_pose_configured = true;
        PoseAxisReferenceValues references;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        const geometry_msgs::msg::Pose work_pose =
          makePoseFromWaypointPreset(get_logger(), *work_preset, references, "Bread place work");
        if (!planAndExecutePoseTarget(
            get_logger(),
            left_arm,
            work_pose,
            left_tcp_link_,
            "bread place work pose",
            task_presets::kDefaultPlanExecuteMaxAttempts,
            cartesian_min_duration_sec_))
        {
          return false;
        }
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
    if (!planAndExecute(
        get_logger(),
        left_gripper,
        "bread place gripper open",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        task_presets::kDefaultGripperMinDurationSec))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    if (!detachTargetCollisionObject(left_arm, bread_target_model, "Bread place")) {
      return false;
    }
    if (!removeTargetCollisionObject(planning_scene_interface, bread_target_model, "Bread place")) {
      return false;
    }

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
    const std::string sausage_target_model =
      target_model_.empty() || target_model_ == "auto" ? sausage_target_model_ : target_model_;

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      play_to_stage_ = ManufacturingStage::Pick;
      const bool sausage_pick_ok = runSausagePick();
      play_to_stage_ = requested_play_to_stage;
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
    if (!loadManufacturingTarget(sausage_target_model, sausage_target) ||
      !loadManufacturingTarget("bread1", bread_target) ||
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
    std::optional<geometry_msgs::msg::Pose> left_work_pose;
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

      const auto * left_work_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Sausage,
          ArmSide::Left,
          task_presets::ManufacturingStage::Work,
          "work");
      if (left_work_preset != nullptr) {
        left_work_pose_configured = true;
        PoseAxisReferenceValues references;
        references.case_position =
          heldCaseCenterFromTcpPose(right_arm.getCurrentPose(right_tcp_link_).pose);
        references.target_position = sausage_target.xyz;
        const geometry_msgs::msg::Pose work_pose =
          makePoseFromWaypointPreset(
            get_logger(), *left_work_preset, references, "Sausage place work");
        left_work_pose = work_pose;
        if (!planAndExecutePoseTarget(
            get_logger(),
            left_arm,
            work_pose,
            left_tcp_link_,
            "sausage place work pose",
            task_presets::kDefaultPlanExecuteMaxAttempts,
            cartesian_min_duration_sec_))
        {
          return false;
        }
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
    const Eigen::Vector3d case_center = heldCaseCenterFromTcpPose(right_tcp_pose);

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
      if (left_work_pose.has_value()) {
        approach_pose = left_work_pose.value();
        RCLCPP_INFO(get_logger(), "Sausage place approach reuses completed work pose");
      } else {
        PoseAxisReferenceValues references;
        references.case_position = case_center;
        references.target_position = sausage_target.xyz;
        approach_pose =
          makePoseFromWaypointPreset(
            get_logger(), *work_preset, references, "Sausage place approach");
        RCLCPP_INFO(get_logger(), "Sausage place approach pose preset applied");
      }
    } else {
      RCLCPP_INFO(
        get_logger(),
        "Sausage place auto approach pose: xyz=[%.3f %.3f %.3f]",
        approach_pose.position.x,
        approach_pose.position.y,
        approach_pose.position.z);
    }

    if (place_preset != nullptr) {
      PoseAxisReferenceValues references;
      references.case_position = case_center;
      references.target_position = sausage_target.xyz;
      release_pose =
        makePoseFromWaypointPreset(get_logger(), *place_preset, references, "Sausage place release");
      RCLCPP_INFO(get_logger(), "Sausage place release pose preset applied");
    } else {
      release_pose.position.x = approach_pose.position.x;
      release_pose.position.y = approach_pose.position.y;
      release_pose.orientation = approach_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "Sausage place auto release pose: xyz=[%.3f %.3f %.3f]",
        release_pose.position.x,
        release_pose.position.y,
        release_pose.position.z);
    }

    if (left_work_pose.has_value()) {
      RCLCPP_INFO(get_logger(), "Sausage place: already at approach pose from work stage");
    } else {
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
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place approach pose");

    if (left_work_pose.has_value() && place_preset == nullptr) {
      release_pose = approach_pose;
      RCLCPP_INFO(
        get_logger(),
        "Sausage place lower skipped; work pose is used as release pose");
    } else {
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
    }
    logCurrentTcpPose(get_logger(), left_arm, left_tcp_link_, "Sausage place release pose");

    RCLCPP_INFO(get_logger(), "Sausage place: opening left gripper");
    left_gripper.setNamedTarget(gripper_open_target_);
    if (!planAndExecute(
        get_logger(),
        left_gripper,
        "sausage place gripper open",
        task_presets::kDefaultPlanExecuteMaxAttempts,
        task_presets::kDefaultGripperMinDurationSec))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    if (!detachTargetCollisionObject(left_arm, sausage_target_model, "Sausage place")) {
      return false;
    }
    if (!removeTargetCollisionObject(planning_scene_interface, sausage_target_model, "Sausage place")) {
      return false;
    }

    if (shouldStopAfter(ManufacturingStage::Place)) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Sausage place: release completed without extra retreat");

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

    if (stageOrder(start_stage_) <= stageOrder(ManufacturingStage::Pick)) {
      const auto requested_play_to_stage = play_to_stage_;
      if (requested_play_to_stage.has_value() &&
        stageOrder(requested_play_to_stage.value()) > stageOrder(ManufacturingStage::Pick))
      {
        play_to_stage_.reset();
      }
      const bool ketchup_pick_ok = runKetchupPick();
      play_to_stage_ = requested_play_to_stage;
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
          if (!planAndExecute(
              get_logger(),
              left_gripper,
              "ketchup squeeze release pressure",
              task_presets::kDefaultPlanExecuteMaxAttempts,
              task_presets::kDefaultGripperMinDurationSec))
          {
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

    const TargetObject ketchup_grasp_target = makeKetchupBodyGraspTarget(ketchup_target);
    PickPlan return_plan =
      makeHorizontalPickPlan(
        ketchup_grasp_target,
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

    moveit::planning_interface::PlanningSceneInterface planning_scene_interface;
    if (!detachTargetCollisionObject(left_arm, ketchup_target_model, "Ketchup place")) {
      return false;
    }
    if (!restoreTargetCollisionObject(
        planning_scene_interface,
        ketchup_target_model,
        "Ketchup place"))
    {
      return false;
    }

    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Hotdog ketchup squeeze completed");
    return true;
  }

  bool runCompletedHotdogPlace()
  {
    RCLCPP_INFO(get_logger(), "Completed hotdog pickup-zone place started");

    if (dry_run_) {
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog place dry run skipped; live right TCP pose is required");
      return true;
    }

    TargetObject pickup_zone;
    TargetObject case_target;
    if (!loadManufacturingTarget("pickup_zone", pickup_zone) ||
      !loadManufacturingTarget(case_target_model_, case_target))
    {
      return false;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface right_arm(self, right_arm_group_);
    moveit::planning_interface::MoveGroupInterface right_gripper(self, right_gripper_group_);

    right_arm.setPlanningTime(planning_time_sec_);
    right_arm.setNumPlanningAttempts(planning_attempts_);
    right_arm.setMaxVelocityScalingFactor(velocity_scaling_);
    right_arm.setMaxAccelerationScalingFactor(acceleration_scaling_);
    right_gripper.setMaxVelocityScalingFactor(gripper_velocity_scaling_);
    right_gripper.setMaxAccelerationScalingFactor(gripper_acceleration_scaling_);

    right_arm.setPoseReferenceFrame(right_arm.getPlanningFrame());
    right_arm.setEndEffectorLink(right_tcp_link_);

    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog place initial");

    const geometry_msgs::msg::Pose current_pose = right_arm.getCurrentPose(right_tcp_link_).pose;
    const Eigen::Matrix3d tcp_rotation = poseOrientation(current_pose).toRotationMatrix();
    const Eigen::Vector3d tcp_z = tcp_rotation.col(2).normalized();

    const Eigen::Matrix3d pickup_rotation = rotationFromRpy(pickup_zone.rpy);
    const Eigen::Vector3d pickup_center = pickup_zone.xyz + pickup_rotation * pickup_zone.local_center;
    const double pickup_top_z = pickup_center.z() + pickup_zone.size.z() * 0.5;
    const Eigen::Vector3d desired_case_center(
      pickup_center.x(),
      pickup_center.y(),
      pickup_top_z + case_target.size.z() * 0.5 +
      task_presets::kCompletedHotdogPickupPlaceClearanceM);

    geometry_msgs::msg::Pose release_pose = current_pose;
    const Eigen::Vector3d release_tcp_position =
      desired_case_center -
      tcp_z * (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
    release_pose.position.x = release_tcp_position.x();
    release_pose.position.y = release_tcp_position.y();
    release_pose.position.z = release_tcp_position.z();

    geometry_msgs::msg::Pose approach_pose = release_pose;
    approach_pose.position.z += task_presets::kCompletedHotdogPickupApproachHeightM;

    bool release_pose_preset_configured = false;
    if (const auto * release_pose_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Hotdog,
          ArmSide::Right,
          ManufacturingStage::Place,
          "release_pose"))
    {
      release_pose_preset_configured = true;
      release_pose = makePoseFromPreset(release_pose_preset->pose);
      approach_pose = release_pose;
      approach_pose.position.z += task_presets::kCompletedHotdogPickupApproachHeightM;
      RCLCPP_INFO(get_logger(), "Completed hotdog place release_pose waypoint pose preset applied");
    } else {
      release_pose.orientation = approach_pose.orientation;
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog auto approach pose: xyz=[%.3f %.3f %.3f]",
        approach_pose.position.x,
        approach_pose.position.y,
        approach_pose.position.z);
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog auto release pose: xyz=[%.3f %.3f %.3f]",
        release_pose.position.x,
        release_pose.position.y,
        release_pose.position.z);
    }

    bool configured_carry_waypoint_used = false;
    for (const char * waypoint_name : {"move1", "move2"}) {
      const auto * waypoint_preset =
        task_presets::findStageWaypointPosePreset(
          ManufacturingTarget::Hotdog,
          ArmSide::Right,
          ManufacturingStage::Place,
          waypoint_name);
      if (waypoint_preset == nullptr) {
        continue;
      }

      configured_carry_waypoint_used = true;
      const geometry_msgs::msg::Pose waypoint_pose = makePoseFromPreset(waypoint_preset->pose);
      RCLCPP_INFO(
        get_logger(),
        "Completed hotdog place: Cartesian carry to waypoint %s",
        waypoint_name);
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {waypoint_pose},
          std::string("completed hotdog pickup ") + waypoint_name,
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup waypoint");
      if (shouldStopAfterWaypoint(ManufacturingStage::Place, waypoint_name)) {
        return true;
      }
    }

    if (!configured_carry_waypoint_used && release_pose_preset_configured) {
      geometry_msgs::msg::Pose midpoint_pose = current_pose;
      midpoint_pose.position.x =
        current_pose.position.x + (release_pose.position.x - current_pose.position.x) * 0.5;
      midpoint_pose.position.y =
        current_pose.position.y + (release_pose.position.y - current_pose.position.y) * 0.5;
      midpoint_pose.position.z = std::max(current_pose.position.z, release_pose.position.z);

      RCLCPP_INFO(get_logger(), "Completed hotdog place: Cartesian carry through auto midpoint");
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {midpoint_pose},
          "completed hotdog pickup auto midpoint",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(
        get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup auto midpoint");
    }

    RCLCPP_INFO(
      get_logger(),
      "Completed hotdog place: Cartesian carry to pickup %s",
      release_pose_preset_configured ? "release_pose" : "approach");
    if (!executeCartesian(
        get_logger(),
        right_arm,
        {approach_pose},
        release_pose_preset_configured ?
        "completed hotdog pickup release_pose" :
        "completed hotdog pickup approach pose",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(
      get_logger(),
      right_arm,
      right_tcp_link_,
      release_pose_preset_configured ?
      "Completed hotdog pickup release_pose" :
      "Completed hotdog pickup approach");
    if (shouldStopAfterWaypoint(
        ManufacturingStage::Place,
        release_pose_preset_configured ? "release_pose" : "approach"))
    {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Completed hotdog place: Cartesian lower to pickup zone");
    const geometry_msgs::msg::Pose before_release_pose =
      right_arm.getCurrentPose(right_tcp_link_).pose;
    const double release_position_error =
      (posePosition(before_release_pose) - posePosition(release_pose)).norm();
    const double release_orientation_error =
      poseOrientationDistanceRad(before_release_pose, release_pose);
    if (release_position_error <= task_presets::kDefaultPoseTargetSkipPositionToleranceM &&
      release_orientation_error <= task_presets::kDefaultPoseTargetSkipOrientationToleranceRad)
    {
      RCLCPP_INFO(
        get_logger(),
        "completed hotdog pickup lower skipped; current TCP is already near release "
        "(pos_error=%.4f m, rot_error=%.4f rad)",
        release_position_error,
        release_orientation_error);
    } else if (!executeCartesian(
        get_logger(),
        right_arm,
        {release_pose},
        "completed hotdog pickup lower",
        cartesian_eef_step_,
        min_cartesian_fraction_,
        cartesian_avoid_collisions_,
        velocity_scaling_,
        acceleration_scaling_,
        cartesian_min_duration_sec_))
    {
      return false;
    }
    logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup release");
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release_pose")) {
      return true;
    }

    RCLCPP_INFO(get_logger(), "Completed hotdog place: opening right gripper");
    if (!openGripperForPickApproach(
        get_logger(),
        right_gripper,
        "Completed hotdog place",
        task_presets::kRightCasePickTuning,
        gripper_open_target_))
    {
      return false;
    }
    rclcpp::sleep_for(300ms);
    if (!detachTargetCollisionObject(right_arm, case_target_model_, "Completed hotdog place")) {
      return false;
    }
    if (shouldStopAfterWaypoint(ManufacturingStage::Place, "release")) {
      return true;
    }

    if (shouldRunStage(ManufacturingStage::ReturnHome)) {
      RCLCPP_INFO(get_logger(), "Completed hotdog place: Cartesian retreat");
      geometry_msgs::msg::Pose retreat_pose = approach_pose;
      retreat_pose.position.z = std::max(
        retreat_pose.position.z,
        release_pose.position.z + task_presets::kCompletedHotdogPickupApproachHeightM);
      if (!executeCartesian(
          get_logger(),
          right_arm,
          {retreat_pose},
          "completed hotdog pickup retreat",
          cartesian_eef_step_,
          min_cartesian_fraction_,
          cartesian_avoid_collisions_,
          velocity_scaling_,
          acceleration_scaling_,
          cartesian_min_duration_sec_))
      {
        return false;
      }
      logCurrentTcpPose(get_logger(), right_arm, right_tcp_link_, "Completed hotdog pickup retreat");

      if (!planAndExecuteReturnHome(
          right_arm,
          ManufacturingTarget::Hotdog,
          ArmSide::Right,
          right_tcp_link_,
          "Completed hotdog"))
      {
        return false;
      }
    }

    RCLCPP_INFO(get_logger(), "Completed hotdog pickup-zone place completed");
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
  std::string task_name_;
  std::string arm_name_;
  ManufacturingTarget target_{ManufacturingTarget::Bread};
  ArmSide arm_{ArmSide::Left};
  std::string target_model_;
  std::string case_target_model_;
  std::string bread_target_model_;
  std::string sausage_target_model_;
  std::string ketchup_target_model_;
  std::string coke_target_model_;
  std::string coffee_target_model_;
  ManufacturingStage start_stage_{ManufacturingStage::Home};
  std::string play_to_stage_name_;
  std::string start_from_waypoint_name_;
  std::optional<ManufacturingStage> play_to_stage_;
  std::string play_to_waypoint_name_;
  std::string play_to_waypoint_;
  bool play_range_valid_{true};
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
  bool allow_gripper_target_collision_for_grasp_{
    task_presets::kDefaultPlanningScene.allow_gripper_target_collision_for_grasp};
  int collision_scene_settle_ms_{task_presets::kDefaultPlanningScene.collision_scene_settle_ms};
  std::set<std::string> attached_collision_objects_;
  double max_pre_grasp_xy_error_{task_presets::kDefaultMaxPreGraspXyError};
  bool dry_run_{false};
  bool enable_vision_pick_{false};
  std::string vision_detections_topic_;
  double vision_pick_timeout_sec_{2.0};
  double vision_pick_max_age_sec_{2.0};
  double vision_pick_max_distance_m_{0.15};
  double vision_pick_min_score_{0.25};
  bool vision_pick_required_{false};
  bool vision_pick_use_orientation_{false};
  bool vision_pick_use_size_{false};
  rclcpp::Subscription<vision_msgs::msg::Detection3DArray>::SharedPtr vision_detection_sub_;
  std::mutex vision_detections_mutex_;
  std::vector<VisionPickDetection> latest_vision_detections_;
  rclcpp::Time latest_vision_detection_stamp_;
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
