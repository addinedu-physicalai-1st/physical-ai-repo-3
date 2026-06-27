#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <thread>

#include <Eigen/Geometry>
#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_task_common.hpp"
#include "manufacturing_task_node.hpp"

namespace ddooby_controller
{

namespace
{

struct PipeCloser
{
  void operator()(FILE * file) const
  {
    if (file != nullptr) {
      (void)pclose(file);
    }
  }
};

std::string readCommandOutput(const char * command)
{
  std::array<char, 4096> buffer{};
  std::string output;
  std::unique_ptr<FILE, PipeCloser> pipe(popen(command, "r"));
  if (!pipe) {
    return output;
  }

  while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe.get()) != nullptr) {
    output += buffer.data();
  }
  return output;
}

std::optional<size_t> matchingBraceEnd(const std::string & text, size_t opening_brace)
{
  int depth = 0;
  for (size_t i = opening_brace; i < text.size(); ++i) {
    if (text[i] == '{') {
      ++depth;
    } else if (text[i] == '}') {
      --depth;
      if (depth == 0) {
        return i;
      }
    }
  }
  return std::nullopt;
}

std::optional<std::string> extractQuotedValue(
  const std::string & text,
  const std::string & key)
{
  const std::string marker = key + ": \"";
  const size_t begin = text.find(marker);
  if (begin == std::string::npos) {
    return std::nullopt;
  }
  const size_t value_begin = begin + marker.size();
  const size_t value_end = text.find('"', value_begin);
  if (value_end == std::string::npos) {
    return std::nullopt;
  }
  return text.substr(value_begin, value_end - value_begin);
}

std::optional<double> extractScalarValue(
  const std::string & text,
  const std::string & key)
{
  const std::string marker = key + ":";
  const size_t begin = text.find(marker);
  if (begin == std::string::npos) {
    return std::nullopt;
  }

  std::istringstream stream(text.substr(begin + marker.size()));
  double value = 0.0;
  stream >> value;
  if (!stream) {
    return std::nullopt;
  }
  return value;
}

std::optional<std::string> extractBlock(
  const std::string & text,
  const std::string & key)
{
  const std::string marker = key + " {";
  const size_t block_begin = text.find(marker);
  if (block_begin == std::string::npos) {
    return std::nullopt;
  }
  const size_t brace_begin = text.find('{', block_begin);
  if (brace_begin == std::string::npos) {
    return std::nullopt;
  }
  const auto brace_end = matchingBraceEnd(text, brace_begin);
  if (!brace_end.has_value()) {
    return std::nullopt;
  }
  return text.substr(brace_begin + 1, brace_end.value() - brace_begin - 1);
}

std::map<std::string, Eigen::Vector3d> parseGazeboPoseInfo(const std::string & text)
{
  std::map<std::string, Eigen::Vector3d> poses;

  size_t search_from = 0;
  while (search_from < text.size()) {
    const size_t pose_begin = text.find("pose {", search_from);
    if (pose_begin == std::string::npos) {
      break;
    }
    const size_t brace_begin = text.find('{', pose_begin);
    if (brace_begin == std::string::npos) {
      break;
    }
    const auto pose_end = matchingBraceEnd(text, brace_begin);
    if (!pose_end.has_value()) {
      break;
    }

    const std::string pose_block =
      text.substr(brace_begin + 1, pose_end.value() - brace_begin - 1);
    const auto name = extractQuotedValue(pose_block, "name");
    const auto position_block = extractBlock(pose_block, "position");
    if (name.has_value() && position_block.has_value()) {
      const auto x = extractScalarValue(position_block.value(), "x");
      const auto y = extractScalarValue(position_block.value(), "y");
      const auto z = extractScalarValue(position_block.value(), "z");
      if (x.has_value() && y.has_value() && z.has_value()) {
        poses[name.value()] = Eigen::Vector3d{x.value(), y.value(), z.value()};
      }
    }

    search_from = pose_end.value() + 1;
  }

  return poses;
}

double xyDistance(const Eigen::Vector3d & lhs, const Eigen::Vector3d & rhs)
{
  return std::hypot(lhs.x() - rhs.x(), lhs.y() - rhs.y());
}

