#include "ddooby_controller/vision_pick_adapter.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>

#include "ddooby_controller/manufacturing_task_common.hpp"
#include "ddooby_controller/manufacturing_pose_utils.hpp"

#include <rclcpp/rclcpp.hpp>

namespace ddooby_controller::manufacturing_task
{

std::vector<std::string> visionClassAliases(
  task_presets::ManufacturingTarget target,
  const std::string & target_model)
{
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
  aliases.erase(std::remove_if(
      aliases.begin(),
      aliases.end(),
      [](const std::string & alias) {return alias.empty();}),
    aliases.end());
  aliases.erase(std::unique(aliases.begin(), aliases.end()), aliases.end());
  return aliases;
}

bool visionClassTokenMatchesAlias(const std::string & normalized_class, const std::string & alias)
{
  if (normalized_class == alias) {
    return true;
  }
  if (alias.size() >= 4 && normalized_class.rfind(alias, 0) == 0) {
    const std::string suffix = normalized_class.substr(alias.size());
    return !suffix.empty() && std::all_of(
      suffix.begin(),
      suffix.end(),
      [](char character) {return std::isdigit(static_cast<unsigned char>(character));});
  }
  return false;
}

bool visionClassMatches(
  const std::string & class_id,
  task_presets::ManufacturingTarget target,
  const std::string & target_model)
{
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

  for (const std::string & normalized_class : normalized_classes) {
    if (normalized_class.empty()) {
      continue;
    }
    for (const std::string & alias : visionClassAliases(target, target_model)) {
      if (visionClassTokenMatchesAlias(normalized_class, alias)) {
        return true;
      }
    }
  }
  return false;
}

bool visionObjectIdMatchesTargetModel(
  const std::string & object_id,
  const std::string & target_model)
{
  return !object_id.empty() &&
         normalizeStageName(object_id) == normalizeStageName(target_model);
}

bool applyVisionDetectionToTarget(
  const rclcpp::Logger & logger,
  task_presets::ManufacturingTarget target,
  const std::string & target_model,
  const VisionPickDetection & detection,
  bool use_detection_size,
  TargetObject & target_object)
{
  const Eigen::Vector3d previous_center = objectWorldCenter(target_object);
  const Eigen::Vector3d detection_center = posePosition(detection.pose);

  if (!poseHasValidOrientation(detection.pose)) {
    RCLCPP_ERROR(
      logger,
      "Vision pick: detection for %s/%s has no valid YOLO-seg PCA orientation; aborting",
      task_presets::targetName(target),
      target_model.c_str());
    return false;
  }

  const Eigen::Matrix3d detection_rotation = poseOrientation(detection.pose).toRotationMatrix();
  const Eigen::Vector3d horizontal_x(
    detection_rotation(0, 0),
    detection_rotation(1, 0),
    0.0);
  if (horizontal_x.norm() <= 1e-6) {
    RCLCPP_ERROR(
      logger,
      "Vision pick: detection for %s/%s has degenerate YOLO-seg PCA yaw axis; aborting",
      task_presets::targetName(target),
      target_model.c_str());
    return false;
  }
  target_object.rpy.z() = std::atan2(horizontal_x.y(), horizontal_x.x());

  if (use_detection_size &&
    detection.size.x() > 0.005 &&
    detection.size.y() > 0.005 &&
    detection.size.z() > 0.005)
  {
    target_object.size = detection.size;
  }

  target_object.xyz = detection_center - rotationFromRpy(target_object.rpy) * target_object.local_center;
  target_object.pose_from_vision = true;

  RCLCPP_INFO(
    logger,
    "Vision pick target '%s': class=%s id=%s score=%.3f center [%.3f %.3f %.3f] -> [%.3f %.3f %.3f], xyz=[%.3f %.3f %.3f], yaw=%.3f (yolo-seg PCA)",
    target_object.name.c_str(),
    detection.class_id.c_str(),
    detection.object_id.c_str(),
    detection.score,
    previous_center.x(),
    previous_center.y(),
    previous_center.z(),
    detection_center.x(),
    detection_center.y(),
    detection_center.z(),
    target_object.xyz.x(),
    target_object.xyz.y(),
    target_object.xyz.z(),
    target_object.rpy.z());
  return true;
}

}  // namespace ddooby_controller::manufacturing_task
