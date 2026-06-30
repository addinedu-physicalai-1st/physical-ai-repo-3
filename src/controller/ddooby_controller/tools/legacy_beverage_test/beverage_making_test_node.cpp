#include <geometric_shapes/shapes.h>
#include <gz/msgs/pose_v.pb.h>

#include <Eigen/Geometry>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <future>
#include <geometry_msgs/msg/pose.hpp>
#include <gz/transport/Node.hh>
#include <iterator>
#include <limits>
#include <memory>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/robot_state/robot_state.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <mutex>
#include <optional>
#include <rclcpp/rclcpp.hpp>
#include <ros_gz_interfaces/msg/entity.hpp>
#include <ros_gz_interfaces/srv/set_entity_pose.hpp>
#include <string>
#include <thread>
#include <trajectory_msgs/msg/joint_trajectory.hpp>
#include <vector>

namespace {
template <typename T>
T getOrDeclareParameter(const rclcpp::Node::SharedPtr& node, const std::string& name,
                        const T& default_value) {
  if (node->has_parameter(name)) {
    return node->get_parameter(name).get_value<T>();
  }
  return node->declare_parameter<T>(name, default_value);
}

geometry_msgs::msg::Pose toPoseMsg(const Eigen::Isometry3d& transform) {
  geometry_msgs::msg::Pose pose;
  pose.position.x = transform.translation().x();
  pose.position.y = transform.translation().y();
  pose.position.z = transform.translation().z();

  const Eigen::Quaterniond orientation(transform.rotation());
  pose.orientation.x = orientation.x();
  pose.orientation.y = orientation.y();
  pose.orientation.z = orientation.z();
  pose.orientation.w = orientation.w();
  return pose;
}

Eigen::Isometry3d poseToIsometry(const geometry_msgs::msg::Pose& pose) {
  Eigen::Isometry3d transform = Eigen::Isometry3d::Identity();
  transform.translation() = Eigen::Vector3d(pose.position.x, pose.position.y, pose.position.z);
  const Eigen::Quaterniond orientation(pose.orientation.w, pose.orientation.x, pose.orientation.y,
                                       pose.orientation.z);
  transform.linear() = orientation.normalized().toRotationMatrix();
  return transform;
}

geometry_msgs::msg::Pose toPoseMsg(const gz::msgs::Pose& gz_pose) {
  geometry_msgs::msg::Pose pose;
  pose.position.x = gz_pose.position().x();
  pose.position.y = gz_pose.position().y();
  pose.position.z = gz_pose.position().z();
  pose.orientation.x = gz_pose.orientation().x();
  pose.orientation.y = gz_pose.orientation().y();
  pose.orientation.z = gz_pose.orientation().z();
  pose.orientation.w = gz_pose.orientation().w();
  return pose;
}

geometry_msgs::msg::Pose rotatePoseLocal(const geometry_msgs::msg::Pose& pose,
                                         const std::string& axis, double angle_rad) {
  Eigen::Vector3d local_axis = Eigen::Vector3d::UnitY();
  if (axis == "x" || axis == "local_x") {
    local_axis = Eigen::Vector3d::UnitX();
  } else if (axis == "z" || axis == "local_z") {
    local_axis = Eigen::Vector3d::UnitZ();
  }

  const Eigen::Quaterniond base_orientation(pose.orientation.w, pose.orientation.x,
                                            pose.orientation.y, pose.orientation.z);
  const Eigen::Quaterniond rotated_orientation =
      base_orientation * Eigen::AngleAxisd(angle_rad, local_axis);

  geometry_msgs::msg::Pose rotated_pose = pose;
  rotated_pose.orientation.x = rotated_orientation.x();
  rotated_pose.orientation.y = rotated_orientation.y();
  rotated_pose.orientation.z = rotated_orientation.z();
  rotated_pose.orientation.w = rotated_orientation.w();
  return rotated_pose;
}

geometry_msgs::msg::Pose makePose(double x, double y, double z, double roll = 0.0,
                                  double pitch = 0.0, double yaw = 0.0) {
  geometry_msgs::msg::Pose pose;
  pose.position.x = x;
  pose.position.y = y;
  pose.position.z = z;

  const Eigen::Quaterniond orientation = Eigen::AngleAxisd(yaw, Eigen::Vector3d::UnitZ()) *
                                         Eigen::AngleAxisd(pitch, Eigen::Vector3d::UnitY()) *
                                         Eigen::AngleAxisd(roll, Eigen::Vector3d::UnitX());
  pose.orientation.x = orientation.x();
  pose.orientation.y = orientation.y();
  pose.orientation.z = orientation.z();
  pose.orientation.w = orientation.w();
  return pose;
}

struct GazeboModelInitialPose {
  std::string name;
  geometry_msgs::msg::Pose pose;
};

bool setGazeboModelPose(const rclcpp::Node::SharedPtr& node, const std::string& service_name,
                        const GazeboModelInitialPose& model, double timeout_sec) {
  using SetEntityPose = ros_gz_interfaces::srv::SetEntityPose;

  auto client = node->create_client<SetEntityPose>(service_name);
  const auto timeout = std::chrono::duration<double>(timeout_sec);
  if (!client->wait_for_service(timeout)) {
    RCLCPP_ERROR(node->get_logger(),
                 "Gazebo set pose service '%s' unavailable while resetting '%s'",
                 service_name.c_str(), model.name.c_str());
    return false;
  }

  auto request = std::make_shared<SetEntityPose::Request>();
  request->entity.name = model.name;
  request->entity.type = ros_gz_interfaces::msg::Entity::MODEL;
  request->pose = model.pose;

  auto future = client->async_send_request(request);
  if (future.wait_for(timeout) != std::future_status::ready) {
    RCLCPP_ERROR(node->get_logger(), "Timed out resetting Gazebo model '%s' through service '%s'",
                 model.name.c_str(), service_name.c_str());
    return false;
  }

  const auto response = future.get();
  if (!response->success) {
    RCLCPP_ERROR(node->get_logger(), "Gazebo rejected reset pose for model '%s'",
                 model.name.c_str());
    return false;
  }
  RCLCPP_INFO(node->get_logger(), "Reset Gazebo model '%s' to [%.3f, %.3f, %.3f]",
              model.name.c_str(), model.pose.position.x, model.pose.position.y,
              model.pose.position.z);
  return true;
}

bool resetGazeboBeverageObjects(const rclcpp::Node::SharedPtr& node,
                                const std::string& service_name,
                                const std::vector<GazeboModelInitialPose>& model_poses,
                                double timeout_sec, double settle_time_sec) {
  for (const auto& model : model_poses) {
    if (!setGazeboModelPose(node, service_name, model, timeout_sec)) {
      return false;
    }
  }

  if (settle_time_sec > 0.0) {
    std::this_thread::sleep_for(std::chrono::duration<double>(settle_time_sec));
  }
  return true;
}

double computePourAngleTowardTarget(const geometry_msgs::msg::Pose& pour_pose,
                                    const geometry_msgs::msg::Pose& target_pose,
                                    const Eigen::Vector3d& horizontal_lateral_vector,
                                    double configured_angle) {
  const Eigen::Vector3d to_target(target_pose.position.x - pour_pose.position.x,
                                  target_pose.position.y - pour_pose.position.y, 0.0);
  const double lateral_component = to_target.dot(horizontal_lateral_vector);
  if (std::abs(lateral_component) < 1e-6) {
    return configured_angle;
  }

  const double angle_magnitude = std::abs(configured_angle);
  return lateral_component < 0.0 ? angle_magnitude : -angle_magnitude;
}

enum class GraspPointMode { ObjectCenter, VerticalStick, HorizontalStickEnd };

struct ObjectGraspProfile {
  std::string name;
  GraspPointMode point_mode;
  double grasp_height_offset;
  double inward_offset;
  double stick_length;
  double stick_grasp_inset;
  double stick_roll_angle;
  std::string gripper_target;
};

const char* graspPointModeName(GraspPointMode mode) {
  switch (mode) {
    case GraspPointMode::ObjectCenter:
      return "object_center";
    case GraspPointMode::VerticalStick:
      return "vertical_stick";
    case GraspPointMode::HorizontalStickEnd:
      return "horizontal_stick_end";
  }
  return "unknown";
}

geometry_msgs::msg::Pose verticalStickGraspPose(const geometry_msgs::msg::Pose& stick_pose,
                                                double grasp_height_offset) {
  geometry_msgs::msg::Pose grasp_pose = stick_pose;
  grasp_pose.position.z += grasp_height_offset;
  return grasp_pose;
}

geometry_msgs::msg::Pose stickEndGraspPose(const geometry_msgs::msg::Pose& stick_pose,
                                           const Eigen::Vector3d& horizontal_approach_vector,
                                           double stick_length, double grasp_inset) {
  const Eigen::Quaterniond stick_orientation(stick_pose.orientation.w, stick_pose.orientation.x,
                                             stick_pose.orientation.y, stick_pose.orientation.z);
  Eigen::Vector3d stick_axis = stick_orientation.normalized().toRotationMatrix().col(0);
  stick_axis.z() = 0.0;
  if (stick_axis.norm() < 1e-6) {
    stick_axis = Eigen::Vector3d::UnitX();
  } else {
    stick_axis.normalize();
  }

  const double end_distance = std::max(0.0, stick_length * 0.5 - std::max(0.0, grasp_inset));
  const double end_sign = stick_axis.dot(horizontal_approach_vector) >= 0.0 ? -1.0 : 1.0;
  const Eigen::Vector3d grasp_point =
      Eigen::Vector3d(stick_pose.position.x, stick_pose.position.y, stick_pose.position.z) +
      end_sign * end_distance * stick_axis;

  geometry_msgs::msg::Pose grasp_pose = stick_pose;
  grasp_pose.position.x = grasp_point.x();
  grasp_pose.position.y = grasp_point.y();
  grasp_pose.position.z = grasp_point.z();
  return grasp_pose;
}

geometry_msgs::msg::Pose graspPointPoseForProfile(
    const geometry_msgs::msg::Pose& object_pose, const ObjectGraspProfile& profile,
    const Eigen::Vector3d& horizontal_approach_vector) {
  switch (profile.point_mode) {
    case GraspPointMode::ObjectCenter: {
      geometry_msgs::msg::Pose grasp_pose = object_pose;
      grasp_pose.position.z += profile.grasp_height_offset;
      return grasp_pose;
    }
    case GraspPointMode::VerticalStick:
      return verticalStickGraspPose(object_pose, profile.grasp_height_offset);
    case GraspPointMode::HorizontalStickEnd:
      return stickEndGraspPose(object_pose, horizontal_approach_vector, profile.stick_length,
                               profile.stick_grasp_inset);
  }
  return object_pose;
}

struct TaskParams {
  double approach_distance;
  double gripper_center_forward_offset;
  ObjectGraspProfile cup_grasp_profile;
  ObjectGraspProfile stir_stick_grasp_profile;
  double cartesian_eef_step;
  double min_cartesian_fraction;
  double min_grasp_approach_fallback_fraction;
  bool allow_planned_grasp_approach_fallback;
  bool cartesian_avoid_collisions;
  double lift_height;
  double mixing_hover_height_offset;
  double post_pour_clearance_height_offset;
  double place_tcp_backward_offset;
  double pour_target_lateral_offset;
  std::string pour_axis;
  double pour_angle;
  double pour_hold_time;
  int pour_waypoint_count;
  double stir_hover_height_offset;
  double stir_cup_stage_x_offset;
  double stir_cup_stage_y;
  double stir_cup_stage_height_offset;
  double stir_stick_insert_hover_height_offset;
  double stir_stick_insert_depth_height_offset;
  double stir_transport_retreat_distance;
  double stir_transport_extra_height;
  std::vector<double> left_stir_entry_guide_joints;
  std::vector<double> left_stir_lift_guide_joints;
  std::vector<double> left_stir_transport_guide_joints;
  double stir_radius;
  int stir_cycles;
  int stir_waypoint_count;
  double right_mixing_pregrasp_lateral_offset;
  double pickup_cup_center_height_offset;
  double pickup_hover_height_offset;
  double pickup_transfer_lift_height;
  double pickup_transfer_x;
  double pickup_transfer_y;
  double pickup_table_size_x;
  double pickup_table_size_y;
  double pickup_table_edge_margin;
  double pickup_release_retreat_distance;
  double pickup_release_settle_time;
  double pickup_release_vertical_retreat_height;
  double dynamic_waypoint_lift;
  std::vector<double> right_pickup_transfer_guide_joints;
  std::vector<double> right_pickup_home_guide_joints;
  std::string final_gripper_target;
};

struct ArmConfig {
  std::string label;
  std::string arm_group;
  std::string gripper_group;
  std::string tcp_link;
  std::string ready_pose_name;
  std::vector<double> ready_joints;
};

struct ArmContext {
  geometry_msgs::msg::Pose cup_pose;
  geometry_msgs::msg::Pose tcp_grasp_pose;
  geometry_msgs::msg::Pose pre_grasp_pose;
  geometry_msgs::msg::Pose lift_pose;
  geometry_msgs::msg::Pose mixing_hover_pose;
  std::optional<geometry_msgs::msg::Pose> held_cup_pose;
  std::optional<Eigen::Isometry3d> tcp_to_cup_transform;
  Eigen::Vector3d horizontal_approach_vector;
  Eigen::Vector3d horizontal_lateral_vector;
  double gripper_center_forward_offset;
};

std::optional<geometry_msgs::msg::Pose> tcpPoseForCupPose(
    const ArmContext& context, const geometry_msgs::msg::Pose& desired_cup_pose) {
  if (!context.tcp_to_cup_transform.has_value()) {
    return std::nullopt;
  }
  return toPoseMsg(poseToIsometry(desired_cup_pose) *
                   context.tcp_to_cup_transform.value().inverse());
}

std::optional<geometry_msgs::msg::Pose> tcpPoseForCupPositionWithTcpOrientation(
    const ArmContext& context, const geometry_msgs::msg::Pose& desired_cup_pose,
    const geometry_msgs::msg::Quaternion& tcp_orientation) {
  if (!context.tcp_to_cup_transform.has_value()) {
    return std::nullopt;
  }

  const Eigen::Quaterniond tcp_rotation(tcp_orientation.w, tcp_orientation.x, tcp_orientation.y,
                                        tcp_orientation.z);
  const Eigen::Vector3d tcp_to_cup = context.tcp_to_cup_transform.value().translation();
  const Eigen::Vector3d desired_cup_position(
      desired_cup_pose.position.x, desired_cup_pose.position.y, desired_cup_pose.position.z);
  const Eigen::Vector3d desired_tcp_position =
      desired_cup_position - tcp_rotation.normalized().toRotationMatrix() * tcp_to_cup;

  geometry_msgs::msg::Pose tcp_pose;
  tcp_pose.position.x = desired_tcp_position.x();
  tcp_pose.position.y = desired_tcp_position.y();
  tcp_pose.position.z = desired_tcp_position.z();
  tcp_pose.orientation = tcp_orientation;
  return tcp_pose;
}

std::optional<geometry_msgs::msg::Pose> cupPoseForTcpPose(
    const ArmContext& context, const geometry_msgs::msg::Pose& tcp_pose) {
  if (!context.tcp_to_cup_transform.has_value()) {
    return std::nullopt;
  }
  return toPoseMsg(poseToIsometry(tcp_pose) * context.tcp_to_cup_transform.value());
}

void setBoundedStartState(moveit::planning_interface::MoveGroupInterface& group) {
  auto current_state = group.getCurrentState(2.0);
  if (!current_state) {
    group.setStartStateToCurrentState();
    return;
  }

  current_state->enforceBounds();
  current_state->update();
  group.setStartState(*current_state);
}

class ArmTask {
 public:
  ArmTask(const rclcpp::Node::SharedPtr& node, moveit::planning_interface::MoveGroupInterface& arm,
          moveit::planning_interface::MoveGroupInterface& gripper, ArmConfig config,
          TaskParams params)
      : node_(node),
        arm_(arm),
        gripper_(gripper),
        config_(std::move(config)),
        params_(std::move(params)) {
    arm_.setMaxVelocityScalingFactor(0.2);
    arm_.setMaxAccelerationScalingFactor(0.2);
    gripper_.setMaxVelocityScalingFactor(0.5);
    gripper_.setMaxAccelerationScalingFactor(0.5);

    if (!config_.ready_joints.empty()) {
      arm_.rememberJointValues(config_.ready_pose_name, config_.ready_joints);
    }
  }

  std::optional<ArmContext> computeContext(const geometry_msgs::msg::Pose& cup_pose,
                                           const geometry_msgs::msg::Pose& mixing_cup_pose) {
    return computeContext(cup_pose, mixing_cup_pose, params_.cup_grasp_profile);
  }

