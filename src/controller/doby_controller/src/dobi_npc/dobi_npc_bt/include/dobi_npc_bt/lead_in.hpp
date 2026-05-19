// lead_in.hpp
// Phase 3 — 카운터 안내 (3 phase StatefulActionNode, vicpinky 시뮬 모드).
//
// 흐름:
//   phase 1: UTTER_DEPART
//     /dialog/request "leadin" publish → "절 따라오세요" 발화 + utter_done 대기
//   phase 2: SIMULATE_TRAVEL
//     travel_sec 동안 가상 진행 (vicpinky 없는 노트북 단독 시뮬).
//     Phase 후속: simulate=false 시 Nav2 NavigateToPose 액션 client 로 교체.
//   phase 3: UTTER_ARRIVED
//     /dialog/request "leadin_arrived" publish → "도착했습니다" 발화 + utter_done
//
// Phase 진화:
//   Phase 후속: counter_pose_id 를 Nav2 goal 로 변환 (Approach 와 유사 패턴).
//   현재는 vicpinky 없는 노트북 단독 데모용 — 페르소나 narrative 에 집중.

#ifndef DOBI_NPC_BT__LEAD_IN_HPP_
#define DOBI_NPC_BT__LEAD_IN_HPP_

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

class LeadIn : public BT::StatefulActionNode
{
public:
  LeadIn(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node)),
    phase_(Phase::UTTER_DEPART),
    utter_done_(false)
  {
    dialog_pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/dialog/request", 10);
    utter_done_sub_ = node_->create_subscription<std_msgs::msg::Empty>(
      "/dialog/utter_done", 10,
      [this](std_msgs::msg::Empty::SharedPtr) {
        utter_done_.store(true);
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>(
        "counter_pose_id", "counter_default",
        "카운터 위치 pose ID (Phase 후속 Nav2 통합)"),
      BT::InputPort<double>(
        "travel_sec", 6.0,
        "시뮬 진행 시간 (초). simulate=true 일 때만 적용"),
      BT::InputPort<double>(
        "utter_timeout_sec", 8.0,
        "각 발화 단계의 utter_done 대기 timeout (초)"),
      BT::InputPort<bool>(
        "simulate", true,
        "true: 가상 진행 / false: Nav2 실 안내 (후속)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    phase_ = Phase::UTTER_DEPART;
    utter_done_.store(false);
    phase_started_ = node_->now();
    publish_dialog_request("leadin");
    RCLCPP_INFO(node_->get_logger(),
      "[LeadIn] phase 1/3 UTTER_DEPART — leadin 발화 요청");
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    double utter_timeout = 8.0;
    double travel_sec = 6.0;
    bool simulate = true;
    getInput<double>("utter_timeout_sec", utter_timeout);
    getInput<double>("travel_sec", travel_sec);
    getInput<bool>("simulate", simulate);

    const double elapsed = (node_->now() - phase_started_).seconds();

    switch (phase_) {
      case Phase::UTTER_DEPART: {
        const bool done = utter_done_.load();
        const bool timed_out = elapsed > utter_timeout;
        if (done || timed_out) {
          if (timed_out && !done) {
            RCLCPP_WARN(node_->get_logger(),
              "[LeadIn] leadin utter timeout %.1fs → 진행 강제 시작",
              elapsed);
          }
          if (!simulate) {
            // Phase 후속: Nav2 NavigateToPose 액션 client 로 교체.
            // 현재는 미구현 — simulate=true 와 동일 처리 + WARN.
            RCLCPP_WARN(node_->get_logger(),
              "[LeadIn] simulate=false 미구현 — 시뮬 모드로 폴백");
          }
          phase_ = Phase::SIMULATE_TRAVEL;
          phase_started_ = node_->now();
          RCLCPP_INFO(node_->get_logger(),
            "[LeadIn] phase 2/3 SIMULATE_TRAVEL — %.1fs 가상 진행",
            travel_sec);
        }
        return BT::NodeStatus::RUNNING;
      }

      case Phase::SIMULATE_TRAVEL: {
        if (elapsed >= travel_sec) {
          publish_dialog_request("leadin_arrived");
          phase_ = Phase::UTTER_ARRIVED;
          phase_started_ = node_->now();
          utter_done_.store(false);
          RCLCPP_INFO(node_->get_logger(),
            "[LeadIn] phase 3/3 UTTER_ARRIVED — leadin_arrived 발화 요청");
        }
        return BT::NodeStatus::RUNNING;
      }

      case Phase::UTTER_ARRIVED: {
        const bool done = utter_done_.load();
        const bool timed_out = elapsed > utter_timeout;
        if (done || timed_out) {
          if (timed_out && !done) {
            RCLCPP_WARN(node_->get_logger(),
              "[LeadIn] arrived utter timeout %.1fs → SUCCESS forced",
              elapsed);
          }
          RCLCPP_INFO(node_->get_logger(), "[LeadIn] 완료 → SUCCESS");
          return BT::NodeStatus::SUCCESS;
        }
        return BT::NodeStatus::RUNNING;
      }
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    RCLCPP_INFO(node_->get_logger(),
      "[LeadIn] halted (abort/외부 halt) phase=%d",
      static_cast<int>(phase_));
  }

private:
  enum class Phase { UTTER_DEPART, SIMULATE_TRAVEL, UTTER_ARRIVED };

  void publish_dialog_request(const std::string & stage_id)
  {
    std_msgs::msg::String msg;
    msg.data = stage_id;
    dialog_pub_->publish(msg);
  }

  rclcpp::Node::SharedPtr node_;
  Phase phase_;
  std::atomic<bool> utter_done_;
  rclcpp::Time phase_started_;

  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr dialog_pub_;
  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr utter_done_sub_;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__LEAD_IN_HPP_
