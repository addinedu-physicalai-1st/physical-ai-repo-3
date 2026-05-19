// approach.hpp
// Phase 1 W2 Step B+C+D: Nav2 NavigateToPose 액션 클라이언트 + Proxemic 로직.
// Funnel Stage 2: 고객을 향해 사회적 거리(1.5m) 떨어진 위치로 접근.
//
// === 동작 흐름 ===
//   onStart:
//     1) Proxemic 계산 (customer_pose 있으면) — Nav2 모드 여부 무관
//     2) Step D abort 체크 (거리 < 1.0m) — 안전 우선, Nav2 무관 → 즉시 FAILURE
//     3) goal_valid=false + allow_dummy_goal=false (기본) →
//        Nav2 송신 스킵, fallback SUCCESS  ← 안전 가드 (2026-05-04)
//     4) Nav2 서버 발견 시도:
//        성공 → goal 송신, RUNNING
//        실패 → no_nav2_fallback_ = true, 다음 tick에 SUCCESS (검증용)
//
//   onRunning:
//     1) Step D abort 체크 (매 tick) — Nav2 무관 → FAILURE
//     2) Nav2 모드: goal 결과 폴링
//     3) Fallback 모드: SUCCESS
//
// === 단순화 가정 (Step C/D) ===
//   로봇 위치 = 원점 (0, 0). 거리 = sqrt(cx^2 + cy^2).
//   Phase 2/4에서 TF (map → base_link) 통합 시 정밀화.
//
// === 안전 가드 (2026-05-04 추가) ===
//   /customer_pose 미수신 + goal_pose 입력 미연결 시 dummy goal (1.0, 0.0)이
//   Nav2에 송신될 위험 — Test 1B에서 라이브 재현됨. 첫 BT 사이클 race로
//   subscriber가 첫 메시지 못 받을 때 발생. allow_dummy_goal=false (기본)로
//   이 경로 차단. dev/시뮬레이션에서 일부러 dummy 송신 원하면 BT XML에서
//   allow_dummy_goal="true" 설정.

#ifndef DOBI_NPC_BT__APPROACH_HPP_
#define DOBI_NPC_BT__APPROACH_HPP_

#include <chrono>
#include <cmath>
#include <memory>
#include <string>
#include <utility>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "nav2_msgs/action/navigate_to_pose.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"

namespace dobi_npc_bt
{

class Approach : public BT::StatefulActionNode
{
public:
  using NavigateToPose = nav2_msgs::action::NavigateToPose;
  using GoalHandleNav = rclcpp_action::ClientGoalHandle<NavigateToPose>;
  using ResultCode = rclcpp_action::ResultCode;

