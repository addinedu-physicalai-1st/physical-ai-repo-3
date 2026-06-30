#pragma once

#include <Eigen/Geometry>
#include <geometry_msgs/msg/pose.hpp>
#include <map>
#include <memory>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <rclcpp/rclcpp.hpp>
#include <set>
#include <string>
#include <vector>
#include <vision_msgs/msg/detection3_d_array.hpp>

#include "ddooby_controller/control/manufacturing_motion_primitives.hpp"
#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"
#include "ddooby_controller/vision/vision_pick_adapter.hpp"

namespace ddooby_controller {

namespace task_presets = manufacturing_task_presets;
using ManufacturingStage = task_presets::ManufacturingStage;
using ManufacturingTarget = task_presets::ManufacturingTarget;
using ArmSide = task_presets::ArmSide;
using manufacturing_task::ManufacturingMotionPrimitives;
using manufacturing_task::MotionPrimitiveConfig;
using manufacturing_task::MotionStepResult;
using manufacturing_task::OptionalStageWaypoint;
using manufacturing_task::PickMotionConfig;
using manufacturing_task::PickPlan;
using manufacturing_task::PreGraspGoalMode;
using manufacturing_task::TargetObject;
using manufacturing_task::VisionPickAdapter;
using manufacturing_task::VisionPickDetection;
using manufacturing_task::VisionPickMatchConfig;

class HotdogMakingNode : public rclcpp::Node {
 public:
  HotdogMakingNode();
  HotdogMakingNode(const HotdogMakingNode&) = delete;
  HotdogMakingNode& operator=(const HotdogMakingNode&) = delete;

  bool run();

 private:
  // Runtime configuration and high-level task flow.
  void declareRuntimeParameters();
  void declareTaskSelectionParameters();
  void declareArmGroupParameters();
  void declareMotionPlanningParameters();
  void declareManufacturingGeometryParameters();
  void declareToolAndSceneParameters();
  void declareVisionPickParameters();
  void configureVisionSubscription();
  void parseExecutionRequest();
  bool runScenario();
  bool runHotdogAssemblyUntil(ManufacturingTarget endpoint);
  bool shouldStopAfter(ManufacturingStage stage) const;
  bool shouldStopAfterWaypoint(ManufacturingStage stage, const std::string& waypoint) const;
  bool shouldRunStage(ManufacturingStage stage) const;
  bool shouldStopAtOrBefore(ManufacturingStage stage) const;
  bool shouldStopAtOrBeforeWaypointStage(ManufacturingStage stage) const;
  bool configureTaskArm(moveit::planning_interface::MoveGroupInterface& arm,
                        const std::string& tcp_link, double velocity_scaling,
                        double acceleration_scaling);
  bool configureTaskArm(moveit::planning_interface::MoveGroupInterface& arm,
                        const std::string& tcp_link);
  void configureTaskGripper(moveit::planning_interface::MoveGroupInterface& gripper);
  MotionPrimitiveConfig motionPrimitiveConfig() const;
  ManufacturingMotionPrimitives makeMotionPrimitives() const;
  bool planAndExecuteReturnHome(moveit::planning_interface::MoveGroupInterface& arm,
                                ManufacturingTarget target, ArmSide arm_side,
                                const std::string& tcp_link, const std::string& label);
  bool runSingleArmReturnHome(ManufacturingTarget target, ArmSide arm_side,
                              const std::string& arm_group, const std::string& tcp_link,
                              const std::string& label);
  void sleepStep() const;

  // Generic pick execution.
  bool prepareAndRunPickMotion(const PickMotionConfig& config, const TargetObject& target,
                               PickPlan pick_plan);
  MotionStepResult runPickHomeStage(const PickMotionConfig& config,
                                    moveit::planning_interface::MoveGroupInterface& arm);
  MotionStepResult runOptionalStageWaypoint(const PickMotionConfig& config,
                                            moveit::planning_interface::MoveGroupInterface& arm,
                                            const OptionalStageWaypoint& stage_waypoint);
  MotionStepResult runPickPreGraspStage(const PickMotionConfig& config,
                                        const task_presets::PickTuningPreset& tuning,
                                        const PickPlan& pick_plan, bool pre_grasp_pose_configured,
                                        moveit::planning_interface::MoveGroupInterface& arm,
                                        moveit::planning_interface::MoveGroupInterface& gripper,
                                        bool& gripper_opened_for_approach,
                                        PreGraspGoalMode& pre_grasp_goal_mode,
                                        geometry_msgs::msg::Pose& reached_pre_grasp_pose);
  MotionStepResult runPickGraspAttachAndDirectLift(
      const PickMotionConfig& config, const task_presets::PickTuningPreset& tuning,
      const TargetObject& target,
      moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
      moveit::planning_interface::MoveGroupInterface& arm,
      moveit::planning_interface::MoveGroupInterface& gripper, bool gripper_opened_for_approach,
      const geometry_msgs::msg::Pose& grasp_pose, const geometry_msgs::msg::Pose& lift_pose);
  MotionStepResult runPickPullOutAndLift(const PickMotionConfig& config, const PickPlan& pick_plan,
                                         moveit::planning_interface::MoveGroupInterface& arm,
                                         geometry_msgs::msg::Pose& lift_pose);
  MotionStepResult runPickTargetAlignment(const PickMotionConfig& config, const PickPlan& pick_plan,
                                          const geometry_msgs::msg::Pose& grasp_pose,
                                          bool pre_grasp_pose_configured, bool pick_pose_configured,
                                          moveit::planning_interface::MoveGroupInterface& arm,
                                          geometry_msgs::msg::Pose& reached_pre_grasp_pose);

