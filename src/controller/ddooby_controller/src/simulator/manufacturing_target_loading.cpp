#include <Eigen/Geometry>
#include <algorithm>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <chrono>
#include <cmath>
#include <geometry_msgs/msg/pose.hpp>
#include <limits>
#include <memory>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <rclcpp/rclcpp.hpp>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "ddooby_controller/control/manufacturing_stage_motion.hpp"
#include "ddooby_controller/control/moveit_task_utils.hpp"
#include "ddooby_controller/control/planning_scene_utils.hpp"
#include "ddooby_controller/simulator/manufacturing_layout_utils.hpp"
#include "ddooby_controller/task/manufacturing_pick_planner.hpp"
#include "ddooby_controller/task/manufacturing_place_planner.hpp"
#include "ddooby_controller/task/manufacturing_pose_utils.hpp"
#include "ddooby_controller/task/manufacturing_task_common.hpp"
#include "ddooby_controller/vision/vision_pick_adapter.hpp"
#include "manufacturing_task_node_private.hpp"

namespace ddooby_controller {
using namespace manufacturing_task;

bool HotdogMakingNode::resolvePackageShareDirectory(std::string& package_share_directory) {
  if (has_package_share_directory_) {
    package_share_directory = package_share_directory_;
    return true;
  }

  try {
    package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
    package_share_directory_ = package_share_directory;
    has_package_share_directory_ = true;
  } catch (const std::exception& error) {
    RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s",
                 error.what());
    return false;
  }
  return true;
}

bool HotdogMakingNode::loadManufacturingTarget(const std::string& target_model,
                                               TargetObject& target) {
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  const std::string layout_path =
      effectiveManufacturingLayoutPath(package_share_directory, layout_path_);

  try {
    target = loadTargetObject(package_share_directory, layout_path, target_model);
  } catch (const std::exception& error) {
    RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", target_model.c_str(),
                 error.what());
    return false;
  }
  return true;
}

bool HotdogMakingNode::moveArmToReadyBeforeVisionPick(const std::string& log_label,
                                                      const std::string& arm_group,
                                                      const std::string& ready_pose_name,
                                                      const std::vector<double>& ready_joints) {
  if (!enable_vision_pick_ || !shouldRunStage(ManufacturingStage::Pick) || dry_run_) {
    return true;
  }

  auto self = shared_from_this();
  moveit::planning_interface::MoveGroupInterface arm(self, arm_group);
  configureTaskArm(arm, "");
  rememberJointTargetIfConfigured(arm, ready_pose_name, ready_joints);

  RCLCPP_INFO(get_logger(), "%s: moving arm to ready pose before vision pick observation",
              log_label.c_str());
  return planAndExecuteNamedTarget(get_logger(), arm, ready_pose_name,
                                   log_label + " vision observation ready");
}

bool HotdogMakingNode::loadTargetForVisionPick(
    ManufacturingTarget target_kind, const std::string& log_label, const std::string& arm_group,
    const std::string& ready_pose_name, const std::vector<double>& ready_joints,
    const std::string& target_model, TargetObject& target) {
  if (!loadManufacturingTarget(target_model, target)) {
    return false;
  }
  if (!moveArmToReadyBeforeVisionPick(log_label, arm_group, ready_pose_name, ready_joints)) {
    return false;
  }
  return applyVisionPickTarget(target_kind, target_model, target);
}

VisionPickMatchConfig HotdogMakingNode::visionPickMatchConfig() const {
  return VisionPickMatchConfig{vision_pick_min_score_, vision_pick_max_age_sec_,
                               vision_pick_max_distance_m_};
}

bool HotdogMakingNode::applyVisionPickTarget(ManufacturingTarget target_kind,
                                             const std::string& target_model,
                                             TargetObject& target) {
  if (!enable_vision_pick_ || !shouldRunStage(ManufacturingStage::Pick)) {
    return true;
  }

  if (!vision_pick_adapter_) {
    RCLCPP_ERROR(get_logger(), "Vision pick enabled but VisionPickAdapter is not configured");
    return false;
  }
  return vision_pick_adapter_->applyTarget(target_kind, target_model, target);
}

bool HotdogMakingNode::applyVisionCollisionObjectIfNeeded(
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const TargetObject& target, const std::string& log_label) {
  if (!target.pose_from_vision) {
    return true;
  }

  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  return applyVisionTargetCollisionObject(get_logger(), planning_scene_interface,
                                          package_share_directory, target, log_label,
                                          collision_scene_settle_ms_);
}

bool HotdogMakingNode::restoreTargetCollisionObject(
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const std::string& target_model, const std::string& log_label) {
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }

  const std::string layout_path =
      effectiveManufacturingLayoutPath(package_share_directory, layout_path_);

  return restoreTargetCollisionObjectFromLayout(get_logger(), planning_scene_interface,
                                                package_share_directory, layout_path, target_model,
                                                log_label, collision_scene_settle_ms_);
}

}  // namespace ddooby_controller
