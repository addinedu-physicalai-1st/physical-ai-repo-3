#include "ddooby_controller/planning_scene_utils.hpp"

#include <algorithm>
#include <chrono>
#include <future>
#include <memory>
#include <stdexcept>
#include <string_view>

#include <moveit_msgs/msg/allowed_collision_entry.hpp>
#include <moveit_msgs/msg/planning_scene.hpp>
#include <moveit_msgs/msg/planning_scene_components.hpp>
#include <moveit_msgs/srv/get_planning_scene.hpp>
#include <rclcpp/rclcpp.hpp>
#include <shape_msgs/msg/solid_primitive.hpp>

#include "ddooby_controller/manufacturing_layout_utils.hpp"
#include "ddooby_controller/manufacturing_pose_utils.hpp"

namespace ddooby_controller::manufacturing_task
{

using namespace std::chrono_literals;

moveit_msgs::msg::CollisionObject makeCollisionObjectFromSdf(
  const std::string & package_share_directory,
  const std::string & layout_path,
  const std::string & target_model,
  const std::string & frame_id)
{
  const std::string layout_text = readTextFile(layout_path);
  const std::string model_block = extractJsonObjectForModel(layout_text, target_model);

  const std::string model_name = extractStringValue(model_block, "name");
  const std::string model_dir = extractStringValue(model_block, "model_dir");
  const Eigen::Vector3d model_xyz = extractVector3Value(model_block, "xyz");
  const Eigen::Vector3d model_rpy = extractVector3Value(model_block, "rpy");
  const Eigen::Matrix3d model_rotation = rotationFromRpy(model_rpy);

  const std::string sdf_path =
    joinPath(joinPath(package_share_directory, "assets"), joinPath(model_dir, "model.sdf"));
  const std::vector<CollisionPrimitiveSpec> primitives =
    parseCollisionPrimitives(readTextFile(sdf_path));
  if (primitives.empty()) {
    throw std::runtime_error("target model '" + target_model + "' has no supported collision geometry");
  }

  moveit_msgs::msg::CollisionObject object;
  object.header.frame_id = frame_id;
  object.id = model_name;
  object.operation = moveit_msgs::msg::CollisionObject::ADD;

  for (const CollisionPrimitiveSpec & primitive_spec : primitives) {
    shape_msgs::msg::SolidPrimitive primitive;
    if (primitive_spec.type == CollisionPrimitiveSpec::Type::Cylinder) {
      primitive.type = shape_msgs::msg::SolidPrimitive::CYLINDER;
      primitive.dimensions.resize(2);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_HEIGHT] =
        primitive_spec.length;
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_RADIUS] =
        primitive_spec.radius;
    } else {
      primitive.type = shape_msgs::msg::SolidPrimitive::BOX;
      primitive.dimensions.resize(3);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_X] = primitive_spec.size.x();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Y] = primitive_spec.size.y();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Z] = primitive_spec.size.z();
    }

    const Eigen::Vector3d global_center =
      model_xyz + model_rotation * primitive_spec.center;
    const Eigen::Matrix3d global_rotation =
      model_rotation * rotationFromRpy(primitive_spec.rpy);

    object.primitives.push_back(primitive);
    object.primitive_poses.push_back(makePose(global_center, Eigen::Quaterniond(global_rotation)));
  }

  return object;
}

moveit_msgs::msg::CollisionObject makeCollisionObjectFromTargetObject(
  const std::string & package_share_directory,
  const TargetObject & target,
  const std::string & frame_id)
{
  const std::string sdf_path =
    joinPath(joinPath(package_share_directory, "assets"), joinPath(target.model_dir, "model.sdf"));
  const std::vector<CollisionPrimitiveSpec> primitives =
    parseCollisionPrimitives(readTextFile(sdf_path));
  if (primitives.empty()) {
    throw std::runtime_error("target model '" + target.name + "' has no supported collision geometry");
  }

  const Eigen::Matrix3d model_rotation = rotationFromRpy(target.rpy);

  moveit_msgs::msg::CollisionObject object;
  object.header.frame_id = frame_id;
  object.id = target.name;
  object.operation = moveit_msgs::msg::CollisionObject::ADD;

  for (const CollisionPrimitiveSpec & primitive_spec : primitives) {
    shape_msgs::msg::SolidPrimitive primitive;
    if (primitive_spec.type == CollisionPrimitiveSpec::Type::Cylinder) {
      primitive.type = shape_msgs::msg::SolidPrimitive::CYLINDER;
      primitive.dimensions.resize(2);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_HEIGHT] =
        primitive_spec.length;
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::CYLINDER_RADIUS] =
        primitive_spec.radius;
    } else {
      primitive.type = shape_msgs::msg::SolidPrimitive::BOX;
      primitive.dimensions.resize(3);
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_X] = primitive_spec.size.x();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Y] = primitive_spec.size.y();
      primitive.dimensions[shape_msgs::msg::SolidPrimitive::BOX_Z] = primitive_spec.size.z();
    }

    const Eigen::Vector3d global_center =
      target.xyz + model_rotation * primitive_spec.center;
    const Eigen::Matrix3d global_rotation =
      model_rotation * rotationFromRpy(primitive_spec.rpy);

    object.primitives.push_back(primitive);
    object.primitive_poses.push_back(makePose(global_center, Eigen::Quaterniond(global_rotation)));
  }

  return object;
}

