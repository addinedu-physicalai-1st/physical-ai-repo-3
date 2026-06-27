#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <Eigen/Geometry>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/wait_for_message.hpp>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/manufacturing_layout_utils.hpp"
#include "ddooby_controller/manufacturing_pick_planner.hpp"
#include "ddooby_controller/manufacturing_place_planner.hpp"
#include "ddooby_controller/manufacturing_pose_utils.hpp"
#include "ddooby_controller/manufacturing_stage_motion.hpp"
#include "ddooby_controller/manufacturing_task_common.hpp"
#include "manufacturing_task_node.hpp"
#include "ddooby_controller/manufacturing_task_runner.hpp"
#include "ddooby_controller/moveit_task_utils.hpp"
#include "ddooby_controller/planning_scene_utils.hpp"
#include "ddooby_controller/vision_pick_adapter.hpp"

namespace ddooby_controller
{
using namespace std::chrono_literals;


bool HotdogMakingNode::resolvePackageShareDirectory(std::string & package_share_directory)
{
    if (package_share_directory_.has_value()) {
      package_share_directory = package_share_directory_.value();
      return true;
    }

    try {
      package_share_directory = ament_index_cpp::get_package_share_directory("ddooby_controller");
      package_share_directory_ = package_share_directory;
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to resolve ddooby_controller share directory: %s", error.what());
      return false;
    }
    return true;
  }

bool HotdogMakingNode::loadManufacturingTarget(const std::string & target_model, TargetObject & target)
{
    std::string package_share_directory;
    if (!resolvePackageShareDirectory(package_share_directory)) {
      return false;
    }
    const std::string layout_path =
      effectiveManufacturingLayoutPath(package_share_directory, layout_path_);

    try {
      target = loadTargetObject(package_share_directory, layout_path, target_model);
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "Failed to load target object '%s': %s", target_model.c_str(), error.what());
      return false;
    }
    return true;
  }

bool HotdogMakingNode::moveArmToReadyBeforeVisionPick(
    const std::string & log_label,
    const std::string & arm_group,
    const std::string & ready_pose_name,
    const std::vector<double> & ready_joints)
{
    if (!enable_vision_pick_ || !shouldRunStage(ManufacturingStage::Pick) || dry_run_) {
      return true;
    }

    auto self = shared_from_this();
    moveit::planning_interface::MoveGroupInterface arm(self, arm_group);
    configureTaskArm(arm, "");
    rememberJointTargetIfConfigured(arm, ready_pose_name, ready_joints);

    RCLCPP_INFO(
      get_logger(),
      "%s: moving arm to ready pose before vision pick observation",
      log_label.c_str());
    return planAndExecuteNamedTarget(
      get_logger(),
      arm,
      ready_pose_name,
      log_label + " vision observation ready");
  }

bool HotdogMakingNode::loadTargetForVisionPick(
    ManufacturingTarget target_kind,
    const std::string & log_label,
    const std::string & arm_group,
    const std::string & ready_pose_name,
    const std::vector<double> & ready_joints,
    const std::string & target_model,
    TargetObject & target)
{
    if (!loadManufacturingTarget(target_model, target)) {
      return false;
    }
    if (!moveArmToReadyBeforeVisionPick(log_label, arm_group, ready_pose_name, ready_joints)) {
      return false;
    }
    return applyVisionPickTarget(target_kind, target_model, target);
  }

void HotdogMakingNode::handleVisionDetections(const vision_msgs::msg::Detection3DArray::SharedPtr msg)
{
    const rclcpp::Time received_stamp = get_clock()->now();
    vision_pick_store_.updateFromMessage(received_stamp, *msg);
    RCLCPP_DEBUG(get_logger(), "Vision pick received %zu detections", msg->detections.size());
  }

std::optional<VisionPickDetection> HotdogMakingNode::findVisionPickDetection(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target)
{
    return vision_pick_store_.findMatching(
      get_logger(),
      *get_clock(),
      target_kind,
      target_model,
      target,
      vision_pick_min_score_,
      vision_pick_max_age_sec_,
      vision_pick_max_distance_m_);
  }