  std::optional<ArmContext> computeContext(const geometry_msgs::msg::Pose& cup_pose,
                                           const geometry_msgs::msg::Pose& mixing_cup_pose,
                                           const ObjectGraspProfile& grasp_profile) {
    auto target_state = arm_.getCurrentState(10.0);
    if (!target_state) {
      RCLCPP_ERROR(node_->get_logger(), "[%s] Failed to get current robot state",
                   config_.label.c_str());
      return std::nullopt;
    }

    if (config_.ready_joints.empty()) {
      RCLCPP_ERROR(node_->get_logger(), "[%s] Ready joints are empty", config_.label.c_str());
      return std::nullopt;
    }

    target_state->setJointGroupPositions(arm_.getName(), config_.ready_joints);
    target_state->update();

    const Eigen::Isometry3d grasp_transform =
        target_state->getGlobalLinkTransform(config_.tcp_link);
    logFingerMidpointOffset(*target_state, grasp_transform);
    const double measured_gripper_forward_offset =
        computeFingerCollisionForwardOffset(*target_state, grasp_transform)
            .value_or(params_.gripper_center_forward_offset);
    const double gripper_forward_offset =
        std::max(0.0, measured_gripper_forward_offset - grasp_profile.inward_offset);
    const Eigen::Vector3d tcp_approach_vector = grasp_transform.rotation().col(2).normalized();
    Eigen::Vector3d horizontal_approach_vector(tcp_approach_vector.x(), tcp_approach_vector.y(),
                                               0.0);
    if (horizontal_approach_vector.norm() < 1e-6) {
      RCLCPP_ERROR(node_->get_logger(),
                   "[%s] TCP approach vector cannot be projected onto the horizontal plane",
                   config_.label.c_str());
      return std::nullopt;
    }
    horizontal_approach_vector.normalize();
    const Eigen::Vector3d horizontal_lateral_vector(-horizontal_approach_vector.y(),
                                                    horizontal_approach_vector.x(), 0.0);

    const geometry_msgs::msg::Pose grasp_point_pose =
        graspPointPoseForProfile(cup_pose, grasp_profile, horizontal_approach_vector);
    geometry_msgs::msg::Pose gripper_center_grasp_pose = toPoseMsg(grasp_transform);
    gripper_center_grasp_pose.position.x = grasp_point_pose.position.x;
    gripper_center_grasp_pose.position.y = grasp_point_pose.position.y;
    gripper_center_grasp_pose.position.z = grasp_point_pose.position.z;

    geometry_msgs::msg::Pose tcp_grasp_pose = gripper_center_grasp_pose;
    tcp_grasp_pose.position.x -= horizontal_approach_vector.x() * gripper_forward_offset;
    tcp_grasp_pose.position.y -= horizontal_approach_vector.y() * gripper_forward_offset;

    geometry_msgs::msg::Pose pre_grasp_pose = tcp_grasp_pose;
    pre_grasp_pose.position.x -= horizontal_approach_vector.x() * params_.approach_distance;
    pre_grasp_pose.position.y -= horizontal_approach_vector.y() * params_.approach_distance;

    geometry_msgs::msg::Pose lift_pose = tcp_grasp_pose;
    lift_pose.position.z += params_.lift_height;

    const double side_pour_target_lateral_offset =
        config_.arm_group == "right_arm" && params_.pour_target_lateral_offset > 0.0
            ? -params_.pour_target_lateral_offset
            : params_.pour_target_lateral_offset;

    geometry_msgs::msg::Pose mixing_hover_pose = lift_pose;
    mixing_hover_pose.position.x = mixing_cup_pose.position.x +
                                   horizontal_lateral_vector.x() * side_pour_target_lateral_offset -
                                   horizontal_approach_vector.x() * gripper_forward_offset;
    mixing_hover_pose.position.y = mixing_cup_pose.position.y +
                                   horizontal_lateral_vector.y() * side_pour_target_lateral_offset -
                                   horizontal_approach_vector.y() * gripper_forward_offset;
    mixing_hover_pose.position.z = mixing_cup_pose.position.z + params_.mixing_hover_height_offset;

    RCLCPP_INFO(
        node_->get_logger(),
        "[%s/%s] object [%.3f, %.3f, %.3f], grasp point [%.3f, %.3f, %.3f] (%s), tcp grasp [%.3f, "
        "%.3f, %.3f], pre-grasp [%.3f, %.3f, %.3f], finger front %.3f m, inward %.3f m, effective "
        "%.3f m",
        config_.label.c_str(), grasp_profile.name.c_str(), cup_pose.position.x, cup_pose.position.y,
        cup_pose.position.z, grasp_point_pose.position.x, grasp_point_pose.position.y,
        grasp_point_pose.position.z, graspPointModeName(grasp_profile.point_mode),
        tcp_grasp_pose.position.x, tcp_grasp_pose.position.y, tcp_grasp_pose.position.z,
        pre_grasp_pose.position.x, pre_grasp_pose.position.y, pre_grasp_pose.position.z,
        measured_gripper_forward_offset, grasp_profile.inward_offset, gripper_forward_offset);

    ArmContext context;
    context.cup_pose = cup_pose;
    context.tcp_grasp_pose = tcp_grasp_pose;
    context.pre_grasp_pose = pre_grasp_pose;
    context.lift_pose = lift_pose;
    context.mixing_hover_pose = mixing_hover_pose;
    context.horizontal_approach_vector = horizontal_approach_vector;
    context.horizontal_lateral_vector = horizontal_lateral_vector;
    context.gripper_center_forward_offset = gripper_forward_offset;
    return context;
  }

  bool pickAndLift(const ArmContext& context, bool use_cartesian_approach = true,
                   const std::string& gripper_target_override = "") {
    RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: ready -> pre-grasp", config_.label.c_str());
    arm_.setNamedTarget(config_.ready_pose_name);
    if (!planAndExecute(arm_, "ready pose")) {
      return false;
    }

    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setPoseTarget(context.pre_grasp_pose, config_.tcp_link);
    if (!planAndExecute(arm_, "pre-grasp pose")) {
      return false;
    }
    logTcpPoseError(context.pre_grasp_pose, "pre-grasp pose");

    RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: open gripper", config_.label.c_str());
    gripper_.setNamedTarget("open");
    if (!planAndExecute(gripper_, "open gripper")) {
      return false;
    }

    RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: Cartesian approach", config_.label.c_str());
    if (use_cartesian_approach) {
      if (!executeCartesian({context.tcp_grasp_pose}, "grasp approach")) {
        return false;
      }
      logTcpPoseError(context.tcp_grasp_pose, "Cartesian grasp pose");
    } else {
      RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: planned approach to grasp pose",
                  config_.label.c_str());
      arm_.clearPoseTargets();
      setBoundedStartState(arm_);
      arm_.setPoseTarget(context.tcp_grasp_pose, config_.tcp_link);
      if (!planAndExecute(arm_, "planned grasp approach")) {
        return false;
      }
      logTcpPoseError(context.tcp_grasp_pose, "planned grasp pose");
    }

    const std::string gripper_target = gripper_target_override.empty()
                                           ? params_.cup_grasp_profile.gripper_target
                                           : gripper_target_override;
    RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: close gripper to %s", config_.label.c_str(),
                gripper_target.c_str());
    gripper_.setNamedTarget(gripper_target);
    if (!planAndExecute(gripper_, "pick gripper close")) {
      return false;
    }
    rclcpp::sleep_for(std::chrono::milliseconds(500));

