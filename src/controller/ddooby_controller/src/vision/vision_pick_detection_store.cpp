#include "ddooby_controller/vision/vision_pick_detection_store.hpp"

#include <algorithm>
#include <mutex>
#include <utility>

namespace ddooby_controller::manufacturing_task {

void VisionPickDetectionStore::updateFromMessage(const rclcpp::Time& received_stamp,
                                                 const vision_msgs::msg::Detection3DArray& msg) {
  std::vector<VisionPickDetection> detections;
  detections.reserve(msg.detections.size());

  for (const auto& detection : msg.detections) {
    if (detection.results.empty()) {
      continue;
    }

    const auto best_result =
        std::max_element(detection.results.begin(), detection.results.end(),
                         [](const auto& left, const auto& right) {
                           return left.hypothesis.score < right.hypothesis.score;
                         });
    if (best_result == detection.results.end()) {
      continue;
    }

    VisionPickDetection stored_detection;
    stored_detection.class_id = best_result->hypothesis.class_id;
    stored_detection.object_id = detection.id;
    stored_detection.score = best_result->hypothesis.score;
    stored_detection.stamp = received_stamp;
    stored_detection.frame_id = msg.header.frame_id;
    stored_detection.pose = detection.bbox.center;
    stored_detection.size =
        Eigen::Vector3d(detection.bbox.size.x, detection.bbox.size.y, detection.bbox.size.z);
    detections.push_back(stored_detection);
  }

  std::lock_guard<std::mutex> lock(mutex_);
  detections_ = std::move(detections);
}

std::vector<VisionPickDetection> VisionPickDetectionStore::snapshot() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return detections_;
}

}  // namespace ddooby_controller::manufacturing_task
