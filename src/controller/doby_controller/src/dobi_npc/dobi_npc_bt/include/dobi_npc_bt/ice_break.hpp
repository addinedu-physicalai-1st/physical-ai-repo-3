// ice_break.hpp
// Phase 1 W3 → Phase 2 W4-③ 후속:
//   StatefulActionNode로 변환. /dialog/utter_done 대기로 발화 완료 동기화.
//   공통 로직은 UtterActionBase로 추출.

#ifndef DOBI_NPC_BT__ICE_BREAK_HPP_
#define DOBI_NPC_BT__ICE_BREAK_HPP_

#include <string>

#include "dobi_npc_bt/utter_action_base.hpp"

namespace dobi_npc_bt
{

class IceBreak : public UtterActionBase
{
public:
  IceBreak(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : UtterActionBase(name, config, std::move(ros_node), "icebreak") {}

  static BT::PortsList providedPorts()
  {
    auto ports = UtterActionBase::commonPorts();
    ports.insert(BT::InputPort<std::string>(
      "phrase_pool_id", "casual_browser",
      "페르소나 phrase pool ID (참고용)"));
    return ports;
  }
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__ICE_BREAK_HPP_
