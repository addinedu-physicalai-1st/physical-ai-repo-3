#include "ddooby_controller/task/manufacturing_result_validator.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <utility>

#include "ddooby_controller/simulator/manufacturing_layout_utils.hpp"
#include "ddooby_controller/task/manufacturing_pick_planner.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"

#include <rclcpp/rclcpp.hpp>

#include "manufacturing_task_node_private.hpp"

namespace ddooby_controller::manufacturing_task
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

bool matchingBraceEnd(const std::string & text, size_t opening_brace, size_t & closing_brace)
{
  int depth = 0;
  for (size_t i = opening_brace; i < text.size(); ++i) {
    if (text[i] == '{') {
      ++depth;
    } else if (text[i] == '}') {
      --depth;
      if (depth == 0) {
        closing_brace = i;
        return true;
      }
    }
  }
  return false;
}

bool extractQuotedValue(
  const std::string & text,
  const std::string & key,
  std::string & value)
{
  const std::string marker = key + ": \"";
  const size_t begin = text.find(marker);
  if (begin == std::string::npos) {
    return false;
  }
  const size_t value_begin = begin + marker.size();
  const size_t value_end = text.find('"', value_begin);
  if (value_end == std::string::npos) {
    return false;
  }
  value = text.substr(value_begin, value_end - value_begin);
  return true;
}

bool extractScalarValue(
  const std::string & text,
  const std::string & key,
  double & value)
{
  const std::string marker = key + ":";
  const size_t begin = text.find(marker);
  if (begin == std::string::npos) {
    return false;
  }

  std::istringstream stream(text.substr(begin + marker.size()));
  stream >> value;
  if (!stream) {
    return false;
  }
  return true;
}

bool extractBlock(
  const std::string & text,
  const std::string & key,
  std::string & block)
{
  const std::string marker = key + " {";
  const size_t block_begin = text.find(marker);
  if (block_begin == std::string::npos) {
    return false;
  }
  const size_t brace_begin = text.find('{', block_begin);
  if (brace_begin == std::string::npos) {
    return false;
  }
  size_t brace_end = 0;
  if (!matchingBraceEnd(text, brace_begin, brace_end)) {
    return false;
  }
  block = text.substr(brace_begin + 1, brace_end - brace_begin - 1);
  return true;
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
    size_t pose_end = 0;
    if (!matchingBraceEnd(text, brace_begin, pose_end)) {
      break;
    }

    const std::string pose_block =
      text.substr(brace_begin + 1, pose_end - brace_begin - 1);
    std::string name;
    std::string position_block;
    if (extractQuotedValue(pose_block, "name", name) && extractBlock(pose_block, "position", position_block)) {
      double x = 0.0;
      double y = 0.0;
      double z = 0.0;
      if (extractScalarValue(position_block, "x", x) &&
        extractScalarValue(position_block, "y", y) &&
        extractScalarValue(position_block, "z", z))
      {
        poses[name] = Eigen::Vector3d{x, y, z};
      }
    }

    search_from = pose_end + 1;
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

bool validateInsideFootprint(
  const rclcpp::Logger & logger,
  const std::string & label,
  const Eigen::Vector3d & position,
  const TargetObject & target,
  double margin_m)
{
  if (target.size.x() <= 1e-6 || target.size.y() <= 1e-6) {
    return validateDistance(
      logger,
      label,
      xyDistance(position, target.xyz),
      margin_m);
  }

  const double dx = std::abs(position.x() - target.xyz.x());
  const double dy = std::abs(position.y() - target.xyz.y());
  const double max_x = target.size.x() * 0.5 + margin_m;
  const double max_y = target.size.y() * 0.5 + margin_m;
  const bool ok = dx <= max_x && dy <= max_y;
  if (ok) {
    RCLCPP_INFO(
      logger,
      "Gazebo result validation OK: %s dx=%.3fm/%.3fm dy=%.3fm/%.3fm",
      label.c_str(),
      dx,
      max_x,
      dy,
      max_y);
  } else {
    RCLCPP_ERROR(
      logger,
      "Gazebo result validation FAILED: %s dx=%.3fm/%.3fm dy=%.3fm/%.3fm",
      label.c_str(),
      dx,
      max_x,
      dy,
      max_y);
  }
  return ok;
}

}  // namespace

ManufacturingResultValidator::ManufacturingResultValidator(
  const rclcpp::Logger & logger,
  ManufacturingResultValidatorConfig config)
