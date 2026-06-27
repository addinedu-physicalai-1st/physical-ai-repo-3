#pragma once

#include <string>
#include <vector>

#include <rclcpp/logger.hpp>

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

bool applyVisionDetectionToTarget(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget target,
  const std::string & target_model,
  const VisionPickDetection & detection,
  bool use_detection_size,
  TargetObject & target_object);

}  // namespace ddooby_controller::manufacturing_task
