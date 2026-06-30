#pragma once

#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <rclcpp/logger.hpp>
#include <rclcpp/node.hpp>
#include <set>
#include <string>
#include <vector>

#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task {

moveit_msgs::msg::CollisionObject makeCollisionObjectFromSdf(
    const std::string& package_share_directory, const std::string& layout_path,
    const std::string& target_model, const std::string& frame_id);

moveit_msgs::msg::CollisionObject makeCollisionObjectFromTargetObject(
    const std::string& package_share_directory, const TargetObject& target,
    const std::string& frame_id);

std::vector<std::string> makeGripperTouchLinks(
    const moveit::planning_interface::MoveGroupInterface& gripper, const std::string& tcp_link);

bool applyTargetGripperAllowedCollision(
    const rclcpp::Node::SharedPtr& node, const rclcpp::Logger& logger,
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const std::string& target_object, const std::vector<std::string>& touch_links, bool allow,
    int settle_ms);

bool attachTargetCollisionObject(const rclcpp::Logger& logger,
                                 moveit::planning_interface::MoveGroupInterface& arm,
                                 std::set<std::string>& attached_collision_objects,
                                 const std::string& target_model, const std::string& attach_link,
                                 const std::vector<std::string>& touch_links,
                                 const std::string& log_label, int settle_ms);

bool detachTargetCollisionObject(const rclcpp::Logger& logger,
                                 moveit::planning_interface::MoveGroupInterface& arm,
                                 std::set<std::string>& attached_collision_objects,
                                 const std::string& target_model, const std::string& log_label,
                                 int settle_ms);

bool removeTargetCollisionObject(
    const rclcpp::Logger& logger,
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const std::string& target_model, const std::string& log_label, int settle_ms);

bool applyVisionTargetCollisionObject(
    const rclcpp::Logger& logger,
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const std::string& package_share_directory, const TargetObject& target,
    const std::string& log_label, int settle_ms);

bool restoreTargetCollisionObjectFromLayout(
    const rclcpp::Logger& logger,
    moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
    const std::string& package_share_directory, const std::string& layout_path,
    const std::string& target_model, const std::string& log_label, int settle_ms);

}  // namespace ddooby_controller::manufacturing_task