    RCLCPP_INFO(node_->get_logger(), "[%s] Pick phase: lift", config_.label.c_str());
    return executeCartesian({context.lift_pose}, "lift");
  }

  bool approachGraspOnly(const ArmContext& context, bool use_cartesian_approach = false) {
    RCLCPP_INFO(node_->get_logger(), "[%s] Approach-only phase: ready -> pre-grasp",
                config_.label.c_str());
    arm_.setNamedTarget(config_.ready_pose_name);
    if (!planAndExecute(arm_, "ready pose")) {
      return false;
    }

    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setPoseTarget(context.pre_grasp_pose, config_.tcp_link);
    if (!planAndExecute(arm_, "pre-grasp pose")) {
      return false;
    }
    logTcpPoseError(context.pre_grasp_pose, "pre-grasp pose");

    RCLCPP_INFO(node_->get_logger(), "[%s] Approach-only phase: open gripper",
                config_.label.c_str());
    gripper_.setNamedTarget("open");
    if (!planAndExecute(gripper_, "open gripper")) {
      return false;
    }

    RCLCPP_INFO(node_->get_logger(),
                "[%s] Approach-only phase: move to grasp pose without closing or lifting",
                config_.label.c_str());
    if (use_cartesian_approach) {
      if (!executeCartesian({context.tcp_grasp_pose}, "grasp approach only")) {
        return false;
      }
      logTcpPoseError(context.tcp_grasp_pose, "Cartesian grasp pose");
      return true;
    }

    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setPoseTarget(context.tcp_grasp_pose, config_.tcp_link);
    if (!planAndExecute(arm_, "planned grasp approach only")) {
      return false;
    }
    logTcpPoseError(context.tcp_grasp_pose, "planned grasp pose");
    return true;
  }

  bool executeCartesianWaypoints(const std::vector<geometry_msgs::msg::Pose>& waypoints,
                                 const std::string& label) {
    return executeCartesian(waypoints, label);
  }

  bool closeGripperTo(const std::string& target, const std::string& label) {
    gripper_.setNamedTarget(target);
    return planAndExecute(gripper_, label);
  }

  bool liftOnly(const ArmContext& context) { return executeCartesian({context.lift_pose}, "lift"); }

  bool moveToReady(const std::string& label) {
    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setNamedTarget(config_.ready_pose_name);
    return planAndExecute(arm_, label);
  }

  bool moveToPose(const geometry_msgs::msg::Pose& pose, const std::string& label) {
    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setPoseTarget(pose, config_.tcp_link);
    if (!planAndExecute(arm_, label)) {
      return false;
    }
    logTcpPoseError(pose, label);
    return true;
  }

  bool moveToPoseWithFallbacks(const geometry_msgs::msg::Pose& target_pose,
                               const std::string& label,
                               const std::vector<double>& guide_joint_waypoints = {}) {
    RCLCPP_INFO(node_->get_logger(), "[%s] %s: direct target pose attempt", config_.label.c_str(),
                label.c_str());
    if (moveToPose(target_pose, label + " direct")) {
      return true;
    }

    RCLCPP_WARN(node_->get_logger(),
                "[%s] %s: direct pose failed; trying configured guide joint waypoints if available",
                config_.label.c_str(), label.c_str());

    if (!guide_joint_waypoints.empty()) {
      if (moveThroughJointValueWaypoints(guide_joint_waypoints, label + " guide") &&
          moveToPose(target_pose, label + " after guide")) {
        return true;
      }

      RCLCPP_WARN(
          node_->get_logger(),
          "[%s] %s: configured guide joint waypoints failed; trying dynamic waypoint candidates",
          config_.label.c_str(), label.c_str());
    } else {
      RCLCPP_WARN(
          node_->get_logger(),
          "[%s] %s: no configured guide joint waypoints; trying dynamic waypoint candidates",
          config_.label.c_str(), label.c_str());
    }

    const geometry_msgs::msg::Pose current_pose = currentTcpPose();
    const double safe_z =
        std::max(current_pose.position.z, target_pose.position.z) + params_.dynamic_waypoint_lift;

    std::vector<std::vector<geometry_msgs::msg::Pose>> dynamic_candidates;

    geometry_msgs::msg::Pose midpoint_pose = target_pose;
    midpoint_pose.position.x = 0.5 * (current_pose.position.x + target_pose.position.x);
    midpoint_pose.position.y = 0.5 * (current_pose.position.y + target_pose.position.y);
    midpoint_pose.position.z = safe_z;
    dynamic_candidates.push_back({midpoint_pose, target_pose});

    geometry_msgs::msg::Pose y_first_pose = target_pose;
    y_first_pose.position.x = current_pose.position.x;
    y_first_pose.position.y = target_pose.position.y;
    y_first_pose.position.z = safe_z;
    dynamic_candidates.push_back({y_first_pose, target_pose});

    geometry_msgs::msg::Pose x_first_pose = target_pose;
    x_first_pose.position.x = target_pose.position.x;
    x_first_pose.position.y = current_pose.position.y;
    x_first_pose.position.z = safe_z;
    dynamic_candidates.push_back({x_first_pose, target_pose});

    geometry_msgs::msg::Pose target_high_pose = target_pose;
    target_high_pose.position.z = safe_z;
    dynamic_candidates.push_back({target_high_pose, target_pose});

    for (size_t candidate_index = 0; candidate_index < dynamic_candidates.size();
         ++candidate_index) {
      bool candidate_ok = true;
      for (size_t waypoint_index = 0; waypoint_index < dynamic_candidates[candidate_index].size();
           ++waypoint_index) {
        const std::string waypoint_label = label + " dynamic " +
                                           std::to_string(candidate_index + 1) + "." +
                                           std::to_string(waypoint_index + 1);
        if (!moveToPose(dynamic_candidates[candidate_index][waypoint_index], waypoint_label)) {
          candidate_ok = false;
          break;
        }
      }
      if (candidate_ok) {
        return true;
      }
    }

    RCLCPP_ERROR(node_->get_logger(), "[%s] %s: all pose fallback attempts failed",
                 config_.label.c_str(), label.c_str());
    return false;
  }

  bool moveToPosition(const geometry_msgs::msg::Point& position, const std::string& label) {
    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setPositionTarget(position.x, position.y, position.z, config_.tcp_link);
    if (!planAndExecute(arm_, label)) {
      return false;
    }

    const auto actual_pose = arm_.getCurrentPose(config_.tcp_link).pose;
    const double dx = actual_pose.position.x - position.x;
    const double dy = actual_pose.position.y - position.y;
    const double dz = actual_pose.position.z - position.z;
    RCLCPP_INFO(
        node_->get_logger(),
        "[%s] %s position target [%.3f, %.3f, %.3f], actual [%.3f, %.3f, %.3f], error %.4f m",
        config_.label.c_str(), label.c_str(), position.x, position.y, position.z,
        actual_pose.position.x, actual_pose.position.y, actual_pose.position.z,
        std::sqrt(dx * dx + dy * dy + dz * dz));
    return true;
  }

  bool moveToJointValues(const std::vector<double>& joints, const std::string& label) {
    if (joints.empty()) {
      return true;
    }

    const auto joint_names = arm_.getJointNames();
    if (joints.size() != joint_names.size()) {
      RCLCPP_ERROR(node_->get_logger(), "[%s] %s has %zu joint values, but group '%s' expects %zu",
                   config_.label.c_str(), label.c_str(), joints.size(), arm_.getName().c_str(),
                   joint_names.size());
      return false;
    }

    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setJointValueTarget(joints);
    return planAndExecute(arm_, label);
  }

  bool moveThroughJointValueWaypoints(const std::vector<double>& flat_joint_waypoints,
                                      const std::string& label) {
    if (flat_joint_waypoints.empty()) {
      return true;
    }

    const auto joint_names = arm_.getJointNames();
    const size_t joint_count = joint_names.size();
    if (joint_count == 0 || flat_joint_waypoints.size() % joint_count != 0) {
      RCLCPP_ERROR(node_->get_logger(),
                   "[%s] %s has %zu values, but group '%s' expects a multiple of %zu",
                   config_.label.c_str(), label.c_str(), flat_joint_waypoints.size(),
                   arm_.getName().c_str(), joint_count);
      return false;
    }

    const size_t waypoint_count = flat_joint_waypoints.size() / joint_count;
    for (size_t i = 0; i < waypoint_count; ++i) {
      const auto begin =
          flat_joint_waypoints.begin() + static_cast<std::ptrdiff_t>(i * joint_count);
      const auto end = begin + static_cast<std::ptrdiff_t>(joint_count);
      std::vector<double> waypoint(begin, end);
      if (!moveToJointValues(waypoint, label + " " + std::to_string(i + 1))) {
        return false;
      }
    }
    return true;
  }

  geometry_msgs::msg::Pose currentTcpPose() const {
    return arm_.getCurrentPose(config_.tcp_link).pose;
  }

  size_t jointCount() const { return arm_.getJointNames().size(); }

  bool moveHomeAndClose(const std::string& label) {
    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setNamedTarget("home");
    if (!planAndExecute(arm_, label + " arm")) {
      return false;
    }

    gripper_.setNamedTarget(params_.final_gripper_target);
    return planAndExecute(gripper_, label + " gripper");
  }

  bool moveHomeViaGuideAndClose(const std::string& label,
                                const std::vector<double>& guide_joint_waypoints) {
    if (!guide_joint_waypoints.empty()) {
      RCLCPP_INFO(node_->get_logger(), "[%s] %s: trying configured home guide joint waypoints",
                  config_.label.c_str(), label.c_str());
      if (moveThroughJointValueWaypoints(guide_joint_waypoints, label + " guide") &&
          moveHomeAndClose(label)) {
        return true;
      }
      RCLCPP_WARN(node_->get_logger(), "[%s] %s: configured home guide failed; trying direct home",
                  config_.label.c_str(), label.c_str());
    }

    return moveHomeAndClose(label);
  }

  bool pourPlaceHome(const ArmContext& context, const geometry_msgs::msg::Pose& mixing_cup_pose) {
    return pourAtMixing(context, mixing_cup_pose) && clearAfterPour(context, mixing_cup_pose) &&
           placeHome(context);
  }

  bool pourAtMixing(const ArmContext& context, const geometry_msgs::msg::Pose& mixing_cup_pose) {
    RCLCPP_INFO(node_->get_logger(), "[%s] Pour phase: move to mixing hover",
                config_.label.c_str());
    geometry_msgs::msg::Pose lift_clearance_pose = context.lift_pose;
    lift_clearance_pose.position.z = context.mixing_hover_pose.position.z;
    if (!executeCartesian({lift_clearance_pose, context.mixing_hover_pose}, "mixing hover")) {
      return false;
    }

    RCLCPP_INFO(node_->get_logger(), "[%s] Pour phase: tilt", config_.label.c_str());
    const double dynamic_pour_angle =
        computePourAngleTowardTarget(context.mixing_hover_pose, mixing_cup_pose,
                                     context.horizontal_lateral_vector, params_.pour_angle);
    RCLCPP_INFO(node_->get_logger(), "[%s] Dynamic pour angle: %.3f rad", config_.label.c_str(),
                dynamic_pour_angle);
    std::vector<geometry_msgs::msg::Pose> pour_waypoints;
    for (int i = 1; i <= params_.pour_waypoint_count; ++i) {
      const double ratio =
          static_cast<double>(i) / static_cast<double>(params_.pour_waypoint_count);
      pour_waypoints.push_back(rotatePoseLocal(context.mixing_hover_pose, params_.pour_axis,
                                               dynamic_pour_angle * ratio));
    }
    if (!executeCartesian(pour_waypoints, "pour tilt")) {
      return false;
    }
    rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(params_.pour_hold_time)));

    RCLCPP_INFO(node_->get_logger(), "[%s] Pour phase: upright", config_.label.c_str());
    std::vector<geometry_msgs::msg::Pose> upright_waypoints;
    for (int i = params_.pour_waypoint_count - 1; i >= 0; --i) {
      const double ratio =
          static_cast<double>(i) / static_cast<double>(params_.pour_waypoint_count);
      upright_waypoints.push_back(rotatePoseLocal(context.mixing_hover_pose, params_.pour_axis,
                                                  dynamic_pour_angle * ratio));
    }
    if (!executeCartesian(upright_waypoints, "wrist upright")) {
      return false;
    }

    return true;
  }

  bool clearAfterPour(const ArmContext& context, const geometry_msgs::msg::Pose& mixing_cup_pose) {
    RCLCPP_INFO(node_->get_logger(), "[%s] Place phase: return above original place",
                config_.label.c_str());
    const geometry_msgs::msg::Pose corrected_lift_pose = correctedLiftPose(context);

    geometry_msgs::msg::Pose post_pour_clearance_pose = context.mixing_hover_pose;
    post_pour_clearance_pose.position.z =
        mixing_cup_pose.position.z + params_.post_pour_clearance_height_offset;
    geometry_msgs::msg::Pose return_clearance_pose = corrected_lift_pose;
    return_clearance_pose.position.z = post_pour_clearance_pose.position.z;
    if (!executeCartesian({post_pour_clearance_pose, return_clearance_pose, corrected_lift_pose},
                          "return hover")) {
      return false;
    }

    return true;
  }

  bool placeHome(const ArmContext& context) {
    RCLCPP_INFO(node_->get_logger(), "[%s] Place phase: lower and release", config_.label.c_str());
    const geometry_msgs::msg::Pose corrected_place_pose = correctedPlacePose(context);
    if (!executeCartesian({corrected_place_pose}, "place lower")) {
      return false;
    }

    gripper_.setNamedTarget("open");
    if (!planAndExecute(gripper_, "release gripper")) {
      return false;
    }

    RCLCPP_INFO(node_->get_logger(), "[%s] Place phase: retreat and home", config_.label.c_str());
    if (!executeCartesian({context.pre_grasp_pose}, "retreat")) {
      return false;
    }

    arm_.clearPoseTargets();
    setBoundedStartState(arm_);
    arm_.setNamedTarget("home");
    if (!planAndExecute(arm_, "home")) {
      return false;
    }

    gripper_.setNamedTarget(params_.final_gripper_target);
    return planAndExecute(gripper_, "final gripper close");
  }

 private:
  void logTcpPoseError(const geometry_msgs::msg::Pose& target_pose, const std::string& label) {
    const geometry_msgs::msg::PoseStamped actual_pose = arm_.getCurrentPose(config_.tcp_link);
    const double dx = actual_pose.pose.position.x - target_pose.position.x;
    const double dy = actual_pose.pose.position.y - target_pose.position.y;
    const double dz = actual_pose.pose.position.z - target_pose.position.z;
    const double position_error = std::sqrt(dx * dx + dy * dy + dz * dz);
    RCLCPP_INFO(node_->get_logger(),
                "[%s] %s target [%.3f, %.3f, %.3f], actual [%.3f, %.3f, %.3f], error %.4f m",
                config_.label.c_str(), label.c_str(), target_pose.position.x,
                target_pose.position.y, target_pose.position.z, actual_pose.pose.position.x,
                actual_pose.pose.position.y, actual_pose.pose.position.z, position_error);
  }

  geometry_msgs::msg::Pose correctedPlacePose(const ArmContext& context) const {
    geometry_msgs::msg::Pose corrected_place_pose =
        tcpPoseForCupPose(context, context.cup_pose).value_or(context.tcp_grasp_pose);
    corrected_place_pose.position.x -=
        context.horizontal_approach_vector.x() * params_.place_tcp_backward_offset;
    corrected_place_pose.position.y -=
        context.horizontal_approach_vector.y() * params_.place_tcp_backward_offset;
    return corrected_place_pose;
  }

  geometry_msgs::msg::Pose correctedLiftPose(const ArmContext& context) const {
    geometry_msgs::msg::Pose lifted_cup_pose = context.cup_pose;
    lifted_cup_pose.position.z += params_.lift_height;
    geometry_msgs::msg::Pose corrected_lift_pose =
        tcpPoseForCupPose(context, lifted_cup_pose).value_or(correctedPlacePose(context));
    if (!context.tcp_to_cup_transform.has_value()) {
      corrected_lift_pose.position.z += params_.lift_height;
    }
    return corrected_lift_pose;
  }

  bool planAndExecute(moveit::planning_interface::MoveGroupInterface& group,
                      const std::string& label) {
    constexpr int max_attempts = 2;
    for (int attempt = 1; attempt <= max_attempts; ++attempt) {
      moveit::planning_interface::MoveGroupInterface::Plan plan;
      if (group.plan(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
        RCLCPP_ERROR(node_->get_logger(), "[%s] Failed to plan %s%s", config_.label.c_str(),
                     label.c_str(),
                     attempt < max_attempts ? "; retrying from refreshed state" : "");
        if (attempt < max_attempts) {
          rclcpp::sleep_for(std::chrono::milliseconds(300));
          setBoundedStartState(group);
          continue;
        }
        return false;
      }
      if (group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
        return true;
      }

      RCLCPP_ERROR(node_->get_logger(), "[%s] Failed to execute %s%s", config_.label.c_str(),
                   label.c_str(), attempt < max_attempts ? "; retrying from refreshed state" : "");
      if (attempt < max_attempts) {
        rclcpp::sleep_for(std::chrono::milliseconds(500));
        setBoundedStartState(group);
      }
    }
    return false;
  }

  bool executeCartesian(const std::vector<geometry_msgs::msg::Pose>& waypoints,
                        const std::string& label) {
    arm_.clearPoseTargets();
    setBoundedStartState(arm_);

    moveit_msgs::msg::RobotTrajectory trajectory;
    const double fraction = arm_.computeCartesianPath(
        waypoints, params_.cartesian_eef_step, trajectory, params_.cartesian_avoid_collisions);

    RCLCPP_INFO(node_->get_logger(), "[%s] %s Cartesian path fraction: %.3f", config_.label.c_str(),
                label.c_str(), fraction);

    if (fraction < params_.min_cartesian_fraction) {
      RCLCPP_ERROR(node_->get_logger(),
                   "[%s] %s Cartesian path fraction %.3f is below required %.3f",
                   config_.label.c_str(), label.c_str(), fraction, params_.min_cartesian_fraction);
      return false;
    }

    moveit::planning_interface::MoveGroupInterface::Plan plan;
    plan.trajectory = trajectory;
    if (arm_.execute(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(node_->get_logger(), "[%s] Failed to execute %s Cartesian path",
                   config_.label.c_str(), label.c_str());
      return false;
    }
    return true;
  }

  rclcpp::Node::SharedPtr node_;
  moveit::planning_interface::MoveGroupInterface& arm_;
  moveit::planning_interface::MoveGroupInterface& gripper_;
  ArmConfig config_;
  TaskParams params_;

  void logFingerMidpointOffset(const moveit::core::RobotState& state,
                               const Eigen::Isometry3d& tcp_transform) const {
    const std::string suffix = "hand_tcp";
    if (config_.tcp_link.size() < suffix.size() ||
        config_.tcp_link.compare(config_.tcp_link.size() - suffix.size(), suffix.size(), suffix) !=
            0) {
      return;
    }

    const std::string prefix = config_.tcp_link.substr(0, config_.tcp_link.size() - suffix.size());
    const std::string left_finger_link = prefix + "left_finger";
    const std::string right_finger_link = prefix + "right_finger";
    const auto robot_model = state.getRobotModel();
    if (robot_model->getLinkModel(left_finger_link) == nullptr ||
        robot_model->getLinkModel(right_finger_link) == nullptr) {
      RCLCPP_WARN(node_->get_logger(), "[%s] Cannot find finger links '%s' and '%s' in robot model",
                  config_.label.c_str(), left_finger_link.c_str(), right_finger_link.c_str());
      return;
    }

    const Eigen::Vector3d midpoint =
        0.5 * (state.getGlobalLinkTransform(left_finger_link).translation() +
               state.getGlobalLinkTransform(right_finger_link).translation());
    const Eigen::Vector3d tcp_to_midpoint_local =
        tcp_transform.rotation().transpose() * (midpoint - tcp_transform.translation());
    RCLCPP_INFO(node_->get_logger(),
                "[%s] TCP -> finger-link midpoint in TCP frame: [%.3f, %.3f, %.3f] m",
                config_.label.c_str(), tcp_to_midpoint_local.x(), tcp_to_midpoint_local.y(),
                tcp_to_midpoint_local.z());
  }

  std::optional<double> computeFingerCollisionForwardOffset(
      const moveit::core::RobotState& state, const Eigen::Isometry3d& tcp_transform) const {
    const std::string suffix = "hand_tcp";
    if (config_.tcp_link.size() < suffix.size() ||
        config_.tcp_link.compare(config_.tcp_link.size() - suffix.size(), suffix.size(), suffix) !=
            0) {
      return std::nullopt;
    }

    const std::string prefix = config_.tcp_link.substr(0, config_.tcp_link.size() - suffix.size());
    const std::array<std::string, 2> finger_links{prefix + "left_finger", prefix + "right_finger"};

    const auto robot_model = state.getRobotModel();
    double max_forward = -std::numeric_limits<double>::infinity();
    bool found_collision_vertex = false;

    for (const auto& finger_link : finger_links) {
      const auto* link_model = robot_model->getLinkModel(finger_link);
      if (link_model == nullptr) {
        return std::nullopt;
      }

      const Eigen::Isometry3d link_transform = state.getGlobalLinkTransform(finger_link);
      const auto& shapes = link_model->getShapes();
      const auto& collision_origins = link_model->getCollisionOriginTransforms();
      for (std::size_t i = 0; i < shapes.size() && i < collision_origins.size(); ++i) {
        if (shapes[i]->type != shapes::MESH) {
          continue;
        }
        const auto* mesh = static_cast<const shapes::Mesh*>(shapes[i].get());
        const Eigen::Isometry3d shape_transform = link_transform * collision_origins[i];
        for (unsigned int vertex_index = 0; vertex_index < mesh->vertex_count; ++vertex_index) {
          const Eigen::Vector3d vertex(mesh->vertices[3 * vertex_index],
                                       mesh->vertices[3 * vertex_index + 1],
                                       mesh->vertices[3 * vertex_index + 2]);
          const Eigen::Vector3d vertex_in_tcp =
              tcp_transform.rotation().transpose() *
              (shape_transform * vertex - tcp_transform.translation());
          max_forward = std::max(max_forward, vertex_in_tcp.z());
          found_collision_vertex = true;
        }
      }
    }

    if (!found_collision_vertex) {
      return std::nullopt;
    }

    RCLCPP_INFO(node_->get_logger(), "[%s] TCP -> finger collision front along TCP +Z: %.3f m",
                config_.label.c_str(), max_forward);
    return max_forward;
  }
};

double durationSeconds(const builtin_interfaces::msg::Duration& duration) {
  return static_cast<double>(duration.sec) + static_cast<double>(duration.nanosec) * 1e-9;
}

builtin_interfaces::msg::Duration durationFromSeconds(double seconds) {
  builtin_interfaces::msg::Duration duration;
  duration.sec = static_cast<int32_t>(std::floor(seconds));
  duration.nanosec =
      static_cast<uint32_t>(std::round((seconds - static_cast<double>(duration.sec)) * 1e9));
  if (duration.nanosec >= 1000000000U) {
    ++duration.sec;
    duration.nanosec -= 1000000000U;
  }
  return duration;
}

bool planGroup(const rclcpp::Node::SharedPtr& node,
               moveit::planning_interface::MoveGroupInterface& group, const std::string& label,
               moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  if (group.plan(plan) != moveit::core::MoveItErrorCode::SUCCESS) {
    RCLCPP_ERROR(node->get_logger(), "Failed to plan %s", label.c_str());
    return false;
  }
  return true;
}

bool executeGroupPlan(const rclcpp::Node::SharedPtr& node,
                      moveit::planning_interface::MoveGroupInterface& group,
                      const std::string& label,
                      const moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  if (group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
    return true;
  }

  RCLCPP_ERROR(node->get_logger(), "Failed to execute %s; retrying from refreshed state",
               label.c_str());
  rclcpp::sleep_for(std::chrono::milliseconds(500));
  setBoundedStartState(group);

  moveit::planning_interface::MoveGroupInterface::Plan retry_plan;
  if (group.plan(retry_plan) != moveit::core::MoveItErrorCode::SUCCESS) {
    RCLCPP_ERROR(node->get_logger(), "Failed to replan %s after execution abort", label.c_str());
    return false;
  }
  if (group.execute(retry_plan) != moveit::core::MoveItErrorCode::SUCCESS) {
    RCLCPP_ERROR(node->get_logger(), "Failed to execute %s after retry", label.c_str());
    return false;
  }
  return true;
}

std::vector<double> interpolateJointValues(
    const trajectory_msgs::msg::JointTrajectory& trajectory, double sample_time,
    const std::vector<double> trajectory_msgs::msg::JointTrajectoryPoint::*field) {
  if (trajectory.points.empty()) {
    return {};
  }

  const auto& first_point = trajectory.points.front();
  const auto& first_values = first_point.*field;
  if (trajectory.points.size() == 1 || first_values.empty() ||
      sample_time <= durationSeconds(first_point.time_from_start)) {
    return first_values;
  }

  for (size_t i = 1; i < trajectory.points.size(); ++i) {
    const auto& previous_point = trajectory.points[i - 1];
    const auto& next_point = trajectory.points[i];
    const auto& previous_values = previous_point.*field;
    const auto& next_values = next_point.*field;
    if (previous_values.empty() || next_values.empty() ||
        previous_values.size() != next_values.size()) {
      return {};
    }

    const double previous_time = durationSeconds(previous_point.time_from_start);
    const double next_time = durationSeconds(next_point.time_from_start);
    if (sample_time > next_time) {
      continue;
    }
    if (next_time <= previous_time + 1e-9) {
      return next_values;
    }

    const double ratio =
        std::clamp((sample_time - previous_time) / (next_time - previous_time), 0.0, 1.0);
    std::vector<double> values;
    values.reserve(next_values.size());
    for (size_t value_index = 0; value_index < next_values.size(); ++value_index) {
      values.push_back(previous_values[value_index] +
                       (next_values[value_index] - previous_values[value_index]) * ratio);
    }
    return values;
  }

  return trajectory.points.back().*field;
}

void appendIfAvailable(std::vector<double>& destination, const std::vector<double>& values) {
  if (!values.empty()) {
    destination.insert(destination.end(), values.begin(), values.end());
  }
}

bool mergeJointTrajectories(const trajectory_msgs::msg::JointTrajectory& left,
                            const trajectory_msgs::msg::JointTrajectory& right,
                            const std::string& label, moveit_msgs::msg::RobotTrajectory& merged) {
  if (left.points.empty() || right.points.empty()) {
    return false;
  }

  auto& output = merged.joint_trajectory;
  output.header = left.header;
  output.joint_names.clear();
  output.joint_names.insert(output.joint_names.end(), left.joint_names.begin(),
                            left.joint_names.end());
  output.joint_names.insert(output.joint_names.end(), right.joint_names.begin(),
                            right.joint_names.end());
  output.points.clear();

  const size_t point_count = std::max(left.points.size(), right.points.size());
  const double left_duration = durationSeconds(left.points.back().time_from_start);
  const double right_duration = durationSeconds(right.points.back().time_from_start);
  const double merged_duration =
      std::max(std::max(left_duration, right_duration), 0.05 * static_cast<double>(point_count));
  const bool merge_velocities =
      !left.points.front().velocities.empty() && !right.points.front().velocities.empty();
  const bool merge_accelerations =
      !left.points.front().accelerations.empty() && !right.points.front().accelerations.empty();

  for (size_t i = 0; i <= point_count; ++i) {
    const double time_ratio =
        point_count == 0 ? 1.0 : static_cast<double>(i) / static_cast<double>(point_count);
    const double merged_time = merged_duration * time_ratio;
    const double left_time = std::min(left_duration, merged_time);
    const double right_time = std::min(right_duration, merged_time);

    trajectory_msgs::msg::JointTrajectoryPoint point;
    appendIfAvailable(point.positions,
                      interpolateJointValues(
                          left, left_time, &trajectory_msgs::msg::JointTrajectoryPoint::positions));
    appendIfAvailable(point.positions, interpolateJointValues(
                                           right, right_time,
                                           &trajectory_msgs::msg::JointTrajectoryPoint::positions));

    if (merge_velocities) {
      appendIfAvailable(
          point.velocities,
          interpolateJointValues(left, left_time,
                                 &trajectory_msgs::msg::JointTrajectoryPoint::velocities));
      appendIfAvailable(
          point.velocities,
          interpolateJointValues(right, right_time,
                                 &trajectory_msgs::msg::JointTrajectoryPoint::velocities));
    }
    if (merge_accelerations) {
      appendIfAvailable(
          point.accelerations,
          interpolateJointValues(left, left_time,
                                 &trajectory_msgs::msg::JointTrajectoryPoint::accelerations));
      appendIfAvailable(
          point.accelerations,
          interpolateJointValues(right, right_time,
                                 &trajectory_msgs::msg::JointTrajectoryPoint::accelerations));
    }

    if (point.positions.size() != output.joint_names.size()) {
      return false;
    }
    if (!point.velocities.empty() && point.velocities.size() != output.joint_names.size()) {
      point.velocities.clear();
    }
    if (!point.accelerations.empty() && point.accelerations.size() != output.joint_names.size()) {
      point.accelerations.clear();
    }

    point.time_from_start = durationFromSeconds(merged_time);
    output.points.push_back(point);
  }

  if (!output.points.empty()) {
    output.points.back().time_from_start = durationFromSeconds(merged_duration);
  }

  (void)label;
  return true;
}

bool executeMergedPlan(const rclcpp::Node::SharedPtr& node,
                       moveit::planning_interface::MoveGroupInterface& both_arms,
                       const std::string& label,
                       const moveit::planning_interface::MoveGroupInterface::Plan& left_plan,
                       const moveit::planning_interface::MoveGroupInterface::Plan& right_plan) {
  moveit::planning_interface::MoveGroupInterface::Plan merged_plan;
  if (!mergeJointTrajectories(left_plan.trajectory.joint_trajectory,
                              right_plan.trajectory.joint_trajectory, label,
                              merged_plan.trajectory)) {
    RCLCPP_ERROR(node->get_logger(), "Failed to merge trajectories for %s", label.c_str());
    return false;
  }
  return executeGroupPlan(node, both_arms, label, merged_plan);
}

bool planSingleArmPose(const rclcpp::Node::SharedPtr& node,
                       moveit::planning_interface::MoveGroupInterface& arm,
                       const geometry_msgs::msg::Pose& pose, const std::string& tcp_link,
                       const std::string& label,
                       moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(pose, tcp_link);
  return planGroup(node, arm, label, plan);
}

bool planSingleArmJointValues(const rclcpp::Node::SharedPtr& node,
                              moveit::planning_interface::MoveGroupInterface& arm,
                              const std::vector<double>& joints, const std::string& label,
                              moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  const auto joint_names = arm.getJointNames();
  if (joints.size() != joint_names.size()) {
    RCLCPP_ERROR(node->get_logger(), "%s has %zu joint values, but group '%s' expects %zu",
                 label.c_str(), joints.size(), arm.getName().c_str(), joint_names.size());
    return false;
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setJointValueTarget(joints);
  return planGroup(node, arm, label, plan);
}

bool computeSingleArmCartesian(const rclcpp::Node::SharedPtr& node,
                               moveit::planning_interface::MoveGroupInterface& arm,
                               const TaskParams& params,
                               const std::vector<geometry_msgs::msg::Pose>& waypoints,
                               const std::string& label,
                               moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  arm.clearPoseTargets();
  setBoundedStartState(arm);

  const double fraction = arm.computeCartesianPath(
      waypoints, params.cartesian_eef_step, plan.trajectory, params.cartesian_avoid_collisions);

  RCLCPP_INFO(node->get_logger(), "%s Cartesian path fraction: %.3f", label.c_str(), fraction);
  if (fraction < params.min_cartesian_fraction) {
    RCLCPP_ERROR(node->get_logger(), "%s Cartesian path fraction %.3f is below required %.3f",
                 label.c_str(), fraction, params.min_cartesian_fraction);
    return false;
  }
  return true;
}

void logPlannedFinalTcpPose(const rclcpp::Node::SharedPtr& node,
                            moveit::planning_interface::MoveGroupInterface& arm,
                            const moveit::planning_interface::MoveGroupInterface::Plan& plan,
                            const std::string& tcp_link,
                            const geometry_msgs::msg::Pose& target_pose, const std::string& label) {
  const auto& trajectory = plan.trajectory.joint_trajectory;
  if (trajectory.points.empty()) {
    RCLCPP_WARN(node->get_logger(), "%s has no trajectory points for FK check", label.c_str());
    return;
  }
  const auto& final_point = trajectory.points.back();
  if (final_point.positions.size() != trajectory.joint_names.size()) {
    RCLCPP_WARN(node->get_logger(),
                "%s final point has %zu positions for %zu joints; skipping FK check", label.c_str(),
                final_point.positions.size(), trajectory.joint_names.size());
    return;
  }

  auto planned_state = arm.getCurrentState(2.0);
  if (!planned_state) {
    RCLCPP_WARN(node->get_logger(), "%s could not read current state for FK check", label.c_str());
    return;
  }

  planned_state->setVariablePositions(trajectory.joint_names, final_point.positions);
  planned_state->update();
  const geometry_msgs::msg::Pose planned_pose =
      toPoseMsg(planned_state->getGlobalLinkTransform(tcp_link));

  RCLCPP_INFO(node->get_logger(),
              "%s planned final TCP [%.3f, %.3f, %.3f], target [%.3f, %.3f, %.3f], error [%.3f, "
              "%.3f, %.3f]",
              label.c_str(), planned_pose.position.x, planned_pose.position.y,
              planned_pose.position.z, target_pose.position.x, target_pose.position.y,
              target_pose.position.z, planned_pose.position.x - target_pose.position.x,
              planned_pose.position.y - target_pose.position.y,
              planned_pose.position.z - target_pose.position.z);
}

bool computeSingleArmGraspApproach(const rclcpp::Node::SharedPtr& node,
                                   moveit::planning_interface::MoveGroupInterface& arm,
                                   const TaskParams& params,
                                   const geometry_msgs::msg::Pose& grasp_pose,
                                   const std::string& tcp_link, const std::string& label,
                                   moveit::planning_interface::MoveGroupInterface::Plan& plan) {
  arm.clearPoseTargets();
  setBoundedStartState(arm);

  const double fraction = arm.computeCartesianPath(
      {grasp_pose}, params.cartesian_eef_step, plan.trajectory, params.cartesian_avoid_collisions);

  RCLCPP_INFO(node->get_logger(), "%s Cartesian path fraction: %.3f", label.c_str(), fraction);
  if (fraction >= params.min_cartesian_fraction) {
    return true;
  }

  if (!params.allow_planned_grasp_approach_fallback ||
      fraction < params.min_grasp_approach_fallback_fraction) {
    RCLCPP_ERROR(node->get_logger(), "%s Cartesian path fraction %.3f is below required %.3f",
                 label.c_str(), fraction, params.min_cartesian_fraction);
    return false;
  }

  RCLCPP_WARN(
      node->get_logger(),
      "%s Cartesian fraction %.3f is below %.3f; using MoveIt planned grasp approach fallback",
      label.c_str(), fraction, params.min_cartesian_fraction);
  return planSingleArmPose(node, arm, grasp_pose, tcp_link, label + " planned fallback", plan);
}

void logPoseDelta(const rclcpp::Node::SharedPtr& node,
                  moveit::planning_interface::MoveGroupInterface& arm, const std::string& tcp_link,
                  const geometry_msgs::msg::Pose& target_pose, const std::string& label) {
  const auto current_pose = arm.getCurrentPose(tcp_link).pose;
  RCLCPP_INFO(node->get_logger(),
              "%s target [%.3f, %.3f, %.3f], actual [%.3f, %.3f, %.3f], error [%.3f, %.3f, %.3f]",
              label.c_str(), target_pose.position.x, target_pose.position.y, target_pose.position.z,
              current_pose.position.x, current_pose.position.y, current_pose.position.z,
              current_pose.position.x - target_pose.position.x,
              current_pose.position.y - target_pose.position.y,
              current_pose.position.z - target_pose.position.z);
}

bool executeDualGripperTarget(const rclcpp::Node::SharedPtr& node,
                              moveit::planning_interface::MoveGroupInterface& left_gripper,
                              moveit::planning_interface::MoveGroupInterface& right_gripper,
                              const std::string& target, const std::string& label) {
  auto execute_one = [&](moveit::planning_interface::MoveGroupInterface& gripper,
                         const std::string& side_label) {
    gripper.setNamedTarget(target);
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    if (!planGroup(node, gripper, side_label, plan)) {
      return false;
    }
    return executeGroupPlan(node, gripper, side_label, plan);
  };

  auto left_future = std::async(
      std::launch::async, [&]() { return execute_one(left_gripper, label + " left gripper"); });
  auto right_future = std::async(
      std::launch::async, [&]() { return execute_one(right_gripper, label + " right gripper"); });
  const bool left_ok = left_future.get();
  const bool right_ok = right_future.get();
  return left_ok && right_ok;
}

bool executeSingleGripperTarget(const rclcpp::Node::SharedPtr& node,
                                moveit::planning_interface::MoveGroupInterface& gripper,
                                const std::string& target, const std::string& label) {
  gripper.setNamedTarget(target);
  moveit::planning_interface::MoveGroupInterface::Plan plan;
  if (!planGroup(node, gripper, label, plan)) {
    return false;
  }
  return executeGroupPlan(node, gripper, label, plan);
}

geometry_msgs::msg::Pose correctedPlacePose(const ArmContext& context, const TaskParams& params) {
  geometry_msgs::msg::Pose corrected_place_pose =
      tcpPoseForCupPose(context, context.cup_pose).value_or(context.tcp_grasp_pose);
  corrected_place_pose.position.x -=
      context.horizontal_approach_vector.x() * params.place_tcp_backward_offset;
  corrected_place_pose.position.y -=
      context.horizontal_approach_vector.y() * params.place_tcp_backward_offset;
  return corrected_place_pose;
}

geometry_msgs::msg::Pose correctedLiftPose(const ArmContext& context, const TaskParams& params) {
  geometry_msgs::msg::Pose lifted_cup_pose = context.cup_pose;
  lifted_cup_pose.position.z += params.lift_height;
  geometry_msgs::msg::Pose corrected_lift_pose =
      tcpPoseForCupPose(context, lifted_cup_pose).value_or(correctedPlacePose(context, params));
  if (!context.tcp_to_cup_transform.has_value()) {
    corrected_lift_pose.position.z += params.lift_height;
  }
  return corrected_lift_pose;
}

void rotateContextLocal(ArmContext& context, const std::string& axis, double angle_rad) {
  context.tcp_grasp_pose = rotatePoseLocal(context.tcp_grasp_pose, axis, angle_rad);
  context.pre_grasp_pose = rotatePoseLocal(context.pre_grasp_pose, axis, angle_rad);
  context.lift_pose = rotatePoseLocal(context.lift_pose, axis, angle_rad);
  context.mixing_hover_pose = rotatePoseLocal(context.mixing_hover_pose, axis, angle_rad);
}

void seedIdealHeldCupTransform(ArmContext& context) {
  context.held_cup_pose = context.cup_pose;
  context.tcp_to_cup_transform =
      poseToIsometry(context.tcp_grasp_pose).inverse() * poseToIsometry(context.cup_pose);
}

geometry_msgs::msg::Pose poseWithAxes(const geometry_msgs::msg::Pose& pose, Eigen::Vector3d x_axis,
                                      Eigen::Vector3d z_axis) {
  if (x_axis.norm() < 1e-6) {
    x_axis = Eigen::Vector3d::UnitX();
  }
  if (z_axis.norm() < 1e-6) {
    z_axis = Eigen::Vector3d::UnitZ();
  }
  x_axis.normalize();
  z_axis.normalize();

  Eigen::Vector3d y_axis = z_axis.cross(x_axis);
  if (y_axis.norm() < 1e-6) {
    y_axis = std::abs(z_axis.dot(Eigen::Vector3d::UnitX())) < 0.9
                 ? z_axis.cross(Eigen::Vector3d::UnitX())
                 : z_axis.cross(Eigen::Vector3d::UnitY());
  }
  y_axis.normalize();
  x_axis = y_axis.cross(z_axis).normalized();

  Eigen::Matrix3d rotation;
  rotation.col(0) = x_axis;
  rotation.col(1) = y_axis;
  rotation.col(2) = z_axis;

  const Eigen::Quaterniond orientation(rotation);
  geometry_msgs::msg::Pose oriented_pose = pose;
  oriented_pose.orientation.x = orientation.x();
  oriented_pose.orientation.y = orientation.y();
  oriented_pose.orientation.z = orientation.z();
  oriented_pose.orientation.w = orientation.w();
  return oriented_pose;
}

geometry_msgs::msg::Pose poseWithZAxisClosestToCurrent(const geometry_msgs::msg::Pose& pose,
                                                       Eigen::Vector3d z_axis) {
  if (z_axis.norm() < 1e-6) {
    z_axis = Eigen::Vector3d::UnitZ();
  }
  z_axis.normalize();

  const Eigen::Quaterniond current_orientation(pose.orientation.w, pose.orientation.x,
                                               pose.orientation.y, pose.orientation.z);
  Eigen::Vector3d x_axis = current_orientation.normalized().toRotationMatrix().col(0);
  x_axis -= x_axis.dot(z_axis) * z_axis;
  if (x_axis.norm() < 1e-6) {
    x_axis = std::abs(z_axis.dot(Eigen::Vector3d::UnitX())) < 0.9 ? Eigen::Vector3d::UnitX()
                                                                  : Eigen::Vector3d::UnitY();
  }

  return poseWithAxes(pose, x_axis, z_axis);
}

std::vector<geometry_msgs::msg::Pose> pourTiltWaypoints(
    const ArmContext& context, const geometry_msgs::msg::Pose& mixing_cup_pose,
    const TaskParams& params) {
  const double dynamic_pour_angle =
      computePourAngleTowardTarget(context.mixing_hover_pose, mixing_cup_pose,
                                   context.horizontal_lateral_vector, params.pour_angle);

  std::vector<geometry_msgs::msg::Pose> waypoints;
  for (int i = 1; i <= params.pour_waypoint_count; ++i) {
    const double ratio = static_cast<double>(i) / static_cast<double>(params.pour_waypoint_count);
    waypoints.push_back(
        rotatePoseLocal(context.mixing_hover_pose, params.pour_axis, dynamic_pour_angle * ratio));
  }
  return waypoints;
}

std::vector<geometry_msgs::msg::Pose> pourUprightWaypoints(
    const ArmContext& context, const geometry_msgs::msg::Pose& mixing_cup_pose,
    const TaskParams& params) {
  const double dynamic_pour_angle =
      computePourAngleTowardTarget(context.mixing_hover_pose, mixing_cup_pose,
                                   context.horizontal_lateral_vector, params.pour_angle);

  std::vector<geometry_msgs::msg::Pose> waypoints;
  for (int i = params.pour_waypoint_count - 1; i >= 0; --i) {
    const double ratio = static_cast<double>(i) / static_cast<double>(params.pour_waypoint_count);
    waypoints.push_back(
        rotatePoseLocal(context.mixing_hover_pose, params.pour_axis, dynamic_pour_angle * ratio));
  }
  return waypoints;
}

std::vector<geometry_msgs::msg::Pose> stirWaypoints(
    const geometry_msgs::msg::Pose& stir_center_pose, const TaskParams& params) {
  std::vector<geometry_msgs::msg::Pose> waypoints;
  const int waypoint_count = std::max(4, params.stir_waypoint_count);
  const int cycles = std::max(1, params.stir_cycles);
  waypoints.reserve(static_cast<size_t>(waypoint_count * cycles + 1));

  geometry_msgs::msg::Pose start_pose = stir_center_pose;
  start_pose.position.x += params.stir_radius;
  waypoints.push_back(start_pose);

  for (int cycle = 0; cycle < cycles; ++cycle) {
    for (int i = 1; i <= waypoint_count; ++i) {
      const double theta =
          2.0 * std::acos(-1.0) * static_cast<double>(i) / static_cast<double>(waypoint_count);
      geometry_msgs::msg::Pose waypoint = stir_center_pose;
      waypoint.position.x += params.stir_radius * std::cos(theta);
      waypoint.position.y += params.stir_radius * std::sin(theta);
      waypoints.push_back(waypoint);
    }
  }

  return waypoints;
}

std::vector<double> reversedFlatJointWaypoints(const std::vector<double>& flat_joint_waypoints,
                                               size_t joint_count) {
  std::vector<double> reversed;
  if (joint_count == 0 || flat_joint_waypoints.empty() ||
      flat_joint_waypoints.size() % joint_count != 0) {
    return reversed;
  }

  const size_t waypoint_count = flat_joint_waypoints.size() / joint_count;
  reversed.reserve(flat_joint_waypoints.size());
  for (size_t waypoint_index = waypoint_count; waypoint_index > 0; --waypoint_index) {
    const auto begin = flat_joint_waypoints.begin() +
                       static_cast<std::ptrdiff_t>((waypoint_index - 1) * joint_count);
    const auto end = begin + static_cast<std::ptrdiff_t>(joint_count);
    reversed.insert(reversed.end(), begin, end);
  }
  return reversed;
}

std::vector<geometry_msgs::msg::Pose> linearPoseWaypoints(
    const geometry_msgs::msg::Pose& start_pose, const geometry_msgs::msg::Pose& end_pose,
    double max_segment_length) {
  const Eigen::Vector3d start_position(start_pose.position.x, start_pose.position.y,
                                       start_pose.position.z);
  const Eigen::Vector3d end_position(end_pose.position.x, end_pose.position.y, end_pose.position.z);
  const double distance = (end_position - start_position).norm();
  const int segment_count =
      std::max(1, static_cast<int>(std::ceil(distance / std::max(max_segment_length, 1e-3))));

  const Eigen::Quaterniond start_orientation(start_pose.orientation.w, start_pose.orientation.x,
                                             start_pose.orientation.y, start_pose.orientation.z);
  const Eigen::Quaterniond end_orientation(end_pose.orientation.w, end_pose.orientation.x,
                                           end_pose.orientation.y, end_pose.orientation.z);

  std::vector<geometry_msgs::msg::Pose> waypoints;
  waypoints.reserve(static_cast<size_t>(segment_count));
  for (int i = 1; i <= segment_count; ++i) {
    const double ratio = static_cast<double>(i) / static_cast<double>(segment_count);
    const Eigen::Vector3d position = start_position + (end_position - start_position) * ratio;
    const Eigen::Quaterniond orientation =
        start_orientation.normalized().slerp(ratio, end_orientation.normalized());

    geometry_msgs::msg::Pose waypoint;
    waypoint.position.x = position.x();
    waypoint.position.y = position.y();
    waypoint.position.z = position.z();
    waypoint.orientation.x = orientation.x();
    waypoint.orientation.y = orientation.y();
    waypoint.orientation.z = orientation.z();
    waypoint.orientation.w = orientation.w();
    waypoints.push_back(waypoint);
  }

  return waypoints;
}

bool executeDualCupStepRange(const rclcpp::Node::SharedPtr& node,
                             moveit::planning_interface::MoveGroupInterface& both_arms,
                             moveit::planning_interface::MoveGroupInterface& left_arm,
                             moveit::planning_interface::MoveGroupInterface& left_gripper,
                             moveit::planning_interface::MoveGroupInterface& right_arm,
                             moveit::planning_interface::MoveGroupInterface& right_gripper,
                             const ArmConfig& left_config, const ArmConfig& right_config,
                             const TaskParams& params, ArmContext& left_context,
                             ArmContext& right_context, size_t start_index, size_t end_index) {
  auto should_run = [&](size_t step_index) {
    return start_index <= step_index && step_index <= end_index;
  };

  moveit::planning_interface::MoveGroupInterface::Plan left_plan;
  moveit::planning_interface::MoveGroupInterface::Plan right_plan;

  if (should_run(0)) {
    RCLCPP_INFO(node->get_logger(), "Cup step [cup_ready]: synchronized ready");
    left_arm.setNamedTarget(left_config.ready_pose_name);
    right_arm.setNamedTarget(right_config.ready_pose_name);
    if (!planGroup(node, left_arm, "left ready", left_plan) ||
        !planGroup(node, right_arm, "right ready", right_plan) ||
        !executeMergedPlan(node, both_arms, "dual ready", left_plan, right_plan)) {
      return false;
    }
  }

  if (should_run(1)) {
    RCLCPP_INFO(node->get_logger(), "Cup step [cup_pre_grasp]: synchronized pre-grasp");
    if (!planSingleArmPose(node, left_arm, left_context.pre_grasp_pose, left_config.tcp_link,
                           "left pre-grasp", left_plan) ||
        !planSingleArmPose(node, right_arm, right_context.pre_grasp_pose, right_config.tcp_link,
                           "right pre-grasp", right_plan) ||
        !executeMergedPlan(node, both_arms, "dual pre-grasp", left_plan, right_plan)) {
      return false;
    }
    logPoseDelta(node, left_arm, left_config.tcp_link, left_context.pre_grasp_pose,
                 "left pre-grasp");
    logPoseDelta(node, right_arm, right_config.tcp_link, right_context.pre_grasp_pose,
                 "right pre-grasp");
  }

  if (should_run(2)) {
    RCLCPP_INFO(node->get_logger(), "Cup step [cup_open]: open grippers");
    if (!executeDualGripperTarget(node, left_gripper, right_gripper, "open", "dual open")) {
      return false;
    }
  }

  if (should_run(3)) {
    RCLCPP_INFO(node->get_logger(), "Cup step [cup_grasp]: synchronized grasp approach");
    if (!computeSingleArmGraspApproach(node, left_arm, params, left_context.tcp_grasp_pose,
                                       left_config.tcp_link, "left grasp approach", left_plan) ||
        !computeSingleArmGraspApproach(node, right_arm, params, right_context.tcp_grasp_pose,
                                       right_config.tcp_link, "right grasp approach", right_plan) ||
        !executeMergedPlan(node, both_arms, "dual grasp approach", left_plan, right_plan)) {
      return false;
    }
    logPoseDelta(node, left_arm, left_config.tcp_link, left_context.tcp_grasp_pose, "left grasp");
    logPoseDelta(node, right_arm, right_config.tcp_link, right_context.tcp_grasp_pose,
                 "right grasp");
  }

  if (should_run(4)) {
    RCLCPP_INFO(node->get_logger(), "Cup step [cup_close]: close grippers");
    if (!executeDualGripperTarget(node, left_gripper, right_gripper,
                                  params.cup_grasp_profile.gripper_target, "dual close")) {
      return false;
    }
    rclcpp::sleep_for(std::chrono::milliseconds(500));
  }

  if (should_run(5)) {
    RCLCPP_INFO(
        node->get_logger(),
        "Cup step [cup_lift]: synchronized Cartesian lift with merged both_arms trajectory");
    if (!computeSingleArmCartesian(node, left_arm, params, {left_context.lift_pose}, "left lift",
                                   left_plan) ||
        !computeSingleArmCartesian(node, right_arm, params, {right_context.lift_pose}, "right lift",
                                   right_plan)) {
      return false;
    }
    logPlannedFinalTcpPose(node, left_arm, left_plan, left_config.tcp_link, left_context.lift_pose,
                           "left lift");
    logPlannedFinalTcpPose(node, right_arm, right_plan, right_config.tcp_link,
                           right_context.lift_pose, "right lift");
    if (!executeMergedPlan(node, both_arms, "dual Cartesian lift", left_plan, right_plan)) {
      return false;
    }
  }

  return true;
}

bool executeDualPickAndLift(const rclcpp::Node::SharedPtr& node,
                            moveit::planning_interface::MoveGroupInterface& both_arms,
                            moveit::planning_interface::MoveGroupInterface& left_arm,
                            moveit::planning_interface::MoveGroupInterface& left_gripper,
                            moveit::planning_interface::MoveGroupInterface& right_arm,
                            moveit::planning_interface::MoveGroupInterface& right_gripper,
                            const ArmConfig& left_config, const ArmConfig& right_config,
                            const TaskParams& params, ArmContext& left_context,
                            ArmContext& right_context) {
  return executeDualCupStepRange(node, both_arms, left_arm, left_gripper, right_arm, right_gripper,
                                 left_config, right_config, params, left_context, right_context, 0,
                                 5);
}

bool executeDualCupApproachOnly(const rclcpp::Node::SharedPtr& node,
                                moveit::planning_interface::MoveGroupInterface& both_arms,
                                moveit::planning_interface::MoveGroupInterface& left_arm,
                                moveit::planning_interface::MoveGroupInterface& left_gripper,
                                moveit::planning_interface::MoveGroupInterface& right_arm,
                                moveit::planning_interface::MoveGroupInterface& right_gripper,
                                const ArmConfig& left_config, const ArmConfig& right_config,
                                const TaskParams& params, ArmContext& left_context,
                                ArmContext& right_context) {
  return executeDualCupStepRange(node, both_arms, left_arm, left_gripper, right_arm, right_gripper,
                                 left_config, right_config, params, left_context, right_context, 0,
                                 3);
}

bool executeOverlappedPostWaterSequence(
    const rclcpp::Node::SharedPtr& node, moveit::planning_interface::MoveGroupInterface& both_arms,
    moveit::planning_interface::MoveGroupInterface& left_arm,
    moveit::planning_interface::MoveGroupInterface& left_gripper,
    moveit::planning_interface::MoveGroupInterface& right_arm,
    moveit::planning_interface::MoveGroupInterface& right_gripper, const TaskParams& params,
    const ArmContext& left_context, const ArmContext& right_context,
    const geometry_msgs::msg::Pose& mixing_cup_pose) {
  moveit::planning_interface::MoveGroupInterface::Plan left_plan;
  moveit::planning_interface::MoveGroupInterface::Plan right_plan;

  const auto left_place_pose = correctedPlacePose(left_context, params);
  const auto right_place_pose = right_context.tcp_grasp_pose;
  const auto left_lift_pose = correctedLiftPose(left_context, params);

  RCLCPP_INFO(node->get_logger(),
              "Dual-arm post-water phase: right water place lower while left ingredient moves to "
              "mixing hover");
  geometry_msgs::msg::Pose left_lift_clearance_pose = left_context.lift_pose;
  left_lift_clearance_pose.position.z = left_context.mixing_hover_pose.position.z;
  if (!computeSingleArmCartesian(node, right_arm, params, {right_place_pose},
                                 "right water place lower", right_plan) ||
      !computeSingleArmCartesian(node, left_arm, params,
                                 {left_lift_clearance_pose, left_context.mixing_hover_pose},
                                 "left ingredient mixing hover", left_plan) ||
      !executeMergedPlan(node, both_arms, "dual left ingredient hover/right water place", left_plan,
                         right_plan)) {
    return false;
  }

  if (!executeSingleGripperTarget(node, right_gripper, "open", "right water release gripper")) {
    return false;
  }

  RCLCPP_INFO(node->get_logger(),
              "Dual-arm post-water phase: right water retreats while left ingredient pours");
  RCLCPP_INFO(
      node->get_logger(), "[left/ingredient] Dynamic pour angle: %.3f rad",
      computePourAngleTowardTarget(left_context.mixing_hover_pose, mixing_cup_pose,
                                   left_context.horizontal_lateral_vector, params.pour_angle));
  if (!computeSingleArmCartesian(node, right_arm, params, {right_context.pre_grasp_pose},
                                 "right water retreat", right_plan) ||
      !computeSingleArmCartesian(node, left_arm, params,
                                 pourTiltWaypoints(left_context, mixing_cup_pose, params),
                                 "left ingredient pour tilt", left_plan) ||
      !executeMergedPlan(node, both_arms, "dual left ingredient pour/right water retreat",
                         left_plan, right_plan)) {
    return false;
  }

  rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::duration<double>(params.pour_hold_time)));

  RCLCPP_INFO(node->get_logger(),
              "Dual-arm post-water phase: right water home while left ingredient returns upright");
  right_arm.clearPoseTargets();
  setBoundedStartState(right_arm);
  right_arm.setNamedTarget("home");
  if (!planGroup(node, right_arm, "right water home", right_plan) ||
      !computeSingleArmCartesian(node, left_arm, params,
                                 pourUprightWaypoints(left_context, mixing_cup_pose, params),
                                 "left ingredient wrist upright", left_plan) ||
      !executeMergedPlan(node, both_arms, "dual left ingredient upright/right water home",
                         left_plan, right_plan)) {
    return false;
  }

  RCLCPP_INFO(node->get_logger(), "Dual-arm post-water phase: left ingredient clears mixing area");
  geometry_msgs::msg::Pose left_post_pour_clearance_pose = left_context.mixing_hover_pose;
  left_post_pour_clearance_pose.position.z =
      mixing_cup_pose.position.z + params.post_pour_clearance_height_offset;
  geometry_msgs::msg::Pose left_return_clearance_pose = left_lift_pose;
  left_return_clearance_pose.position.z = left_post_pour_clearance_pose.position.z;

  if (!computeSingleArmCartesian(
          node, left_arm, params,
          {left_post_pour_clearance_pose, left_return_clearance_pose, left_lift_pose},
          "left ingredient return hover", left_plan) ||
      !executeGroupPlan(node, left_arm, "left ingredient return hover", left_plan)) {
    return false;
  }

  if (!executeSingleGripperTarget(node, right_gripper, params.final_gripper_target,
                                  "right water final gripper")) {
    return false;
  }

  RCLCPP_INFO(node->get_logger(), "[left/ingredient] Place phase: lower and release");
  if (!computeSingleArmCartesian(node, left_arm, params, {left_place_pose},
                                 "left ingredient place lower", left_plan) ||
      !executeGroupPlan(node, left_arm, "left ingredient place lower", left_plan)) {
    return false;
  }

  if (!executeSingleGripperTarget(node, left_gripper, "open", "left ingredient release gripper")) {
    return false;
  }

  RCLCPP_INFO(node->get_logger(), "[left/ingredient] Place phase: retreat and home");
  if (!computeSingleArmCartesian(node, left_arm, params, {left_context.pre_grasp_pose},
                                 "left ingredient retreat", left_plan) ||
      !executeGroupPlan(node, left_arm, "left ingredient retreat", left_plan)) {
    return false;
  }

  left_arm.clearPoseTargets();
  setBoundedStartState(left_arm);
  left_arm.setNamedTarget("home");
  if (!planGroup(node, left_arm, "left ingredient home", left_plan) ||
      !executeGroupPlan(node, left_arm, "left ingredient home", left_plan)) {
    return false;
  }

  return executeSingleGripperTarget(node, left_gripper, params.final_gripper_target,
                                    "left ingredient final gripper");
}

