// utter_action_base.hpp
// Phase 2 W4-③ 후속: BT 노드가 TTS 발화 완료를 기다려야 사이클이 자연스러움.
//
// IceBreak/Offer/LeadIn 공통 패턴:
//   onStart   — /dialog/request 에 stage_id publish, RUNNING 반환
//   onRunning — /dialog/utter_done (Empty) 수신 시 SUCCESS, timeout 시 SUCCESS+WARN
//   onHalted  — abort/외부 halt 시 cleanup
//
// 타임아웃이 FAILURE가 아닌 SUCCESS인 이유: 호객 funnel은 끝까지 진행이 자연.
// TTS 합성 실패/네트워크 장애 등으로 utter_done이 안 와도 다음 stage로 넘어감.

#ifndef DOBI_NPC_BT__UTTER_ACTION_BASE_HPP_
#define DOBI_NPC_BT__UTTER_ACTION_BASE_HPP_

#include <atomic>
#include <memory>
#include <string>
#include <utility>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/empty.hpp"
#include "std_msgs/msg/string.hpp"

namespace dobi_npc_bt
{

class UtterActionBase : public BT::StatefulActionNode
{
public:
  UtterActionBase(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node,
    const std::string & stage_id)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node)),
    stage_id_(stage_id),
    done_received_(false)
  {
    pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/dialog/request", 10);
    done_sub_ = node_->create_subscription<std_msgs::msg::Empty>(
      "/dialog/utter_done", 10,
      [this](std_msgs::msg::Empty::SharedPtr) {
        done_received_.store(true);
      });
  }

  // 자식이 자기 만의 입력 포트를 추가할 때 base의 timeout_sec와 머지
  static BT::PortsList commonPorts()
  {
    return {
      BT::InputPort<double>(
        "timeout_sec", 10.0,
        "발화 완료 대기 timeout (초). 초과 시 SUCCESS+WARN")
    };
  }

  BT::NodeStatus onStart() override
  {
    done_received_.store(false);
    started_ = node_->now();
    std_msgs::msg::String msg;
    msg.data = stage_id_;
    pub_->publish(msg);
    RCLCPP_INFO(node_->get_logger(),
      "[%s] publish stage=%s, waiting utter_done...",
      name().c_str(), stage_id_.c_str());
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    if (done_received_.load()) {
      RCLCPP_INFO(node_->get_logger(),
        "[%s] utter_done → SUCCESS", name().c_str());
      return BT::NodeStatus::SUCCESS;
    }
    double timeout_sec = 10.0;
    getInput<double>("timeout_sec", timeout_sec);
    const double elapsed = (node_->now() - started_).seconds();
    if (elapsed > timeout_sec) {
      RCLCPP_WARN(node_->get_logger(),
        "[%s] timeout %.1fs → SUCCESS (forced)",
        name().c_str(), elapsed);
      return BT::NodeStatus::SUCCESS;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    RCLCPP_INFO(node_->get_logger(),
      "[%s] halted (abort 또는 외부 halt)", name().c_str());
  }

private:
  rclcpp::Node::SharedPtr node_;
  std::string stage_id_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_;
  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr done_sub_;
  std::atomic<bool> done_received_;
  rclcpp::Time started_;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__UTTER_ACTION_BASE_HPP_
