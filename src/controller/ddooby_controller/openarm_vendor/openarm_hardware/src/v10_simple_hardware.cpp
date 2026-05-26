// Copyright 2025 Enactic, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "openarm_hardware/v10_simple_hardware.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <thread>
#include <vector>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "rclcpp/logging.hpp"
#include "rclcpp/rclcpp.hpp"

namespace openarm_hardware {


OpenArm_v10HW::OpenArm_v10HW() = default;

bool OpenArm_v10HW::parse_config(const hardware_interface::HardwareInfo& info) {
  auto parse_bool = [](const std::string& value, bool default_value) {
    std::string normalized = value;
    normalized.erase(std::remove_if(normalized.begin(), normalized.end(),
                                    [](unsigned char ch) { return std::isspace(ch) != 0; }),
                     normalized.end());
    std::transform(normalized.begin(), normalized.end(), normalized.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });

    if (normalized == "true" || normalized == "1" || normalized == "yes" ||
        normalized == "on") {
      return true;
    }
    if (normalized == "false" || normalized == "0" || normalized == "no" ||
        normalized == "off") {
      return false;
    }
    return default_value;
  };

  // ===========================================================================
  // 설정 해석 설명
  // - 모든 파라미터는 <ros2_control><hardware><param .../></hardware></ros2_control>에서 가져옴
  // - 파라미터가 누락된 경우, 이 함수에 정의된 기본값을 사용함
  // ===========================================================================

  // 1) 기초 통신 파라미터
  auto it = info.hardware_parameters.find("can_interface");
  can_interface_ = (it != info.hardware_parameters.end()) ? it->second : "can0";

  it = info.hardware_parameters.find("arm_prefix");
  arm_prefix_ = (it != info.hardware_parameters.end()) ? it->second : "";

  it = info.hardware_parameters.find("hand");
  hand_ = (it == info.hardware_parameters.end()) ? true : parse_bool(it->second, true);

  it = info.hardware_parameters.find("can_fd");
  can_fd_ = (it == info.hardware_parameters.end()) ? true : parse_bool(it->second, true);

  // 2) 보상 기능 스위치
  it = info.hardware_parameters.find("enable_gravity_comp");
  enable_gravity_comp_ =
      (it == info.hardware_parameters.end()) ? true : parse_bool(it->second, true);

  it = info.hardware_parameters.find("enable_coriolis_comp");
  enable_coriolis_comp_ =
      (it == info.hardware_parameters.end()) ? false : parse_bool(it->second, false);

  it = info.hardware_parameters.find("return_to_zero_on_activate");
  return_to_zero_on_activate_ =
      (it == info.hardware_parameters.end()) ? false : parse_bool(it->second, false);

  it = info.hardware_parameters.find("hold_current_on_activate");
  hold_current_on_activate_ =
      (it == info.hardware_parameters.end()) ? true : parse_bool(it->second, true);
  
  // 3) 동역학 체인 끝점: tip_link가 설정되지 않은 경우 arm_prefix를 통해 자동으로 추론함.
  it = info.hardware_parameters.find("root_link");
  root_link_ = (it != info.hardware_parameters.end()) ? it->second : "openarm_body_link0";

  it = info.hardware_parameters.find("tip_link");
  if (it != info.hardware_parameters.end()) {
    tip_link_ = it->second;
  } else if (arm_prefix_.empty()) {
    tip_link_ = "openarm_hand";
  } else if (arm_prefix_ == "left_") {
    tip_link_ = "openarm_left_hand";
  } else {
    tip_link_ = "openarm_right_hand";
  }