bool executeSingleArmCartesian(const rclcpp::Node::SharedPtr& node,
                               moveit::planning_interface::MoveGroupInterface& arm,
                               const TaskParams& params,
                               const std::vector<geometry_msgs::msg::Pose>& waypoints,
                               const std::string& label) {
  moveit::planning_interface::MoveGroupInterface::Plan plan;
  if (!computeSingleArmCartesian(node, arm, params, waypoints, label, plan)) {
    return false;
  }
  return executeGroupPlan(node, arm, label, plan);
}

bool executePickupPlacePrimitive(
    const rclcpp::Node::SharedPtr& node, ArmTask& right_task, const TaskParams& params,
    ArmContext& mixing_context, const geometry_msgs::msg::Pose& staged_cup_pose,
    const geometry_msgs::msg::Pose& pickup_zone_pose,
    const std::optional<geometry_msgs::msg::Pose>& prepared_current_high_pose) {
  if (!mixing_context.tcp_to_cup_transform.has_value()) {
    seedIdealHeldCupTransform(mixing_context);
  }
  RCLCPP_INFO(node->get_logger(), "Pickup place: move mixing cup to pickup zone [%.3f, %.3f, %.3f]",
              pickup_zone_pose.position.x, pickup_zone_pose.position.y,
              pickup_zone_pose.position.z);

  const Eigen::Isometry3d pickup_zone_transform = poseToIsometry(pickup_zone_pose);
  const Eigen::Vector3d pickup_transfer_point(params.pickup_transfer_x, params.pickup_transfer_y,
                                              pickup_zone_pose.position.z);
  Eigen::Vector3d local_pickup_point = pickup_zone_transform.inverse() * pickup_transfer_point;
  const double safe_half_x =
      std::max(0.0, params.pickup_table_size_x * 0.5 - params.pickup_table_edge_margin);
  const double safe_half_y =
      std::max(0.0, params.pickup_table_size_y * 0.5 - params.pickup_table_edge_margin);
  local_pickup_point.x() = std::clamp(local_pickup_point.x(), -safe_half_x, safe_half_x);
  local_pickup_point.y() = std::clamp(local_pickup_point.y(), -safe_half_y, safe_half_y);
  local_pickup_point.z() = 0.0;
  const Eigen::Vector3d pickup_place_point = pickup_zone_transform * local_pickup_point;

  geometry_msgs::msg::Pose pickup_cup_pose = staged_cup_pose;
  pickup_cup_pose.position.x = pickup_place_point.x();
  pickup_cup_pose.position.y = pickup_place_point.y();
  pickup_cup_pose.position.z = pickup_zone_pose.position.z + params.pickup_cup_center_height_offset;
  RCLCPP_INFO(node->get_logger(),
              "Pickup place: selected reachable point [%.3f, %.3f, %.3f] on pickup table footprint",
              pickup_cup_pose.position.x, pickup_cup_pose.position.y, pickup_cup_pose.position.z);

  geometry_msgs::msg::Pose pickup_hover_cup_pose = pickup_cup_pose;
  pickup_hover_cup_pose.position.z += params.pickup_hover_height_offset;

  geometry_msgs::msg::Pose current_high_pose =
      prepared_current_high_pose.value_or(right_task.currentTcpPose());
  if (!prepared_current_high_pose.has_value()) {
    current_high_pose.position.z =
        std::max({current_high_pose.position.z,
                  staged_cup_pose.position.z + params.pickup_transfer_lift_height});
    if (!right_task.executeCartesianWaypoints({current_high_pose},
                                              "mixing cup raise before pickup transfer")) {
      return false;
    }
  }

  geometry_msgs::msg::Pose pickup_hover_tcp_pose;
  geometry_msgs::msg::Pose pickup_place_tcp_pose;
  bool used_pickup_transfer_guide = false;
  if (!params.right_pickup_transfer_guide_joints.empty()) {
    RCLCPP_INFO(
        node->get_logger(),
        "Pickup place: using configured right pickup guide joint waypoints before -z place");
    if (!right_task.moveThroughJointValueWaypoints(params.right_pickup_transfer_guide_joints,
                                                   "mixing cup pickup transfer guide")) {
      return false;
    }

    pickup_hover_tcp_pose = right_task.currentTcpPose();
    const auto guided_hover_cup_pose = cupPoseForTcpPose(mixing_context, pickup_hover_tcp_pose);
    if (!guided_hover_cup_pose.has_value()) {
      RCLCPP_ERROR(node->get_logger(), "Pickup place: failed to compute guided cup pose");
      return false;
    }

    geometry_msgs::msg::Pose guided_place_cup_pose = guided_hover_cup_pose.value();
    guided_place_cup_pose.position.z =
        pickup_zone_pose.position.z + params.pickup_cup_center_height_offset;
    const auto guided_place_tcp_pose = tcpPoseForCupPositionWithTcpOrientation(
        mixing_context, guided_place_cup_pose, pickup_hover_tcp_pose.orientation);
    if (!guided_place_tcp_pose.has_value()) {
      RCLCPP_ERROR(node->get_logger(), "Pickup place: failed to compute guided place TCP pose");
      return false;
    }
    pickup_place_tcp_pose = guided_place_tcp_pose.value();
    RCLCPP_INFO(node->get_logger(), "Pickup place: guided place cup target [%.3f, %.3f, %.3f]",
                guided_place_cup_pose.position.x, guided_place_cup_pose.position.y,
                guided_place_cup_pose.position.z);
    used_pickup_transfer_guide = true;
  } else {
    const auto computed_pickup_hover_tcp_pose = tcpPoseForCupPositionWithTcpOrientation(
        mixing_context, pickup_hover_cup_pose, current_high_pose.orientation);
    const auto computed_pickup_place_tcp_pose = tcpPoseForCupPositionWithTcpOrientation(
        mixing_context, pickup_cup_pose, current_high_pose.orientation);
    if (!computed_pickup_hover_tcp_pose.has_value() ||
        !computed_pickup_place_tcp_pose.has_value()) {
      RCLCPP_ERROR(node->get_logger(), "Pickup place: failed to compute pickup TCP poses");
      return false;
    }

    geometry_msgs::msg::Pose pickup_transfer_pose = current_high_pose;
    pickup_transfer_pose.position.x = params.pickup_transfer_x;
    pickup_transfer_pose.position.y = params.pickup_transfer_y;
    geometry_msgs::msg::Pose pickup_transfer_y_pose = current_high_pose;
    pickup_transfer_y_pose.position.y = params.pickup_transfer_y;
    if (!right_task.moveToPoseWithFallbacks(pickup_transfer_y_pose,
                                            "mixing cup pickup transfer y") ||
        !right_task.moveToPoseWithFallbacks(pickup_transfer_pose, "mixing cup pickup transfer x") ||
        !right_task.moveToPoseWithFallbacks(computed_pickup_hover_tcp_pose.value(),
                                            "mixing cup pickup hover")) {
      return false;
    }
    pickup_hover_tcp_pose = computed_pickup_hover_tcp_pose.value();
    pickup_place_tcp_pose = computed_pickup_place_tcp_pose.value();
  }
  if (!right_task.executeCartesianWaypoints({pickup_place_tcp_pose},
                                            "mixing cup lower to pickup zone")) {
    return false;
  }
  if (!right_task.closeGripperTo("open", "right mixing cup release at pickup zone")) {
    return false;
  }
  rclcpp::sleep_for(
      std::chrono::milliseconds(static_cast<int>(params.pickup_release_settle_time * 1000.0)));
  if (used_pickup_transfer_guide && !params.right_pickup_home_guide_joints.empty()) {
    RCLCPP_INFO(
        node->get_logger(),
        "Pickup place: returning home through configured pickup home guide joint waypoints");
    return right_task.moveHomeViaGuideAndClose("right pickup place home",
                                               params.right_pickup_home_guide_joints);
  }

  geometry_msgs::msg::Pose pickup_vertical_retreat_pose = pickup_place_tcp_pose;
  pickup_vertical_retreat_pose.position.z += params.pickup_release_vertical_retreat_height;
  if (!right_task.executeCartesianWaypoints({pickup_vertical_retreat_pose},
                                            "right pickup vertical retreat after release")) {
    return false;
  }

  geometry_msgs::msg::Pose pickup_release_retreat_pose = pickup_vertical_retreat_pose;
  pickup_release_retreat_pose.position.x -=
      mixing_context.horizontal_approach_vector.x() * params.pickup_release_retreat_distance;
  pickup_release_retreat_pose.position.y -=
      mixing_context.horizontal_approach_vector.y() * params.pickup_release_retreat_distance;
  if (!right_task.executeCartesianWaypoints({pickup_release_retreat_pose},
                                            "right pickup horizontal retreat after release")) {
    return false;
  }

  if (!right_task.executeCartesianWaypoints({pickup_hover_tcp_pose},
                                            "right pickup retreat to hover")) {
    return false;
  }
  return right_task.moveHomeViaGuideAndClose("right pickup place home",
                                             params.right_pickup_home_guide_joints);
}

