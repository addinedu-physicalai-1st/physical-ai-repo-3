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
#include <rclcpp/wait_for_message.hpp>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <vision_msgs/msg/detection3_d_array.hpp>

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

HotdogMakingNode::HotdogMakingNode() : Node("ddooby_hotdog_making_node") {
  declareRuntimeParameters();
  configureVisionSubscription();
  parseExecutionRequest();
}

bool HotdogMakingNode::run() {
  if (!play_range_valid_) {
    return false;
  }

  if (scenario_only_) {
    return runScenario();
  }

  RCLCPP_INFO(get_logger(), "Manufacturing request: task=%s, start_stage=%s, play_to_stage=%s",
              task_presets::targetName(target_), task_presets::stageName(start_stage_),
              has_play_to_stage_ ? task_presets::stageName(play_to_stage_) : "complete");

  ArmSide parsed_arm = ArmSide::Left;
  if (parseArmSide(arm_name_, parsed_arm)) {
    RCLCPP_WARN(
        get_logger(),
        "arm:=%s is deprecated for manufacturing tasks; task determines the required arm sequence",
        arm_name_.c_str());
  }

  if (isHotdogAssemblyEndpoint(target_)) {
    return runHotdogAssemblyUntil(target_);
  }

  if (isBeverageTarget(target_)) {
    return runBeverageCanServe(target_);
  }

  RCLCPP_ERROR(get_logger(), "Unsupported task: %s", task_presets::targetName(target_));
  return false;
}

void HotdogMakingNode::declareRuntimeParameters() {
  declareTaskSelectionParameters();
  declareArmGroupParameters();
  declareMotionPlanningParameters();
  declareManufacturingGeometryParameters();
  declareToolAndSceneParameters();
  declareVisionPickParameters();
}

void HotdogMakingNode::declareTaskSelectionParameters() {
  item_name_ = declare_parameter<std::string>("item_name", "new_york_hotdog");
  scenario_only_ = declare_parameter<bool>("scenario_only", true);
  step_delay_ms_ = declare_parameter<int>("step_delay_ms", 150);
  task_name_ = declare_parameter<std::string>("task", "bread");
  arm_name_ = declare_parameter<std::string>("arm", "auto");
  target_model_ = declare_parameter<std::string>("target_model", "auto");
  case_target_model_ = declare_parameter<std::string>("case_target_model", "case");
  bread_target_model_ = declare_parameter<std::string>("bread_target_model", "bread1");
  sausage_target_model_ = declare_parameter<std::string>("sausage_target_model", "sausage");
  ketchup_target_model_ = declare_parameter<std::string>("ketchup_target_model", "kachup");
  coke_target_model_ = declare_parameter<std::string>("coke_target_model", "can_coke");
  coffee_target_model_ = declare_parameter<std::string>("coffee_target_model", "can_coffee");
  play_to_stage_name_ = declare_parameter<std::string>("play_to_stage", "complete");
  start_from_waypoint_name_ = declare_parameter<std::string>("start_from_waypoint", "");
  play_to_waypoint_name_ = declare_parameter<std::string>("play_to_waypoint", "");
  layout_path_ = declare_parameter<std::string>("layout_path", "");
}

void HotdogMakingNode::declareArmGroupParameters() {
  left_arm_group_ = declare_parameter<std::string>("left_arm_group", "left_arm");
  left_gripper_group_ = declare_parameter<std::string>("left_gripper_group", "left_gripper");
  left_tcp_link_ = declare_parameter<std::string>("left_tcp_link", "openarm_left_hand_tcp");
  left_ready_pose_name_ =
      declare_parameter<std::string>("left_ready_pose_name", "left_bread_pick_ready");
  left_ready_joints_ = declare_parameter<std::vector<double>>(
      "left_ready_joints",
      {1.239329032213002, 0.0010114715451901488, -0.0009259087954886816, 1.718774510702148,
       0.0010237185554880786, -0.0010588666577850028, -1.0783557656423297});
  right_arm_group_ = declare_parameter<std::string>("right_arm_group", "right_arm");
  right_gripper_group_ = declare_parameter<std::string>("right_gripper_group", "right_gripper");
  right_tcp_link_ = declare_parameter<std::string>("right_tcp_link", "openarm_right_hand_tcp");
  right_ready_pose_name_ =
      declare_parameter<std::string>("right_ready_pose_name", "right_case_pick_ready");
  right_ready_joints_ = declare_parameter<std::vector<double>>(
      "right_ready_joints",
      {-1.239329032213002, 0.0010114715451901488, 0.0009259087954886816, 1.718774510702148,
       -0.0010237185554880786, -0.0010588666577850028, 1.0783557656423297});
}