  Approach(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node))
  {
    action_client_ = rclcpp_action::create_client<NavigateToPose>(
      node_, "navigate_to_pose");

    customer_sub_ = node_->create_subscription<geometry_msgs::msg::PoseStamped>(
      "/customer_pose", 10,
      [this](const geometry_msgs::msg::PoseStamped::SharedPtr msg) {
        last_customer_pose_ = *msg;
        has_customer_pose_ = true;
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>(
        "customer_id", "", "고객 식별자 (Phase 2에서 활성화)"),
      BT::InputPort<geometry_msgs::msg::PoseStamped>(
        "goal_pose", "직접 지정 PoseStamped (없고 /customer_pose도 없으면 더미 사용)"),
      BT::InputPort<double>(
        "social_distance", "1.5", "사회적 거리 (한국 보정 1.5m)"),
      BT::InputPort<double>(
        "abort_threshold", "1.0", "abort 거리 (1.0m 이내 손님 시 정지)"),
      BT::InputPort<double>(
        "server_timeout_sec", "1.0", "Nav2 서버 발견 타임아웃 (초)"),
      BT::InputPort<std::string>(
        "allow_dummy_goal", "false",
        "/customer_pose 미수신 + goal_pose 미연결 시 더미 (1.0, 0.0) Nav2 송신 허용. "
        "기본 \"false\" (안전) — 첫 사이클 race로 vic_pinky 무계획 1m 이동 차단. "
        "허용 값 \"true\"/\"1\"/\"TRUE\"/\"True\" 외엔 모두 false로 처리."),
    };
  }

  BT::NodeStatus onStart() override
  {
    auto logger = node_->get_logger();

    double timeout_sec = 1.0;
    double social_distance = 1.5;
    double abort_threshold = 1.0;
    getInput("server_timeout_sec", timeout_sec);
    getInput("social_distance", social_distance);
    getInput("abort_threshold", abort_threshold);

    // === 1. Proxemic 계산 (Nav2 모드 무관, 항상 실행) ===
    geometry_msgs::msg::PoseStamped goal_pose;
    bool goal_valid = false;

    if (has_customer_pose_) {
      const double cx = last_customer_pose_.pose.position.x;
      const double cy = last_customer_pose_.pose.position.y;
      const double dist = std::hypot(cx, cy);

      // === 2. Step D abort: 안전 우선, Nav2 여부 무관 ===
      if (dist < abort_threshold) {
        RCLCPP_WARN(logger,
          "[Approach] onStart abort: 고객 거리 %.2fm < %.2fm → FAILURE",
          dist, abort_threshold);
        return BT::NodeStatus::FAILURE;
      }

      // Proxemic goal 계산: 고객에서 로봇 쪽으로 social_distance 떨어진 점
      const double goal_x = cx + (-cx / dist) * social_distance;
      const double goal_y = cy + (-cy / dist) * social_distance;

      goal_pose.header.frame_id = last_customer_pose_.header.frame_id;
      goal_pose.header.stamp = node_->now();
      goal_pose.pose.position.x = goal_x;
      goal_pose.pose.position.y = goal_y;
      goal_pose.pose.orientation.w = 1.0;
      goal_valid = true;

      RCLCPP_INFO(logger,
        "[Approach] Proxemic goal: customer(%.2f,%.2f) dist=%.2fm "
        "→ goal(%.2f,%.2f) social=%.2fm",
        cx, cy, dist, goal_x, goal_y, social_distance);
    } else if (getInput("goal_pose", goal_pose) && !goal_pose.header.frame_id.empty()) {
      goal_valid = true;
      RCLCPP_INFO(logger,
        "[Approach] goal_pose 입력 포트 사용: (%.2f, %.2f)",
        goal_pose.pose.position.x, goal_pose.pose.position.y);
    }

    if (!goal_valid) {
      // 안전 가드: 기본은 dummy goal Nav2 송신 차단.
      // BT.CPP InputPort<bool> 기본값 문자열 파싱 회피 위해 string 포트로 받고 수동 변환.
      std::string allow_dummy_str = "false";
      getInput("allow_dummy_goal", allow_dummy_str);
      const bool allow_dummy =
        (allow_dummy_str == "true" || allow_dummy_str == "1" ||
         allow_dummy_str == "TRUE" || allow_dummy_str == "True");

      RCLCPP_DEBUG(logger,
        "[Approach] allow_dummy_goal raw='%s' → %s",
        allow_dummy_str.c_str(), allow_dummy ? "true" : "false");

      if (!allow_dummy) {
        RCLCPP_WARN(logger,
          "[Approach] goal_valid=false (customer_pose/goal_pose 미연결). "
          "allow_dummy_goal='%s' (false) → Nav2 송신 스킵, fallback SUCCESS. "
          "(첫 BT 사이클 race로 첫 customer_pose 메시지 놓치면 발생 — "
          "다음 사이클에 정상 Proxemic 진입)",
          allow_dummy_str.c_str());
        no_nav2_fallback_ = true;
        return BT::NodeStatus::RUNNING;
      }

      goal_pose.header.frame_id = "map";
      goal_pose.header.stamp = node_->now();
      goal_pose.pose.position.x = 1.0;
      goal_pose.pose.position.y = 0.0;
      goal_pose.pose.orientation.w = 1.0;
      RCLCPP_INFO(logger,
        "[Approach] /customer_pose 미수신 + goal_pose 미연결 → 더미 (1.0, 0.0) "
        "(allow_dummy_goal='%s', Nav2 송신 진행)",
        allow_dummy_str.c_str());
    }

    // === 3. Nav2 액션 서버 발견 시도 ===
    if (!action_client_->wait_for_action_server(
        std::chrono::milliseconds(static_cast<int>(timeout_sec * 1000))))
    {
      RCLCPP_WARN(logger,
        "[Approach] Nav2 'navigate_to_pose' 서버 미발견 (%.1fs). "
        "BT 단독 fallback: 다음 tick에 SUCCESS (계산된 goal은 송신 안 함).",
        timeout_sec);
      no_nav2_fallback_ = true;
      return BT::NodeStatus::RUNNING;
    }

    // === 4. Nav2 모드: goal 송신 ===
    no_nav2_fallback_ = false;
    goal_rejected_ = false;
    result_received_ = false;
    result_code_ = ResultCode::UNKNOWN;

    NavigateToPose::Goal goal_msg;
    goal_msg.pose = goal_pose;

    auto opts = rclcpp_action::Client<NavigateToPose>::SendGoalOptions();
    opts.goal_response_callback =
      [this](const GoalHandleNav::SharedPtr & gh) {
        if (!gh) {
          RCLCPP_ERROR(node_->get_logger(), "[Approach] goal rejected");
          goal_rejected_ = true;
        } else {
          RCLCPP_INFO(node_->get_logger(), "[Approach] goal accepted");
        }
      };
    opts.result_callback =
      [this](const GoalHandleNav::WrappedResult & result) {
        result_received_ = true;
        result_code_ = result.code;
        RCLCPP_INFO(node_->get_logger(),
          "[Approach] result code: %d", static_cast<int>(result.code));
      };

    action_client_->async_send_goal(goal_msg, opts);

    RCLCPP_INFO(logger,
      "[Approach] Goal sent: (%.2f, %.2f) frame=%s",
      goal_pose.pose.position.x, goal_pose.pose.position.y,
      goal_pose.header.frame_id.c_str());

    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    // === Step D: 매 tick abort 체크 (안전 우선, Nav2 무관) ===
    if (has_customer_pose_) {
      double abort_threshold = 1.0;
      getInput("abort_threshold", abort_threshold);
      const double cx = last_customer_pose_.pose.position.x;
      const double cy = last_customer_pose_.pose.position.y;
      const double dist = std::hypot(cx, cy);
      if (dist < abort_threshold) {
        RCLCPP_WARN(node_->get_logger(),
          "[Approach] tick abort: 손님 진입 (%.2fm < %.2fm) → FAILURE",
          dist, abort_threshold);
        if (!no_nav2_fallback_) {
          action_client_->async_cancel_all_goals();
        }
        return BT::NodeStatus::FAILURE;
      }
    }

    if (no_nav2_fallback_) {
      return BT::NodeStatus::SUCCESS;
    }
    if (goal_rejected_) {
      return BT::NodeStatus::FAILURE;
    }
    if (result_received_) {
      return result_code_ == ResultCode::SUCCEEDED
        ? BT::NodeStatus::SUCCESS
        : BT::NodeStatus::FAILURE;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    if (no_nav2_fallback_) return;
    RCLCPP_INFO(node_->get_logger(),
      "[Approach] Halted — canceling Nav2 goal.");
    action_client_->async_cancel_all_goals();
  }

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<NavigateToPose>::SharedPtr action_client_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr customer_sub_;

  geometry_msgs::msg::PoseStamped last_customer_pose_;
  bool has_customer_pose_ = false;

  bool goal_rejected_ = false;
  bool result_received_ = false;
  bool no_nav2_fallback_ = false;
  ResultCode result_code_ = ResultCode::UNKNOWN;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__APPROACH_HPP_
