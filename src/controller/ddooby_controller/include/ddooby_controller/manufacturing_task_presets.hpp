#pragma once

#include <array>
#include <cstddef>
#include <string_view>

namespace ddooby_controller::manufacturing_task_presets
{

// 제조 대상 구분.
enum class ManufacturingTarget
{
  Bread,
  Case,
  Coffee,
  Coke,
  Hotdog,
  Ketchup,
  Sausage,
};

// 제조에 사용하는 팔 구분.
enum class ArmSide
{
  Left,
  Right,
};

// 제조 공정의 큰 단계 구분.
// 외부 실행 단위는 home -> pick -> work -> place -> return_home이고,
// pre_grasp/pull_out은 pick 내부 waypoint로 사용한다.
enum class ManufacturingStage
{
  Home,
  Pick,
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

enum class PoseAxisSource
{
  // waypoint pose preset에 저장된 축 값을 그대로 사용.
  Preset,

  // 현재 오른손이 들고 있는 케이스 중심 위치의 해당 축 값을 사용.
  CaseTcp,

  // 선택된 target object 중심 위치의 해당 축 값을 사용.
  TargetObject,
};

struct StageWaypointPosePreset
{
  ManufacturingTarget target;
  ArmSide arm;
  ManufacturingStage stage;
  const char * name;
  TcpPosePreset pose;
  PoseAxisSource x_source{PoseAxisSource::Preset};
  PoseAxisSource y_source{PoseAxisSource::Preset};
  PoseAxisSource z_source{PoseAxisSource::Preset};
  double x_offset{0.0};
  double y_offset{0.0};
  double z_offset{0.0};
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

struct PlanningPreset
{
  // MoveIt planning 시간과 시도 횟수.
  double planning_time_sec;
  int planning_attempts;

  // 일반 pose target trajectory에 적용할 최소 실행 시간.
  double pose_min_duration_sec;
};

struct PickGeometryPreset
{
  // 자동 pre-grasp 높이와 lift 높이.
  double pre_grasp_height_m;
  double lift_height_m;

