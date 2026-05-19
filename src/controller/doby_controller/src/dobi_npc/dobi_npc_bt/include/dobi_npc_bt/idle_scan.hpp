// idle_scan.hpp
// Phase 1 W1: 더미 SUCCESS. W2에서 ceiling camera + customer detection.
// Funnel Stage 1: 고객 후보 탐지.

#ifndef DOBI_NPC_BT__IDLE_SCAN_HPP_
#define DOBI_NPC_BT__IDLE_SCAN_HPP_

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"

namespace dobi_npc_bt
{

class IdleScan : public BT::SyncActionNode
{
public:
  IdleScan(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}

  static BT::PortsList providedPorts()
  {
    return {
      BT::OutputPort<std::string>("customer_id", "탐지된 고객 후보 ID")
    };
  }

  BT::NodeStatus tick() override
  {
    // Phase 1 W1: 더미 customer_id 출력 + SUCCESS.
    setOutput("customer_id", "dummy_customer_001");
    return BT::NodeStatus::SUCCESS;
  }
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__IDLE_SCAN_HPP_
