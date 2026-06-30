#include "ddooby_controller/control/manufacturing_stage_motion.hpp"

#include <algorithm>
#include <string>

#include "ddooby_controller/control/moveit_task_utils.hpp"
#include "ddooby_controller/task/manufacturing_pose_utils.hpp"

namespace ddooby_controller::manufacturing_task {

bool planAndExecuteStageWaypointPoseIfConfigured(
    const rclcpp::Logger& logger, moveit::planning_interface::MoveGroupInterface& arm,
    task_presets::ManufacturingTarget target, task_presets::ArmSide arm_side,
    task_presets::ManufacturingStage stage, const char* waypoint, const std::string& tcp_link,
    bool& configured, double min_duration_sec) {
  configured = false;
  const auto* preset = task_presets::findStageWaypointPosePreset(target, arm_side, stage, waypoint);
  if (preset == nullptr) {
    return true;
  }

  configured = true;
  geometry_msgs::msg::Pose target_pose = makePoseFromPreset(preset->pose);

  const std::string label =
      std::string("stage waypoint pose ") + task_presets::stageName(stage) + "." + waypoint;
  const geometry_msgs::msg::Pose current_pose = arm.getCurrentPose(tcp_link).pose;
  const double position_error = (posePosition(current_pose) - posePosition(target_pose)).norm();
  const double orientation_error = poseOrientationDistanceRad(current_pose, target_pose);
  if (position_error <= task_presets::kDefaultPoseTargetSkipPositionToleranceM &&
      orientation_error <= task_presets::kDefaultPoseTargetSkipOrientationToleranceRad) {
    RCLCPP_INFO(
        logger,
        "%s skipped; current TCP is already near target (pos_error=%.4f m, rot_error=%.4f rad)",
        label.c_str(), position_error, orientation_error);
    return true;
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(target_pose, tcp_link);

  return planAndExecute(logger, arm, label, task_presets::kDefaultPlanExecuteMaxAttempts,
                        min_duration_sec);
}

const char* preGraspGoalModeName(PreGraspGoalMode mode) {
  switch (mode) {
    case PreGraspGoalMode::ExactPose:
      return "exact_pose";
  }
  return "unknown";
}

bool planAndExecutePreGrasp(const rclcpp::Logger& logger,
                            moveit::planning_interface::MoveGroupInterface& arm,
                            const geometry_msgs::msg::Pose& pre_grasp_pose,
                            const std::string& tcp_link, bool use_clearance_approach,
                            double min_duration_sec, PreGraspGoalMode& used_mode) {
  if (use_clearance_approach) {
    constexpr double kPreGraspClearanceHeight = 0.07;
    const geometry_msgs::msg::Pose current_pose = arm.getCurrentPose(tcp_link).pose;
    geometry_msgs::msg::Pose approach_pose = pre_grasp_pose;
    approach_pose.position.z =
        std::max(current_pose.position.z, pre_grasp_pose.position.z + kPreGraspClearanceHeight);
    approach_pose.orientation = current_pose.orientation;

    RCLCPP_INFO(logger,
                "Moving to pre-grasp clearance pose at z=%.3f with current TCP orientation before "
                "descending to pre-grasp",
                approach_pose.position.z);
    if (!planAndExecutePoseTarget(logger, arm, approach_pose, tcp_link, "pre-grasp clearance pose",
                                  2, min_duration_sec)) {
      RCLCPP_ERROR(
          logger,
          "Pre-grasp clearance pose failed; aborting to avoid unsafe direct pre-grasp path");
      return false;
    }
  }

  arm.clearPoseTargets();
  setBoundedStartState(arm);
  arm.setPoseTarget(pre_grasp_pose, tcp_link);
  if (planAndExecute(logger, arm, "pre-grasp exact pose",
                     task_presets::kDefaultPlanExecuteMaxAttempts, min_duration_sec)) {
    used_mode = PreGraspGoalMode::ExactPose;
    return true;
  }

  return false;
}

}  // namespace ddooby_controller::manufacturing_task
