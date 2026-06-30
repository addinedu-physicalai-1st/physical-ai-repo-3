#include "ddooby_controller/vision/vision_pick_adapter.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <limits>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/wait_for_message.hpp>
#include <sstream>

#include "ddooby_controller/task/manufacturing_pose_utils.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"

namespace ddooby_controller::manufacturing_task {

namespace {

enum class VisionPickRejectReason {
  Usable,
  LowScore,
  Frame,
  ClassOrId,
  Stale,
  FarFromLayout,
};

const char* rejectReasonName(VisionPickRejectReason reason) {
  switch (reason) {
    case VisionPickRejectReason::Usable:
      return "usable";
    case VisionPickRejectReason::LowScore:
      return "low_score";
    case VisionPickRejectReason::Frame:
      return "frame";
    case VisionPickRejectReason::ClassOrId:
      return "class_or_id";
    case VisionPickRejectReason::Stale:
      return "stale";
    case VisionPickRejectReason::FarFromLayout:
      return "far_from_layout";
  }
  return "unknown";
}

struct VisionPickCandidateEvaluation {
  bool object_id_matches{false};
  bool class_matches{false};
  double age_sec{0.0};
  double distance_m{std::numeric_limits<double>::infinity()};
  VisionPickRejectReason reject_reason{VisionPickRejectReason::Usable};
};

VisionPickCandidateEvaluation evaluateVisionPickCandidate(
    const VisionPickDetection& detection, task_presets::ManufacturingTarget target_kind,
    const std::string& target_model, const TargetObject& target, double min_score,
    double max_age_sec, double max_distance_m, const rclcpp::Time& now) {
  VisionPickCandidateEvaluation evaluation;
  evaluation.object_id_matches =
      visionObjectIdMatchesTargetModel(detection.object_id, target_model);
  evaluation.class_matches = visionClassMatches(detection.class_id, target_kind, target_model);
  evaluation.age_sec = (now - detection.stamp).seconds();

  const Eigen::Vector3d expected_center = objectWorldCenter(target);
  const Eigen::Vector3d detection_center = posePosition(detection.pose);
  evaluation.distance_m = (detection_center - expected_center).norm();

  const bool frame_matches = detection.frame_id.empty() || detection.frame_id == "world";
  const bool score_ok = detection.score >= min_score;
  const bool class_or_id_ok =
      evaluation.object_id_matches || (detection.object_id.empty() && evaluation.class_matches);
  const bool age_ok =
      !std::isfinite(evaluation.age_sec) || std::abs(evaluation.age_sec) <= max_age_sec;
  const bool distance_ok = evaluation.object_id_matches || max_distance_m <= 0.0 ||
                           evaluation.distance_m <= max_distance_m;

  if (!score_ok) {
    evaluation.reject_reason = VisionPickRejectReason::LowScore;
  } else if (!frame_matches) {
    evaluation.reject_reason = VisionPickRejectReason::Frame;
  } else if (!class_or_id_ok) {
    evaluation.reject_reason = VisionPickRejectReason::ClassOrId;
  } else if (!age_ok) {
    evaluation.reject_reason = VisionPickRejectReason::Stale;
  } else if (!distance_ok) {
    evaluation.reject_reason = VisionPickRejectReason::FarFromLayout;
  }
  return evaluation;
}

bool visionPickCandidateUsable(const VisionPickCandidateEvaluation& evaluation) {
  return evaluation.reject_reason == VisionPickRejectReason::Usable;
}

double normalizeYaw(double yaw) {
  constexpr double kPi = 3.14159265358979323846;
  while (yaw > kPi) {
    yaw -= 2.0 * kPi;
  }
  while (yaw < -kPi) {
    yaw += 2.0 * kPi;
  }
  return yaw;
}

double yawDistance(double first_yaw, double second_yaw) {
  return std::abs(normalizeYaw(first_yaw - second_yaw));
}

double choosePcaYawClosestToLayout(double pca_yaw, double layout_yaw) {
  constexpr double kPi = 3.14159265358979323846;
  const double direct_yaw = normalizeYaw(pca_yaw);
  const double flipped_yaw = normalizeYaw(pca_yaw + kPi);
  if (yawDistance(flipped_yaw, layout_yaw) < yawDistance(direct_yaw, layout_yaw)) {
    return flipped_yaw;
  }
  return direct_yaw;
}

}  // namespace

std::vector<std::string> visionClassAliases(task_presets::ManufacturingTarget target,
                                            const std::string& target_model) {
  std::vector<std::string> aliases{
      normalizeStageName(target_model),
      normalizeStageName(task_presets::targetName(target)),
  };

  switch (target) {
    case task_presets::ManufacturingTarget::Bread:
      aliases.insert(aliases.end(), {"bread", "bread1", "bread2", "bun", "hotdogbun"});
      break;
    case task_presets::ManufacturingTarget::Case:
      aliases.insert(aliases.end(), {"case", "case1", "case2", "tray", "box", "hotdogcase"});
      break;
    case task_presets::ManufacturingTarget::Coffee:
      aliases.insert(aliases.end(), {"coffee", "cancoffee", "concoffee", "cup"});
      break;
    case task_presets::ManufacturingTarget::Coke:
      aliases.insert(aliases.end(), {"coke", "cola", "cancoke", "concoke"});
      break;
    case task_presets::ManufacturingTarget::Ketchup:
      aliases.insert(aliases.end(), {"ketchup", "kachup", "bottle"});
      break;
    case task_presets::ManufacturingTarget::Sausage:
      aliases.insert(aliases.end(), {"sausage", "sausage1", "sausage2", "hotdogsausage"});
      break;
    case task_presets::ManufacturingTarget::Hotdog:
      aliases.insert(aliases.end(), {"hotdog", "newyorkhotdog"});
      break;
  }

  std::sort(aliases.begin(), aliases.end());
  aliases.erase(std::remove_if(aliases.begin(), aliases.end(),
                               [](const std::string& alias) { return alias.empty(); }),
                aliases.end());
  aliases.erase(std::unique(aliases.begin(), aliases.end()), aliases.end());
  return aliases;
}

bool visionClassTokenMatchesAlias(const std::string& normalized_class, const std::string& alias) {
  if (normalized_class == alias) {
    return true;
  }
  if (alias.size() >= 4 && normalized_class.rfind(alias, 0) == 0) {
    const std::string suffix = normalized_class.substr(alias.size());
    return !suffix.empty() && std::all_of(suffix.begin(), suffix.end(), [](char character) {
      return std::isdigit(static_cast<unsigned char>(character));
    });
  }
  return false;
}

bool visionClassMatches(const std::string& class_id, task_presets::ManufacturingTarget target,
                        const std::string& target_model) {
  std::vector<std::string> normalized_classes;
  std::string token;
  for (char character : class_id) {
    if (character == '|') {
      normalized_classes.push_back(normalizeStageName(token));
      token.clear();
      continue;
    }
    token.push_back(character);
  }
  normalized_classes.push_back(normalizeStageName(token));

  for (const std::string& normalized_class : normalized_classes) {
    if (normalized_class.empty()) {
      continue;
    }
    for (const std::string& alias : visionClassAliases(target, target_model)) {
      if (visionClassTokenMatchesAlias(normalized_class, alias)) {
        return true;
      }
    }
  }
  return false;
}

bool visionObjectIdMatchesTargetModel(const std::string& object_id,
                                      const std::string& target_model) {
  return !object_id.empty() && normalizeStageName(object_id) == normalizeStageName(target_model);
}

bool findMatchingVisionPickDetection(const rclcpp::Logger& logger, rclcpp::Clock& clock,
                                     const std::vector<VisionPickDetection>& detections,
                                     task_presets::ManufacturingTarget target_kind,
                                     const std::string& target_model, const TargetObject& target,
                                     const VisionPickMatchConfig& config,
                                     VisionPickDetection& matched_detection) {
  if (detections.empty()) {
    RCLCPP_WARN_THROTTLE(logger, clock, 1000, "Vision pick has no received detections yet");
    return false;
  }

  const rclcpp::Time now = clock.now();
  double best_distance = std::numeric_limits<double>::infinity();
  bool found_best_detection = false;
  VisionPickDetection best_detection;

  for (const auto& detection : detections) {
    const auto evaluation =
        evaluateVisionPickCandidate(detection, target_kind, target_model, target, config.min_score,
                                    config.max_age_sec, config.max_distance_m, now);

    if (evaluation.reject_reason == VisionPickRejectReason::LowScore) {
      continue;
    }
    if (evaluation.reject_reason == VisionPickRejectReason::Frame) {
      RCLCPP_WARN_THROTTLE(logger, clock, 2000,
                           "Vision pick ignores detection '%s' in frame '%s'; expected world frame",
                           detection.class_id.c_str(), detection.frame_id.c_str());
      continue;
    }
    if (!detection.object_id.empty() && !evaluation.object_id_matches) {
      RCLCPP_DEBUG(logger, "Vision pick skip id=%s for target_model=%s",
                   detection.object_id.c_str(), target_model.c_str());
      continue;
    }
    if (evaluation.reject_reason == VisionPickRejectReason::ClassOrId) {
      RCLCPP_DEBUG(logger, "Vision pick skip class=%s id=%s for target=%s/%s",
                   detection.class_id.c_str(), detection.object_id.c_str(),
                   task_presets::targetName(target_kind), target_model.c_str());
      continue;
    }
    if (evaluation.reject_reason == VisionPickRejectReason::Stale) {
      RCLCPP_DEBUG(logger, "Vision pick skip stale class=%s id=%s age=%.3f",
                   detection.class_id.c_str(), detection.object_id.c_str(), evaluation.age_sec);
      continue;
    }
    if (evaluation.reject_reason == VisionPickRejectReason::FarFromLayout) {
      RCLCPP_DEBUG(logger, "Vision pick skip far class=%s id=%s distance=%.3f",
                   detection.class_id.c_str(), detection.object_id.c_str(), evaluation.distance_m);
      continue;
    }
    if (!visionPickCandidateUsable(evaluation)) {
      continue;
    }
    if (evaluation.distance_m < best_distance) {
      best_distance = evaluation.distance_m;
      best_detection = detection;
      found_best_detection = true;
    }
  }

  if (!found_best_detection) {
    return false;
  }
  matched_detection = best_detection;
  return true;
}

std::string summarizeVisionPickCandidates(const std::vector<VisionPickDetection>& detections,
                                          task_presets::ManufacturingTarget target_kind,
                                          const std::string& target_model,
                                          const TargetObject& target,
                                          const VisionPickMatchConfig& config,
                                          const rclcpp::Time& now) {
  std::ostringstream stream;
  stream << "Vision pick candidates for " << task_presets::targetName(target_kind) << "/"
         << target_model << ": count=" << detections.size();
  std::size_t count = 0;
  std::size_t score_reject_count = 0;
  std::size_t frame_reject_count = 0;
  std::size_t class_reject_count = 0;
  std::size_t age_reject_count = 0;
  std::size_t distance_reject_count = 0;
  std::size_t usable_count = 0;
  for (const auto& detection : detections) {
    if (count++ >= 12) {
      stream << " ...";
      break;
    }
    const auto evaluation =
        evaluateVisionPickCandidate(detection, target_kind, target_model, target, config.min_score,
                                    config.max_age_sec, config.max_distance_m, now);

    if (evaluation.reject_reason == VisionPickRejectReason::LowScore) {
      ++score_reject_count;
    } else if (evaluation.reject_reason == VisionPickRejectReason::Frame) {
      ++frame_reject_count;
    } else if (evaluation.reject_reason == VisionPickRejectReason::ClassOrId) {
      ++class_reject_count;
    } else if (evaluation.reject_reason == VisionPickRejectReason::Stale) {
      ++age_reject_count;
    } else if (evaluation.reject_reason == VisionPickRejectReason::FarFromLayout) {
      ++distance_reject_count;
    } else {
      ++usable_count;
    }
    stream << " [class=" << detection.class_id << " id=" << detection.object_id
           << " score=" << detection.score << " frame=" << detection.frame_id
           << " class_match=" << (evaluation.class_matches ? "Y" : "N")
           << " id_match=" << (evaluation.object_id_matches ? "Y" : "N")
           << " age=" << evaluation.age_sec << " dist=" << evaluation.distance_m
           << " reject=" << rejectReasonName(evaluation.reject_reason) << "]";
  }
  stream << " summary{usable=" << usable_count << ", low_score=" << score_reject_count
         << ", frame=" << frame_reject_count << ", class_or_id=" << class_reject_count
         << ", stale=" << age_reject_count << ", far_from_layout=" << distance_reject_count << "}";
  return stream.str();
}

bool applyVisionDetectionToTarget(const rclcpp::Logger& logger,
                                  task_presets::ManufacturingTarget target,
                                  const std::string& target_model,
                                  const VisionPickDetection& detection, bool use_detection_size,
                                  TargetObject& target_object) {
  const Eigen::Vector3d previous_center = objectWorldCenter(target_object);
  const Eigen::Vector3d detection_center = posePosition(detection.pose);

  if (!poseHasValidOrientation(detection.pose)) {
    RCLCPP_ERROR(logger,
                 "Vision pick: detection for %s/%s has no valid YOLO-seg PCA orientation; aborting",
                 task_presets::targetName(target), target_model.c_str());
    return false;
  }

  const Eigen::Matrix3d detection_rotation = poseOrientation(detection.pose).toRotationMatrix();
  const Eigen::Vector3d horizontal_x(detection_rotation(0, 0), detection_rotation(1, 0), 0.0);
  if (horizontal_x.norm() <= 1e-6) {
    RCLCPP_ERROR(logger,
                 "Vision pick: detection for %s/%s has degenerate YOLO-seg PCA yaw axis; aborting",
                 task_presets::targetName(target), target_model.c_str());
    return false;
  }

  const double layout_yaw = target_object.rpy.z();
  const double pca_yaw = std::atan2(horizontal_x.y(), horizontal_x.x());
  const bool align_pca_yaw_to_layout = target == task_presets::ManufacturingTarget::Case;
  if (align_pca_yaw_to_layout) {
    target_object.rpy.z() = choosePcaYawClosestToLayout(pca_yaw, layout_yaw);
  } else {
    target_object.rpy.z() = pca_yaw;
  }

  if (use_detection_size && detection.size.x() > 0.005 && detection.size.y() > 0.005 &&
      detection.size.z() > 0.005) {
    target_object.size = detection.size;
  }

  target_object.xyz =
      detection_center - rotationFromRpy(target_object.rpy) * target_object.local_center;
  target_object.pose_from_vision = true;

  RCLCPP_INFO(logger,
              "Vision pick target '%s': class=%s id=%s score=%.3f center [%.3f %.3f %.3f] -> [%.3f "
              "%.3f %.3f], xyz=[%.3f %.3f %.3f], yaw=%.3f (yolo-seg PCA)",
              target_object.name.c_str(), detection.class_id.c_str(), detection.object_id.c_str(),
              detection.score, previous_center.x(), previous_center.y(), previous_center.z(),
              detection_center.x(), detection_center.y(), detection_center.z(),
              target_object.xyz.x(), target_object.xyz.y(), target_object.xyz.z(),
              target_object.rpy.z());
  if (align_pca_yaw_to_layout) {
    RCLCPP_INFO(logger,
                "Vision pick target '%s': case PCA yaw %.3f aligned to layout yaw %.3f -> %.3f",
                target_object.name.c_str(), pca_yaw, layout_yaw, target_object.rpy.z());
  }
  return true;
}

VisionPickAdapter::VisionPickAdapter(rclcpp::Node& node, const VisionPickAdapterConfig& config)
    : node_(node), config_(config) {
  subscription_ = node_.create_subscription<vision_msgs::msg::Detection3DArray>(
      config_.detections_topic, rclcpp::QoS(10),
      [this](const vision_msgs::msg::Detection3DArray::SharedPtr msg) { handleDetections(msg); });
}

void VisionPickAdapter::handleDetections(const vision_msgs::msg::Detection3DArray::SharedPtr msg) {
  const rclcpp::Time received_stamp = node_.get_clock()->now();
  store_.updateFromMessage(received_stamp, *msg);
  RCLCPP_DEBUG(node_.get_logger(), "Vision pick received %zu detections", msg->detections.size());
}

bool VisionPickAdapter::findDetection(task_presets::ManufacturingTarget target_kind,
                                      const std::string& target_model, const TargetObject& target,
                                      VisionPickDetection& detection) {
  return findMatchingVisionPickDetection(node_.get_logger(), *node_.get_clock(), store_.snapshot(),
                                         target_kind, target_model, target, config_.match,
                                         detection);
}

bool VisionPickAdapter::waitForDetection(task_presets::ManufacturingTarget target_kind,
                                         const std::string& target_model,
                                         const TargetObject& target,
                                         VisionPickDetection& detection) {
  const auto deadline =
      std::chrono::steady_clock::now() + std::chrono::duration<double>(config_.timeout_sec);

  rclcpp::NodeOptions waiter_options;
  waiter_options.context(node_.get_node_options().context());
  waiter_options.start_parameter_services(false);
  waiter_options.start_parameter_event_publisher(false);
  waiter_options.enable_rosout(false);
  auto waiter_node = std::make_shared<rclcpp::Node>("ddooby_vision_pick_waiter", waiter_options);
  auto waiter_subscription = waiter_node->create_subscription<vision_msgs::msg::Detection3DArray>(
      config_.detections_topic, rclcpp::QoS(10),
      [](vision_msgs::msg::Detection3DArray::ConstSharedPtr) {});

  while (rclcpp::ok() && std::chrono::steady_clock::now() < deadline) {
    if (findDetection(target_kind, target_model, target, detection)) {
      return true;
    }

    vision_msgs::msg::Detection3DArray msg;
    if (rclcpp::wait_for_message(msg, waiter_subscription, node_.get_node_options().context(),
                                 std::chrono::milliseconds{100})) {
      handleDetections(std::make_shared<vision_msgs::msg::Detection3DArray>(std::move(msg)));
      if (findDetection(target_kind, target_model, target, detection)) {
        return true;
      }
    }
  }

  return findDetection(target_kind, target_model, target, detection);
}

std::string VisionPickAdapter::summarizeCandidates(task_presets::ManufacturingTarget target_kind,
                                                   const std::string& target_model,
                                                   const TargetObject& target) {
  return summarizeVisionPickCandidates(store_.snapshot(), target_kind, target_model, target,
                                       config_.match, node_.get_clock()->now());
}

bool VisionPickAdapter::applyTarget(task_presets::ManufacturingTarget target_kind,
                                    const std::string& target_model, TargetObject& target) {
  if (!config_.enabled) {
    return true;
  }

  RCLCPP_INFO(node_.get_logger(), "Vision pick: waiting up to %.2fs for %s/%s detection",
              config_.timeout_sec, task_presets::targetName(target_kind), target_model.c_str());
  VisionPickDetection detection;
  if (!waitForDetection(target_kind, target_model, target, detection)) {
    const std::string message = "Vision pick: no matching detection for " +
                                std::string(task_presets::targetName(target_kind)) + "/" +
                                target_model + "; aborting";
    RCLCPP_ERROR(node_.get_logger(), "%s", message.c_str());
    RCLCPP_ERROR(node_.get_logger(), "%s",
                 summarizeCandidates(target_kind, target_model, target).c_str());
    return false;
  }

  return applyVisionDetectionToTarget(node_.get_logger(), target_kind, target_model, detection,
                                      config_.use_detection_size, target);
}

}  // namespace ddooby_controller::manufacturing_task