  // 수평 pick에서 target 중심으로부터 떨어지는 거리.
  double case_pre_grasp_distance_m;
  double ketchup_pre_grasp_distance_m;
};

struct PlaceGeometryPreset
{
  // place 접근 높이와 케이스 위 재료별 여유 높이.
  double approach_height_m;
  double case_bread_clearance_m;
  double case_sausage_clearance_m;
};

struct CartesianPreset
{
  // Cartesian path 계산 및 실행 튜닝.
  double eef_step_m;
  double min_fraction;
  bool avoid_collisions;
  double min_duration_sec;
};

struct PlanningScenePreset
{
  // grasp 직전 target object와 gripper touch link 사이의 collision 허용 여부와 settle 시간.
  bool allow_gripper_target_collision_for_grasp;
  int collision_scene_settle_ms;
};

struct KetchupSqueezePreset
{
  // 케첩을 뿌리는 길이, 소시지 위 노즐 높이, squeeze 시 그리퍼 닫힘량.
  double length_m;
  double height_m;
  double gripper_joint_position;
};

// Gazebo와 실물 OpenArm에 공통 적용되는 기본 이동 속도 preset.
inline constexpr MotionScalingPreset kDefaultMotionScaling{
  0.05,
  0.05,
  0.12,
  0.12
};

inline constexpr PlanningPreset kDefaultPlanning{
  8.0,
  8,
  3.5
};

inline constexpr PickGeometryPreset kDefaultPickGeometry{
  0.12,
  0.12,
  0.10,
  0.10
};

inline constexpr PlaceGeometryPreset kDefaultPlaceGeometry{
  0.08,
  0.005,
  0.004
};

inline constexpr CartesianPreset kDefaultCartesian{
  0.005,
  0.90,
  false,
  3.5
};

inline constexpr PlanningScenePreset kDefaultPlanningScene{
  true,
  300
};

inline constexpr KetchupSqueezePreset kDefaultKetchupSqueeze{
  0.12,
  0.060,
  0.010
};

// joint limit에 딱 붙지 않도록 안쪽으로 유지할 최소 margin.
inline constexpr double kDefaultJointLimitSafetyMargin = 0.00001;

// MoveIt plan + execute를 같은 목표에 대해 재시도할 기본 횟수.
inline constexpr int kDefaultPlanExecuteMaxAttempts = 5;

// Gazebo gripper action이 짧은 trajectory를 timeout/abort 처리하지 않도록 보장할 최소 시간.
inline constexpr double kDefaultGripperMinDurationSec = 2.0;

// 현재 TCP가 pose target에 이미 충분히 가까우면 짧은 보정 trajectory 실행을 건너뛴다.
inline constexpr double kDefaultPoseTargetSkipPositionToleranceM = 0.015;
inline constexpr double kDefaultPoseTargetSkipOrientationToleranceRad = 0.05;

// pre-grasp 도달 후 pick 진행을 허용할 최대 TCP xy 오차(m).
inline constexpr double kDefaultMaxPreGraspXyError = 0.035;

inline constexpr const char * stageName(ManufacturingStage stage)
{
  switch (stage) {
    case ManufacturingStage::Home:
      return "home";
    case ManufacturingStage::Pick:
      return "pick";
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
    case ManufacturingTarget::Coffee:
      return "coffee";
    case ManufacturingTarget::Coke:
      return "coke";
    case ManufacturingTarget::Hotdog:
      return "hotdog";
    case ManufacturingTarget::Ketchup:
      return "ketchup";
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

// target + arm + stage + waypoint별 커스텀 TCP pose 설정 테이블.
// 큰 stage는 home/pick/work/place/return_home 실행 범위만 나타내고,
// 실제 pose guide는 모두 waypoint로 정의한다.
// enabled=true인 pose만 가이드로 쓰고, 같은 큰 stage의 나머지 동작은 자동 계산/Planner가 처리한다.
// 예: Pick 내부에서 pre_grasp만 활성화하면 pre-grasp 자세만 고정하고 grasp/close/lift는 계속 자동 진행한다.
// waypoint name과 개수는 target/task마다 다르게 정의할 수 있다.
// 왼손 pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
// 오른손 pose 확인: ROS_LOG_DIR=/tmp/ros_logs ros2 run tf2_ros tf2_echo world openarm_right_hand_tcp
inline constexpr std::array<StageWaypointPosePreset, 52> kStageWaypointPosePresets{{
  // 빵 home stage: 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 work stage: 케이스 위 빵 놓기 직전 pose.
  // x/y는 현재 오른손 케이스 중심을 따라가고, z/orientation은 guide pose를 유지한다.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Work,
    "work",
    {true, 0.196, 0.035, 0.446, 0.728, -0.686, -0.002, 0.003},
    PoseAxisSource::CaseTcp,
    PoseAxisSource::CaseTcp,
    PoseAxisSource::Preset
  },
  // 빵 place stage: 케이스 위 빵 release pose, 비활성화 시 work pose에서 drop.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Place,
    "release",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 return_home stage: 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케이스 home stage: 작업 시작 pose, 비활성화 시 기존 ready pose 사용.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케이스 work stage: 케이스를 빵 받는 위치로 내미는 pose, 비활성화 시 현재 오른손 pose 사용.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Work,
    "work",
    {true, 0.204, -0.007, 0.367, 0.504, 0.497, 0.503, -0.496}
  },
  // 케이스 place stage: place pose, 현재는 비활성화.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Place,
    "release",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케이스 return_home stage: 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 소시지 home stage: 작업 시작 pose, 비활성화 시 기존 left ready pose 사용.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 소시지 work stage: 빵 위 소시지 놓기 직전 pose, 비활성화 시 자동 approach pose 사용.
  // x/y는 현재 오른손 케이스 중심을 따라가되 길쭉한 소시지를 위해 y 방향으로 살짝 앞쪽에 둔다.
  // z/orientation은 guide pose를 유지한다.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Work,
    "work",
    {true, 0.203, 0.029, 0.436, -0.707, 0.707, 0.002, -0.002},
    PoseAxisSource::CaseTcp,
    PoseAxisSource::CaseTcp,
    PoseAxisSource::Preset,
    0.0,
    0.020,
    0.0
  },
  // 소시지 place stage: 빵 위 소시지 release pose, 비활성화 시 오른손 케이스 pose 기준 자동 계산.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Place,
    "release",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 소시지 return_home stage: 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 home stage: 작업 시작 pose, 비활성화 시 기존 left ready pose 사용.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 work stage: 기본 pose, 비활성화 시 aim waypoint 또는 자동 계산.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Work,
    "work",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 work stage: 케첩을 뿌리기 전 오른손 케이스 presentation pose.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Right,
    ManufacturingStage::Work,
    "case_present",
    {true, 0.204, -0.039, 0.504, 0.505, 0.497, 0.503, -0.496}
  },
  // 케첩 place stage: 케첩 반환 pose. 비활성화 시 자동 반환 pose 사용.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Place,
    "return_pose",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 return_home stage: 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 완성 핫도그 place stage: pickup zone으로 가기 전 중간 경유 pose. 비활성화 시 건너뜀.
  {
    ManufacturingTarget::Hotdog,
    ArmSide::Right,
    ManufacturingStage::Place,
    "move1",
    {true, 0.451, -0.342, 0.507, 0.701, 0.033, 0.712, -0.025}
  },
  // 완성 핫도그 place stage: pickup zone으로 가기 전 두 번째 중간 경유 pose. 비활성화 시 건너뜀.
  {
    ManufacturingTarget::Hotdog,
    ArmSide::Right,
    ManufacturingStage::Place,
    "move2",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 완성 핫도그 place stage: pickup zone에 놓기 직전 release pose. 비활성화 시 자동 계산.
  {
    ManufacturingTarget::Hotdog,
    ArmSide::Right,
    ManufacturingStage::Place,
    "release_pose",
    {true, 0.012, -0.572, 0.318, 0.510, -0.483, 0.502, 0.504}
  },
  // 완성 핫도그 place stage: gripper open 이후 release waypoint. pose preset으로는 사용하지 않음.
  {
    ManufacturingTarget::Hotdog,
    ArmSide::Right,
    ManufacturingStage::Place,
    "release",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 완성 핫도그 return_home stage: 복귀 pose, 현재는 비활성화.
  {
    ManufacturingTarget::Hotdog,
    ArmSide::Right,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 빵 pick stage: 빵 위 접근 pose.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.391, 0.077, 0.401, 1.000, -0.001, -0.003, 0.000}
  },
  // 빵 pick stage: 빵 집기 pose. 비활성화 시 자동 계산.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "grasp",
    {false, 0.313, 0.184, 0.336, 1.000, -0.000, 0.004, 0.000}
  },
  // 빵 pick stage: 물체를 빼는 pose, 현재 비활성화.
  {
    ManufacturingTarget::Bread,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pull_out",
    {false, 0.329, 0.188, 0.458, 1.000, 0.000, -0.004, 0.001}
  },
  // 케이스 pick stage: 케이스 앞 접근 pose.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.324, -0.201, 0.398, 0.721, 0.000, 0.693, -0.000}
  },
  // 케이스 pick stage: 케이스 집기 pose. 비활성화 시 자동 계산.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Pick,
    "grasp",
    {false, 0.555, -0.191, 0.423, 0.0, 0.707, 0.0, 0.707}
  },
  // 케이스 pick stage: 케이스를 스탠드에서 빼는 pose.
  {
    ManufacturingTarget::Case,
    ArmSide::Right,
    ManufacturingStage::Pick,
    "pull_out",
    {true, 0.360, -0.201, 0.405, 0.721, -0.000, 0.693, -0.000}
  },
  // 소시지 pick stage: 소시지 위 접근 pose.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.391, 0.259, 0.401, 1.000, -0.001, -0.003, -0.000}
  },
  // 소시지 pick stage: 소시지 집기 pose. 비활성화 시 자동 계산.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "grasp",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 소시지 pick stage: 물체를 빼는 pose, 현재 비활성화.
  {
    ManufacturingTarget::Sausage,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pull_out",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 pick stage: 케첩 앞 접근 pose.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.438, 0.205, 0.600, 0.711, 0.036, 0.701, 0.035}
  },
  // 케첩 pick stage: 케첩 집기 pose. 비활성화 시 자동 계산.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "grasp",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 pick stage: 물체를 빼는 pose, 현재 비활성화.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pull_out",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 케첩 work stage: 소시지 위 시작 aim pose.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Work,
    "aim",
    {true, 0.204, -0.024, 0.700, -0.478, -0.517, 0.527, -0.476}
  },
  // 케첩 work stage: 소시지 길이 방향으로 뿌린 뒤 끝 pose.
  {
    ManufacturingTarget::Ketchup,
    ArmSide::Left,
    ManufacturingStage::Work,
    "squeeze",
    {true, 0.205, 0.040, 0.699, -0.478, -0.517, 0.527, -0.476}
  },
  // 콜라 home stage: 작업 시작 pose, 비활성화 시 기존 left ready pose 사용.
  {
    ManufacturingTarget::Coke,
    ArmSide::Left,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 콜라 pick stage: 음료 진열대 앞 접근 pose.
  {
    ManufacturingTarget::Coke,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.438, 0.241, 0.520, 0.711, 0.036, 0.701, 0.035}
  },
  // 콜라 work stage: 왼팔이 오른팔에 캔을 넘겨주는 pose.
  {
    ManufacturingTarget::Coke,
    ArmSide::Left,
    ManufacturingStage::Work,
    "handoff",
    {true, 0.186, 0.028, 0.553, 0.503, -0.504, 0.480, 0.512}
  },
  // 콜라 work stage: 오른팔이 캔을 넘겨받기 전 진입 가이드 pose.
  {
    ManufacturingTarget::Coke,
    ArmSide::Right,
    ManufacturingStage::Work,
    "pre_receive",
    {true, 0.170, -0.101, 0.436, 0.511, 0.490, 0.503, -0.495}
  },
  // 콜라 work stage: 오른팔 인계 후 왼팔이 캔을 치지 않고 빠지는 pose.
  {
    ManufacturingTarget::Coke,
    ArmSide::Left,
    ManufacturingStage::Work,
    "left_pull_out",
    {true, 0.187, 0.060, 0.553, 0.503, -0.504, 0.480, 0.512}
  },
  // 콜라 place stage: pickup zone release pose로 가기 전 오른팔 중간 경유 pose.
  {
    ManufacturingTarget::Coke,
    ArmSide::Right,
    ManufacturingStage::Place,
    "approach",
    {true, -0.009, -0.613, 0.507, 0.499, -0.499, 0.494, 0.507}
  },
  // 콜라 place stage: pickup zone에 놓기 직전 pose. 비활성화 시 pickup zone 기준 자동 계산.
  {
    ManufacturingTarget::Coke,
    ArmSide::Right,
    ManufacturingStage::Place,
    "release_pose",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 콜라 return_home stage: 오른팔 복귀 pose, 비활성화 시 named home pose 사용.
  {
    ManufacturingTarget::Coke,
    ArmSide::Right,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 커피 home stage: 작업 시작 pose, 비활성화 시 기존 left ready pose 사용.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Left,
    ManufacturingStage::Home,
    "ready",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 커피 pick stage: 음료 진열대 앞 접근 pose.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Left,
    ManufacturingStage::Pick,
    "pre_grasp",
    {true, 0.438, 0.086, 0.520, 0.711, 0.036, 0.701, 0.035}
  },
  // 커피 work stage: 왼팔이 오른팔에 캔을 넘겨주는 pose.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Left,
    ManufacturingStage::Work,
    "handoff",
    {true, 0.186, 0.028, 0.553, 0.503, -0.504, 0.480, 0.512}
  },
  // 커피 work stage: 오른팔이 캔을 넘겨받기 전 진입 가이드 pose.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Right,
    ManufacturingStage::Work,
    "pre_receive",
    {true, 0.170, -0.101, 0.436, 0.511, 0.490, 0.503, -0.495}
  },
  // 커피 work stage: 오른팔 인계 후 왼팔이 캔을 치지 않고 빠지는 pose.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Left,
    ManufacturingStage::Work,
    "left_pull_out",
    {true, 0.187, 0.060, 0.553, 0.503, -0.504, 0.480, 0.512}
  },
  // 커피 place stage: pickup zone release pose로 가기 전 오른팔 중간 경유 pose.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Right,
    ManufacturingStage::Place,
    "approach",
    {true, -0.009, -0.613, 0.507, 0.499, -0.499, 0.494, 0.507}
  },
  // 커피 place stage: pickup zone에 놓기 직전 pose. 비활성화 시 pickup zone 기준 자동 계산.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Right,
    ManufacturingStage::Place,
    "release_pose",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
  // 커피 return_home stage: 오른팔 복귀 pose, 비활성화 시 named home pose 사용.
  {
    ManufacturingTarget::Coffee,
    ArmSide::Right,
    ManufacturingStage::ReturnHome,
    "return_home",
    {false, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}
  },
}};

