#pragma once

#include <array>
#include <cstddef>

namespace ddooby_controller::manufacturing_task_presets
{

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

  // pick 시점의 그리퍼 닫힘 설정.
  GripperJointPreset gripper_close;
};

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

// 빵 pick 단계별 커스텀 TCP pose 설정 테이블.
// pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
inline constexpr std::array<StagePosePreset, 7> kLeftBreadPickStagePoses{{
  // 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingStage::Home,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 위 접근 pose, 활성화 시 전체 pose 사용.
  {
    ManufacturingStage::PreGrasp,
    {true, 0.313, 0.184, 0.360, 1.000, -0.000, 0.004, 0.000}
  },
  // 빵 집기 pose, 비활성화 시 빵 위치 기준 자동 계산.
  {
    ManufacturingStage::Pick,
    {false, 0.313, 0.184, 0.336, 1.000, -0.000, 0.004, 0.000}
  },
  // 물체를 빼는 pose, 빵 pick에서는 현재 비활성화.
  {
    ManufacturingStage::PullOut,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // pick 이후 작업 pose, 현재는 비활성화.
  {
    ManufacturingStage::Work,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // place pose, 현재는 비활성화.
  {
    ManufacturingStage::Place,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 복귀 pose, 현재는 비활성화.
  {
    ManufacturingStage::ReturnHome,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
}};

// 케이스 pick 단계별 커스텀 TCP pose 설정 테이블.
// pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_right_hand_tcp
inline constexpr std::array<StagePosePreset, 7> kRightCasePickStagePoses{{
  // 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingStage::Home,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케이스 앞 접근 pose, 비활성화 시 케이스 위치 기준 자동 계산.
  {
    ManufacturingStage::PreGrasp,
    {true, 0.441, -0.190, 0.437, 0.720, 0.000, 0.694, -0.000}
  },
  // 케이스 집기 pose, 비활성화 시 케이스 위치 기준 자동 계산.
  {
    ManufacturingStage::Pick,
    {false, 0.555, -0.191, 0.423, 0.0, 0.707, 0.0, 0.707}
  },
  // 케이스를 스탠드에서 빼는 pose, 활성화 시 자동 pull-out 대신 사용.
  {
    ManufacturingStage::PullOut,
    {true, 0.279, -0.191, 0.452, 0.720, -0.000, 0.694, 0.000}
  },
  // pick 이후 작업 pose, 현재는 비활성화.
  {
    ManufacturingStage::Work,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // place pose, 현재는 비활성화.
  {
    ManufacturingStage::Place,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 복귀 pose, 현재는 비활성화.
  {
    ManufacturingStage::ReturnHome,
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
}};

// 빵 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftBreadPickTuning{
  0.0,
  {true, 0.022}
};

// 케이스 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kRightCasePickTuning{
  -0.055,
  {true, 0.034}
};

inline const StagePosePreset * findLeftBreadPickStagePose(ManufacturingStage stage)
{
  for (const auto & preset : kLeftBreadPickStagePoses) {
    if (preset.stage == stage && preset.pose.enabled) {
      return &preset;
    }
  }
  return nullptr;
}

inline const StagePosePreset * findRightCasePickStagePose(ManufacturingStage stage)
{
  for (const auto & preset : kRightCasePickStagePoses) {
    if (preset.stage == stage && preset.pose.enabled) {
      return &preset;
    }
  }
  return nullptr;
}

}  // namespace ddooby_controller::manufacturing_task_presets