void logModelPosition(
  const rclcpp::Logger & logger,
  const std::string & model_name,
  const Eigen::Vector3d & position)
{
  RCLCPP_INFO(
    logger,
    "Gazebo result pose: %s xyz=[%.3f %.3f %.3f]",
    model_name.c_str(),
    position.x(),
    position.y(),
    position.z());
}

bool validateDistance(
  const rclcpp::Logger & logger,
  const std::string & label,
  double distance,
  double tolerance)
{
  const bool ok = distance <= tolerance;
  if (ok) {
    RCLCPP_INFO(
      logger,
      "Gazebo result validation OK: %s distance=%.3fm tolerance=%.3fm",
      label.c_str(),
      distance,
      tolerance);
  } else {
    RCLCPP_ERROR(
      logger,
      "Gazebo result validation FAILED: %s distance=%.3fm tolerance=%.3fm",
      label.c_str(),
      distance,
      tolerance);
  }
  return ok;
}

bool validateAbsDelta(
  const rclcpp::Logger & logger,
  const std::string & label,
  double delta,
  double tolerance)
{
  const bool ok = std::abs(delta) <= tolerance;
  if (ok) {
    RCLCPP_INFO(
      logger,
      "Gazebo result validation OK: %s delta=%.3fm tolerance=%.3fm",
      label.c_str(),
      delta,
      tolerance);
  } else {
    RCLCPP_ERROR(
      logger,
      "Gazebo result validation FAILED: %s delta=%.3fm tolerance=%.3fm",
      label.c_str(),
      delta,
      tolerance);
  }
  return ok;
}

bool validateMinimumDistance(
  const rclcpp::Logger & logger,
  const std::string & label,
  double distance,
  double minimum)
{
  const bool ok = distance >= minimum;
  if (ok) {
    RCLCPP_INFO(
      logger,
      "Gazebo result validation OK: %s distance=%.3fm minimum=%.3fm",
      label.c_str(),
      distance,
      minimum);
  } else {
    RCLCPP_ERROR(
      logger,
      "Gazebo result validation FAILED: %s distance=%.3fm minimum=%.3fm",
      label.c_str(),
      distance,
      minimum);
  }
  return ok;
}

}  // namespace

bool HotdogMakingNode::shouldValidateGazeboResult() const
{
  if (!validate_gazebo_result_ || dry_run_) {
    return false;
  }
  if (play_to_stage_.has_value() || !play_to_waypoint_.empty()) {
    return false;
  }
  return true;
}

std::optional<std::map<std::string, Eigen::Vector3d>>
HotdogMakingNode::readGazeboModelPositions() const
{
  const std::string output =
    readCommandOutput("timeout 5s gz topic -e -t /world/default/pose/info -n 1 2>/dev/null");
  if (output.empty()) {
    RCLCPP_ERROR(
      get_logger(),
      "Gazebo result validation failed: unable to read /world/default/pose/info");
    return std::nullopt;
  }

  auto poses = parseGazeboPoseInfo(output);
  if (poses.empty()) {
    RCLCPP_ERROR(
      get_logger(),
      "Gazebo result validation failed: /world/default/pose/info did not contain model poses");
    return std::nullopt;
  }

  return poses;
}