std::vector<std::string> makeGripperTouchLinks(
  const moveit::planning_interface::MoveGroupInterface & gripper,
  const std::string & tcp_link)
{
  std::vector<std::string> touch_links = gripper.getLinkNames();
  touch_links.push_back(tcp_link);

  constexpr std::string_view kHandTcpSuffix = "_hand_tcp";
  if (tcp_link.size() > kHandTcpSuffix.size() &&
    tcp_link.compare(
      tcp_link.size() - kHandTcpSuffix.size(),
      kHandTcpSuffix.size(),
      kHandTcpSuffix) == 0)
  {
    const std::string arm_prefix = tcp_link.substr(0, tcp_link.size() - kHandTcpSuffix.size());
    touch_links.push_back(arm_prefix + "_hand");
    touch_links.push_back(arm_prefix + "_hand_tcp");
    touch_links.push_back(arm_prefix + "_left_finger");
    touch_links.push_back(arm_prefix + "_right_finger");
  }

  std::sort(touch_links.begin(), touch_links.end());
  touch_links.erase(std::unique(touch_links.begin(), touch_links.end()), touch_links.end());
  return touch_links;
}

bool applyTargetGripperAllowedCollision(
  const rclcpp::Node::SharedPtr & node,
  const rclcpp::Logger & logger,
  moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
  const std::string & target_object,
  const std::vector<std::string> & touch_links,
  bool allow,
  int settle_ms)
{
  if (target_object.empty() || touch_links.empty()) {
    return true;
  }

  auto client = node->create_client<moveit_msgs::srv::GetPlanningScene>("get_planning_scene");
  if (!client->wait_for_service(2s)) {
    RCLCPP_ERROR(logger, "MoveIt get_planning_scene service is not available");
    return false;
  }

  auto request = std::make_shared<moveit_msgs::srv::GetPlanningScene::Request>();
  request->components.components =
    moveit_msgs::msg::PlanningSceneComponents::ALLOWED_COLLISION_MATRIX;
  auto future = client->async_send_request(request);
  if (future.wait_for(2s) != std::future_status::ready) {
    RCLCPP_ERROR(logger, "Timed out while reading MoveIt allowed collision matrix");
    return false;
  }

  auto acm = future.get()->scene.allowed_collision_matrix;
  auto ensure_entry = [&acm](const std::string & name) {
      const auto found = std::find(acm.entry_names.begin(), acm.entry_names.end(), name);
      if (found != acm.entry_names.end()) {
        return static_cast<std::size_t>(std::distance(acm.entry_names.begin(), found));
      }

      const std::size_t new_size = acm.entry_names.size() + 1;
      acm.entry_names.push_back(name);
      for (auto & entry : acm.entry_values) {
        entry.enabled.resize(new_size, false);
      }
      moveit_msgs::msg::AllowedCollisionEntry entry;
      entry.enabled.assign(new_size, false);
      acm.entry_values.push_back(entry);
      return new_size - 1;
    };

  const std::size_t target_index = ensure_entry(target_object);
  for (const auto & link : touch_links) {
    const std::size_t link_index = ensure_entry(link);
    acm.entry_values[target_index].enabled[link_index] = allow;
    acm.entry_values[link_index].enabled[target_index] = allow;
  }

  moveit_msgs::msg::PlanningScene scene;
  scene.is_diff = true;
  scene.allowed_collision_matrix = acm;

  RCLCPP_INFO(
    logger,
    "%s target collision between '%s' and %zu links",
    allow ? "Allowing" : "Disallowing",
    target_object.c_str(),
    touch_links.size());
  if (!planning_scene_interface.applyPlanningScene(scene)) {
    RCLCPP_ERROR(
      logger,
      "Failed to apply allowed collision update for target '%s'",
      target_object.c_str());
    return false;
  }
  if (settle_ms > 0) {
    rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
  }
  return true;
}

