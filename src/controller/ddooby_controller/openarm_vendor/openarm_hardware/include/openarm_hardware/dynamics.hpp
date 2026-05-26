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

#pragma once

#include <memory>
#include <string>

#include <kdl/chain.hpp>
#include <kdl/chaindynparam.hpp>
#include <kdl_parser/kdl_parser.hpp>
#include <urdf/model.h>

namespace openarm_hardware {

/**
 * @brief 가벼운 동력학 래퍼 (KDL)
 *
 * 설계 목적:
 * - hardware 주기에서 가장 자주 사용되고 안정적인 두 가지 보상량만 제공
 * - 인터페이스를 단순하게 유지하여 유지보수 및 디버깅 용이
 * - 복잡한 제어 전략을 이 클래스에 결합하지 않음
 *
 * 현재 공개된 기능:
 * - GetGravity : τ_g = G(q) 계산
 * - GetCoriolis: τ_c = C(q, qdot) * qdot 계산
 *
 * 전형적인 사용 예:
 * - write() 주기에서 현재 상태(q, qdot)를 기반으로 보상 토크를 획득하고,
 *   상위 레이어에서 주어진 tau 명령과 중첩하여 모터에 하달함.
 */
class Dynamics {
 public:
  // urdf_or_xml:
  // - is_urdf_xml=false: URDF 파일 경로 전달
  // - is_urdf_xml=true : URDF XML 문자열 전달 (ros2_control info.original_xml 사용 권장)
  Dynamics(const std::string& urdf_or_xml, const std::string& root_link,
           const std::string& tip_link, bool is_urdf_xml = false);

  // URDF 해석 -> KDL tree/chain 구축 -> 동역학 솔버 초기화.
  // false 반환은 보통 다음을 의미함:
  // - URDF 해석 실패;
  // - root_link / tip_link가 존재하지 않음;
  // - 트리에서 대상 운동 체인을 추출할 수 없음.
  bool Init();

  size_t JointCount() const;

  // 현재 관절각을 입력하여 각 관절의 중력 보상 토크(Nm)를 출력함.
  // 입력/출력 배열 길이는 체인 관절 수(보통 7개)와 같아야 함.
  void GetGravity(const double* joint_position, double* gravity);

  // 관절각과 관절 속도를 입력하여 코리올리/원심력 보상 토크(Nm)를 출력함.
  // 저속 운동에서는 보통 이 항이 작지만, 고속 추종 시에는 가치가 더 명확해짐.
  void GetCoriolis(const double* joint_position, const double* joint_velocity,
                   double* coriolis);

 private:
  std::string urdf_or_xml_;
  std::string root_link_;
  std::string tip_link_;
  bool is_urdf_xml_ = false;

  KDL::Chain kdl_chain_;
  KDL::JntArray gravity_forces_;
  KDL::JntArray coriolis_forces_;
  std::unique_ptr<KDL::ChainDynParam> solver_;
};

}  // namespace openarm_hardware