bool executeStirAndPickupStage(const rclcpp::Node::SharedPtr& node,
                               moveit::planning_interface::MoveGroupInterface& both_arms,
                               moveit::planning_interface::MoveGroupInterface& left_arm,
                               moveit::planning_interface::MoveGroupInterface& left_gripper,
                               moveit::planning_interface::MoveGroupInterface& right_arm,
                               moveit::planning_interface::MoveGroupInterface& right_gripper,
                               const ArmConfig& left_config, const ArmConfig& right_config,
                               ArmTask& left_task, ArmTask& right_task, const TaskParams& params,
                               const geometry_msgs::msg::Pose& mixing_cup_pose,
                               const geometry_msgs::msg::Pose& stir_stick_pose,
                               const geometry_msgs::msg::Pose& pickup_zone_pose, bool run_grasp,
                               bool run_pick_lift, bool stop_after_stick_close,
                               bool stop_after_stick_hover, bool run_motion, bool run_cleanup,
                               bool run_pickup_place) {
  RCLCPP_INFO(node->get_logger(), "Stir stage: right arm targets mixing cup");
  auto mixing_context = right_task.computeContext(mixing_cup_pose, mixing_cup_pose);
  if (!mixing_context.has_value()) {
    return false;
  }
  RCLCPP_INFO(
      node->get_logger(),
      "Stir stage: right mixing cup TCP grasp [%.3f, %.3f, %.3f] with shared cup offset %.3f",
      mixing_context->tcp_grasp_pose.position.x, mixing_context->tcp_grasp_pose.position.y,
      mixing_context->tcp_grasp_pose.position.z, mixing_context->gripper_center_forward_offset);
  if (params.right_mixing_pregrasp_lateral_offset > 0.0) {
    mixing_context->pre_grasp_pose.position.y -= params.right_mixing_pregrasp_lateral_offset;
    RCLCPP_INFO(
        node->get_logger(), "Stir stage: adjusted right mixing pre-grasp to [%.3f, %.3f, %.3f]",
        mixing_context->pre_grasp_pose.position.x, mixing_context->pre_grasp_pose.position.y,
        mixing_context->pre_grasp_pose.position.z);
  }

  RCLCPP_INFO(node->get_logger(), "Stir stage: left arm targets stir stick");
  auto stick_context =
      left_task.computeContext(stir_stick_pose, mixing_cup_pose, params.stir_stick_grasp_profile);
  if (!stick_context.has_value()) {
    return false;
  }
  if (params.stir_stick_grasp_profile.point_mode == GraspPointMode::HorizontalStickEnd) {
    rotateContextLocal(stick_context.value(), "local_z",
                       params.stir_stick_grasp_profile.stick_roll_angle);
    RCLCPP_INFO(
        node->get_logger(),
        "Stir stage: rotated left wrist %.3f rad around TCP approach axis for flat stick grasp",
        params.stir_stick_grasp_profile.stick_roll_angle);
  } else {
    RCLCPP_INFO(
        node->get_logger(),
        "Stir stage: stick is already vertical in holder; keeping normal wrist orientation");
  }

  geometry_msgs::msg::Pose staged_cup_pose = mixing_cup_pose;
  staged_cup_pose.position.x += params.stir_cup_stage_x_offset;
  staged_cup_pose.position.y = params.stir_cup_stage_y;
  staged_cup_pose.position.z = mixing_cup_pose.position.z + params.stir_cup_stage_height_offset;
  std::optional<geometry_msgs::msg::Pose> inserted_stick_pose_for_motion;

  if (run_grasp && !run_pick_lift && !run_motion && !run_cleanup && !run_pickup_place) {
    if (!right_task.approachGraspOnly(mixing_context.value(), false)) {
      return false;
    }
    if (!left_task.approachGraspOnly(stick_context.value(), false)) {
      return false;
    }
    RCLCPP_INFO(node->get_logger(), "Stir approach-only stage completed");
    return true;
  }

  if (run_pick_lift) {
    seedIdealHeldCupTransform(mixing_context.value());

    geometry_msgs::msg::Pose staged_high_cup_pose = staged_cup_pose;
    staged_high_cup_pose.position.z =
        std::max(staged_high_cup_pose.position.z, mixing_cup_pose.position.z + params.lift_height);

    const auto staged_high_tcp_pose =
        tcpPoseForCupPose(mixing_context.value(), staged_high_cup_pose);
    const auto staged_low_tcp_pose = tcpPoseForCupPose(mixing_context.value(), staged_cup_pose);
    if (!staged_high_tcp_pose.has_value() || !staged_low_tcp_pose.has_value()) {
      RCLCPP_ERROR(node->get_logger(), "Stir stage: failed to compute staged mixing cup TCP poses");
      return false;
    }

    auto stage_mixing_cup = [&]() {
      RCLCPP_INFO(node->get_logger(),
                  "Stir stage: move mixing cup to center staging cup pose [%.3f, %.3f, %.3f]",
                  staged_cup_pose.position.x, staged_cup_pose.position.y,
                  staged_cup_pose.position.z);
      return right_task.executeCartesianWaypoints(
          {staged_high_tcp_pose.value(), staged_low_tcp_pose.value()},
          "mixing cup center stage and lower");
    };

    if (run_grasp) {
      RCLCPP_INFO(node->get_logger(),
                  "Stir stage: using merged both_arms plans for mixing cup/stir stick preparation");
      moveit::planning_interface::MoveGroupInterface::Plan left_plan;
      moveit::planning_interface::MoveGroupInterface::Plan right_plan;

      left_arm.clearPoseTargets();
      right_arm.clearPoseTargets();
      setBoundedStartState(left_arm);
      setBoundedStartState(right_arm);
      left_arm.setNamedTarget(left_config.ready_pose_name);
      right_arm.setNamedTarget(right_config.ready_pose_name);
      if (!planGroup(node, left_arm, "left stir ready", left_plan) ||
          !planGroup(node, right_arm, "right mixing ready", right_plan) ||
          !executeMergedPlan(node, both_arms, "stir dual ready", left_plan, right_plan)) {
        return false;
      }

      const bool has_left_entry_guide = !params.left_stir_entry_guide_joints.empty();
      if (!has_left_entry_guide &&
          !planSingleArmPose(node, left_arm, stick_context->pre_grasp_pose, left_config.tcp_link,
                             "left stir stick pre-grasp", left_plan)) {
        return false;
      }
      if (!planSingleArmPose(node, right_arm, mixing_context->pre_grasp_pose, right_config.tcp_link,
                             "right mixing pre-grasp", right_plan)) {
        return false;
      }
      if (has_left_entry_guide) {
        const auto left_joint_count = left_arm.getJointNames().size();
        if (left_joint_count > 0 &&
            params.left_stir_entry_guide_joints.size() == left_joint_count) {
          RCLCPP_INFO(node->get_logger(),
                      "Stir stage: move through manual left stir entry guide while right arm moves "
                      "to mixing pre-grasp");
          if (!planSingleArmJointValues(node, left_arm, params.left_stir_entry_guide_joints,
                                        "left stir entry guide joints", left_plan) ||
              !executeMergedPlan(node, both_arms, "stir left entry guide / right mixing pre-grasp",
                                 left_plan, right_plan)) {
            return false;
          }
        } else {
          RCLCPP_INFO(
              node->get_logger(),
              "Stir stage: move through manual left stir entry guide joints before stick approach");
          if (!left_task.moveThroughJointValueWaypoints(params.left_stir_entry_guide_joints,
                                                        "left stir entry guide joints") ||
              !executeGroupPlan(node, right_arm, "right mixing pre-grasp", right_plan)) {
            return false;
          }
        }
      } else if (!executeMergedPlan(node, both_arms, "stir mixing pre-grasp / stick pre-grasp",
                                    left_plan, right_plan)) {
        return false;
      }
      if (!has_left_entry_guide) {
        logPoseDelta(node, left_arm, left_config.tcp_link, stick_context->pre_grasp_pose,
                     "left stir stick pre-grasp");
      } else {
        RCLCPP_INFO(node->get_logger(),
                    "Stir stage: left entry guide replaces automatic pre-grasp entry");
      }
      logPoseDelta(node, right_arm, right_config.tcp_link, mixing_context->pre_grasp_pose,
                   "right mixing pre-grasp");

      if (!executeDualGripperTarget(node, left_gripper, right_gripper, "open",
                                    "stir prep dual open")) {
        return false;
      }

      if (!planSingleArmPose(node, left_arm, stick_context->pre_grasp_pose, left_config.tcp_link,
                             "left stir stick pre-grasp", left_plan) ||
          !planSingleArmPose(node, right_arm, mixing_context->tcp_grasp_pose, right_config.tcp_link,
                             "right mixing grasp", right_plan) ||
          !executeMergedPlan(node, both_arms, "stir mixing grasp / stick pre-grasp", left_plan,
                             right_plan)) {
        return false;
      }
      logPoseDelta(node, left_arm, left_config.tcp_link, stick_context->pre_grasp_pose,
                   "left stir stick pre-grasp");
      logPoseDelta(node, right_arm, right_config.tcp_link, mixing_context->tcp_grasp_pose,
                   "right mixing grasp");

      if (!right_task.closeGripperTo(params.cup_grasp_profile.gripper_target,
                                     "right mixing cup close gripper")) {
        return false;
      }
      rclcpp::sleep_for(std::chrono::milliseconds(500));

      if (!planSingleArmPose(node, left_arm, stick_context->tcp_grasp_pose, left_config.tcp_link,
                             "left stir stick grasp approach", left_plan) ||
          !computeSingleArmCartesian(node, right_arm, params, {mixing_context->lift_pose},
                                     "right mixing lift", right_plan) ||
          !executeMergedPlan(node, both_arms, "stir mixing lift / stick grasp", left_plan,
                             right_plan)) {
        return false;
      }

      if (!left_task.closeGripperTo(params.stir_stick_grasp_profile.gripper_target,
                                    "left stir stick close gripper")) {
        return false;
      }
      rclcpp::sleep_for(std::chrono::milliseconds(500));

      if (stop_after_stick_close && !run_motion && !run_cleanup && !run_pickup_place) {
        RCLCPP_INFO(node->get_logger(), "Stir stage: stopped after closing stir stick gripper");
        return true;
      }

      if (!params.left_stir_lift_guide_joints.empty()) {
        RCLCPP_INFO(
            node->get_logger(),
            "Stir stage: move through manual left stir lift guide joints before holder lift");
        if (!left_task.moveThroughJointValueWaypoints(params.left_stir_lift_guide_joints,
                                                      "left stir lift guide joints")) {
          return false;
        }
      }

      if (!computeSingleArmCartesian(node, left_arm, params, {stick_context->lift_pose},
                                     "left stir stick lift from holder", left_plan) ||
          !computeSingleArmCartesian(node, right_arm, params,
                                     {staged_high_tcp_pose.value(), staged_low_tcp_pose.value()},
                                     "right mixing cup center stage and lower", right_plan) ||
          !executeMergedPlan(node, both_arms, "stir mixing stage / stick lift", left_plan,
                             right_plan)) {
        return false;
      }
    } else {
      RCLCPP_INFO(node->get_logger(), "Stir stage: right arm picks mixing cup");
      if (!right_task.pickAndLift(mixing_context.value(), false)) {
        return false;
      }
      if (!stage_mixing_cup()) {
        return false;
      }
    }

    if (!run_grasp) {
      RCLCPP_INFO(node->get_logger(), "Stir stage: left arm picks and lifts stir stick");
      if (!left_task.pickAndLift(stick_context.value(), false,
                                 params.stir_stick_grasp_profile.gripper_target)) {
        return false;
      }
    }

    geometry_msgs::msg::Pose stick_hover_pose = stick_context->lift_pose;
    stick_hover_pose.position.x =
        staged_cup_pose.position.x - stick_context->horizontal_approach_vector.x() *
                                         stick_context->gripper_center_forward_offset;
    stick_hover_pose.position.y =
        staged_cup_pose.position.y - stick_context->horizontal_approach_vector.y() *
                                         stick_context->gripper_center_forward_offset;
    stick_hover_pose.position.z =
        staged_cup_pose.position.z + params.stir_stick_insert_hover_height_offset;

    const double transport_safe_z =
        std::max(stick_context->lift_pose.position.z, stick_hover_pose.position.z) +
        params.stir_transport_extra_height;

    geometry_msgs::msg::Pose transport_approach_pose = stick_hover_pose;
    transport_approach_pose.position.z = transport_safe_z;

    RCLCPP_INFO(
        node->get_logger(),
        "Stir stage: route stir tool after holder lift at z=%.3f to hover [%.3f, %.3f, %.3f]",
        transport_safe_z, stick_hover_pose.position.x, stick_hover_pose.position.y,
        stick_hover_pose.position.z);
    if (!params.left_stir_transport_guide_joints.empty()) {
      RCLCPP_INFO(node->get_logger(),
                  "Stir stage: move through manual left stir transport guide joints");
      if (!left_task.moveThroughJointValueWaypoints(params.left_stir_transport_guide_joints,
                                                    "left stir transport guide joints")) {
        return false;
      }
      const auto guided_tcp_pose = left_task.currentTcpPose();
      transport_approach_pose.orientation = guided_tcp_pose.orientation;
      stick_hover_pose.orientation = guided_tcp_pose.orientation;
    }
    if (!left_task.moveToPose(transport_approach_pose, "stir stick approach above staged cup")) {
      return false;
    }
    if (!left_task.executeCartesianWaypoints({stick_hover_pose}, "stir stick lower to cup hover")) {
      return false;
    }

    if (stop_after_stick_hover && !run_motion && !run_cleanup && !run_pickup_place) {
      RCLCPP_INFO(node->get_logger(), "Stir stage: stopped at stir stick cup hover");
      return true;
    }

    geometry_msgs::msg::Pose inserted_stick_pose = stick_hover_pose;
    if (params.stir_stick_grasp_profile.point_mode == GraspPointMode::HorizontalStickEnd) {
      geometry_msgs::msg::Pose vertical_stick_pose =
          poseWithZAxisClosestToCurrent(stick_hover_pose, Eigen::Vector3d(0.0, 0.0, -1.0));
      RCLCPP_INFO(node->get_logger(), "Stir stage: rotate stir stick vertical above cup");
      if (!left_task.moveToPose(vertical_stick_pose, "stir stick vertical")) {
        RCLCPP_WARN(node->get_logger(),
                    "Stir stage: vertical stick pose with TCP -Z failed; retrying with TCP +Z");
        vertical_stick_pose =
            poseWithZAxisClosestToCurrent(stick_hover_pose, Eigen::Vector3d(0.0, 0.0, 1.0));
        if (!left_task.moveToPose(vertical_stick_pose, "stir stick vertical alternate")) {
          return false;
        }
      }
      inserted_stick_pose = vertical_stick_pose;
    } else {
      RCLCPP_INFO(
          node->get_logger(),
          "Stir stage: vertical holder stick already has the desired insertion orientation");
    }

    inserted_stick_pose.position.z =
        staged_cup_pose.position.z + params.stir_stick_insert_depth_height_offset;
    RCLCPP_INFO(node->get_logger(),
                "Stir stage: lower vertical stir stick into cup [%.3f, %.3f, %.3f]",
                inserted_stick_pose.position.x, inserted_stick_pose.position.y,
                inserted_stick_pose.position.z);
    if (!left_task.executeCartesianWaypoints({inserted_stick_pose}, "stir stick insert into cup")) {
      return false;
    }
    inserted_stick_pose_for_motion = inserted_stick_pose;
  }

  if (!run_motion && !run_cleanup && !run_pickup_place) {
    RCLCPP_INFO(node->get_logger(), "Stir pick/lift and insert-prep stage completed");
    return true;
  }

  geometry_msgs::msg::Pose stir_center_pose =
      inserted_stick_pose_for_motion.value_or(left_task.currentTcpPose());

  if (run_motion) {
    RCLCPP_INFO(node->get_logger(),
                "Stir stage: Cartesian circular stir around current inserted TCP center [%.3f, "
                "%.3f, %.3f], radius %.3f, cycles %d",
                stir_center_pose.position.x, stir_center_pose.position.y,
                stir_center_pose.position.z, params.stir_radius, params.stir_cycles);
    auto stir_path = stirWaypoints(stir_center_pose, params);
    if (stir_path.empty()) {
      return false;
    }
    if (!left_task.executeCartesianWaypoints({stir_path.front()}, "stir start")) {
      return false;
    }
    std::vector<geometry_msgs::msg::Pose> circular_path;
    circular_path.reserve(stir_path.size() - 1);
    circular_path.insert(circular_path.end(), std::next(stir_path.begin()), stir_path.end());
    if (!left_task.executeCartesianWaypoints(circular_path, "stir circular motion")) {
      return false;
    }
    if (!left_task.executeCartesianWaypoints({stir_center_pose}, "stir return to center")) {
      return false;
    }
    RCLCPP_INFO(node->get_logger(), "Stir motion completed");
  }

  bool left_cleanup_home_deferred = false;
  std::optional<geometry_msgs::msg::Pose> prepared_pickup_initial_high_pose;

  if (run_cleanup) {
    RCLCPP_INFO(node->get_logger(), "Stir cleanup: lift stick out of mixing cup");
    geometry_msgs::msg::Pose stick_out_pose = left_task.currentTcpPose();
    stick_out_pose.position.z =
        staged_cup_pose.position.z + params.stir_stick_insert_hover_height_offset;
    if (!left_task.executeCartesianWaypoints({stick_out_pose}, "stir stick lift out of cup")) {
      return false;
    }

    geometry_msgs::msg::Pose stick_holder_hover_pose = stick_context->tcp_grasp_pose;
    stick_holder_hover_pose.position.z =
        stick_context->tcp_grasp_pose.position.z + params.lift_height;

    if (!params.left_stir_transport_guide_joints.empty()) {
      RCLCPP_INFO(node->get_logger(), "Stir cleanup: return through reversed guide joints");
      const auto reversed_guides = reversedFlatJointWaypoints(
          params.left_stir_transport_guide_joints, left_task.jointCount());
      if (!left_task.moveThroughJointValueWaypoints(reversed_guides,
                                                    "left stir cleanup reversed guide joints")) {
        return false;
      }
    }

    if (!left_task.moveToPose(stick_holder_hover_pose, "stir stick holder hover")) {
      return false;
    }
    if (!left_task.executeCartesianWaypoints({stick_context->tcp_grasp_pose},
                                             "stir stick vertical place into holder")) {
      return false;
    }
    if (!left_task.closeGripperTo("open", "left stir stick release in holder")) {
      return false;
    }
    if (!left_task.executeCartesianWaypoints({stick_holder_hover_pose},
                                             "stir stick vertical retreat from holder")) {
      return false;
    }
    geometry_msgs::msg::Pose stick_holder_backout_pose = stick_holder_hover_pose;
    stick_holder_backout_pose.position.x -= params.stir_transport_retreat_distance;
    if (run_pickup_place) {
      geometry_msgs::msg::Pose pickup_initial_high_pose = right_task.currentTcpPose();
      pickup_initial_high_pose.position.z =
          std::max({pickup_initial_high_pose.position.z,
                    staged_cup_pose.position.z + params.pickup_transfer_lift_height});

      moveit::planning_interface::MoveGroupInterface::Plan left_backout_plan;
      moveit::planning_interface::MoveGroupInterface::Plan right_raise_plan;
      if (!computeSingleArmCartesian(node, left_arm, params, {stick_holder_backout_pose},
                                     "left stir stick holder Cartesian -x backout",
                                     left_backout_plan) ||
          !computeSingleArmCartesian(node, right_arm, params, {pickup_initial_high_pose},
                                     "right mixing cup initial pickup raise", right_raise_plan) ||
          !executeMergedPlan(node, both_arms, "stir holder backout / pickup initial raise",
                             left_backout_plan, right_raise_plan)) {
        return false;
      }
      prepared_pickup_initial_high_pose = pickup_initial_high_pose;
      left_cleanup_home_deferred = true;
    } else {
      if (!left_task.executeCartesianWaypoints({stick_holder_backout_pose},
                                               "stir stick holder Cartesian -x backout") ||
          !left_task.moveHomeAndClose("left stir cleanup home")) {
        return false;
      }
    }
  }

  if (run_pickup_place) {
    if (left_cleanup_home_deferred) {
      moveit::planning_interface::MoveGroupInterface::Plan left_home_plan;
      left_arm.clearPoseTargets();
      setBoundedStartState(left_arm);
      left_arm.setNamedTarget("home");
      if (!planGroup(node, left_arm, "left stir cleanup home", left_home_plan) ||
          !executeGroupPlan(node, left_arm, "left stir cleanup home", left_home_plan) ||
          !executeSingleGripperTarget(node, left_gripper, params.final_gripper_target,
                                      "left stir cleanup final gripper")) {
        return false;
      }
      if (!executePickupPlacePrimitive(node, right_task, params, mixing_context.value(),
                                       staged_cup_pose, pickup_zone_pose,
                                       prepared_pickup_initial_high_pose)) {
        return false;
      }
    } else if (!executePickupPlacePrimitive(node, right_task, params, mixing_context.value(),
                                            staged_cup_pose, pickup_zone_pose, std::nullopt)) {
      return false;
    }
  }

  return true;
}