std::string HotdogMakingNode::summarizeVisionPickCandidates(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target)
{
    return vision_pick_store_.summarizeCandidates(
      target_kind,
      target_model,
      target,
      get_clock()->now());
  }

std::optional<VisionPickDetection> HotdogMakingNode::waitForVisionPickDetection(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    const TargetObject & target)
{
    const auto deadline = std::chrono::steady_clock::now() +
      std::chrono::duration<double>(vision_pick_timeout_sec_);

    rclcpp::NodeOptions waiter_options;
    waiter_options.context(get_node_options().context());
    waiter_options.start_parameter_services(false);
    waiter_options.start_parameter_event_publisher(false);
    waiter_options.enable_rosout(false);
    auto waiter_node = std::make_shared<rclcpp::Node>("ddooby_vision_pick_waiter", waiter_options);
    auto waiter_subscription = waiter_node->create_subscription<vision_msgs::msg::Detection3DArray>(
      vision_detections_topic_,
      rclcpp::QoS(10),
      [](vision_msgs::msg::Detection3DArray::ConstSharedPtr) {});

    while (rclcpp::ok() && std::chrono::steady_clock::now() < deadline) {
      if (const auto detection = findVisionPickDetection(target_kind, target_model, target)) {
        return detection;
      }

      vision_msgs::msg::Detection3DArray msg;
      if (rclcpp::wait_for_message(
          msg,
          waiter_subscription,
          get_node_options().context(),
          100ms))
      {
        handleVisionDetections(std::make_shared<vision_msgs::msg::Detection3DArray>(std::move(msg)));
        if (const auto detection = findVisionPickDetection(target_kind, target_model, target)) {
          return detection;
        }
      }
    }

    return findVisionPickDetection(target_kind, target_model, target);
  }

bool HotdogMakingNode::applyVisionPickTarget(
    ManufacturingTarget target_kind,
    const std::string & target_model,
    TargetObject & target)
{
    if (!enable_vision_pick_ || !shouldRunStage(ManufacturingStage::Pick)) {
      return true;
    }

    RCLCPP_INFO(
      get_logger(),
      "Vision pick: waiting up to %.2fs for %s/%s detection",
      vision_pick_timeout_sec_,
      task_presets::targetName(target_kind),
      target_model.c_str());
    const auto detection = waitForVisionPickDetection(target_kind, target_model, target);
    if (!detection.has_value()) {
      const std::string message =
        "Vision pick: no matching detection for " +
        std::string(task_presets::targetName(target_kind)) +
        "/" + target_model + "; aborting";
      RCLCPP_ERROR(get_logger(), "%s", message.c_str());
      RCLCPP_ERROR(get_logger(), "%s", summarizeVisionPickCandidates(target_kind, target_model, target).c_str());
      return false;
    }

    return applyVisionDetectionToTarget(
      get_logger(),
      target_kind,
      target_model,
      *detection,
      vision_pick_use_size_,
      target);
  }

bool HotdogMakingNode::applyVisionCollisionObjectIfNeeded(
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    const TargetObject & target,
    const std::string & log_label)
{
    if (!target.pose_from_vision) {
      return true;
    }

    std::string package_share_directory;
    if (!resolvePackageShareDirectory(package_share_directory)) {
      return false;
    }
    return applyVisionTargetCollisionObject(
      get_logger(),
      planning_scene_interface,
      package_share_directory,
      target,
      log_label,
      collision_scene_settle_ms_);
  }

bool HotdogMakingNode::restoreTargetCollisionObject(
    moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
    const std::string & target_model,
    const std::string & log_label)
{
    std::string package_share_directory;
    if (!resolvePackageShareDirectory(package_share_directory)) {
      return false;
    }

    const std::string layout_path =
      effectiveManufacturingLayoutPath(package_share_directory, layout_path_);

    return restoreTargetCollisionObjectFromLayout(
      get_logger(),
      planning_scene_interface,
      package_share_directory,
      layout_path,
      target_model,
      log_label,
      collision_scene_settle_ms_);
  }

}  // namespace ddooby_controller
