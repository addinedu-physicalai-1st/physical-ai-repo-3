#pragma once

#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include <rclcpp/clock.hpp>
#include <rclcpp/logger.hpp>
#include <rclcpp/time.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/manufacturing_task_presets.hpp"
#include "ddooby_controller/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

class VisionPickDetectionStore
{
public:
  void updateFromMessage(
    const rclcpp::Time & received_stamp,
    const vision_msgs::msg::Detection3DArray & msg);

  std::optional<VisionPickDetection> findMatching(
    const rclcpp::Logger & logger,
    rclcpp::Clock & clock,
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target,
    double min_score,
    double max_age_sec,
    double max_distance_m) const;

  std::string summarizeCandidates(
    task_presets::ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target,
    double min_score,
    double max_age_sec,
    double max_distance_m,
    const rclcpp::Time & now) const;

private:
  std::vector<VisionPickDetection> snapshot() const;

  mutable std::mutex mutex_;
  std::vector<VisionPickDetection> detections_;
};

}  // namespace ddooby_controller::manufacturing_task