  // 4) URDF에서 각 관절의 MIT 게인값을 읽어옴.
  // 주의: 여기서는 joint1..joint7 순서대로 kp_[0..6], kd_[0..6]에 기록함.
  for (size_t i = 1; i <= ARM_DOF; ++i) {
    it = info.hardware_parameters.find("kp" + std::to_string(i));
    if (it != info.hardware_parameters.end()) {
      kp_[i - 1] = std::stod(it->second);
    }
    it = info.hardware_parameters.find("kd" + std::to_string(i));
    if (it != info.hardware_parameters.end()) {
      kd_[i - 1] = std::stod(it->second);
    }
  }
  RCLCPP_INFO(
      rclcpp::get_logger("OpenArm_v10HW"),
      "【설정 개요】CAN=%s | arm_prefix=%s | 핸드=%s | CAN-FD=%s | 중력 보상=%s | 코리올리 보상=%s | 0점복귀=%s | 현재자세유지=%s",
      can_interface_.c_str(), arm_prefix_.c_str(),
      hand_ ? "활성화" : "비활성화", can_fd_ ? "활성화" : "비활성화",
      enable_gravity_comp_ ? "활성화" : "비활성화",
      enable_coriolis_comp_ ? "활성화" : "비활성화",
      return_to_zero_on_activate_ ? "활성화" : "비활성화",
      hold_current_on_activate_ ? "활성화" : "비활성화");

  if (enable_gravity_comp_ || enable_coriolis_comp_) {
    RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
                "【동역학 체인】root=%s | tip=%s",
                root_link_.c_str(), tip_link_.c_str());
  }

  return true;
}

void OpenArm_v10HW::generate_joint_names() {
  joint_names_.clear();

  // 관절 명명 규칙은 URDF / 컨트롤러 설정과 일치해야 함.
  // 예: openarm_left_joint1, openarm_right_joint1, openarm_joint1
  for (size_t i = 1; i <= ARM_DOF; ++i) {
    std::string joint_name =
        "openarm_" + arm_prefix_ + "joint" + std::to_string(i);
    joint_names_.push_back(joint_name);
  }

  if (hand_) {
    std::string gripper_joint_name = "openarm_" + arm_prefix_ + "finger_joint1";
    joint_names_.push_back(gripper_joint_name);
    RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"), "Added gripper joint: %s",
                gripper_joint_name.c_str());
  } else {
    RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
                "Gripper joint NOT added because hand_=false");
  }

  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
              "Generated %zu joint names for arm prefix '%s'",
              joint_names_.size(), arm_prefix_.c_str());
}

hardware_interface::CallbackReturn OpenArm_v10HW::on_init(
    const hardware_interface::HardwareInfo& info) {
  // 생명주기 진입점
  // 전형적인 호출 순서: on_init -> on_configure -> on_activate -> (read/write 루프)
  if (hardware_interface::SystemInterface::on_init(info) !=
      CallbackReturn::SUCCESS) {
    return CallbackReturn::ERROR;
  }
  // 설정 해석
  if (!parse_config(info)) {
    return CallbackReturn::ERROR;
  }
  // 관절 이름 생성
  generate_joint_names();
  // 관절 수 검증 (암 관절 7개 + 선택적 그리스퍼 관절 1개)
  size_t expected_joints = ARM_DOF + (hand_ ? 1 : 0);
  if (joint_names_.size() != expected_joints) {
    RCLCPP_ERROR(rclcpp::get_logger("OpenArm_v10HW"),
                 "Generated %zu joint names, expected %zu", joint_names_.size(),
                 expected_joints);
    return CallbackReturn::ERROR;
  }
  // OpenArm CAN 통신 초기화
  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
              "Initializing OpenArm on %s with CAN-FD %s...",
              can_interface_.c_str(), can_fd_ ? "enabled" : "disabled");
  // 모터 초기화
  openarm_ =
      std::make_unique<openarm::can::socket::OpenArm>(can_interface_, can_fd_);

  openarm_->init_arm_motors(DEFAULT_MOTOR_TYPES, DEFAULT_SEND_CAN_IDS,
                            DEFAULT_RECV_CAN_IDS);
  // 암 관절 7개의 send/recv CAN ID는 하드웨어 토폴로지와 일치해야 함.

  if (hand_) {
    RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"), "Initializing gripper...");
    openarm_->init_gripper_motor(DEFAULT_GRIPPER_MOTOR_TYPE,
                                 DEFAULT_GRIPPER_SEND_CAN_ID,
                                 DEFAULT_GRIPPER_RECV_CAN_ID);
  }
  // 상태/명령 벡터 초기화
  const size_t total_joints = joint_names_.size();
  pos_commands_.resize(total_joints, 0.0);
  vel_commands_.resize(total_joints, 0.0);
  tau_commands_.resize(total_joints, 0.0);
  pos_states_.resize(total_joints, 0.0);
  vel_states_.resize(total_joints, 0.0);
  tau_states_.resize(total_joints, 0.0);

  // 동역학 모델은 외부 파일 경로 의존성을 피하기 위해 URDF 원본 XML을 사용함.
  // 이렇게 하면 launch/시뮬레이션/실제 하드웨어 환경에서 절대 경로에 의존하지 않아 더욱 안정적임.
  if (enable_gravity_comp_ || enable_coriolis_comp_) {
    dynamics_ = std::make_unique<Dynamics>(info.original_xml, root_link_, tip_link_, true);
    if (!dynamics_->Init()) {
      RCLCPP_ERROR(rclcpp::get_logger("OpenArm_v10HW"),
                   "Failed to initialize dynamics solver");
      return CallbackReturn::ERROR;
    }
  }

  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
              "OpenArm V10 Simple HW initialized successfully");

  return CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn OpenArm_v10HW::on_configure(
    const rclcpp_lifecycle::State& /*previous_state*/) {
  // 통신을 한 프레임 예열하여 activate 전에 상태 캐시가 유효하도록 함.
  openarm_->refresh_all();
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  openarm_->recv_all();

  return CallbackReturn::SUCCESS;
}

