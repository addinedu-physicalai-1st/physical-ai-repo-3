// emotion_monitor.hpp
// Phase 2 W4: /rapport/event 구독 → BT alarm 노드.
//
// === SUCCESS/FAILURE 시맨틱 (SafetyCheck와 동일 alarm 패턴) ===
//   SUCCESS = abort_trigger 수신됨 → ReactiveFallback이 즉시 멈춤 (funnel 차단)
//   FAILURE = abort_trigger 없음   → Fallback이 다음 자식(funnel) 진행
//
// 즉 정상 운영 시 FAILURE, 손님이 화내거나 두려워할 때만 SUCCESS.
//
// 시동 직후(아직 어떤 RapportEvent도 못 받음) → FAILURE (정상으로 취급).
//
// === Phase 진화 ===
//   Phase 2 후속: hysteresis / 지속성 (예: abort_trigger가 1초 이상이어야 차단)
//   Phase 3: rapport_delta 출력 포트 추가 (Minigame이 받음)
//   Phase 5: 학습 기반 abort 임계값 조정

#ifndef DOBI_NPC_BT__EMOTION_MONITOR_HPP_
#define DOBI_NPC_BT__EMOTION_MONITOR_HPP_

#include <atomic>
#include <memory>
#include <string>
#include <utility>

#include "behaviortree_cpp/condition_node.h"
#include "rclcpp/rclcpp.hpp"

#include "dobi_npc_msgs/msg/rapport_event.hpp"

namespace dobi_npc_bt
{

class EmotionMonitor : public BT::ConditionNode
{
public:
  EmotionMonitor(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::ConditionNode(name, config),
    node_(std::move(ros_node)),
    abort_active_(false)
  {
    sub_ = node_->create_subscription<dobi_npc_msgs::msg::RapportEvent>(
      "/rapport/event", 10,
      [this](dobi_npc_msgs::msg::RapportEvent::SharedPtr msg) {
        const bool is_abort = (msg->event_type == "abort_trigger");
        const bool prev = abort_active_.exchange(is_abort);
        if (is_abort && !prev) {
          RCLCPP_WARN(node_->get_logger(),
            "[EmotionMonitor] abort_trigger ON  (reason=%s, V=%.2f, A=%.2f)",
            msg->reason.c_str(),
            msg->emotion.valence,
            msg->emotion.arousal);
        } else if (!is_abort && prev) {
          RCLCPP_INFO(node_->get_logger(),
            "[EmotionMonitor] abort_trigger OFF (event=%s)",
            msg->event_type.c_str());
        }
      });
  }

  static BT::PortsList providedPorts()
  {
    // v1: 입력 포트 없음. Phase 후속에서 hysteresis_ms / rapport_delta 출력 등 추가.
    return {};
  }

  BT::NodeStatus tick() override
  {
    return abort_active_.load()
      ? BT::NodeStatus::SUCCESS   // alarm 발동
      : BT::NodeStatus::FAILURE;  // 정상 → 다음 자식으로 진행
  }

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<dobi_npc_msgs::msg::RapportEvent>::SharedPtr sub_;
  std::atomic<bool> abort_active_;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__EMOTION_MONITOR_HPP_
