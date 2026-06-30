#pragma once

#include <string>
#include <vector>

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

enum class GripperPickAction
{
  Open,
  Close,
};

struct MotionPrimitiveConfig
{
  // 런타임 MoveIt 설정을 primitive 계층에서 사용할 형태로 모은다.
  double cartesian_eef_step{task_presets::kDefaultCartesian.eef_step_m};
  double cartesian_min_fraction{task_presets::kDefaultCartesian.min_fraction};
  bool cartesian_avoid_collisions{task_presets::kDefaultCartesian.avoid_collisions};
  double cartesian_velocity_scaling{task_presets::kDefaultMotionScaling.arm_velocity_scaling};
  double cartesian_acceleration_scaling{task_presets::kDefaultMotionScaling.arm_acceleration_scaling};
  double cartesian_min_duration_sec{task_presets::kDefaultCartesian.min_duration_sec};
  double pose_min_duration_sec{task_presets::kDefaultPlanning.pose_min_duration_sec};
  int pose_max_attempts{task_presets::kDefaultPlanExecuteMaxAttempts};
  std::string gripper_open_target{"open"};
  std::string gripper_grasp_target{"half_closed"};
};

// task 조립에서 공통으로 사용하는 동작 단위.
// task 파일은 MoveIt helper를 직접 부르지 않고 이 primitive를 조합한다.
class ManufacturingMotionPrimitives
{
public:
  ManufacturingMotionPrimitives(
    const rclcpp::Logger & logger,
    MotionPrimitiveConfig config);

  // ready/home/open 같은 named joint target으로 이동한다.
  bool moveToNamed(
    moveit::planning_interface::MoveGroupInterface & group,
    const std::string & target_name,
    const std::string & label,
    double min_duration_sec = -1.0) const;

  // 설정된 pose planner로 절대 엔드이펙터 pose까지 이동한다.
  bool moveToPose(
    moveit::planning_interface::MoveGroupInterface & arm,
    const geometry_msgs::msg::Pose & target_pose,
    const std::string & tcp_link,
    const std::string & label,
    double min_duration_sec = -1.0) const;

  // 한 번의 pose 이동에 대해서만 arm velocity/acceleration scaling을 임시 적용한다.
  bool moveToPoseWithScaling(
    moveit::planning_interface::MoveGroupInterface & arm,
    const geometry_msgs::msg::Pose & target_pose,
    const std::string & tcp_link,
    const std::string & label,
    double current_velocity_scaling,
    double current_acceleration_scaling,
    double scoped_velocity_scaling,
    double scoped_acceleration_scaling,
    double min_duration_sec = -1.0) const;

  // 단일 target pose로 Cartesian 이동을 수행한다.
  bool cartesianMoveToPose(
    moveit::planning_interface::MoveGroupInterface & arm,
    const geometry_msgs::msg::Pose & target_pose,
    const std::string & label,
    bool avoid_collisions,
    double min_duration_sec = -1.0) const;

  // 명시된 waypoint 목록을 따라 Cartesian 이동을 수행한다.
  bool cartesianMove(
    moveit::planning_interface::MoveGroupInterface & arm,
    const std::vector<geometry_msgs::msg::Pose> & waypoints,
    const std::string & label,
    bool avoid_collisions,
    double min_duration_sec = -1.0) const;

  // Cartesian 이동을 먼저 시도하고, 필요하면 pose planning으로 fallback한다.
  bool cartesianMoveToPoseWithPlanningFallback(
    moveit::planning_interface::MoveGroupInterface & arm,
    const geometry_msgs::msg::Pose & target_pose,
    const std::string & tcp_link,
    const std::string & cartesian_label,
    const std::string & planned_label,
    bool allow_planned_fallback,
    bool avoid_collisions,
    double planned_min_duration_sec = -1.0) const;

  // 현재 TCP pose 기준으로 지정한 방향만큼 clearance를 확보한다.
  bool clearance(
    moveit::planning_interface::MoveGroupInterface & arm,
    const std::string & tcp_link,
    const std::string & label,
    const Eigen::Vector3d & direction,
    double distance_m,
    bool avoid_collisions,
    double min_duration_sec = -1.0) const;

  // 현재 TCP pose 기준의 일반 상대 Cartesian 이동이다.
  bool moveRelative(
    moveit::planning_interface::MoveGroupInterface & arm,
    const std::string & tcp_link,
    const std::string & label,
    const Eigen::Vector3d & direction,
    double distance_m,
    bool avoid_collisions,
    double min_duration_sec = -1.0) const;

  // gripper를 open/half_closed 같은 named target으로 이동한다.
  bool gripperNamedTarget(
    moveit::planning_interface::MoveGroupInterface & gripper,
    const std::string & target_name,
    const std::string & label) const;

  // 대상 물체별 pick tuning을 적용해 gripper open/close를 수행한다.
  bool gripperPickAction(
    moveit::planning_interface::MoveGroupInterface & gripper,
    const std::string & label,
    const task_presets::PickTuningPreset & tuning,
    GripperPickAction action) const;

  // squeeze나 특수 release에 쓰는 gripper joint position 직접 명령이다.
  bool gripperJointPosition(
    moveit::planning_interface::MoveGroupInterface & gripper,
    const std::string & label,
    const std::string & action,
    double joint_position) const;

private:
  double poseMinDuration(double override_sec) const;
  double cartesianMinDuration(double override_sec) const;

  rclcpp::Logger logger_;
  MotionPrimitiveConfig config_;
};

}  // namespace ddooby_controller::manufacturing_task