// 빵 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftBreadPickTuning{
  0.0,
  {true, 0.030},
  {true, 0.021}
};

// 케이스 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kRightCasePickTuning{
  -0.020,
  {true, 0.043},
  {true, 0.034}
};

// 케이스 pre_grasp 이후 target 방향으로 정렬하는 중간 pose 높이 보정값.
// 오른팔 joint2 하한에 붙지 않도록 실제 grasp 진입 전만 살짝 띄운다.
inline constexpr double kRightCaseTargetAlignZOffsetM = 0.015;

// 케이스 grasp 시 면에 너무 붙어 MoveIt gripper close collision이 나는 것을 피하기 위한 world z 여유.
// 깊이는 kRightCasePickTuning.grasp_tcp_z_offset_m으로 유지하고 높이만 올린다.
inline constexpr double kRightCaseGraspWorldZOffsetM = 0.004;

// 소시지 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftSausagePickTuning{
  0.006,
  {true, 0.024},
  {true, 0.005}
};

// 케첩 pick 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftKetchupPickTuning{
  0.0,
  {true, 0.040},
  {true, 0.018}
};

// 음료 캔 pick/인계 파지 세부 조정값.
inline constexpr PickTuningPreset kLeftBeverageCanPickTuning{
  0.0,
  {true, 0.043},
  {true, 0.018}
};