void updateHeldCupState(const rclcpp::Node::SharedPtr& node, ArmContext& context,
                        moveit::planning_interface::MoveGroupInterface& arm,
                        const ArmConfig& config, const TaskParams& params,
                        const geometry_msgs::msg::Pose& actual_cup_pose,
                        const geometry_msgs::msg::Pose& mixing_cup_pose) {
  const geometry_msgs::msg::Pose tcp_pose = arm.getCurrentPose(config.tcp_link).pose;
  context.held_cup_pose = actual_cup_pose;
  context.tcp_to_cup_transform =
      poseToIsometry(tcp_pose).inverse() * poseToIsometry(actual_cup_pose);

  geometry_msgs::msg::Pose desired_lift_cup_pose = actual_cup_pose;
  desired_lift_cup_pose.position.z += params.lift_height;
  context.lift_pose = tcpPoseForCupPose(context, desired_lift_cup_pose).value_or(tcp_pose);
  if (!context.tcp_to_cup_transform.has_value()) {
    context.lift_pose.position.z += params.lift_height;
  }

  const double side_pour_target_lateral_offset =
      config.arm_group == "right_arm" && params.pour_target_lateral_offset > 0.0
          ? -params.pour_target_lateral_offset
          : params.pour_target_lateral_offset;

  geometry_msgs::msg::Pose desired_hover_cup_pose = actual_cup_pose;
  desired_hover_cup_pose.position.x =
      mixing_cup_pose.position.x +
      context.horizontal_lateral_vector.x() * side_pour_target_lateral_offset;
  desired_hover_cup_pose.position.y =
      mixing_cup_pose.position.y +
      context.horizontal_lateral_vector.y() * side_pour_target_lateral_offset;
  desired_hover_cup_pose.position.z =
      mixing_cup_pose.position.z + params.mixing_hover_height_offset;

  if (const auto tcp_hover_pose = tcpPoseForCupPose(context, desired_hover_cup_pose)) {
    context.mixing_hover_pose = tcp_hover_pose.value();
  }

  const Eigen::Vector3d tcp_to_cup_translation = context.tcp_to_cup_transform->translation();
  RCLCPP_INFO(node->get_logger(),
              "[%s] Refreshed held cup state: cup [%.3f, %.3f, %.3f], tcp [%.3f, %.3f, %.3f], "
              "tcp->cup [%.3f, %.3f, %.3f], lift tcp [%.3f, %.3f, %.3f]",
              config.label.c_str(), actual_cup_pose.position.x, actual_cup_pose.position.y,
              actual_cup_pose.position.z, tcp_pose.position.x, tcp_pose.position.y,
              tcp_pose.position.z, tcp_to_cup_translation.x(), tcp_to_cup_translation.y(),
              tcp_to_cup_translation.z(), context.lift_pose.position.x,
              context.lift_pose.position.y, context.lift_pose.position.z);
}

