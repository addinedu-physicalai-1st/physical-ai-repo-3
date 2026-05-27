#pragma once

#include <array>
#include <cstddef>

namespace ddooby_controller::manufacturing_task_presets
{

// 제조 대상 구분.
enum class ManufacturingTarget
{
  Bread,
  Case,
  Hotdog,
  Sausage,
};

// 제조에 사용하는 팔 구분.
enum class ArmSide
{
  Left,
  Right,
};

// 제조 공정의 큰 단계 구분.
enum class ManufacturingStage
{
  Home,
  PreGrasp,
  Pick,
  PullOut,
  Work,
  Place,
  ReturnHome,
};

// TF/RViz에서 캡처한 TCP pose 값.
struct TcpPosePreset
{
  // false면 이 pose preset은 무시.
  bool enabled;

  // MoveIt planning frame 기준 위치.
  double x;
  double y;
  double z;

  // TCP 자세 quaternion 값, 순서는 xyzw.
  double qx;
  double qy;
  double qz;
  double qw;
};

struct StagePosePreset
{
  ManufacturingTarget target;
  ArmSide arm;
  ManufacturingStage stage;
  TcpPosePreset pose;
};

struct GripperJointPreset
{
  // false면 named target 방식으로 그리퍼를 닫음.
  bool enabled;

  // 그리퍼 joint 목표값, 0.0은 closed이고 0.044는 open.
  double joint_position;
};

struct PickTuningPreset
{
  // 자동 계산된 grasp pose에서 TCP local z축으로 더할 값(m).
  double grasp_tcp_z_offset_m;

  // 접근 시점의 그리퍼 열림 설정. 비활성화 시 named open target 사용.
  GripperJointPreset gripper_pre_open;

  // pick 시점의 그리퍼 닫힘 설정.
  GripperJointPreset gripper_close;
};

struct MotionScalingPreset
{
  // MoveIt arm trajectory 최대 속도 비율.
  double arm_velocity_scaling;

  // MoveIt arm trajectory 최대 가속도 비율.
  double arm_acceleration_scaling;

  // MoveIt gripper trajectory 최대 속도 비율.
  double gripper_velocity_scaling;