void HotdogMakingNode::declareMotionPlanningParameters() {
  planning_time_sec_ = declare_parameter<double>("planning_time_sec",
                                                 task_presets::kDefaultPlanning.planning_time_sec);
  planning_attempts_ =
      declare_parameter<int>("planning_attempts", task_presets::kDefaultPlanning.planning_attempts);
  velocity_scaling_ = declare_parameter<double>(
      "velocity_scaling", task_presets::kDefaultMotionScaling.arm_velocity_scaling);
  acceleration_scaling_ = declare_parameter<double>(
      "acceleration_scaling", task_presets::kDefaultMotionScaling.arm_acceleration_scaling);
  gripper_velocity_scaling_ = declare_parameter<double>(
      "gripper_velocity_scaling", task_presets::kDefaultMotionScaling.gripper_velocity_scaling);
  gripper_acceleration_scaling_ =
      declare_parameter<double>("gripper_acceleration_scaling",
                                task_presets::kDefaultMotionScaling.gripper_acceleration_scaling);
  cartesian_eef_step_ =
      declare_parameter<double>("cartesian_eef_step", task_presets::kDefaultCartesian.eef_step_m);
  min_cartesian_fraction_ = declare_parameter<double>("min_cartesian_fraction",
                                                      task_presets::kDefaultCartesian.min_fraction);
  cartesian_avoid_collisions_ = declare_parameter<bool>(
      "cartesian_avoid_collisions", task_presets::kDefaultCartesian.avoid_collisions);
  cartesian_min_duration_sec_ = declare_parameter<double>(
      "cartesian_min_duration_sec", task_presets::kDefaultCartesian.min_duration_sec);
  pose_min_duration_sec_ = declare_parameter<double>(
      "pose_min_duration_sec", task_presets::kDefaultPlanning.pose_min_duration_sec);
}

void HotdogMakingNode::declareManufacturingGeometryParameters() {
  pre_grasp_height_ = declare_parameter<double>(
      "pre_grasp_height", task_presets::kDefaultPickGeometry.pre_grasp_height_m);
  case_pre_grasp_distance_ = declare_parameter<double>(
      "case_pre_grasp_distance", task_presets::kDefaultPickGeometry.case_pre_grasp_distance_m);
  ketchup_pre_grasp_distance_ =
      declare_parameter<double>("ketchup_pre_grasp_distance",
                                task_presets::kDefaultPickGeometry.ketchup_pre_grasp_distance_m);
  lift_height_ =
      declare_parameter<double>("lift_height", task_presets::kDefaultPickGeometry.lift_height_m);
  place_approach_height_ = declare_parameter<double>(
      "place_approach_height", task_presets::kDefaultPlaceGeometry.approach_height_m);
  case_bread_place_clearance_ = declare_parameter<double>(
      "case_bread_place_clearance", task_presets::kDefaultPlaceGeometry.case_bread_clearance_m);
  case_sausage_place_clearance_ = declare_parameter<double>(
      "case_sausage_place_clearance", task_presets::kDefaultPlaceGeometry.case_sausage_clearance_m);
  ketchup_squeeze_length_ = declare_parameter<double>(
      "ketchup_squeeze_length", task_presets::kDefaultKetchupSqueeze.length_m);
  ketchup_squeeze_height_ = declare_parameter<double>(
      "ketchup_squeeze_height", task_presets::kDefaultKetchupSqueeze.height_m);
  ketchup_squeeze_gripper_position_ =
      declare_parameter<double>("ketchup_squeeze_gripper_position",
                                task_presets::kDefaultKetchupSqueeze.gripper_joint_position);
  enable_ketchup_squeeze_gripper_ =
      declare_parameter<bool>("enable_ketchup_squeeze_gripper", false);
}

