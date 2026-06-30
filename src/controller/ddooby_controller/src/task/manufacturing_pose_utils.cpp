#include "ddooby_controller/task/manufacturing_pose_utils.hpp"

#include <algorithm>
#include <cmath>
#include <rclcpp/logging.hpp>

namespace ddooby_controller::manufacturing_task {

Eigen::Matrix3d rotationFromRpy(const Eigen::Vector3d& rpy) {
  return (Eigen::AngleAxisd(rpy.z(), Eigen::Vector3d::UnitZ()) *
          Eigen::AngleAxisd(rpy.y(), Eigen::Vector3d::UnitY()) *
          Eigen::AngleAxisd(rpy.x(), Eigen::Vector3d::UnitX()))
      .toRotationMatrix();
}

geometry_msgs::msg::Pose makePose(const Eigen::Vector3d& position,
                                  const Eigen::Quaterniond& orientation) {
  geometry_msgs::msg::Pose pose;
  pose.position.x = position.x();
  pose.position.y = position.y();
  pose.position.z = position.z();
  pose.orientation.x = orientation.x();
  pose.orientation.y = orientation.y();
  pose.orientation.z = orientation.z();
  pose.orientation.w = orientation.w();
  return pose;
}

geometry_msgs::msg::Quaternion makeQuaternion(const task_presets::TcpPosePreset& preset) {
  geometry_msgs::msg::Quaternion quaternion;
  quaternion.x = preset.qx;
  quaternion.y = preset.qy;
  quaternion.z = preset.qz;
  quaternion.w = preset.qw;
  return quaternion;
}

geometry_msgs::msg::Pose makePoseFromPreset(const task_presets::TcpPosePreset& preset) {
  geometry_msgs::msg::Pose pose;
  pose.position.x = preset.x;
  pose.position.y = preset.y;
  pose.position.z = preset.z;
  pose.orientation = makeQuaternion(preset);
  return pose;
}

const char* poseAxisSourceName(task_presets::PoseAxisSource source) {
  switch (source) {
    case task_presets::PoseAxisSource::Preset:
      return "preset";
    case task_presets::PoseAxisSource::CaseTcp:
      return "case_tcp";
    case task_presets::PoseAxisSource::TargetObject:
      return "target_object";
  }
  return "unknown";
}

double resolvePoseAxisValue(const rclcpp::Logger& logger, task_presets::PoseAxisSource source,
                            double preset_value, int axis_index,
                            const PoseAxisReferenceValues& references, const char* label) {
  if (source == task_presets::PoseAxisSource::CaseTcp) {
    if (references.has_case_position) {
      return references.case_position[axis_index];
    }
    RCLCPP_WARN(
        logger,
        "%s requested case_tcp axis source, but case reference is unavailable; using preset value",
        label);
    return preset_value;
  }

  if (source == task_presets::PoseAxisSource::TargetObject) {
    if (references.has_target_position) {
      return references.target_position[axis_index];
    }
    RCLCPP_WARN(logger,
                "%s requested target_object axis source, but target reference is unavailable; "
                "using preset value",
                label);
    return preset_value;
  }

  return preset_value;
}

geometry_msgs::msg::Pose makePoseFromWaypointPreset(
    const rclcpp::Logger& logger, const task_presets::StageWaypointPosePreset& preset,
    const PoseAxisReferenceValues& references, const char* label) {
  geometry_msgs::msg::Pose pose = makePoseFromPreset(preset.pose);
  pose.position.x =
      resolvePoseAxisValue(logger, preset.x_source, preset.pose.x, 0, references, label) +
      preset.x_offset;
  pose.position.y =
      resolvePoseAxisValue(logger, preset.y_source, preset.pose.y, 1, references, label) +
      preset.y_offset;
  pose.position.z =
      resolvePoseAxisValue(logger, preset.z_source, preset.pose.z, 2, references, label) +
      preset.z_offset;

  RCLCPP_INFO(
      logger,
      "%s waypoint axis sources: x=%s y=%s z=%s, offsets=[%.3f %.3f %.3f] -> xyz=[%.3f %.3f %.3f]",
      label, poseAxisSourceName(preset.x_source), poseAxisSourceName(preset.y_source),
      poseAxisSourceName(preset.z_source), preset.x_offset, preset.y_offset, preset.z_offset,
      pose.position.x, pose.position.y, pose.position.z);
  return pose;
}

Eigen::Vector3d posePosition(const geometry_msgs::msg::Pose& pose) {
  return Eigen::Vector3d(pose.position.x, pose.position.y, pose.position.z);
}

Eigen::Quaterniond poseOrientation(const geometry_msgs::msg::Pose& pose) {
  Eigen::Quaterniond orientation(pose.orientation.w, pose.orientation.x, pose.orientation.y,
                                 pose.orientation.z);
  orientation.normalize();
  return orientation;
}

void applyLocalTcpZRoll(geometry_msgs::msg::Pose& pose, double roll_deg) {
  if (std::abs(roll_deg) < 1e-9) {
    return;
  }

  const double roll_rad = roll_deg * std::acos(-1.0) / 180.0;
  Eigen::Quaterniond orientation =
      poseOrientation(pose) * Eigen::AngleAxisd(roll_rad, Eigen::Vector3d::UnitZ());
  orientation.normalize();
  pose.orientation.x = orientation.x();
  pose.orientation.y = orientation.y();
  pose.orientation.z = orientation.z();
  pose.orientation.w = orientation.w();
}

Eigen::Vector3d rpyFromRotation(const Eigen::Matrix3d& rotation) {
  const double pitch = std::asin(std::max(-1.0, std::min(-rotation(2, 0), 1.0)));
  const double cos_pitch = std::cos(pitch);
  double roll = 0.0;
  double yaw = 0.0;
  if (std::abs(cos_pitch) > 1e-6) {
    roll = std::atan2(rotation(2, 1), rotation(2, 2));
    yaw = std::atan2(rotation(1, 0), rotation(0, 0));
  } else {
    roll = std::atan2(-rotation(1, 2), rotation(1, 1));
    yaw = 0.0;
  }
  return Eigen::Vector3d(roll, pitch, yaw);
}

Eigen::Vector3d objectWorldCenter(const TargetObject& target) {
  return target.xyz + rotationFromRpy(target.rpy) * target.local_center;
}

bool poseHasValidOrientation(const geometry_msgs::msg::Pose& pose) {
  const double norm_squared =
      pose.orientation.x * pose.orientation.x + pose.orientation.y * pose.orientation.y +
      pose.orientation.z * pose.orientation.z + pose.orientation.w * pose.orientation.w;
  return norm_squared > 1e-8;
}

Eigen::Vector3d heldCaseCenterFromTcpPose(const geometry_msgs::msg::Pose& right_tcp_pose) {
  const Eigen::Matrix3d right_tcp_rotation = poseOrientation(right_tcp_pose).toRotationMatrix();
  return posePosition(right_tcp_pose) +
         right_tcp_rotation.col(2).normalized() *
             (-task_presets::kRightCasePickTuning.grasp_tcp_z_offset_m);
}

double poseOrientationDistanceRad(const geometry_msgs::msg::Pose& first,
                                  const geometry_msgs::msg::Pose& second) {
  const Eigen::Quaterniond first_orientation = poseOrientation(first);
  const Eigen::Quaterniond second_orientation = poseOrientation(second);
  const double dot = std::abs(first_orientation.dot(second_orientation));
  return 2.0 * std::acos(std::max(-1.0, std::min(dot, 1.0)));
}

}  // namespace ddooby_controller::manufacturing_task