struct PoseCache {
  std::optional<geometry_msgs::msg::Pose> water;
  std::optional<geometry_msgs::msg::Pose> ingredient;
  std::optional<geometry_msgs::msg::Pose> mixing;
  std::optional<geometry_msgs::msg::Pose> stir_stick;
  std::optional<geometry_msgs::msg::Pose> pickup;
};

constexpr size_t kCupReadyIndex = 0;
constexpr size_t kCupPreGraspIndex = 1;
constexpr size_t kCupOpenIndex = 2;
constexpr size_t kCupGraspIndex = 3;
constexpr size_t kCupCloseIndex = 4;
constexpr size_t kCupLiftIndex = 5;
constexpr size_t kWaterPourIndex = 6;
constexpr size_t kWaterClearIndex = 7;
constexpr size_t kIngredientPourPlaceIndex = 8;
constexpr size_t kStirGraspIndex = 9;
constexpr size_t kStirPickLiftIndex = 10;
constexpr size_t kStirStickCloseIndex = 11;
constexpr size_t kStirHoverIndex = 12;
constexpr size_t kStirMotionIndex = 13;
constexpr size_t kStirCleanupIndex = 14;
constexpr size_t kPickupPlaceIndex = 15;

std::optional<size_t> findStepIndex(const std::vector<std::string>& steps,
                                    const std::string& step_name) {
  const auto it = std::find(steps.begin(), steps.end(), step_name);
  if (it == steps.end()) {
    return std::nullopt;
  }
  return static_cast<size_t>(std::distance(steps.begin(), it));
}

bool stepInRange(size_t step_index, size_t start_step_index, size_t end_step_index) {
  return start_step_index <= step_index && step_index <= end_step_index;
}

bool rangeIncludes(size_t start_step_index, size_t end_step_index, size_t first_step_index,
                   size_t last_step_index) {
  return start_step_index <= last_step_index && end_step_index >= first_step_index;
}

PoseCache latestPoseCache(std::mutex& pose_mutex, const PoseCache& pose_cache) {
  std::lock_guard<std::mutex> lock(pose_mutex);
  return pose_cache;
}

void refreshHeldCupTargetsFromGazebo(const rclcpp::Node::SharedPtr& node, std::mutex& pose_mutex,
                                     const PoseCache& pose_cache,
                                     moveit::planning_interface::MoveGroupInterface& left_arm,
                                     moveit::planning_interface::MoveGroupInterface& right_arm,
                                     const ArmConfig& left_config, const ArmConfig& right_config,
                                     const TaskParams& params, bool run_ingredient, bool run_water,
                                     std::optional<ArmContext>& left_context,
                                     std::optional<ArmContext>& right_context) {
  const PoseCache latest = latestPoseCache(pose_mutex, pose_cache);
  if (!latest.mixing.has_value()) {
    return;
  }
  if (run_ingredient && left_context.has_value() && latest.ingredient.has_value()) {
    updateHeldCupState(node, left_context.value(), left_arm, left_config, params,
                       latest.ingredient.value(), latest.mixing.value());
  }
  if (run_water && right_context.has_value() && latest.water.has_value()) {
    updateHeldCupState(node, right_context.value(), right_arm, right_config, params,
                       latest.water.value(), latest.mixing.value());
  }
}

bool runCupPrimitiveSteps(const rclcpp::Node::SharedPtr& node,
                          moveit::planning_interface::MoveGroupInterface& both_arms,
                          moveit::planning_interface::MoveGroupInterface& left_arm,
                          moveit::planning_interface::MoveGroupInterface& left_gripper,
                          moveit::planning_interface::MoveGroupInterface& right_arm,
                          moveit::planning_interface::MoveGroupInterface& right_gripper,
                          const ArmConfig& left_config, const ArmConfig& right_config,
                          const TaskParams& params, bool run_water, bool run_ingredient,
                          size_t start_step_index, size_t end_step_index, std::mutex& pose_mutex,
                          const PoseCache& pose_cache, std::optional<ArmContext>& left_context,
                          std::optional<ArmContext>& right_context) {
  if (!rangeIncludes(start_step_index, end_step_index, kCupReadyIndex, kCupLiftIndex)) {
    return true;
  }
  if (!run_water || !run_ingredient || !left_context.has_value() || !right_context.has_value()) {
    RCLCPP_ERROR(node->get_logger(),
                 "Cup primitive steps require both run_water:=true and run_ingredient:=true");
    return false;
  }

  const size_t cup_start = std::max(start_step_index, kCupReadyIndex);
  const size_t cup_end = std::min(end_step_index, kCupLiftIndex);
  bool cup_ok = true;
  if (cup_start <= kCupCloseIndex && cup_end >= kCupLiftIndex) {
    cup_ok =
        executeDualCupStepRange(node, both_arms, left_arm, left_gripper, right_arm, right_gripper,
                                left_config, right_config, params, left_context.value(),
                                right_context.value(), cup_start, kCupCloseIndex);
    if (cup_ok) {
      refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm,
                                      left_config, right_config, params, run_ingredient, run_water,
                                      left_context, right_context);
      cup_ok =
          executeDualCupStepRange(node, both_arms, left_arm, left_gripper, right_arm, right_gripper,
                                  left_config, right_config, params, left_context.value(),
                                  right_context.value(), kCupLiftIndex, cup_end);
    }
  } else if (cup_start <= kCupLiftIndex && cup_end >= kCupLiftIndex) {
    refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm, left_config,
                                    right_config, params, run_ingredient, run_water, left_context,
                                    right_context);
    cup_ok = executeDualCupStepRange(
        node, both_arms, left_arm, left_gripper, right_arm, right_gripper, left_config,
        right_config, params, left_context.value(), right_context.value(), cup_start, cup_end);
  } else {
    cup_ok = executeDualCupStepRange(
        node, both_arms, left_arm, left_gripper, right_arm, right_gripper, left_config,
        right_config, params, left_context.value(), right_context.value(), cup_start, cup_end);
  }

  if (!cup_ok) {
    RCLCPP_ERROR(node->get_logger(), "Cup primitive steps failed");
    return false;
  }
  if (cup_end >= kCupLiftIndex) {
    refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm, left_config,
                                    right_config, params, run_ingredient, run_water, left_context,
                                    right_context);
  }
  return true;
}

bool runWaterPourPrimitive(const rclcpp::Node::SharedPtr& node, std::mutex& pose_mutex,
                           const PoseCache& pose_cache, const PoseCache& initial_poses,
                           ArmTask& right_task, std::optional<ArmContext>& right_context) {
  RCLCPP_INFO(node->get_logger(), "Primitive [water_pour]");
  const PoseCache current_poses = latestPoseCache(pose_mutex, pose_cache);
  const auto water_pour_mixing_pose = current_poses.mixing.value_or(initial_poses.mixing.value());
  return right_context.has_value() &&
         right_task.pourAtMixing(right_context.value(), water_pour_mixing_pose);
}

bool runWaterClearPrimitive(const rclcpp::Node::SharedPtr& node, std::mutex& pose_mutex,
                            const PoseCache& pose_cache, const PoseCache& initial_poses,
                            ArmTask& right_task, std::optional<ArmContext>& right_context) {
  RCLCPP_INFO(node->get_logger(), "Primitive [water_clear]");
  const PoseCache current_poses = latestPoseCache(pose_mutex, pose_cache);
  const auto water_clear_mixing_pose = current_poses.mixing.value_or(initial_poses.mixing.value());
  return right_context.has_value() &&
         right_task.clearAfterPour(right_context.value(), water_clear_mixing_pose);
}

bool runIngredientPourPlacePrimitive(const rclcpp::Node::SharedPtr& node,
                                     moveit::planning_interface::MoveGroupInterface& both_arms,
                                     moveit::planning_interface::MoveGroupInterface& left_arm,
                                     moveit::planning_interface::MoveGroupInterface& left_gripper,
                                     moveit::planning_interface::MoveGroupInterface& right_arm,
                                     moveit::planning_interface::MoveGroupInterface& right_gripper,
                                     const TaskParams& params, std::mutex& pose_mutex,
                                     const PoseCache& pose_cache, const PoseCache& initial_poses,
                                     std::optional<ArmContext>& left_context,
                                     std::optional<ArmContext>& right_context) {
  RCLCPP_INFO(node->get_logger(), "Primitive [ingredient_pour_place]");
  const PoseCache current_poses = latestPoseCache(pose_mutex, pose_cache);
  const auto ingredient_mixing_pose = current_poses.mixing.value_or(initial_poses.mixing.value());
  if (!left_context.has_value() || !right_context.has_value()) {
    return false;
  }
  return executeOverlappedPostWaterSequence(node, both_arms, left_arm, left_gripper, right_arm,
                                            right_gripper, params, left_context.value(),
                                            right_context.value(), ingredient_mixing_pose);
}

bool runPreStirBoundaryPrimitive(const rclcpp::Node::SharedPtr& node,
                                 moveit::planning_interface::MoveGroupInterface& both_arms,
                                 moveit::planning_interface::MoveGroupInterface& left_arm,
                                 moveit::planning_interface::MoveGroupInterface& left_gripper,
                                 moveit::planning_interface::MoveGroupInterface& right_arm,
                                 moveit::planning_interface::MoveGroupInterface& right_gripper,
                                 const TaskParams& params) {
  RCLCPP_INFO(
      node->get_logger(),
      "Primitive boundary: synchronize both arms to stable home/closed state before stir steps");
  rclcpp::sleep_for(std::chrono::milliseconds(500));
  moveit::planning_interface::MoveGroupInterface::Plan left_home_plan;
  moveit::planning_interface::MoveGroupInterface::Plan right_home_plan;
  left_arm.clearPoseTargets();
  right_arm.clearPoseTargets();
  setBoundedStartState(left_arm);
  setBoundedStartState(right_arm);
  left_arm.setNamedTarget("home");
  right_arm.setNamedTarget("home");
  if (!planGroup(node, left_arm, "left pre-stir boundary home", left_home_plan) ||
      !planGroup(node, right_arm, "right pre-stir boundary home", right_home_plan) ||
      !executeMergedPlan(node, both_arms, "pre-stir boundary merged home", left_home_plan,
                         right_home_plan) ||
      !executeDualGripperTarget(node, left_gripper, right_gripper, params.final_gripper_target,
                                "pre-stir boundary close")) {
    RCLCPP_ERROR(node->get_logger(), "Failed to synchronize primitive boundary before stir steps");
    return false;
  }
  rclcpp::sleep_for(std::chrono::milliseconds(500));
  return true;
}