void HotdogMakingNode::declareToolAndSceneParameters() {
  gripper_open_target_ = declare_parameter<std::string>("gripper_open_target", "open");
  gripper_grasp_target_ = declare_parameter<std::string>("gripper_grasp_target", "half_closed");
  allow_gripper_target_collision_for_grasp_ = declare_parameter<bool>(
      "allow_gripper_target_collision_for_grasp",
      task_presets::kDefaultPlanningScene.allow_gripper_target_collision_for_grasp);
  collision_scene_settle_ms_ = declare_parameter<int>(
      "collision_scene_settle_ms", task_presets::kDefaultPlanningScene.collision_scene_settle_ms);
  max_pre_grasp_xy_error_ =
      declare_parameter<double>("max_pre_grasp_xy_error", task_presets::kDefaultMaxPreGraspXyError);
  dry_run_ = declare_parameter<bool>("dry_run", false);
  validate_gazebo_result_ = declare_parameter<bool>("validate_gazebo_result", false);
  result_validation_settle_ms_ = declare_parameter<int>("result_validation_settle_ms", 1000);
  result_validation_hotdog_item_xy_tolerance_m_ =
      declare_parameter<double>("result_validation_hotdog_item_xy_tolerance", 0.18);
  result_validation_ketchup_return_xy_tolerance_m_ =
      declare_parameter<double>("result_validation_ketchup_return_xy_tolerance", 0.08);
  result_validation_ketchup_return_z_tolerance_m_ =
      declare_parameter<double>("result_validation_ketchup_return_z_tolerance", 0.08);
  result_validation_beverage_pickup_xy_tolerance_m_ =
      declare_parameter<double>("result_validation_beverage_pickup_xy_tolerance", 0.35);
}

void HotdogMakingNode::declareVisionPickParameters() {
  enable_vision_pick_ = declare_parameter<bool>("enable_vision_pick", false);
  vision_detections_topic_ =
      declare_parameter<std::string>("vision_detections_topic", "/manufacturing_vision/detections");
  vision_pick_timeout_sec_ = declare_parameter<double>("vision_pick_timeout_sec", 8.0);
  vision_pick_max_age_sec_ = declare_parameter<double>("vision_pick_max_age_sec", 5.0);
  vision_pick_max_distance_m_ = declare_parameter<double>("vision_pick_max_distance_m", 0.15);
  vision_pick_min_score_ = declare_parameter<double>("vision_pick_min_score", 0.25);
  vision_pick_use_size_ = declare_parameter<bool>("vision_pick_use_size", false);
}

void HotdogMakingNode::configureVisionSubscription() {
  if (enable_vision_pick_) {
    vision_pick_adapter_ = std::make_unique<VisionPickAdapter>(
        *this, manufacturing_task::VisionPickAdapterConfig{
                   true, vision_detections_topic_, vision_pick_timeout_sec_, vision_pick_use_size_,
                   visionPickMatchConfig()});
    RCLCPP_INFO(get_logger(),
                "Vision pick enabled: topic=%s timeout=%.2fs max_age=%.2fs max_distance=%.3fm "
                "min_score=%.2f method=yolo-seg+pca",
                vision_detections_topic_.c_str(), vision_pick_timeout_sec_,
                vision_pick_max_age_sec_, vision_pick_max_distance_m_, vision_pick_min_score_);
  }
}

