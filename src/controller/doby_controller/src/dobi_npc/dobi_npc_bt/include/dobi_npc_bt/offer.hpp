// offer.hpp
// Phase 1 W3 → Phase 2 W4-③ 후속: StatefulActionNode + utter_done 대기.

#ifndef DOBI_NPC_BT__OFFER_HPP_
#define DOBI_NPC_BT__OFFER_HPP_

#include <string>

#include "dobi_npc_bt/utter_action_base.hpp"

namespace dobi_npc_bt
{

class Offer : public UtterActionBase
{
public:
  Offer(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : UtterActionBase(name, config, std::move(ros_node), "offer") {}

  static BT::PortsList providedPorts()
  {
    auto ports = UtterActionBase::commonPorts();
    ports.insert(BT::InputPort<std::string>(
      "menu_category", "default",
      "추천 메뉴 카테고리 (Phase 2 메뉴 추천 통합)"));
    return ports;
  }
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__OFFER_HPP_