: logger_(logger),
  config_(std::move(config))
{
}

bool ManufacturingResultValidator::shouldValidate() const
{
  return config_.enabled &&
         !config_.dry_run &&
         !config_.has_partial_stage_limit &&
         !config_.has_partial_waypoint_limit;
}

bool ManufacturingResultValidator::readGazeboModelPositions(
  std::map<std::string, Eigen::Vector3d> & poses) const
{
  const std::string output =
    readCommandOutput("timeout 5s gz topic -e -t /world/default/pose/info -n 1 2>/dev/null");
  if (output.empty()) {
    RCLCPP_ERROR(
      logger_,
      "Gazebo result validation failed: unable to read /world/default/pose/info");
    return false;
  }

  poses = parseGazeboPoseInfo(output);
  if (poses.empty()) {
    RCLCPP_ERROR(
      logger_,
      "Gazebo result validation failed: /world/default/pose/info did not contain model poses");
    return false;
  }

  return true;
}

bool ManufacturingResultValidator::loadTarget(
  const std::string & target_model,
  TargetObject & target) const
{
  const std::string layout_path =
    effectiveManufacturingLayoutPath(config_.package_share_directory, config_.layout_path);

  try {
    target = loadTargetObject(config_.package_share_directory, layout_path, target_model);
  } catch (const std::exception & error) {
    RCLCPP_ERROR(logger_, "Failed to load target object '%s': %s", target_model.c_str(), error.what());
    return false;
  }
  return true;
}

bool ManufacturingResultValidator::validateHotdogPlacement()
{
  if (!shouldValidate()) {
    return true;
  }

  if (config_.settle_ms > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(config_.settle_ms));
  }

  std::map<std::string, Eigen::Vector3d> poses;
  if (!readGazeboModelPositions(poses)) {
    return false;
  }

  TargetObject ketchup_layout;
  TargetObject pickup_zone_layout;
  if (!loadTarget(config_.ketchup_target_model, ketchup_layout) ||
    !loadTarget("pickup_zone", pickup_zone_layout))
  {
    return false;
  }

  auto find_pose = [&](const std::string & model_name, Eigen::Vector3d & position) {
      const auto pose = poses.find(model_name);
      if (pose == poses.end()) {
        RCLCPP_ERROR(
          logger_,
          "Gazebo result validation failed: model '%s' was not found in Gazebo poses",
          model_name.c_str());
        return false;
      }
      logModelPosition(logger_, model_name, pose->second);
      position = pose->second;
      return true;
    };

  Eigen::Vector3d case_pose;
  Eigen::Vector3d bread_pose;
  Eigen::Vector3d sausage_pose;
  Eigen::Vector3d ketchup_pose;
  if (!find_pose(config_.case_target_model, case_pose) ||
    !find_pose(config_.bread_target_model, bread_pose) ||
    !find_pose(config_.sausage_target_model, sausage_pose) ||
    !find_pose(config_.ketchup_target_model, ketchup_pose))
  {
    return false;
  }

  bool ok = true;
  ok &= validateDistance(
    logger_,
    config_.bread_target_model + " near " + config_.case_target_model,
    xyDistance(bread_pose, case_pose),
    config_.hotdog_item_xy_tolerance_m);
  ok &= validateDistance(
    logger_,
    config_.sausage_target_model + " near " + config_.case_target_model,
    xyDistance(sausage_pose, case_pose),
    config_.hotdog_item_xy_tolerance_m);
  ok &= validateDistance(
    logger_,
    config_.case_target_model + " near pickup_zone",
    xyDistance(case_pose, pickup_zone_layout.xyz),
    config_.beverage_pickup_xy_tolerance_m);
  ok &= validateDistance(
    logger_,
    config_.ketchup_target_model + " returned near layout pose",
    xyDistance(ketchup_pose, ketchup_layout.xyz),
    config_.ketchup_return_xy_tolerance_m);
  ok &= validateAbsDelta(
    logger_,
    config_.ketchup_target_model + " returned near layout height",
    ketchup_pose.z() - ketchup_layout.xyz.z(),
    config_.ketchup_return_z_tolerance_m);

  if (!ok) {
    RCLCPP_ERROR(logger_, "Gazebo result validation failed for New York hotdog assembly");
    return false;
  }

  RCLCPP_INFO(logger_, "Gazebo result validation passed for New York hotdog assembly");
  return true;
}

