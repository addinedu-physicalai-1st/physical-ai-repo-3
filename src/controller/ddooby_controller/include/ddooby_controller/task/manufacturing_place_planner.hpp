#pragma once

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task {

struct SausagePlacePlan {
  geometry_msgs::msg::Pose approach_pose;
  geometry_msgs::msg::Pose release_pose;
  bool approach_reuses_completed_work_pose{false};
  bool lower_to_release_pose{true};
};

struct KetchupSqueezePlan {
  geometry_msgs::msg::Pose aim_pose;
  geometry_msgs::msg::Pose squeeze_pose;
};

struct KetchupReturnPlacePlan {
  geometry_msgs::msg::Pose return_pose;
  geometry_msgs::msg::Pose lift_pose;
};

struct KetchupPostReleaseRetreatPlan {
  geometry_msgs::msg::Pose horizontal_retreat_pose;
  geometry_msgs::msg::Pose clear_retreat_pose;
};

struct CompletedHotdogPlacePlan {
  geometry_msgs::msg::Pose approach_pose;
  geometry_msgs::msg::Pose release_pose;
  bool release_pose_preset_configured{false};
};

struct BeverageHandoffPlan {
  geometry_msgs::msg::Pose left_handoff_pose;
  geometry_msgs::msg::Pose right_pre_receive_pose;
  geometry_msgs::msg::Pose right_receive_pose;
  bool right_pre_receive_pose_preset_enabled{false};
};

struct BeveragePickupPlacePlan {
  geometry_msgs::msg::Pose approach_pose;
  geometry_msgs::msg::Pose release_pose;
  bool approach_preset_enabled{false};
  bool release_preset_enabled{false};
};

SausagePlacePlan makeSausagePlacePlan(
    const rclcpp::Logger& logger, const TargetObject& sausage_target,
    const TargetObject& bread_target, const TargetObject& case_target,
    const Eigen::Vector3d& held_case_center, const geometry_msgs::msg::Pose& left_current_pose,
    bool has_completed_left_work_pose, const geometry_msgs::msg::Pose& completed_left_work_pose,
    double place_approach_height_m, double case_sausage_place_clearance_m);

KetchupSqueezePlan makeKetchupSqueezePlan(
    const rclcpp::Logger& logger, const TargetObject& sausage_target,
    const TargetObject& bread_target, const TargetObject& case_target,
    const Eigen::Vector3d& held_case_center, const geometry_msgs::msg::Pose& left_current_pose,
    double ketchup_squeeze_height_m, double ketchup_squeeze_length_m);

KetchupReturnPlacePlan makeKetchupReturnPlacePlan(const rclcpp::Logger& logger,
                                                  const TargetObject& ketchup_target,
                                                  double ketchup_pre_grasp_distance_m,
                                                  double lift_height_m);

KetchupPostReleaseRetreatPlan makeKetchupPostReleaseRetreatPlan(
    const geometry_msgs::msg::Pose& return_pose, const geometry_msgs::msg::Pose& return_lift_pose);

CompletedHotdogPlacePlan makeCompletedHotdogPlacePlan(const rclcpp::Logger& logger,
                                                      const TargetObject& pickup_zone,
                                                      const TargetObject& case_target,
                                                      const geometry_msgs::msg::Pose& current_pose);

BeverageHandoffPlan makeBeverageHandoffPlan(const rclcpp::Logger& logger,
                                            task_presets::ManufacturingTarget beverage_target,
                                            const TargetObject& beverage_target_object,
                                            const geometry_msgs::msg::Pose& left_current_pose);

BeveragePickupPlacePlan makeBeveragePickupPlacePlan(
    const rclcpp::Logger& logger, task_presets::ManufacturingTarget beverage_target,
    const TargetObject& beverage_target_object, const TargetObject& pickup_zone,
    const geometry_msgs::msg::Pose& right_current_pose);

}  // namespace ddooby_controller::manufacturing_task