bool attachTargetCollisionObject(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  std::set<std::string> & attached_collision_objects,
  const std::string & target_model,
  const std::string & attach_link,
  const std::vector<std::string> & touch_links,
  const std::string & log_label,
  int settle_ms)
{
  if (target_model.empty()) {
    return true;
  }
  if (attached_collision_objects.find(target_model) != attached_collision_objects.end()) {
    RCLCPP_INFO(
      logger,
      "%s: collision object '%s' is already attached",
      log_label.c_str(),
      target_model.c_str());
    return true;
  }

  RCLCPP_INFO(
    logger,
    "%s: attaching collision object '%s' to '%s' with %zu touch links",
    log_label.c_str(),
    target_model.c_str(),
    attach_link.c_str(),
    touch_links.size());
  if (!arm.attachObject(target_model, attach_link, touch_links)) {
    RCLCPP_ERROR(
      logger,
      "%s: failed to attach collision object '%s'",
      log_label.c_str(),
      target_model.c_str());
    return false;
  }

  attached_collision_objects.insert(target_model);
  if (settle_ms > 0) {
    rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
  }
  return true;
}

bool detachTargetCollisionObject(
  const rclcpp::Logger & logger,
  moveit::planning_interface::MoveGroupInterface & arm,
  std::set<std::string> & attached_collision_objects,
  const std::string & target_model,
  const std::string & log_label,
  int settle_ms)
{
  if (target_model.empty()) {
    return true;
  }
  if (attached_collision_objects.find(target_model) == attached_collision_objects.end()) {
    RCLCPP_INFO(
      logger,
      "%s: collision object '%s' is not attached; skipping detach",
      log_label.c_str(),
      target_model.c_str());
    return true;
  }

  RCLCPP_INFO(
    logger,
    "%s: detaching collision object '%s'",
    log_label.c_str(),
    target_model.c_str());
  if (!arm.detachObject(target_model)) {
    RCLCPP_ERROR(
      logger,
      "%s: failed to detach collision object '%s'",
      log_label.c_str(),
      target_model.c_str());
    return false;
  }

  attached_collision_objects.erase(target_model);
  if (settle_ms > 0) {
    rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
  }
  return true;
}

bool removeTargetCollisionObject(
  const rclcpp::Logger & logger,
  moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
  const std::string & target_model,
  const std::string & log_label,
  int settle_ms)
{
  if (target_model.empty()) {
    return true;
  }

  RCLCPP_INFO(
    logger,
    "%s: removing world collision object '%s'",
    log_label.c_str(),
    target_model.c_str());
  planning_scene_interface.removeCollisionObjects({target_model});
  if (settle_ms > 0) {
    rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
  }
  return true;
}

bool applyVisionTargetCollisionObject(
  const rclcpp::Logger & logger,
  moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
  const std::string & package_share_directory,
  const TargetObject & target,
  const std::string & log_label,
  int settle_ms)
{
  try {
    auto collision_object =
      makeCollisionObjectFromTargetObject(package_share_directory, target, "world");
    RCLCPP_INFO(
      logger,
      "%s: updating collision object '%s' from vision target with %zu primitive(s)",
      log_label.c_str(),
      collision_object.id.c_str(),
      collision_object.primitives.size());
    planning_scene_interface.applyCollisionObject(collision_object);
    if (settle_ms > 0) {
      rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
    }
  } catch (const std::exception & error) {
    RCLCPP_ERROR(
      logger,
      "%s: failed to update vision collision object '%s': %s",
      log_label.c_str(),
      target.name.c_str(),
      error.what());
    return false;
  }

  return true;
}

bool restoreTargetCollisionObjectFromLayout(
  const rclcpp::Logger & logger,
  moveit::planning_interface::PlanningSceneInterface & planning_scene_interface,
  const std::string & package_share_directory,
  const std::string & layout_path,
  const std::string & target_model,
  const std::string & log_label,
  int settle_ms)
{
  try {
    auto collision_object =
      makeCollisionObjectFromSdf(package_share_directory, layout_path, target_model, "world");
    RCLCPP_INFO(
      logger,
      "%s: restoring collision object '%s' with %zu primitive(s)",
      log_label.c_str(),
      collision_object.id.c_str(),
      collision_object.primitives.size());
    planning_scene_interface.applyCollisionObject(collision_object);
    if (settle_ms > 0) {
      rclcpp::sleep_for(std::chrono::milliseconds(settle_ms));
    }
  } catch (const std::exception & error) {
    RCLCPP_ERROR(
      logger,
      "%s: failed to restore collision object for '%s': %s",
      log_label.c_str(),
      target_model.c_str(),
      error.what());
    return false;
  }

  return true;
}

}  // namespace ddooby_controller::manufacturing_task
