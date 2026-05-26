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

#include "openarm_hardware/dynamics.hpp"

#include <fstream>
#include <algorithm>
#include <sstream>

#include "rclcpp/rclcpp.hpp"

namespace openarm_hardware {

Dynamics::Dynamics(const std::string& urdf_or_xml, const std::string& root_link,
                   const std::string& tip_link, bool is_urdf_xml)
    : urdf_or_xml_(urdf_or_xml),
      root_link_(root_link),
      tip_link_(tip_link),
      is_urdf_xml_(is_urdf_xml) {}

bool Dynamics::Init() {
  // ===========================================================================
  // Step 1) URDF 텍스트 획득
  // ===========================================================================
  std::string urdf_content;

  // 두 가지 입력 지원: URDF 파일 경로 / URDF XML 문자열.
  if (is_urdf_xml_) {
    urdf_content = urdf_or_xml_;
  } else {
    std::ifstream file(urdf_or_xml_);
    if (!file.is_open()) {
      RCLCPP_ERROR(rclcpp::get_logger("OpenArmDynamics"),
                   "Failed to open URDF file: %s", urdf_or_xml_.c_str());
      return false;
    }
    std::stringstream buffer;
    buffer << file.rdbuf();
    urdf_content = buffer.str();
  }

  // ===========================================================================
  // Step 2) URDF 해석 -> urdf::Model
  // ===========================================================================
  urdf::Model urdf_model;
  if (!urdf_model.initString(urdf_content)) {
    RCLCPP_ERROR(rclcpp::get_logger("OpenArmDynamics"), "Failed to parse URDF");
    return false;
  }

  // ===========================================================================
  // Step 3) urdf model -> KDL Tree (전체 로봇)
  // ===========================================================================
  KDL::Tree kdl_tree;
  if (!kdl_parser::treeFromUrdfModel(urdf_model, kdl_tree)) {
    RCLCPP_ERROR(rclcpp::get_logger("OpenArmDynamics"),
                 "Failed to extract KDL tree from URDF");
    return false;
  }

  // ===========================================================================
  // Step 4) Tree에서 root->tip의 KDL Chain 추출 (제어에 필요한 관절 체인)
  // ===========================================================================
  // 전체 로봇 트리에서 root_link -> tip_link에 대응하는 운동 체인을 추출함.
  if (!kdl_tree.getChain(root_link_, tip_link_, kdl_chain_)) {
    RCLCPP_ERROR(rclcpp::get_logger("OpenArmDynamics"),
                 "Failed to get KDL chain from '%s' to '%s'", root_link_.c_str(),
                 tip_link_.c_str());
    return false;
  }

  // ===========================================================================
  // Step 5) 중간 캐시 및 솔버 초기화
  // ===========================================================================
  // 제어 주기에서 메모리 반복 할당을 피하기 위해 캐시 할당.
  gravity_forces_.resize(kdl_chain_.getNrOfJoints());
  coriolis_forces_.resize(kdl_chain_.getNrOfJoints());
  
  gravity_forces_.data.setZero();
  coriolis_forces_.data.setZero();

  // 중력 방향은 기본적으로 세계 좌표계의 -Z 방향(m/s^2)을 채택함.
  solver_ = std::make_unique<KDL::ChainDynParam>(kdl_chain_, KDL::Vector(0.0, 0.0, -9.81));

  RCLCPP_INFO(rclcpp::get_logger("OpenArmDynamics"),
              "Dynamics initialized, chain joints=%u", kdl_chain_.getNrOfJoints());
  return true;
}

size_t Dynamics::JointCount() const {
  return kdl_chain_.getNrOfJoints();
}

void Dynamics::GetGravity(const double* joint_position, double* gravity) {
  // q(관절각) 입력
  // 네이티브 배열을 KDL::JntArray로 변환하고, KDL을 호출하여 τ_g = G(q)를 계산함.
  KDL::JntArray q(kdl_chain_.getNrOfJoints());
  for (size_t i = 0; i < kdl_chain_.getNrOfJoints(); ++i) {
    q(i) = joint_position[i];
  }

  solver_->JntToGravity(q, gravity_forces_);

  // τ_g 출력
  // 호출자 버퍼에 다시 씀.
  for (size_t i = 0; i < kdl_chain_.getNrOfJoints(); ++i) {
    gravity[i] = gravity_forces_(i);
  }
}

void Dynamics::GetCoriolis(const double* joint_position,
                           const double* joint_velocity, double* coriolis) {
  // q, qdot(관절각, 관절 속도) 입력
  // KDL을 호출하여 τ_c = C(q, qdot) * qdot을 계산함.
  KDL::JntArray q(kdl_chain_.getNrOfJoints());
  KDL::JntArray qd(kdl_chain_.getNrOfJoints());

  for (size_t i = 0; i < kdl_chain_.getNrOfJoints(); ++i) {
    q(i) = joint_position[i];
    qd(i) = joint_velocity[i];
  }

  solver_->JntToCoriolis(q, qd, coriolis_forces_);

  // τ_c 출력
  // 호출자 버퍼에 다시 씀.
  for (size_t i = 0; i < kdl_chain_.getNrOfJoints(); ++i) {
    coriolis[i] = coriolis_forces_(i);
  }
}

}  // namespace openarm_hardware
