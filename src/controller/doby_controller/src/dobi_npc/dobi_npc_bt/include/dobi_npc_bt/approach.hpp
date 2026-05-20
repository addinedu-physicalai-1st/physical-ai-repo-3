// approach.hpp
// Phase 2 W4 후속: Nav2 액션 코드 제거. approach_controller_node 의 PD 제어를
// /approach/enable Bool 게이트로 ON/OFF. bbox 높이 비율 (bh) 안정 검사로 SUCCESS.
//
// === 동작 흐름 ===
//   onStart:   stable_count_=0, last_track_seen_=now, /approach/enable=true 발행, RUNNING
//   onRunning: now - last_track_seen_ > lost_timeout_sec → enable=false + FAILURE
//              bh >= bh_threshold → stable_count++
//              stable_count >= stable_frames → enable=false + SUCCESS
//   onHalted:  enable=false 발행
//
// === stale guard (IdleScan 패턴 동일) ===
//   /customer_pose 도 카메라 끊기면 stale. /person_tracking/tracks 의 last_track_seen_
//   기반 lost_timeout_sec 이 stale + lost 둘 다 커버.

#ifndef DOBI_NPC_BT__APPROACH_HPP_
#define DOBI_NPC_BT__APPROACH_HPP_

#include <memory>
#include <string>
#include <utility>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"
#include "dobi_npc_msgs/msg/person_track_array.hpp"

namespace dobi_npc_bt
{

class Approach : public BT::StatefulActionNode
{
public:
  Approach(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node))
  {
    enable_pub_ = node_->create_publisher<std_msgs::msg::Bool>(
      "/approach/enable", 10);

    pose_sub_ = node_->create_subscription<geometry_msgs::msg::PoseStamped>(
      "/customer_pose", 10,
      [this](const geometry_msgs::msg::PoseStamped::SharedPtr msg) {
        last_bh_ = msg->pose.position.z;
        has_pose_ = true;
      });

    tracks_sub_ = node_->create_subscription<dobi_npc_msgs::msg::PersonTrackArray>(
      "/person_tracking/tracks", 10,
      [this](const dobi_npc_msgs::msg::PersonTrackArray::SharedPtr msg) {
        if (!msg->tracks.empty()) {
          last_track_seen_ = node_->now();
        }
      });

    last_track_seen_ = node_->now();
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>(
        "customer_id", "", "(미사용 — IdleScan 출력 호환)"),
      BT::InputPort<double>(
        "bh_threshold", 0.6, "bbox 높이 비율 종료 임계 (0~1, 클수록 가까움)"),
      BT::InputPort<int>(
        "stable_frames", 5, "bh 안정 프레임 (default 5)"),
      BT::InputPort<double>(
        "lost_timeout_sec", 2.0, "사람 lost 허용 시간 (초)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    stable_count_ = 0;
    last_track_seen_ = node_->now();
    publish_enable(true);
    RCLCPP_INFO(node_->get_logger(), "[Approach] start — /approach/enable=true");
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    double bh_threshold = 0.6;
    int stable_frames = 5;
    double lost_timeout_sec = 2.0;
    getInput("bh_threshold", bh_threshold);
    getInput("stable_frames", stable_frames);
    getInput("lost_timeout_sec", lost_timeout_sec);

    const auto now = node_->now();
    if ((now - last_track_seen_).seconds() > lost_timeout_sec) {
      RCLCPP_WARN(node_->get_logger(),
        "[Approach] lost timeout (%.1fs) — FAILURE", lost_timeout_sec);
      publish_enable(false);
      return BT::NodeStatus::FAILURE;
    }

    if (has_pose_ && last_bh_ >= bh_threshold) {
      stable_count_++;
      if (stable_count_ >= stable_frames) {
        RCLCPP_INFO(node_->get_logger(),
          "[Approach] SUCCESS — bh=%.2f stable=%d", last_bh_, stable_count_);
        publish_enable(false);
        return BT::NodeStatus::SUCCESS;
      }
    } else {
      stable_count_ = 0;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    publish_enable(false);
    RCLCPP_INFO(node_->get_logger(), "[Approach] halted — /approach/enable=false");
  }

private:
  void publish_enable(bool v)
  {
    std_msgs::msg::Bool msg;
    msg.data = v;
    enable_pub_->publish(msg);
  }

  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr enable_pub_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr pose_sub_;
  rclcpp::Subscription<dobi_npc_msgs::msg::PersonTrackArray>::SharedPtr tracks_sub_;

  double last_bh_ = 0.0;
  bool has_pose_ = false;
  rclcpp::Time last_track_seen_;
  int stable_count_ = 0;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__APPROACH_HPP_
