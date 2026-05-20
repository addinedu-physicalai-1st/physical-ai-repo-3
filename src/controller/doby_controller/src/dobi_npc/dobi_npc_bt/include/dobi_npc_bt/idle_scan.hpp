// idle_scan.hpp
// Phase 2 W4 후속: person_tracking_pkg 통합. /person_tracking/tracks 구독 후
// tracks.size>=1 이 stable_frames 연속 안정 시 SUCCESS + top track_id 출력.
//
// === 동작 흐름 ===
//   onStart:  stable_count_ = 0, RUNNING
//   onRunning: 메시지 stale (>msg_timeout_sec) → stable_count = 0
//              tracks.size>=1 → stable_count++ 아니면 reset
//              stable_count>=stable_frames → SUCCESS + customer_id 출력
//              아니면 RUNNING
//   onHalted: no-op
//
// === stale guard (2026-05-20 code review 후 추가) ===
//   카메라/트래킹 노드 단절 시 last_tracks_ 가 마지막 본 사람으로 stale 유지 →
//   stable_count 계속 누적 → 잘못된 SUCCESS 위험. msg_timeout_sec(default 0.5s)
//   초과 시 stable_count 강제 0 으로.

#ifndef DOBI_NPC_BT__IDLE_SCAN_HPP_
#define DOBI_NPC_BT__IDLE_SCAN_HPP_

#include <algorithm>
#include <memory>
#include <string>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "dobi_npc_msgs/msg/person_track_array.hpp"

namespace dobi_npc_bt
{

class IdleScan : public BT::StatefulActionNode
{
public:
  IdleScan(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node))
  {
    tracks_sub_ = node_->create_subscription<dobi_npc_msgs::msg::PersonTrackArray>(
      "/person_tracking/tracks", 10,
      [this](const dobi_npc_msgs::msg::PersonTrackArray::SharedPtr msg) {
        last_tracks_ = *msg;
        last_msg_time_ = node_->now();
        has_msg_ = true;
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>(
        "stable_frames", 5, "사람 발견 연속 안정 프레임 (default 5)"),
      BT::InputPort<double>(
        "msg_timeout_sec", 0.5,
        "마지막 /person_tracking/tracks 메시지로부터 허용 시간 (초). "
        "초과 시 stale 로 간주 → stable_count 강제 reset"),
      BT::OutputPort<std::string>(
        "customer_id", "탐지된 고객 track_id (가장 큰 bbox 사람)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    stable_count_ = 0;
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    int stable_frames = 5;
    double msg_timeout_sec = 0.5;
    getInput("stable_frames", stable_frames);
    getInput("msg_timeout_sec", msg_timeout_sec);

    // === stale guard: 메시지 0.5s 이상 끊기면 즉시 reset ===
    const bool stale = !has_msg_ ||
      (node_->now() - last_msg_time_).seconds() > msg_timeout_sec;

    if (stale) {
      stable_count_ = 0;
      return BT::NodeStatus::RUNNING;
    }

    if (!last_tracks_.tracks.empty()) {
      stable_count_++;
      if (stable_count_ >= stable_frames) {
        const auto & top = *std::max_element(
          last_tracks_.tracks.begin(), last_tracks_.tracks.end(),
          [](const auto & a, const auto & b) {
            const float a_area = (a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]);
            const float b_area = (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]);
            return a_area < b_area;
          });
        setOutput("customer_id", std::to_string(top.track_id));
        RCLCPP_INFO(node_->get_logger(),
          "[IdleScan] SUCCESS — customer_id=%d stable=%d tracks=%zu",
          top.track_id, stable_count_, last_tracks_.tracks.size());
        return BT::NodeStatus::SUCCESS;
      }
    } else {
      stable_count_ = 0;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    // no-op
  }

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<dobi_npc_msgs::msg::PersonTrackArray>::SharedPtr tracks_sub_;
  dobi_npc_msgs::msg::PersonTrackArray last_tracks_;
  rclcpp::Time last_msg_time_;
  bool has_msg_ = false;
  int stable_count_ = 0;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__IDLE_SCAN_HPP_