void HotdogMakingNode::parseExecutionRequest() {
  try {
    start_stage_ = ManufacturingStage::Home;
    if (!normalizeStageName(start_from_waypoint_name_).empty()) {
      ManufacturingStage start_stage = ManufacturingStage::Home;
      if (stageHintFromWaypointName(start_from_waypoint_name_, start_stage)) {
        start_stage_ = start_stage;
        ManufacturingStage endpoint_stage = ManufacturingStage::Home;
        if (!stageEndpointFromWaypointName(start_from_waypoint_name_, endpoint_stage)) {
          RCLCPP_WARN(get_logger(),
                      "start_from_waypoint='%s' starts from containing stage '%s'; "
                      "intra-stage waypoint resume is not exact yet",
                      start_from_waypoint_name_.c_str(), task_presets::stageName(start_stage_));
        }
      } else {
        throw std::invalid_argument("unsupported start_from_waypoint '" +
                                    start_from_waypoint_name_ + "'");
      }
    }

    ManufacturingStage parsed_play_to_stage = ManufacturingStage::Home;
    if (parsePlayToStage(play_to_stage_name_, parsed_play_to_stage)) {
      play_to_stage_ = parsed_play_to_stage;
      has_play_to_stage_ = true;
    } else {
      has_play_to_stage_ = false;
    }

    play_to_waypoint_ = normalizeStageName(play_to_waypoint_name_);
    ManufacturingStage waypoint_stage_endpoint = ManufacturingStage::Home;
    if (stageEndpointFromWaypointName(play_to_waypoint_name_, waypoint_stage_endpoint)) {
      play_to_stage_ = waypoint_stage_endpoint;
      has_play_to_stage_ = true;
      play_to_waypoint_.clear();
    }
    if (play_to_waypoint_ == "complete" || play_to_waypoint_ == "all" ||
        play_to_waypoint_ == "none") {
      play_to_waypoint_.clear();
    }
    target_ = parseManufacturingTask(task_name_);
    ArmSide requested_arm = ArmSide::Left;
    arm_ = parseArmSide(arm_name_, requested_arm) ? requested_arm : defaultArmForTarget(target_);
    if (has_play_to_stage_ && stageOrder(play_to_stage_) < stageOrder(start_stage_)) {
      throw std::invalid_argument(
          "play_to_stage must be the same as or later than start_from_waypoint");
    }
  } catch (const std::exception& error) {
    play_range_valid_ = false;
    RCLCPP_ERROR(get_logger(), "%s", error.what());
  }
}

bool HotdogMakingNode::runScenario() {
  RCLCPP_INFO(get_logger(), "Hotdog making task accepted: item=%s, scenario_only=%s",
              item_name_.c_str(), scenario_only_ ? "true" : "false");

  const std::vector<ScenarioStep> steps = makeHotdogScenarioSteps();

  for (size_t i = 0; i < steps.size(); ++i) {
    if (!rclcpp::ok()) {
      RCLCPP_WARN(get_logger(), "Hotdog task interrupted before step %zu", i + 1);
      return false;
    }
    RCLCPP_INFO(get_logger(), "Hotdog scenario step %zu/%zu [%s]: %s", i + 1, steps.size(),
                steps[i].name.c_str(), steps[i].description.c_str());
    sleepStep();
  }

  RCLCPP_INFO(get_logger(), "Hotdog task scenario completed");
  return true;
}

bool HotdogMakingNode::shouldStopAfter(ManufacturingStage stage) const {
  if (!has_play_to_stage_ || play_to_stage_ != stage) {
    return false;
  }

  RCLCPP_INFO(get_logger(), "Stopping after manufacturing stage: %s",
              task_presets::stageName(stage));
  return true;
}

bool HotdogMakingNode::shouldStopAfterWaypoint(ManufacturingStage stage,
                                               const std::string& waypoint) const {
  if (!stopWaypointMatches(play_to_waypoint_, stage, waypoint)) {
    return false;
  }

  RCLCPP_INFO(get_logger(), "Stopping after manufacturing waypoint: %s.%s",
              task_presets::stageName(stage), waypoint.c_str());
  return true;
}

bool HotdogMakingNode::shouldRunStage(ManufacturingStage stage) const {
  return shouldRunManufacturingStage(stage, start_stage_);
}

bool HotdogMakingNode::shouldStopAtOrBefore(ManufacturingStage stage) const {
  return shouldStopAtOrBeforeStage(has_play_to_stage_, play_to_stage_, stage);
}

bool HotdogMakingNode::shouldStopAtOrBeforeWaypointStage(ManufacturingStage stage) const {
  return ddooby_controller::manufacturing_task::shouldStopAtOrBeforeWaypointStage(play_to_waypoint_,
                                                                                  stage);
}

bool HotdogMakingNode::configureTaskArm(moveit::planning_interface::MoveGroupInterface& arm,
                                        const std::string& tcp_link, double velocity_scaling,
                                        double acceleration_scaling) {
  return configureArmGroupForTask(arm, planning_time_sec_, planning_attempts_, velocity_scaling,
                                  acceleration_scaling, tcp_link);
}

bool HotdogMakingNode::configureTaskArm(moveit::planning_interface::MoveGroupInterface& arm,
                                        const std::string& tcp_link) {
  return configureTaskArm(arm, tcp_link, velocity_scaling_, acceleration_scaling_);
}