bool ManufacturingResultValidator::validateBeveragePlacement(
  task_presets::ManufacturingTarget beverage_target)
{
  if (!shouldValidate()) {
    return true;
  }

  if (config_.settle_ms > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(config_.settle_ms));
  }

  std::map<std::string, Eigen::Vector3d> poses;
  if (!readGazeboModelPositions(poses)) {
    return false;
  }

  const std::string beverage_model =
    beverageTargetModel(beverage_target, config_.target_model, config_.coffee_target_model, config_.coke_target_model);
  TargetObject pickup_zone_layout;
  TargetObject beverage_layout;
  if (!loadTarget("pickup_zone", pickup_zone_layout) ||
    !loadTarget(beverage_model, beverage_layout))
  {
    return false;
  }

  const auto beverage_pose_it = poses.find(beverage_model);
  if (beverage_pose_it == poses.end()) {
    RCLCPP_ERROR(
      logger_,
      "Gazebo result validation failed: model '%s' was not found in Gazebo poses",
      beverage_model.c_str());
    return false;
  }
  logModelPosition(logger_, beverage_model, beverage_pose_it->second);

  bool ok = true;
  constexpr double kPickupZoneFootprintMarginM = 0.05;
  ok &= validateInsideFootprint(
    logger_,
    beverage_model + " inside pickup_zone footprint",
    beverage_pose_it->second,
    pickup_zone_layout,
    kPickupZoneFootprintMarginM);

  constexpr double kMinimumMovedDistanceM = 0.20;
  ok &= validateMinimumDistance(
    logger_,
    beverage_model + " moved from layout pose",
    xyDistance(beverage_pose_it->second, beverage_layout.xyz),
    kMinimumMovedDistanceM);

  if (!ok) {
    RCLCPP_ERROR(
      logger_,
      "Gazebo result validation failed for beverage %s serving",
      task_presets::targetName(beverage_target));
    return false;
  }

  RCLCPP_INFO(
    logger_,
    "Gazebo result validation passed for beverage %s serving",
    task_presets::targetName(beverage_target));
  return true;
}

}  // namespace ddooby_controller::manufacturing_task

namespace ddooby_controller
{

using manufacturing_task::ManufacturingResultValidator;
using manufacturing_task::ManufacturingResultValidatorConfig;

bool HotdogMakingNode::shouldValidateGazeboResult() const
{
  return validate_gazebo_result_ &&
         !dry_run_ &&
         !has_play_to_stage_ &&
         play_to_waypoint_.empty();
}

bool HotdogMakingNode::validateFinalHotdogPlacement()
{
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  ManufacturingResultValidator validator(
    get_logger(),
    ManufacturingResultValidatorConfig{
      validate_gazebo_result_,
      dry_run_,
      has_play_to_stage_,
      !play_to_waypoint_.empty(),
      result_validation_settle_ms_,
      result_validation_hotdog_item_xy_tolerance_m_,
      result_validation_ketchup_return_xy_tolerance_m_,
      result_validation_ketchup_return_z_tolerance_m_,
      result_validation_beverage_pickup_xy_tolerance_m_,
      package_share_directory,
      layout_path_,
      case_target_model_,
      bread_target_model_,
      sausage_target_model_,
      ketchup_target_model_,
      coke_target_model_,
      coffee_target_model_,
      target_model_});
  return validator.validateHotdogPlacement();
}

bool HotdogMakingNode::validateFinalBeveragePlacement(ManufacturingTarget beverage_target)
{
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  ManufacturingResultValidator validator(
    get_logger(),
    ManufacturingResultValidatorConfig{
      validate_gazebo_result_,
      dry_run_,
      has_play_to_stage_,
      !play_to_waypoint_.empty(),
      result_validation_settle_ms_,
      result_validation_hotdog_item_xy_tolerance_m_,
      result_validation_ketchup_return_xy_tolerance_m_,
      result_validation_ketchup_return_z_tolerance_m_,
      result_validation_beverage_pickup_xy_tolerance_m_,
      package_share_directory,
      layout_path_,
      case_target_model_,
      bread_target_model_,
      sausage_target_model_,
      ketchup_target_model_,
      coke_target_model_,
      coffee_target_model_,
      target_model_});
  return validator.validateBeveragePlacement(beverage_target);
}

}  // namespace ddooby_controller
