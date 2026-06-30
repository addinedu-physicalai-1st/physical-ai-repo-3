#pragma once

#include <optional>
#include <string>
#include <vector>

#include <rclcpp/node.hpp>
#include <rclcpp/clock.hpp>
#include <rclcpp/logger.hpp>
#include <rclcpp/time.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"
#include "ddooby_controller/vision/vision_pick_detection_store.hpp"

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

struct VisionPickAdapterConfig
{
  bool enabled{false};
  std::string detections_topic{"/manufacturing_vision/detections"};
  double timeout_sec{0.0};
  bool use_detection_size{false};
  VisionPickMatchConfig match;
};

class VisionPickAdapter
{
public:
  VisionPickAdapter(
    rclcpp::Node & node,
    const VisionPickAdapterConfig & config);

  void handleDetections(const vision_msgs::msg::Detection3DArray::SharedPtr msg);

  std::optional<VisionPickDetection> findDetection(
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target);

  std::optional<VisionPickDetection> waitForDetection(
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target);

  std::string summarizeCandidates(
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target);

  bool applyTarget(
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    TargetObject & target);

private:
  rclcpp::Node & node_;
  VisionPickAdapterConfig config_;
  VisionPickDetectionStore store_;
  rclcpp::Subscription<vision_msgs::msg::Detection3DArray>::SharedPtr subscription_;
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