  // Target loading, vision pick matching, and collision object synchronization.
  bool resolvePackageShareDirectory(std::string& package_share_directory);
  bool loadManufacturingTarget(const std::string& target_model, TargetObject& target);
  bool moveArmToReadyBeforeVisionPick(const std::string& log_label, const std::string& arm_group,
                                      const std::string& ready_pose_name,
                                      const std::vector<double>& ready_joints);
  bool loadTargetForVisionPick(ManufacturingTarget target_kind, const std::string& log_label,
                               const std::string& arm_group, const std::string& ready_pose_name,
                               const std::vector<double>& ready_joints,
                               const std::string& target_model, TargetObject& target);
  VisionPickMatchConfig visionPickMatchConfig() const;
  bool applyVisionPickTarget(ManufacturingTarget target_kind, const std::string& target_model,
                             TargetObject& target);
  bool applyVisionCollisionObjectIfNeeded(
      moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
      const TargetObject& target, const std::string& log_label);
  bool restoreTargetCollisionObject(
      moveit::planning_interface::PlanningSceneInterface& planning_scene_interface,
      const std::string& target_model, const std::string& log_label);

  // Concrete manufacturing tasks.
  bool runBreadPick();
  bool runCasePick();
  bool runSausagePick();
  bool runBeverageCanPick(ManufacturingTarget beverage_target);
  MotionStepResult runBeveragePickStageIfNeeded(ManufacturingTarget beverage_target);
  bool loadBeverageServeTargets(ManufacturingTarget beverage_target,
                                std::string& beverage_target_model,
                                TargetObject& beverage_target_object, TargetObject& pickup_zone);
  MotionStepResult runBeverageHandoffStage(
      ManufacturingTarget beverage_target, const std::string& beverage_target_model,
      const TargetObject& beverage_target_object,
      moveit::planning_interface::MoveGroupInterface& left_arm,
      moveit::planning_interface::MoveGroupInterface& left_gripper,
      moveit::planning_interface::MoveGroupInterface& right_arm,
      moveit::planning_interface::MoveGroupInterface& right_gripper);
  MotionStepResult runBeveragePlaceStage(
      ManufacturingTarget beverage_target, const std::string& beverage_target_model,
      const TargetObject& beverage_target_object, const TargetObject& pickup_zone,
      moveit::planning_interface::MoveGroupInterface& left_arm,
      moveit::planning_interface::MoveGroupInterface& right_arm,
      moveit::planning_interface::MoveGroupInterface& right_gripper);
  bool runBeverageCanServe(ManufacturingTarget beverage_target);
  bool runKetchupPick();
  bool runBreadPlace();
  bool runSausagePlace();
  MotionStepResult runKetchupPickStageIfNeeded();
  bool loadKetchupSqueezeTargets(std::string& ketchup_target_model, TargetObject& sausage_target,
                                 TargetObject& bread_target, TargetObject& case_target,
                                 TargetObject& ketchup_target);
  bool runKetchupSqueeze();
  MotionStepResult runCompletedHotdogCarryWaypoints(
      moveit::planning_interface::MoveGroupInterface& right_arm,
      const geometry_msgs::msg::Pose& current_pose, const geometry_msgs::msg::Pose& release_pose,
      bool release_pose_preset_configured, double carry_min_duration_sec);
  MotionStepResult runCompletedHotdogApproachAndLower(
      moveit::planning_interface::MoveGroupInterface& right_arm,
      const geometry_msgs::msg::Pose& approach_pose, const geometry_msgs::msg::Pose& release_pose,
      bool release_pose_preset_configured, double carry_velocity_scaling,
      double carry_acceleration_scaling, double carry_min_duration_sec);
  MotionStepResult runCompletedHotdogReleaseAndReturn(
      moveit::planning_interface::MoveGroupInterface& right_arm,
      moveit::planning_interface::MoveGroupInterface& right_gripper,
      const geometry_msgs::msg::Pose& approach_pose, const geometry_msgs::msg::Pose& release_pose,
      double carry_velocity_scaling, double carry_acceleration_scaling,
      double carry_min_duration_sec);
  bool runCompletedHotdogPlace();

  // Headless Gazebo result validation.
  bool shouldValidateGazeboResult() const;
  bool validateFinalHotdogPlacement();
  bool validateFinalBeveragePlacement(ManufacturingTarget beverage_target);

