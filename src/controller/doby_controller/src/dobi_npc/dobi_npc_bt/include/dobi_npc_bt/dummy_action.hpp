// dummy_action.hpp
// Phase 0-B 빌드 검증용 placeholder.
// Phase 1 Week 1에서 실제 BT 노드(IdleScan, Approach, IceBreak 등)로 교체됨.

#ifndef DOBI_NPC_BT__DUMMY_ACTION_HPP_
#define DOBI_NPC_BT__DUMMY_ACTION_HPP_

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"

namespace dobi_npc_bt
{

class DummyAction : public BT::SyncActionNode
{
public:
  DummyAction(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}

  static BT::PortsList providedPorts()
  {
    return {};
  }

  BT::NodeStatus tick() override
  {
    // Phase 0-B: 항상 SUCCESS (실제 로직은 Phase 1에서 구현)
    return BT::NodeStatus::SUCCESS;
  }
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__DUMMY_ACTION_HPP_