void HotdogMakingNode::configureTaskGripper(
    moveit::planning_interface::MoveGroupInterface& gripper) {
  configureGripperGroupForTask(gripper, gripper_velocity_scaling_, gripper_acceleration_scaling_);
}

MotionPrimitiveConfig HotdogMakingNode::motionPrimitiveConfig() const {
  // task 파일이 런타임 파라미터 이름에 직접 의존하지 않도록 설정을 모은다.
  MotionPrimitiveConfig config;
  config.cartesian_eef_step = cartesian_eef_step_;
  config.cartesian_min_fraction = min_cartesian_fraction_;
  config.cartesian_avoid_collisions = cartesian_avoid_collisions_;
  config.cartesian_velocity_scaling = velocity_scaling_;
  config.cartesian_acceleration_scaling = acceleration_scaling_;
  config.cartesian_min_duration_sec = cartesian_min_duration_sec_;
  config.pose_min_duration_sec = pose_min_duration_sec_;
  config.pose_max_attempts = task_presets::kDefaultPlanExecuteMaxAttempts;
  config.gripper_open_target = gripper_open_target_;
  config.gripper_grasp_target = gripper_grasp_target_;
  return config;
}

ManufacturingMotionPrimitives HotdogMakingNode::makeMotionPrimitives() const {
  // 각 task가 최신 런타임 설정을 쓰도록 가벼운 primitive facade를 생성한다.
  return ManufacturingMotionPrimitives(get_logger(), motionPrimitiveConfig());
}

bool HotdogMakingNode::planAndExecuteReturnHome(moveit::planning_interface::MoveGroupInterface& arm,
                                                ManufacturingTarget target, ArmSide arm_side,
                                                const std::string& tcp_link,
                                                const std::string& label) {
  bool return_home_pose_configured = false;
  if (!planAndExecuteStageWaypointPoseIfConfigured(
          get_logger(), arm, target, arm_side, task_presets::ManufacturingStage::ReturnHome,
          "return_home", tcp_link, return_home_pose_configured, pose_min_duration_sec_)) {
    return false;
  }

  if (return_home_pose_configured) {
    logCurrentTcpPose(get_logger(), arm, tcp_link, label + " return-home waypoint");
    return true;
  }

  const std::string ready_pose_name =
      arm_side == ArmSide::Right ? right_ready_pose_name_ : left_ready_pose_name_;
  const std::vector<double>& ready_joints =
      arm_side == ArmSide::Right ? right_ready_joints_ : left_ready_joints_;
  rememberJointTargetIfConfigured(arm, ready_pose_name, ready_joints);
  RCLCPP_INFO(get_logger(), "%s: moving arm through ready pose before home", label.c_str());
  if (!planAndExecuteNamedTarget(get_logger(), arm, ready_pose_name, label + " ready before home",
                                 task_presets::kDefaultPlanExecuteMaxAttempts,
                                 pose_min_duration_sec_)) {
    return false;
  }
  logCurrentTcpPose(get_logger(), arm, tcp_link, label + " ready before home");

  RCLCPP_INFO(get_logger(), "%s: moving arm to home pose", label.c_str());
  if (!planAndExecuteNamedTarget(get_logger(), arm, "home", label + " home",
                                 task_presets::kDefaultPlanExecuteMaxAttempts,
                                 pose_min_duration_sec_)) {
    return false;
  }

  logCurrentTcpPose(get_logger(), arm, tcp_link, label + " home");
  return true;
}

bool HotdogMakingNode::runSingleArmReturnHome(ManufacturingTarget target, ArmSide arm_side,
                                              const std::string& arm_group,
                                              const std::string& tcp_link,
                                              const std::string& label) {
  if (!shouldRunStage(ManufacturingStage::ReturnHome)) {
    return true;
  }

  auto self = shared_from_this();
  moveit::planning_interface::MoveGroupInterface arm(self, arm_group);
  configureTaskArm(arm, tcp_link);

  return planAndExecuteReturnHome(arm, target, arm_side, tcp_link, label);
}

void HotdogMakingNode::sleepStep() const {
  if (step_delay_ms_ > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(step_delay_ms_));
  }
}

}  // namespace ddooby_controller