  std::string item_name_;
  bool scenario_only_{true};
  int step_delay_ms_{150};
  std::string task_name_;
  std::string arm_name_;
  ManufacturingTarget target_{ManufacturingTarget::Bread};
  ArmSide arm_{ArmSide::Left};
  std::string target_model_;
  std::string case_target_model_;
  std::string bread_target_model_;
  std::string sausage_target_model_;
  std::string ketchup_target_model_;
  std::string coke_target_model_;
  std::string coffee_target_model_;
  ManufacturingStage start_stage_{ManufacturingStage::Home};
  std::string play_to_stage_name_;
  std::string start_from_waypoint_name_;
  bool has_play_to_stage_{false};
  ManufacturingStage play_to_stage_{ManufacturingStage::Home};
  std::string play_to_waypoint_name_;
  std::string play_to_waypoint_;
  bool play_range_valid_{true};
  std::string layout_path_;
  bool has_package_share_directory_{false};
  std::string package_share_directory_;
  std::string left_arm_group_;
  std::string left_gripper_group_;
  std::string left_tcp_link_;
  std::string left_ready_pose_name_;
  std::vector<double> left_ready_joints_;
  std::string right_arm_group_;
  std::string right_gripper_group_;
  std::string right_tcp_link_;
  std::string right_ready_pose_name_;
  std::vector<double> right_ready_joints_;
  double planning_time_sec_{task_presets::kDefaultPlanning.planning_time_sec};
  int planning_attempts_{task_presets::kDefaultPlanning.planning_attempts};
  double velocity_scaling_{task_presets::kDefaultMotionScaling.arm_velocity_scaling};
  double acceleration_scaling_{task_presets::kDefaultMotionScaling.arm_acceleration_scaling};
  double gripper_velocity_scaling_{task_presets::kDefaultMotionScaling.gripper_velocity_scaling};
  double gripper_acceleration_scaling_{
      task_presets::kDefaultMotionScaling.gripper_acceleration_scaling};
  double pre_grasp_height_{task_presets::kDefaultPickGeometry.pre_grasp_height_m};
  double case_pre_grasp_distance_{task_presets::kDefaultPickGeometry.case_pre_grasp_distance_m};
  double ketchup_pre_grasp_distance_{
      task_presets::kDefaultPickGeometry.ketchup_pre_grasp_distance_m};
  double lift_height_{task_presets::kDefaultPickGeometry.lift_height_m};
  double place_approach_height_{task_presets::kDefaultPlaceGeometry.approach_height_m};
  double case_bread_place_clearance_{task_presets::kDefaultPlaceGeometry.case_bread_clearance_m};
  double case_sausage_place_clearance_{
      task_presets::kDefaultPlaceGeometry.case_sausage_clearance_m};
  double cartesian_eef_step_{task_presets::kDefaultCartesian.eef_step_m};
  double min_cartesian_fraction_{task_presets::kDefaultCartesian.min_fraction};
  bool cartesian_avoid_collisions_{task_presets::kDefaultCartesian.avoid_collisions};
  double cartesian_min_duration_sec_{task_presets::kDefaultCartesian.min_duration_sec};
  double pose_min_duration_sec_{task_presets::kDefaultPlanning.pose_min_duration_sec};
  double ketchup_squeeze_length_{task_presets::kDefaultKetchupSqueeze.length_m};
  double ketchup_squeeze_height_{task_presets::kDefaultKetchupSqueeze.height_m};
  double ketchup_squeeze_gripper_position_{
      task_presets::kDefaultKetchupSqueeze.gripper_joint_position};
  bool enable_ketchup_squeeze_gripper_{false};
  std::string gripper_open_target_;
  std::string gripper_grasp_target_;
  bool allow_gripper_target_collision_for_grasp_{
      task_presets::kDefaultPlanningScene.allow_gripper_target_collision_for_grasp};
  int collision_scene_settle_ms_{task_presets::kDefaultPlanningScene.collision_scene_settle_ms};
  std::set<std::string> attached_collision_objects_;
  double max_pre_grasp_xy_error_{task_presets::kDefaultMaxPreGraspXyError};
  bool dry_run_{false};
  bool validate_gazebo_result_{false};
  int result_validation_settle_ms_{1000};
  double result_validation_hotdog_item_xy_tolerance_m_{0.18};
  double result_validation_ketchup_return_xy_tolerance_m_{0.08};
  double result_validation_ketchup_return_z_tolerance_m_{0.08};
  double result_validation_beverage_pickup_xy_tolerance_m_{0.35};
  bool enable_vision_pick_{false};
  std::string vision_detections_topic_;
  double vision_pick_timeout_sec_{2.0};
  double vision_pick_max_age_sec_{2.0};
  double vision_pick_max_distance_m_{0.15};
  double vision_pick_min_score_{0.25};
  bool vision_pick_use_size_{false};
  std::unique_ptr<VisionPickAdapter> vision_pick_adapter_;
};

}  // namespace ddooby_controller
