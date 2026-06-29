#pragma once

#include <optional>
#include <string>
#include <vector>

#include <rclcpp/clock.hpp>
#include <rclcpp/logger.hpp>
#include <rclcpp/time.hpp>

#include "ddooby_controller/manufacturing_task_presets.hpp"
#include "ddooby_controller/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

std::vector<std::string> visionClassAliases(
  task_presets::ManufacturingTarget target,
  const std::string & target_model);

bool visionClassTokenMatchesAlias(
  const std::string & normalized_class,
  const std::string & alias);

bool visionClassMatches(
  const std::string & class_id,
  task_presets::ManufacturingTarget target,
  const std::string & target_model);

bool visionObjectIdMatchesTargetModel(
  const std::string & object_id,
  const std::string & target_model);

struct VisionPickMatchConfig
{
  double min_score{0.0};
  double max_age_sec{0.0};
  double max_distance_m{0.0};
};

std::optional<VisionPickDetection> findMatchingVisionPickDetection(
  const rclcpp::Logger & logger,
  rclcpp::Clock & clock,
  const std::vector<VisionPickDetection> & detections,
  task_presets::ManufacturingTarget target_kind,
  const std::string & target_model,
  const TargetObject & target,
  const VisionPickMatchConfig & config);

std::string summarizeVisionPickCandidates(
  const std::vector<VisionPickDetection> & detections,
  task_presets::ManufacturingTarget target_kind,
  const std::string & target_model,
  const TargetObject & target,
  const VisionPickMatchConfig & config,
  const rclcpp::Time & now);

bool applyVisionDetectionToTarget(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget target,
  const std::string & target_model,
  const VisionPickDetection & detection,
  bool use_detection_size,
  TargetObject & target_object);

}  // namespace ddooby_controller::manufacturing_task
