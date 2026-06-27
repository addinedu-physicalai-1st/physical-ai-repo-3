#include "ddooby_controller/vision_pick_detection_store.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <utility>

#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_pose_utils.hpp"
#include "ddooby_controller/vision_pick_adapter.hpp"

namespace ddooby_controller::manufacturing_task
{

void VisionPickDetectionStore::updateFromMessage(
  const rclcpp::Time & received_stamp,
  const vision_msgs::msg::Detection3DArray & msg)
{
  std::vector<VisionPickDetection> detections;
  detections.reserve(msg.detections.size());

  for (const auto & detection : msg.detections) {
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

std::optional<VisionPickDetection> VisionPickDetectionStore::findMatching(
  const rclcpp::Logger & logger,
  rclcpp::Clock & clock,
  task_presets::ManufacturingTarget target_kind,
  const std::string & target_model,
  const TargetObject & target,
  double min_score,
  double max_age_sec,
  double max_distance_m) const
{
  const std::vector<VisionPickDetection> detections = snapshot();
  if (detections.empty()) {
    RCLCPP_WARN_THROTTLE(
      logger,
      clock,
      1000,
      "Vision pick has no received detections yet");
    return std::nullopt;
  }

  const rclcpp::Time now = clock.now();
  const Eigen::Vector3d expected_center = objectWorldCenter(target);
  double best_distance = std::numeric_limits<double>::infinity();
  std::optional<VisionPickDetection> best_detection;

  for (const auto & detection : detections) {
    if (detection.score < min_score) {
      continue;
    }
    if (!detection.frame_id.empty() && detection.frame_id != "world") {
      RCLCPP_WARN_THROTTLE(
        logger,
        clock,
        2000,
        "Vision pick ignores detection '%s' in frame '%s'; expected world frame",
        detection.class_id.c_str(),
        detection.frame_id.c_str());
      continue;
    }
    const bool has_object_id = !detection.object_id.empty();
    const bool object_id_matches = visionObjectIdMatchesTargetModel(detection.object_id, target_model);
    if (has_object_id && !object_id_matches) {
      RCLCPP_DEBUG(
        logger,
        "Vision pick skip id=%s for target_model=%s",
        detection.object_id.c_str(),
        target_model.c_str());
      continue;
    }
    if (!object_id_matches && !visionClassMatches(detection.class_id, target_kind, target_model)) {
      RCLCPP_DEBUG(
        logger,
        "Vision pick skip class=%s id=%s for target=%s/%s",
        detection.class_id.c_str(),
        detection.object_id.c_str(),
        task_presets::targetName(target_kind),
        target_model.c_str());
      continue;
    }

    const double age_sec = (now - detection.stamp).seconds();
    if (std::isfinite(age_sec) && std::abs(age_sec) > max_age_sec) {
      RCLCPP_DEBUG(
        logger,
        "Vision pick skip stale class=%s id=%s age=%.3f",
        detection.class_id.c_str(),
        detection.object_id.c_str(),
        age_sec);
      continue;
    }

    const Eigen::Vector3d detection_center = posePosition(detection.pose);
    const double distance = (detection_center - expected_center).norm();
    if (!object_id_matches && max_distance_m > 0.0 && distance > max_distance_m) {
      RCLCPP_DEBUG(
        logger,
        "Vision pick skip far class=%s id=%s distance=%.3f",
        detection.class_id.c_str(),
        detection.object_id.c_str(),
        distance);
      continue;
    }
    if (distance < best_distance) {
      best_distance = distance;
      best_detection = detection;
    }
  }

  return best_detection;
}

std::string VisionPickDetectionStore::summarizeCandidates(
  task_presets::ManufacturingTarget target_kind,
  const std::string & target_model,
  const TargetObject & target,
  const rclcpp::Time & now) const
{
  const std::vector<VisionPickDetection> detections = snapshot();

  std::ostringstream stream;
  stream << "Vision pick candidates for " << task_presets::targetName(target_kind) << "/" << target_model
         << ": count=" << detections.size();
  const Eigen::Vector3d expected_center = objectWorldCenter(target);
  std::size_t count = 0;
  for (const auto & detection : detections) {
    if (count++ >= 12) {
      stream << " ...";
      break;
    }
    const bool object_id_matches = visionObjectIdMatchesTargetModel(detection.object_id, target_model);
    const bool class_matches = visionClassMatches(detection.class_id, target_kind, target_model);
    const double age_sec = (now - detection.stamp).seconds();
    const Eigen::Vector3d detection_center = posePosition(detection.pose);
    const double distance = (detection_center - expected_center).norm();
    stream << " [class=" << detection.class_id
           << " id=" << detection.object_id
           << " score=" << detection.score
           << " class_match=" << (class_matches ? "Y" : "N")
           << " id_match=" << (object_id_matches ? "Y" : "N")
           << " age=" << age_sec
           << " dist=" << distance
           << "]";
  }
  return stream.str();
}

std::vector<VisionPickDetection> VisionPickDetectionStore::snapshot() const
{
  std::lock_guard<std::mutex> lock(mutex_);
  return detections_;
}

}  // namespace ddooby_controller::manufacturing_task