  // MoveIt gripper trajectory 최대 가속도 비율.
  double gripper_acceleration_scaling;
};

// Gazebo와 실물 OpenArm에 공통 적용되는 기본 이동 속도 preset.
inline constexpr MotionScalingPreset kDefaultMotionScaling{
  0.05,
  0.05,
  0.12,
  0.12
};

// joint limit에 딱 붙지 않도록 안쪽으로 유지할 최소 margin.
inline constexpr double kDefaultJointLimitSafetyMargin = 0.00001;

// MoveIt plan + execute를 같은 목표에 대해 재시도할 기본 횟수.
inline constexpr int kDefaultPlanExecuteMaxAttempts = 5;

// pre-grasp 도달 후 pick 진행을 허용할 최대 TCP xy 오차(m).
inline constexpr double kDefaultMaxPreGraspXyError = 0.035;

inline constexpr const char * stageName(ManufacturingStage stage)
{
  switch (stage) {
    case ManufacturingStage::Home:
      return "home";
    case ManufacturingStage::PreGrasp:
      return "pre_grasp";
    case ManufacturingStage::Pick:
      return "pick";
    case ManufacturingStage::PullOut:
      return "pull_out";
    case ManufacturingStage::Work:
      return "work";
    case ManufacturingStage::Place:
      return "place";
    case ManufacturingStage::ReturnHome:
      return "return_home";
  }
  return "unknown";
}

inline constexpr const char * targetName(ManufacturingTarget target)
{
  switch (target) {
    case ManufacturingTarget::Bread:
      return "bread";
    case ManufacturingTarget::Case:
      return "case";
    case ManufacturingTarget::Hotdog:
      return "hotdog";
    case ManufacturingTarget::Sausage:
      return "sausage";
  }
  return "unknown";
}

inline constexpr const char * armName(ArmSide arm)
{
  switch (arm) {
    case ArmSide::Left:
      return "left";
    case ArmSide::Right:
      return "right";
  }
  return "unknown";
}

// target + arm + stage별 커스텀 TCP pose 설정 테이블.
// 왼손 pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
// 오른손 pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_right_hand_tcp
inline constexpr std::array<StagePosePreset, 21> kStagePosePresets{{
  // 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Home,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 위 접근 pose, 활성화 시 전체 pose 사용.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::PreGrasp,
    {true, 0.391, 0.077, 0.401, 1.000, -0.001, -0.003, 0.000}
  },
  // 빵 집기 pose, 비활성화 시 빵 위치 기준 자동 계산.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Pick,
    {false, 0.313, 0.184, 0.336, 1.000, -0.000, 0.004, 0.000}
  },
  // 물체를 빼는 pose, 빵 pick에서는 현재 비활성화.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::PullOut,
    {false, 0.329, 0.188, 0.458, 1.000, 0.000, -0.004, 0.001}
  },
  // 케이스 위 빵 놓기 직전 pose.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Work,
    {true, 0.196, 0.035, 0.446, 0.728, -0.686, -0.002, 0.003}
  },
  // 케이스 위 빵 release pose, 비활성화 시 work pose에서 drop.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Place,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::ReturnHome,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Home,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케이스 앞 접근 pose, 비활성화 시 케이스 위치 기준 자동 계산.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::PreGrasp,
    {true, 0.387, -0.201, 0.395, 0.721, -0.000, 0.693, -0.000}
  },
  // 케이스 집기 pose, 비활성화 시 케이스 위치 기준 자동 계산.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Pick,
    {false, 0.555, -0.191, 0.423, 0.0, 0.707, 0.0, 0.707}
  },
  // 케이스를 스탠드에서 빼는 pose, 활성화 시 자동 pull-out 대신 사용.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::PullOut,
    {true, 0.360, -0.201, 0.405, 0.721, -0.000, 0.693, -0.000}
  },
  // 케이스를 빵 받는 위치로 내미는 pose, 비활성화 시 현재 오른손 pose 사용.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Work,
    {true, 0.204, -0.007, 0.347, 0.504, 0.497, 0.503, -0.496}
  },
  // place pose, 현재는 비활성화.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Place,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::ReturnHome,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 작업 시작 pose, 비활성화 시 기존 left ready pose 사용.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Home,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 소시지 위 접근 pose, 활성화 시 전체 pose 사용.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::PreGrasp,
    {true, 0.391, 0.259, 0.401, 1.000, -0.001, -0.003, -0.000}
  },
  // 소시지 집기 pose, 비활성화 시 소시지 위치 기준 자동 계산.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Pick,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 물체를 빼는 pose, 소시지 pick에서는 현재 비활성화.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::PullOut,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 위 소시지 놓기 직전 pose, 비활성화 시 자동 approach pose 사용.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Work,
    {true, 0.203, 0.029, 0.436, -0.707, 0.707, 0.002, -0.002}
  },
  // 빵 위 소시지 release pose, 비활성화 시 오른손 케이스 pose 기준 자동 계산.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Place,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::ReturnHome,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
}};

// 빵 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftBreadPickTuning{
  0.0,
  {true, 0.030},
  {true, 0.019}
};

// 케이스 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kRightCasePickTuning{
  -0.020,
  {true, 0.040},
  {true, 0.025}
};

// 소시지 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftSausagePickTuning{
  0.005,
  {true, 0.024},
  {true, 0.005}
};

inline const StagePosePreset * findStagePosePreset(
  ManufacturingTarget target,
  ArmSide arm,
  ManufacturingStage stage)
{
  for (const auto & preset : kStagePosePresets) {
    if (preset.target == target && preset.arm == arm && preset.stage == stage &&
      preset.pose.enabled)
    {
      return &preset;
    }
  }
  return nullptr;
}

inline const PickTuningPreset * findPickTuningPreset(ManufacturingTarget target, ArmSide arm)
{
  if (target == ManufacturingTarget::Bread && arm == ArmSide::Left) {
    return &kLeftBreadPickTuning;
  }
  if (target == ManufacturingTarget::Case && arm == ArmSide::Right) {
    return &kRightCasePickTuning;
  }
  if (target == ManufacturingTarget::Sausage && arm == ArmSide::Left) {
    return &kLeftSausagePickTuning;
  }
  return nullptr;
}

}  // namespace ddooby_controller::manufacturing_task_presets