std::vector<hardware_interface::StateInterface>
OpenArm_v10HW::export_state_interfaces() {
  // 상위 레이어에서 읽을 수 있는 상태 인터페이스로 내보냄: position / velocity / effort.
  // 이 값들은 read()에서 업데이트됨.
  std::vector<hardware_interface::StateInterface> state_interfaces;
  for (size_t i = 0; i < joint_names_.size(); ++i) {
    state_interfaces.emplace_back(hardware_interface::StateInterface(
        joint_names_[i], hardware_interface::HW_IF_POSITION, &pos_states_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
        joint_names_[i], hardware_interface::HW_IF_VELOCITY, &vel_states_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
        joint_names_[i], hardware_interface::HW_IF_EFFORT, &tau_states_[i]));
  }

  return state_interfaces;
}

std::vector<hardware_interface::CommandInterface>
OpenArm_v10HW::export_command_interfaces() {
  // 상위 레이어에서 쓸 수 있는 명령 인터페이스로 내보냄: position / velocity / effort.
  // 이 목표값들은 write()에서 MITParam으로 패키징됨.
  std::vector<hardware_interface::CommandInterface> command_interfaces;
  for (size_t i = 0; i < joint_names_.size(); ++i) {
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
        joint_names_[i], hardware_interface::HW_IF_POSITION,
        &pos_commands_[i]));
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
        joint_names_[i], hardware_interface::HW_IF_VELOCITY,
        &vel_commands_[i]));
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
        joint_names_[i], hardware_interface::HW_IF_EFFORT, &tau_commands_[i]));
  }

  return command_interfaces;
}

hardware_interface::CallbackReturn OpenArm_v10HW::on_activate(
    const rclcpp_lifecycle::State& /*previous_state*/) {
  // activate 단계: STATE 콜백 모드로 전환하고 모터를 활성화.
  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"), "Activating OpenArm V10...");
  openarm_->set_callback_mode_all(openarm::damiao_motor::CallbackMode::STATE);
  openarm_->enable_all();
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  openarm_->recv_all();

  if (hold_current_on_activate_) {
    sync_current_state_to_commands();
  }

  if (return_to_zero_on_activate_) {
    return_to_zero();
    std::fill(pos_commands_.begin(), pos_commands_.end(), 0.0);
    std::fill(vel_commands_.begin(), vel_commands_.end(), 0.0);
    std::fill(tau_commands_.begin(), tau_commands_.end(), 0.0);
    commands_initialized_ = true;
  } else {
    RCLCPP_INFO(
        rclcpp::get_logger("OpenArm_v10HW"),
        "Skipping zero return on activation; holding current command state");
  }

  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"), "OpenArm V10 activated");
  return CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn OpenArm_v10HW::on_deactivate(
    const rclcpp_lifecycle::State& /*previous_state*/) {
  // deactivate 단계: 잔여 토크를 피하기 위해 안전하게 전원 차단.
  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
              "Deactivating OpenArm V10...");

  openarm_->disable_all();
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  openarm_->recv_all();

  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"), "OpenArm V10 deactivated");
  return CallbackReturn::SUCCESS;
}