bool runStirAndPickupPrimitiveRange(const rclcpp::Node::SharedPtr& node,
                                    moveit::planning_interface::MoveGroupInterface& both_arms,
                                    moveit::planning_interface::MoveGroupInterface& left_arm,
                                    moveit::planning_interface::MoveGroupInterface& left_gripper,
                                    moveit::planning_interface::MoveGroupInterface& right_arm,
                                    moveit::planning_interface::MoveGroupInterface& right_gripper,
                                    const ArmConfig& left_config, const ArmConfig& right_config,
                                    ArmTask& left_task, ArmTask& right_task,
                                    const TaskParams& params, std::mutex& pose_mutex,
                                    const PoseCache& pose_cache, const PoseCache& initial_poses,
                                    size_t start_step_index, size_t end_step_index,
                                    const std::string& effective_end_step) {
  if (!rangeIncludes(start_step_index, end_step_index, kStirGraspIndex, kPickupPlaceIndex)) {
    return true;
  }

  PoseCache stir_poses = latestPoseCache(pose_mutex, pose_cache);
  if (!stir_poses.mixing.has_value() || !stir_poses.stir_stick.has_value() ||
      (stepInRange(kPickupPlaceIndex, start_step_index, end_step_index) &&
       !stir_poses.pickup.has_value())) {
    RCLCPP_ERROR(node->get_logger(), "Missing latest Gazebo poses for stir stage");
    return false;
  }

  RCLCPP_INFO(node->get_logger(),
              "Latest stir stage poses: mixing [%.3f, %.3f, %.3f], stick [%.3f, %.3f, %.3f]",
              stir_poses.mixing->position.x, stir_poses.mixing->position.y,
              stir_poses.mixing->position.z, stir_poses.stir_stick->position.x,
              stir_poses.stir_stick->position.y, stir_poses.stir_stick->position.z);

  return executeStirAndPickupStage(
      node, both_arms, left_arm, left_gripper, right_arm, right_gripper, left_config, right_config,
      left_task, right_task, params, stir_poses.mixing.value(), stir_poses.stir_stick.value(),
      stir_poses.pickup.value_or(initial_poses.pickup.value_or(stir_poses.mixing.value())),
      stepInRange(kStirGraspIndex, start_step_index, end_step_index),
      stepInRange(kStirPickLiftIndex, start_step_index, end_step_index),
      effective_end_step == "stir_stick_close" &&
          stepInRange(kStirStickCloseIndex, start_step_index, end_step_index),
      effective_end_step == "stir_hover" &&
          stepInRange(kStirHoverIndex, start_step_index, end_step_index),
      stepInRange(kStirMotionIndex, start_step_index, end_step_index),
      stepInRange(kStirCleanupIndex, start_step_index, end_step_index),
      stepInRange(kPickupPlaceIndex, start_step_index, end_step_index));
}
}  // namespace

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>(
      "beverage_making_test_node",
      rclcpp::NodeOptions().automatically_declare_parameters_from_overrides(true));

  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  const std::string water_model =
      getOrDeclareParameter<std::string>(node, "water_model", "water_cup");
  const std::string ingredient_model =
      getOrDeclareParameter<std::string>(node, "ingredient_model", "espresso_cup");
  const std::string mixing_model =
      getOrDeclareParameter<std::string>(node, "mixing_model", "mixing_cup");
  const std::string stir_stick_model =
      getOrDeclareParameter<std::string>(node, "stir_stick_model", "stir_stick");
  const std::string pickup_model =
      getOrDeclareParameter<std::string>(node, "pickup_model", "pickup_zone");
  const std::string gazebo_pose_topic =
      getOrDeclareParameter<std::string>(node, "gazebo_pose_topic", "/world/default/pose/info");
  const std::string gazebo_set_pose_service = getOrDeclareParameter<std::string>(
      node, "gazebo_set_pose_service", "/world/default/set_pose");
  const bool reset_world_on_start = getOrDeclareParameter<bool>(node, "reset_world_on_start", true);
  const double reset_world_service_timeout =
      getOrDeclareParameter<double>(node, "reset_world_service_timeout", 3.0);
  const double reset_world_settle_time =
      getOrDeclareParameter<double>(node, "reset_world_settle_time", 1.0);
  const double pose_timeout = getOrDeclareParameter<double>(node, "target_pose_timeout", 5.0);
  const double planning_time = getOrDeclareParameter<double>(node, "planning_time", 5.0);
  const int planning_attempts = getOrDeclareParameter<int>(node, "planning_attempts", 5);
  const std::string start_step = getOrDeclareParameter<std::string>(node, "start_step", "");
  const std::string end_step = getOrDeclareParameter<std::string>(node, "end_step", "");
  const bool requested_run_water = getOrDeclareParameter<bool>(node, "run_water", true);
  const bool requested_run_ingredient = getOrDeclareParameter<bool>(node, "run_ingredient", true);
  const std::vector<std::string> task_step_names{
      "cup_ready",   "cup_pre_grasp",  "cup_open",
      "cup_grasp",   "cup_close",      "cup_lift",
      "water_pour",  "water_clear",    "ingredient_pour_place",
      "stir_grasp",  "stir_pick_lift", "stir_stick_close",
      "stir_hover",  "stir_motion",    "stir_cleanup",
      "pickup_place"};

  const std::string effective_start_step =
      start_step.empty() ? task_step_names.front() : start_step;
  const std::string effective_end_step = end_step.empty() ? task_step_names.back() : end_step;
  const auto start_step_index = findStepIndex(task_step_names, effective_start_step);
  const auto end_step_index = findStepIndex(task_step_names, effective_end_step);
  if (!start_step_index.has_value() || !end_step_index.has_value()) {
    RCLCPP_ERROR(node->get_logger(),
                 "Invalid step range '%s' -> '%s'. Supported steps: cup_ready, cup_pre_grasp, "
                 "cup_open, cup_grasp, cup_close, cup_lift, water_pour, water_clear, "
                 "ingredient_pour_place, stir_grasp, stir_pick_lift, stir_stick_close, stir_hover, "
                 "stir_motion, stir_cleanup, pickup_place",
                 effective_start_step.c_str(), effective_end_step.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  if (start_step_index.value() > end_step_index.value()) {
    RCLCPP_ERROR(node->get_logger(),
                 "Invalid step range '%s' -> '%s': start_step must be before or equal to end_step",
                 effective_start_step.c_str(), effective_end_step.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }

  if (reset_world_on_start) {
    const std::vector<GazeboModelInitialPose> initial_model_poses{
        {"espresso_cup", makePose(0.38, 0.21, 0.425)},
        {"ade_cup", makePose(0.38, 0.07, 0.425)},
        {mixing_model, makePose(0.38, -0.08, 0.425)},
        {water_model, makePose(0.38, -0.22, 0.425)},
        {"stir_stick_holder", makePose(0.38, 0.36, 0.37)},
        {stir_stick_model, makePose(0.38, 0.36, 0.48)},
        {pickup_model, makePose(0.025, -0.50, 0.35)}};
    RCLCPP_INFO(node->get_logger(),
                "Resetting Gazebo beverage objects before task execution through '%s'",
                gazebo_set_pose_service.c_str());
    if (!resetGazeboBeverageObjects(node, gazebo_set_pose_service, initial_model_poses,
                                    reset_world_service_timeout, reset_world_settle_time)) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }

  const bool requires_cup_tasks = rangeIncludes(start_step_index.value(), end_step_index.value(),
                                                kCupReadyIndex, kIngredientPourPlaceIndex);
  const bool requires_stir_tasks = rangeIncludes(start_step_index.value(), end_step_index.value(),
                                                 kStirGraspIndex, kPickupPlaceIndex);
  const bool requires_pickup_zone_task = rangeIncludes(
      start_step_index.value(), end_step_index.value(), kPickupPlaceIndex, kPickupPlaceIndex);
  const bool requires_mixing_pose = requires_cup_tasks || requires_stir_tasks;
  const bool run_water = requires_cup_tasks && requested_run_water;
  const bool run_ingredient = requires_cup_tasks && requested_run_ingredient;
  const std::string dual_arm_group =
      getOrDeclareParameter<std::string>(node, "dual_arm_group", "both_arms");

  TaskParams params;
  params.approach_distance = getOrDeclareParameter<double>(node, "approach_distance", 0.10);
  params.gripper_center_forward_offset =
      getOrDeclareParameter<double>(node, "gripper_center_forward_offset", 0.145);
  const double legacy_grasp_inward_offset =
      getOrDeclareParameter<double>(node, "grasp_inward_offset", 0.013);
  params.cup_grasp_profile = ObjectGraspProfile{
      "cup",
      GraspPointMode::ObjectCenter,
      getOrDeclareParameter<double>(node, "cup_grasp_height_offset", 0.0),
      getOrDeclareParameter<double>(node, "cup_grasp_inward_offset", legacy_grasp_inward_offset),
      0.0,
      0.0,
      0.0,
      getOrDeclareParameter<std::string>(node, "pick_gripper_target", "half_closed")};
  params.cartesian_eef_step = getOrDeclareParameter<double>(node, "cartesian_eef_step", 0.005);
  params.min_cartesian_fraction =
      getOrDeclareParameter<double>(node, "min_cartesian_fraction", 0.95);
  params.min_grasp_approach_fallback_fraction =
      getOrDeclareParameter<double>(node, "min_grasp_approach_fallback_fraction", 0.85);
  params.allow_planned_grasp_approach_fallback =
      getOrDeclareParameter<bool>(node, "allow_planned_grasp_approach_fallback", true);
  params.cartesian_avoid_collisions =
      getOrDeclareParameter<bool>(node, "cartesian_avoid_collisions", false);
  params.lift_height = getOrDeclareParameter<double>(node, "lift_height", 0.12);
  params.mixing_hover_height_offset =
      getOrDeclareParameter<double>(node, "mixing_hover_height_offset", 0.16);
  params.post_pour_clearance_height_offset =
      getOrDeclareParameter<double>(node, "post_pour_clearance_height_offset", 0.16);
  params.place_tcp_backward_offset =
      getOrDeclareParameter<double>(node, "place_tcp_backward_offset", 0.0);
  params.pour_target_lateral_offset =
      getOrDeclareParameter<double>(node, "pour_target_lateral_offset", 0.08);
  params.pour_axis = getOrDeclareParameter<std::string>(node, "pour_axis", "local_z");
  params.pour_angle = getOrDeclareParameter<double>(node, "pour_angle", 1.05);
  params.pour_hold_time = getOrDeclareParameter<double>(node, "pour_hold_time", 1.0);
  params.pour_waypoint_count = getOrDeclareParameter<int>(node, "pour_waypoint_count", 8);
  const bool vertical_stir_stick = getOrDeclareParameter<bool>(node, "vertical_stir_stick", true);
  params.stir_stick_grasp_profile = ObjectGraspProfile{
      "stir_stick",
      vertical_stir_stick ? GraspPointMode::VerticalStick : GraspPointMode::HorizontalStickEnd,
      getOrDeclareParameter<double>(node, "vertical_stir_stick_grasp_height_offset", 0.045),
      getOrDeclareParameter<double>(node, "stir_stick_grasp_inward_offset", 0.012),
      getOrDeclareParameter<double>(node, "stir_stick_length", 0.18),
      getOrDeclareParameter<double>(node, "stir_stick_grasp_inset", 0.02),
      getOrDeclareParameter<double>(node, "stir_stick_roll_angle", std::acos(-1.0) / 2.0),
      getOrDeclareParameter<std::string>(node, "stir_stick_gripper_target", "closed")};
  params.stir_hover_height_offset =
      getOrDeclareParameter<double>(node, "stir_hover_height_offset", 0.13);
  params.stir_cup_stage_x_offset =
      getOrDeclareParameter<double>(node, "stir_cup_stage_x_offset", 0.0);
  params.stir_cup_stage_y = getOrDeclareParameter<double>(node, "stir_cup_stage_y", 0.0);
  params.stir_cup_stage_height_offset =
      getOrDeclareParameter<double>(node, "stir_cup_stage_height_offset", 0.07);
  params.stir_stick_insert_hover_height_offset =
      getOrDeclareParameter<double>(node, "stir_stick_insert_hover_height_offset", 0.25);
  params.stir_stick_insert_depth_height_offset =
      getOrDeclareParameter<double>(node, "stir_stick_insert_depth_height_offset", 0.10);
  params.stir_transport_retreat_distance =
      getOrDeclareParameter<double>(node, "stir_transport_retreat_distance", 0.18);
  params.stir_transport_extra_height =
      getOrDeclareParameter<double>(node, "stir_transport_extra_height", 0.08);
  params.left_stir_entry_guide_joints =
      getOrDeclareParameter<std::vector<double>>(node, "left_stir_entry_guide_joints", {});
  params.left_stir_lift_guide_joints =
      getOrDeclareParameter<std::vector<double>>(node, "left_stir_lift_guide_joints", {});
  params.left_stir_transport_guide_joints =
      getOrDeclareParameter<std::vector<double>>(node, "left_stir_transport_guide_joints", {});
  params.stir_radius = getOrDeclareParameter<double>(node, "stir_radius", 0.008);
  params.stir_cycles = getOrDeclareParameter<int>(node, "stir_cycles", 1);
  params.stir_waypoint_count = getOrDeclareParameter<int>(node, "stir_waypoint_count", 12);
  params.right_mixing_pregrasp_lateral_offset =
      getOrDeclareParameter<double>(node, "right_mixing_pregrasp_lateral_offset", 0.0);
  params.pickup_cup_center_height_offset =
      getOrDeclareParameter<double>(node, "pickup_cup_center_height_offset", 0.075);
  params.pickup_hover_height_offset =
      getOrDeclareParameter<double>(node, "pickup_hover_height_offset", 0.28);
  params.pickup_transfer_lift_height =
      getOrDeclareParameter<double>(node, "pickup_transfer_lift_height", 0.28);
  params.pickup_transfer_x = getOrDeclareParameter<double>(node, "pickup_transfer_x", 0.25);
  params.pickup_transfer_y = getOrDeclareParameter<double>(node, "pickup_transfer_y", -0.425);
  params.pickup_table_size_x = getOrDeclareParameter<double>(node, "pickup_table_size_x", 0.65);
  params.pickup_table_size_y = getOrDeclareParameter<double>(node, "pickup_table_size_y", 0.27);
  params.pickup_table_edge_margin =
      getOrDeclareParameter<double>(node, "pickup_table_edge_margin", 0.06);
  params.pickup_release_retreat_distance =
      getOrDeclareParameter<double>(node, "pickup_release_retreat_distance", 0.05);
  params.pickup_release_settle_time =
      getOrDeclareParameter<double>(node, "pickup_release_settle_time", 0.8);
  params.pickup_release_vertical_retreat_height =
      getOrDeclareParameter<double>(node, "pickup_release_vertical_retreat_height", 0.08);
  params.dynamic_waypoint_lift = getOrDeclareParameter<double>(node, "dynamic_waypoint_lift", 0.08);
  params.right_pickup_transfer_guide_joints =
      getOrDeclareParameter<std::vector<double>>(node, "right_pickup_transfer_guide_joints", {});
  params.right_pickup_home_guide_joints =
      getOrDeclareParameter<std::vector<double>>(node, "right_pickup_home_guide_joints", {});
  params.final_gripper_target =
      getOrDeclareParameter<std::string>(node, "final_gripper_target", "closed");

  const std::vector<double> default_left_ready{
      1.239329032213002,     0.0010114715451901488,  -0.0009259087954886816, 1.718774510702148,
      0.0010237185554880786, -0.0010588666577850028, -1.0783557656423297};
  const std::vector<double> default_right_ready{
      -1.239329032213002,     0.0010114715451901488,  0.0009259087954886816, 1.718774510702148,
      -0.0010237185554880786, -0.0010588666577850028, 1.0783557656423297};

  ArmConfig left_config;
  left_config.label = "left/ingredient";
  left_config.arm_group = "left_arm";
  left_config.gripper_group = "left_gripper";
  left_config.tcp_link = "openarm_left_hand_tcp";
  left_config.ready_pose_name = "left_cup_pick_ready";
  left_config.ready_joints =
      getOrDeclareParameter<std::vector<double>>(node, "left_ready_joints", default_left_ready);

  ArmConfig right_config;
  right_config.label = "right/water";
  right_config.arm_group = "right_arm";
  right_config.gripper_group = "right_gripper";
  right_config.tcp_link = "openarm_right_hand_tcp";
  right_config.ready_pose_name = "right_cup_pick_ready";
  right_config.ready_joints =
      getOrDeclareParameter<std::vector<double>>(node, "right_ready_joints", default_right_ready);

  moveit::planning_interface::MoveGroupInterface both_arms(node, dual_arm_group);
  moveit::planning_interface::MoveGroupInterface left_arm(node, left_config.arm_group);
  moveit::planning_interface::MoveGroupInterface left_gripper(node, left_config.gripper_group);
  moveit::planning_interface::MoveGroupInterface right_arm(node, right_config.arm_group);
  moveit::planning_interface::MoveGroupInterface right_gripper(node, right_config.gripper_group);

  const std::string planning_frame = both_arms.getPlanningFrame();
  left_arm.setPoseReferenceFrame(planning_frame);
  right_arm.setPoseReferenceFrame(planning_frame);
  const bool left_tcp_set = left_arm.setEndEffectorLink(left_config.tcp_link);
  const bool right_tcp_set = right_arm.setEndEffectorLink(right_config.tcp_link);
  RCLCPP_INFO(
      node->get_logger(),
      "MoveIt Cartesian frame setup: planning_frame='%s', left_eef='%s' (%s), right_eef='%s' (%s)",
      planning_frame.c_str(), left_arm.getEndEffectorLink().c_str(), left_tcp_set ? "ok" : "failed",
      right_arm.getEndEffectorLink().c_str(), right_tcp_set ? "ok" : "failed");

  both_arms.setPlanningTime(planning_time);
  both_arms.setNumPlanningAttempts(planning_attempts);
  both_arms.setMaxVelocityScalingFactor(0.2);
  both_arms.setMaxAccelerationScalingFactor(0.2);
  left_arm.setPlanningTime(planning_time);
  left_arm.setNumPlanningAttempts(planning_attempts);
  right_arm.setPlanningTime(planning_time);
  right_arm.setNumPlanningAttempts(planning_attempts);

  ArmTask left_task(node, left_arm, left_gripper, left_config, params);
  ArmTask right_task(node, right_arm, right_gripper, right_config, params);

  std::mutex pose_mutex;
  PoseCache pose_cache;
  gz::transport::Node gz_node;
  const bool subscribed =
      gz_node.Subscribe<gz::msgs::Pose_V>(gazebo_pose_topic, [&](const gz::msgs::Pose_V& msg) {
        std::lock_guard<std::mutex> lock(pose_mutex);
        for (int i = 0; i < msg.pose_size(); ++i) {
          const auto& pose = msg.pose(i);
          if (pose.name() == water_model) {
            pose_cache.water = toPoseMsg(pose);
          } else if (pose.name() == ingredient_model) {
            pose_cache.ingredient = toPoseMsg(pose);
          } else if (pose.name() == mixing_model) {
            pose_cache.mixing = toPoseMsg(pose);
          } else if (pose.name() == stir_stick_model) {
            pose_cache.stir_stick = toPoseMsg(pose);
          } else if (pose.name() == pickup_model) {
            pose_cache.pickup = toPoseMsg(pose);
          }
        }
      });

  if (!subscribed) {
    RCLCPP_ERROR(node->get_logger(), "Failed to subscribe to Gazebo pose topic: %s",
                 gazebo_pose_topic.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }

  RCLCPP_INFO(node->get_logger(),
              "Step range '%s' -> '%s': waiting for water '%s', ingredient '%s', mixing '%s', stir "
              "stick '%s', pickup '%s' poses on %s",
              effective_start_step.c_str(), effective_end_step.c_str(), water_model.c_str(),
              ingredient_model.c_str(), mixing_model.c_str(), stir_stick_model.c_str(),
              pickup_model.c_str(), gazebo_pose_topic.c_str());

  const auto wait_start = std::chrono::steady_clock::now();
  rclcpp::Rate wait_rate(50.0);
  while (rclcpp::ok() &&
         std::chrono::duration<double>(std::chrono::steady_clock::now() - wait_start).count() <
             pose_timeout) {
    {
      std::lock_guard<std::mutex> lock(pose_mutex);
      const bool have_water = !run_water || pose_cache.water.has_value();
      const bool have_ingredient = !run_ingredient || pose_cache.ingredient.has_value();
      const bool have_stir_stick = !requires_stir_tasks || pose_cache.stir_stick.has_value();
      const bool have_pickup = !requires_pickup_zone_task || pose_cache.pickup.has_value();
      const bool have_mixing = !requires_mixing_pose || pose_cache.mixing.has_value();
      if (have_water && have_ingredient && have_mixing && have_stir_stick && have_pickup) {
        break;
      }
    }
    wait_rate.sleep();
  }

  PoseCache poses;
  {
    std::lock_guard<std::mutex> lock(pose_mutex);
    poses = pose_cache;
  }

  if (run_water && !poses.water.has_value()) {
    RCLCPP_ERROR(node->get_logger(), "Timed out waiting for water model '%s'", water_model.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  if (run_ingredient && !poses.ingredient.has_value()) {
    RCLCPP_ERROR(node->get_logger(), "Timed out waiting for ingredient model '%s'",
                 ingredient_model.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  if (requires_mixing_pose && !poses.mixing.has_value()) {
    RCLCPP_ERROR(node->get_logger(), "Timed out waiting for mixing model '%s'",
                 mixing_model.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  if (requires_stir_tasks && !poses.stir_stick.has_value()) {
    RCLCPP_ERROR(node->get_logger(), "Timed out waiting for stir stick model '%s'",
                 stir_stick_model.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  if (requires_pickup_zone_task && !poses.pickup.has_value()) {
    RCLCPP_ERROR(node->get_logger(), "Timed out waiting for pickup model '%s'",
                 pickup_model.c_str());
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }
  std::optional<ArmContext> left_context;
  std::optional<ArmContext> right_context;
  if (run_ingredient) {
    left_context = left_task.computeContext(poses.ingredient.value(), poses.mixing.value());
    if (!left_context.has_value()) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }
  if (run_water) {
    right_context = right_task.computeContext(poses.water.value(), poses.mixing.value());
    if (!right_context.has_value()) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }

  RCLCPP_INFO(node->get_logger(), "Executing primitive step range '%s' -> '%s'",
              effective_start_step.c_str(), effective_end_step.c_str());

  if (!runCupPrimitiveSteps(node, both_arms, left_arm, left_gripper, right_arm, right_gripper,
                            left_config, right_config, params, run_water, run_ingredient,
                            start_step_index.value(), end_step_index.value(), pose_mutex,
                            pose_cache, left_context, right_context)) {
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }

  if (stepInRange(kWaterPourIndex, start_step_index.value(), end_step_index.value())) {
    refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm, left_config,
                                    right_config, params, run_ingredient, run_water, left_context,
                                    right_context);
    if (!runWaterPourPrimitive(node, pose_mutex, pose_cache, poses, right_task, right_context)) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }

  if (stepInRange(kWaterClearIndex, start_step_index.value(), end_step_index.value())) {
    if (!runWaterClearPrimitive(node, pose_mutex, pose_cache, poses, right_task, right_context)) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
    refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm, left_config,
                                    right_config, params, run_ingredient, run_water, left_context,
                                    right_context);
  }

  if (stepInRange(kIngredientPourPlaceIndex, start_step_index.value(), end_step_index.value())) {
    refreshHeldCupTargetsFromGazebo(node, pose_mutex, pose_cache, left_arm, right_arm, left_config,
                                    right_config, params, run_ingredient, run_water, left_context,
                                    right_context);
    if (!runIngredientPourPlacePrimitive(node, both_arms, left_arm, left_gripper, right_arm,
                                         right_gripper, params, pose_mutex, pose_cache, poses,
                                         left_context, right_context)) {
      RCLCPP_ERROR(node->get_logger(), "Ingredient pour/place primitive failed");
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }

  if (requires_cup_tasks && rangeIncludes(start_step_index.value(), end_step_index.value(),
                                          kStirGraspIndex, kPickupPlaceIndex)) {
    if (!runPreStirBoundaryPrimitive(node, both_arms, left_arm, left_gripper, right_arm,
                                     right_gripper, params)) {
      rclcpp::shutdown();
      spinner.join();
      return 1;
    }
  }

  if (!runStirAndPickupPrimitiveRange(
          node, both_arms, left_arm, left_gripper, right_arm, right_gripper, left_config,
          right_config, left_task, right_task, params, pose_mutex, pose_cache, poses,
          start_step_index.value(), end_step_index.value(), effective_end_step)) {
    RCLCPP_ERROR(node->get_logger(), "Stir primitive steps failed");
    rclcpp::shutdown();
    spinner.join();
    return 1;
  }

  RCLCPP_INFO(node->get_logger(), "Beverage task manager sequence completed");
  rclcpp::shutdown();
  spinner.join();
  return 0;
}