inline constexpr PickTuningPreset kRightBeverageCanReceiveTuning{
  0.0,
  {true, 0.043},
  {true, 0.018}
};

// 음료 캔은 왼손이 캔 중심보다 위를 잡고, 오른손이 캔 중심보다 아래를 잡는다.
// horizontal pick에서 grasp_tcp_z_offset_m은 world z가 아니므로, 음료 전용 world z offset을 별도로 둔다.
inline constexpr double kLeftBeverageCanGraspWorldZOffsetM = 0.025;
inline constexpr double kRightBeverageCanReceiveWorldZOffsetM = -0.025;
inline constexpr double kBeverageHandoffRightFromLeftZOffsetM =
  kRightBeverageCanReceiveWorldZOffsetM - kLeftBeverageCanGraspWorldZOffsetM;
// 왼손이 캔을 놓은 뒤 오른손과 캔을 건드리지 않도록 수평으로 빠지는 거리.
inline constexpr double kBeverageLeftHandoffRetreatDistanceM = 0.120;

// 음료 캔 pickup zone 배치 높이와 품목별 y offset.
inline constexpr double kBeveragePickupApproachHeightM = 0.100;
inline constexpr double kBeveragePickupPlaceClearanceM = 0.005;
inline constexpr double kCokePickupZoneYOffsetM = -0.040;
inline constexpr double kCoffeePickupZoneYOffsetM = 0.040;

