#pragma once

#include <mutex>
#include <vector>

#include <rclcpp/time.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

class VisionPickDetectionStore
{
public:
  void updateFromMessage(
    const rclcpp::Time & received_stamp,
    const vision_msgs::msg::Detection3DArray & msg);

  std::vector<VisionPickDetection> snapshot() const;

private:
  mutable std::mutex mutex_;
  std::vector<VisionPickDetection> detections_;
};

}  // namespace ddooby_controller::manufacturing_task