bool HotdogMakingNode::validateFinalHotdogPlacement()
{
  if (!shouldValidateGazeboResult()) {
    return true;
  }

  if (result_validation_settle_ms_ > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(result_validation_settle_ms_));
  }

  const auto poses = readGazeboModelPositions();
  if (!poses.has_value()) {
    return false;
  }

  TargetObject ketchup_layout;
  TargetObject pickup_zone_layout;
  if (!loadManufacturingTarget(ketchup_target_model_, ketchup_layout) ||
    !loadManufacturingTarget("pickup_zone", pickup_zone_layout))
  {
    return false;
  }

  auto find_pose = [&](const std::string & model_name) -> std::optional<Eigen::Vector3d> {
      const auto pose = poses->find(model_name);
      if (pose == poses->end()) {
        RCLCPP_ERROR(
          get_logger(),
          "Gazebo result validation failed: model '%s' was not found in Gazebo poses",
          model_name.c_str());
        return std::nullopt;
      }
      logModelPosition(get_logger(), model_name, pose->second);
      return pose->second;
    };

  const auto case_pose = find_pose(case_target_model_);
  const auto bread_pose = find_pose(bread_target_model_);
  const auto sausage_pose = find_pose(sausage_target_model_);
  const auto ketchup_pose = find_pose(ketchup_target_model_);
  if (!case_pose.has_value() || !bread_pose.has_value() ||
    !sausage_pose.has_value() || !ketchup_pose.has_value())
  {
    return false;
  }

  bool ok = true;
  ok &= validateDistance(
    get_logger(),
    bread_target_model_ + " near " + case_target_model_,
    xyDistance(bread_pose.value(), case_pose.value()),
    result_validation_hotdog_item_xy_tolerance_m_);
  ok &= validateDistance(
    get_logger(),
    sausage_target_model_ + " near " + case_target_model_,
    xyDistance(sausage_pose.value(), case_pose.value()),
    result_validation_hotdog_item_xy_tolerance_m_);
  ok &= validateDistance(
    get_logger(),
    case_target_model_ + " near pickup_zone",
    xyDistance(case_pose.value(), pickup_zone_layout.xyz),
    result_validation_beverage_pickup_xy_tolerance_m_);
  ok &= validateDistance(
    get_logger(),
    ketchup_target_model_ + " returned near layout pose",
    xyDistance(ketchup_pose.value(), ketchup_layout.xyz),
    result_validation_ketchup_return_xy_tolerance_m_);
  ok &= validateAbsDelta(
    get_logger(),
    ketchup_target_model_ + " returned near layout height",
    ketchup_pose->z() - ketchup_layout.xyz.z(),
    result_validation_ketchup_return_z_tolerance_m_);

  if (!ok) {
    RCLCPP_ERROR(get_logger(), "Gazebo result validation failed for New York hotdog assembly");
    return false;
  }

  RCLCPP_INFO(get_logger(), "Gazebo result validation passed for New York hotdog assembly");
  return true;
}

bool HotdogMakingNode::validateFinalBeveragePlacement(ManufacturingTarget beverage_target)
{
  if (!shouldValidateGazeboResult()) {
    return true;
  }

  if (result_validation_settle_ms_ > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(result_validation_settle_ms_));
  }

  const auto poses = readGazeboModelPositions();
  if (!poses.has_value()) {
    return false;
  }

  const std::string beverage_model =
    beverageTargetModel(beverage_target, target_model_, coffee_target_model_, coke_target_model_);
  TargetObject pickup_zone_layout;
  TargetObject beverage_layout;
  if (!loadManufacturingTarget("pickup_zone", pickup_zone_layout) ||
    !loadManufacturingTarget(beverage_model, beverage_layout))
  {
    return false;
  }

  const auto beverage_pose_it = poses->find(beverage_model);
  if (beverage_pose_it == poses->end()) {
    RCLCPP_ERROR(
      get_logger(),
      "Gazebo result validation failed: model '%s' was not found in Gazebo poses",
      beverage_model.c_str());
    return false;
  }
  logModelPosition(get_logger(), beverage_model, beverage_pose_it->second);

  bool ok = true;
  ok &= validateDistance(
    get_logger(),
    beverage_model + " near pickup_zone",
    xyDistance(beverage_pose_it->second, pickup_zone_layout.xyz),
    result_validation_beverage_pickup_xy_tolerance_m_);

  constexpr double kMinimumMovedDistanceM = 0.20;
  ok &= validateMinimumDistance(
    get_logger(),
    beverage_model + " moved from layout pose",
    xyDistance(beverage_pose_it->second, beverage_layout.xyz),
    kMinimumMovedDistanceM);

  if (!ok) {
    RCLCPP_ERROR(
      get_logger(),
      "Gazebo result validation failed for beverage %s serving",
      task_presets::targetName(beverage_target));
    return false;
  }

  RCLCPP_INFO(
    get_logger(),
    "Gazebo result validation passed for beverage %s serving",
    task_presets::targetName(beverage_target));
  return true;
}

}  // namespace ddooby_controller