// 케첩 반환 시 음료 진열대 천장판을 넘기 위한 return_pose 직전 clearance 높이.
inline constexpr double kLeftKetchupReturnLiftHeightM = 0.120;

// 완성 핫도그를 pickup zone에 놓을 때 쓰는 오른손 접근 높이와 바닥 clearance.
inline constexpr double kCompletedHotdogPickupApproachHeightM = 0.120;
inline constexpr double kCompletedHotdogPickupPlaceClearanceM = 0.010;

inline const StageWaypointPosePreset * findStageWaypointPosePreset(
  ManufacturingTarget target,
  ArmSide arm,
  ManufacturingStage stage,
  const char * name)
{
  for (const auto & preset : kStageWaypointPosePresets) {
    if (preset.target == target && preset.arm == arm && preset.stage == stage &&
      preset.name == std::string_view{name} && preset.pose.enabled)
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
  if (target == ManufacturingTarget::Ketchup && arm == ArmSide::Left) {
    return &kLeftKetchupPickTuning;
  }
  if ((target == ManufacturingTarget::Coke || target == ManufacturingTarget::Coffee) &&
    arm == ArmSide::Left)
  {
    return &kLeftBeverageCanPickTuning;
  }
  return nullptr;
}

}  // namespace ddooby_controller::manufacturing_task_presets