hardware_interface::return_type OpenArm_v10HW::read(
    const rclcpp::Time& /*time*/, const rclcpp::Duration& /*period*/) {
  // read() 데이터 흐름: CAN 피드백 -> pos/vel/tau 상태 인터페이스.
  // 이 단계는 일반적으로 controller_manager에 의해 고정 주기로 호출됨.
  openarm_->refresh_all();
  openarm_->recv_all();
  
  // 암 관절 상태 읽기
  const auto& arm_motors = openarm_->get_arm().get_motors();
  for (size_t i = 0; i < ARM_DOF && i < arm_motors.size(); ++i) {
    pos_states_[i] = arm_motors[i].get_position();
    vel_states_[i] = arm_motors[i].get_velocity();
    tau_states_[i] = arm_motors[i].get_torque();
  }
  // 그리퍼 상태 읽기 (사용 시)
  if (hand_ && joint_names_.size() > ARM_DOF) {
    const auto& gripper_motors = openarm_->get_gripper().get_motors();
    if (!gripper_motors.empty()) {
      double motor_pos = gripper_motors[0].get_position();
      pos_states_[ARM_DOF] = motor_radians_to_joint(motor_pos);

      // 현재 정밀한 그리퍼 속도/토크 매핑이 되어 있지 않으므로 0으로 유지.
      // 추후 그리퍼 힘 제어가 필요한 경우 이 매핑을 보완해야 함.
      vel_states_[ARM_DOF] = 0;  // gripper_motors[0].get_velocity();
      tau_states_[ARM_DOF] = 0;  // gripper_motors[0].get_torque();
    }
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::return_type OpenArm_v10HW::write(
    const rclcpp::Time& /*time*/, const rclcpp::Duration& /*period*/) {
  // write() 데이터 흐름: 컨트롤러 명령 + (선택적) 보상 -> MIT 명령 -> CAN.
  // 이곳이 향후 "제어 전략/보상 전략"을 확장할 주 입구임.
  if (!commands_initialized_) {
    return hardware_interface::return_type::OK;
  }

  std::vector<double> gravity_torque(ARM_DOF, 0.0);
  std::vector<double> coriolis_torque(ARM_DOF, 0.0);

  if (dynamics_) {
    if (enable_gravity_comp_) {
      // τ_g = G(q)
      dynamics_->GetGravity(pos_states_.data(), gravity_torque.data());
    }

    if (enable_coriolis_comp_) {
      // τ_c = C(q, qdot) * qdot
      dynamics_->GetCoriolis(pos_states_.data(), vel_states_.data(),
                             coriolis_torque.data());
    }
  }

  // MIT 제어 명령 구축: 피드포워드 토크 = 사용자 명령 + 보상
  std::vector<openarm::damiao_motor::MITParam> arm_params;
  arm_params.reserve(ARM_DOF);
  for (size_t i = 0; i < ARM_DOF; ++i) {
    // 정상 제어: 사용자 명령 + 동역학 보상
    const double tau_ff =
        tau_commands_[i] + gravity_torque[i] + coriolis_torque[i];
    arm_params.push_back(
        {kp_[i], kd_[i], pos_commands_[i], vel_commands_[i], tau_ff});
  }

  openarm_->get_arm().mit_control_all(arm_params);
  // 그리퍼 제어 (사용 시)
  if (hand_ && joint_names_.size() > ARM_DOF) {
    // 그리퍼는 계속 위치 기반 제어를 유지하여 MoveIt2 기본 컨트롤러와 호환성을 유지함.
    // 향후 그리퍼 힘 제어로 변경 시 마지막 항목인 tau_ff를 파지력 피드포워드로 사용할 수 있음.
    double motor_command = joint_to_motor_radians(pos_commands_[ARM_DOF]);
    openarm_->get_gripper().mit_control_all(
        {{GRIPPER_KP, GRIPPER_KD, motor_command, 0, 0}});
  }
  openarm_->recv_all(100);
  return hardware_interface::return_type::OK;
}

void OpenArm_v10HW::sync_current_state_to_commands() {
  openarm_->refresh_all();
  openarm_->recv_all();

  const auto& arm_motors = openarm_->get_arm().get_motors();
  for (size_t i = 0; i < ARM_DOF && i < arm_motors.size(); ++i) {
    pos_states_[i] = arm_motors[i].get_position();
    vel_states_[i] = arm_motors[i].get_velocity();
    tau_states_[i] = arm_motors[i].get_torque();
    pos_commands_[i] = pos_states_[i];
    vel_commands_[i] = 0.0;
    tau_commands_[i] = 0.0;
  }

  if (hand_ && joint_names_.size() > ARM_DOF) {
    const auto& gripper_motors = openarm_->get_gripper().get_motors();
    if (!gripper_motors.empty()) {
      pos_states_[ARM_DOF] = motor_radians_to_joint(gripper_motors[0].get_position());
      vel_states_[ARM_DOF] = 0.0;
      tau_states_[ARM_DOF] = 0.0;
      pos_commands_[ARM_DOF] = pos_states_[ARM_DOF];
      vel_commands_[ARM_DOF] = 0.0;
      tau_commands_[ARM_DOF] = 0.0;
    }
  }

  commands_initialized_ = true;
  RCLCPP_INFO(
      rclcpp::get_logger("OpenArm_v10HW"),
      "Initialized command state from current hardware position");
}

void OpenArm_v10HW::return_to_zero() {
  RCLCPP_INFO(rclcpp::get_logger("OpenArm_v10HW"),
              "Returning to zero position...");

  std::vector<openarm::damiao_motor::MITParam> arm_params;
  arm_params.reserve(ARM_DOF);
  for (size_t i = 0; i < ARM_DOF; ++i) {
    // 활성화 후 원점 복귀: 현재 Kp/Kd를 사용하고 목표 q=0, qdot=0, tau_ff=0 설정.
    arm_params.push_back({kp_[i], kd_[i], 0.0, 0.0, 0.0});
  }
  openarm_->get_arm().mit_control_all(arm_params);

  if (hand_) {
    // 그리퍼는 닫힌 원점 위치로 복귀 (현재 프로젝트의 기본 정의와 일치).
    openarm_->get_gripper().mit_control_all(
        {{GRIPPER_KP, GRIPPER_KD, GRIPPER_JOINT_0_POSITION, 0.0, 0.0}});
  }
  std::this_thread::sleep_for(std::chrono::microseconds(1000));
  openarm_->recv_all();
}

double OpenArm_v10HW::joint_to_motor_radians(double joint_value) {
  // 선형 매핑: joint [0, 0.044] -> motor [0, -1.0472]
  // 주: 이는 현재 하드웨어에 적합한 근사 모델임. 추후 기구 실측 곡선으로 대체 가능.
  return (joint_value / GRIPPER_JOINT_0_POSITION) *
         GRIPPER_MOTOR_1_RADIANS;
}

double OpenArm_v10HW::motor_radians_to_joint(double motor_radians) {
  // 역매핑: motor [0, -1.0472] -> joint [0, 0.044]
  return GRIPPER_JOINT_0_POSITION *
         (motor_radians / GRIPPER_MOTOR_1_RADIANS);
}

}  // namespace openarm_hardware

#include "pluginlib/class_list_macros.hpp"

PLUGINLIB_EXPORT_CLASS(openarm_hardware::OpenArm_v10HW,
                       hardware_interface::SystemInterface)
