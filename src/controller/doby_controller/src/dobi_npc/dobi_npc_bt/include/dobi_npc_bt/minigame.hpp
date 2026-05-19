// minigame.hpp
// Phase 3 — 미니게임 BT 노드 (Castro-Gonzalez 2016 fully-integrated).
//
// 흐름 (3 phase StatefulActionNode):
//   phase 1: UTTER_INVITE
//     game_type 에 따라 stage_id 다르게 dialog/request publish:
//       rps           → "minigame_invite"                (가위바위보 — 친숙)
//       speed_counter → "minigame_invite_speed_counter"  (양손 합산 — 설명 필요)
//     /dialog/utter_done 대기 (페르소나가 게임 권유/설명 발화)
//   phase 2: GAME_RUNNING
//     /minigame/start (String, game_type) publish
//     /minigame/result (MinigameResult) 대기
//     (minigame_runner 가 face_avatar/geva suspend, 게임 subprocess 진행)
//   phase 3: UTTER_RESULT
//     customer 승리면 "minigame_win", 패배면 "minigame_lose" stage publish
//     /dialog/utter_done 대기
//
// 반환 정책:
//   completed=true (이기든 지든 끝까지 진행) → SUCCESS, rapport_delta 양수/음수
//   completed=false (ESC 중도 포기, abort, timeout) → FAILURE
//
// rapport_delta:
//   customer 승   → rapport_win_delta  (기본 +0.4)
//   customer 패   → rapport_lose_delta (기본 -0.2, 그래도 SUCCESS — funnel 진행)
//   abort/timeout → rapport_lose_delta, FAILURE

#ifndef DOBI_NPC_BT__MINIGAME_HPP_
#define DOBI_NPC_BT__MINIGAME_HPP_

#include <atomic>
#include <memory>
#include <random>
#include <string>
#include <utility>
#include <vector>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/empty.hpp"
#include "std_msgs/msg/string.hpp"

#include "dobi_npc_msgs/msg/minigame_result.hpp"

namespace dobi_npc_bt
{

class Minigame : public BT::StatefulActionNode
{
public:
  Minigame(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node)),
    phase_(Phase::UTTER_INVITE),
    utter_done_(false),
    result_received_(false)
  {
    dialog_pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/dialog/request", 10);
    // /minigame/start: game_type 을 String 으로 publish.
    // minigame_runner_node 가 game_id 별 game.py 를 dispatch.
    start_pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/minigame/start", 10);

    utter_done_sub_ = node_->create_subscription<std_msgs::msg::Empty>(
      "/dialog/utter_done", 10,
      [this](std_msgs::msg::Empty::SharedPtr) {
        utter_done_.store(true);
      });

    result_sub_ = node_->create_subscription<dobi_npc_msgs::msg::MinigameResult>(
      "/minigame/result", 10,
      [this](dobi_npc_msgs::msg::MinigameResult::SharedPtr msg) {
        last_result_ = *msg;
        result_received_.store(true);
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>(
        "game_type", "rotate",
        "미니게임 종류. 'rps' | 'speed_counter' 직접 선택, "
        "또는 'rotate' (cycle 마다 순환), 'random' (매번 무작위)"),
      BT::InputPort<double>(
        "utter_timeout_sec", 8.0,
        "각 발화 단계의 utter_done 대기 timeout (초). 초과 시 다음 phase 강제 진행."),
      BT::InputPort<double>(
        "game_timeout_sec", 60.0,
        "게임 진행 timeout (초). 초과 시 FAILURE."),
      BT::InputPort<double>(
        "rapport_win_delta", 0.4, "customer 승 시 rapport 증분"),
      BT::InputPort<double>(
        "rapport_lose_delta", -0.2, "customer 패/포기 시 rapport 증분"),
      BT::OutputPort<double>(
        "rapport_delta", "rapport_score 증분 (blackboard 기록용)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    phase_ = Phase::UTTER_INVITE;
    utter_done_.store(false);
    result_received_.store(false);
    phase_started_ = node_->now();
    // onStart 시점에 game_type 1번 결정 (rotate/random 도 여기서 resolve).
    // 이후 phase 들은 모두 selected_game_type_ 참조 → 일관성 보장.
    selected_game_type_ = resolve_game_type();
    const std::string invite_stage = invite_stage_for_selected();
    publish_dialog_request(invite_stage);
    RCLCPP_INFO(node_->get_logger(),
      "[Minigame] phase 1/3 UTTER_INVITE — game_type=%s, stage=%s 요청",
      selected_game_type_.c_str(), invite_stage.c_str());
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    double utter_timeout = 8.0;
    double game_timeout = 60.0;
    getInput<double>("utter_timeout_sec", utter_timeout);
    getInput<double>("game_timeout_sec", game_timeout);

    const double elapsed = (node_->now() - phase_started_).seconds();

    switch (phase_) {
      case Phase::UTTER_INVITE: {
        const bool done = utter_done_.load();
        const bool timed_out = elapsed > utter_timeout;
        if (done || timed_out) {
          if (timed_out && !done) {
            RCLCPP_WARN(node_->get_logger(),
              "[Minigame] minigame_invite utter timeout %.1fs → 게임 강제 시작",
              elapsed);
          } else {
            RCLCPP_INFO(node_->get_logger(),
              "[Minigame] minigame_invite utter_done → 게임 시작");
          }
          std_msgs::msg::String start_msg;
          start_msg.data = selected_game_type_;
          start_pub_->publish(start_msg);
          phase_ = Phase::GAME_RUNNING;
          phase_started_ = node_->now();
          utter_done_.store(false);
          result_received_.store(false);
          RCLCPP_INFO(node_->get_logger(),
            "[Minigame] phase 2/3 GAME_RUNNING — /minigame/result 대기");
        }
        return BT::NodeStatus::RUNNING;
      }

      case Phase::GAME_RUNNING: {
        if (result_received_.load()) {
          // 게임 결과 분석
          const bool customer_won =
            last_result_.customer_wins > last_result_.robot_wins;
          const bool completed = last_result_.completed;

          if (!completed) {
            // 중도 포기/abort — utter_result 단계 스킵, 즉 FAILURE
            double lose_delta = -0.2;
            getInput<double>("rapport_lose_delta", lose_delta);
            setOutput("rapport_delta", lose_delta);
            RCLCPP_WARN(node_->get_logger(),
              "[Minigame] 게임 미완료 (abort/포기) → FAILURE");
            return BT::NodeStatus::FAILURE;
          }

          // 결과 발화 단계로 진입
          const std::string stage =
            customer_won ? "minigame_win" : "minigame_lose";
          publish_dialog_request(stage);
          phase_ = Phase::UTTER_RESULT;
          phase_started_ = node_->now();
          utter_done_.store(false);
          RCLCPP_INFO(node_->get_logger(),
            "[Minigame] 결과: customer=%u robot=%u ties=%u win_rate=%.2f → %s",
            last_result_.customer_wins, last_result_.robot_wins,
            last_result_.ties, last_result_.customer_win_rate,
            stage.c_str());
          RCLCPP_INFO(node_->get_logger(),
            "[Minigame] phase 3/3 UTTER_RESULT — %s 발화 요청",
            stage.c_str());
          return BT::NodeStatus::RUNNING;
        }
        if (elapsed > game_timeout) {
          double lose_delta = -0.2;
          getInput<double>("rapport_lose_delta", lose_delta);
          setOutput("rapport_delta", lose_delta);
          RCLCPP_ERROR(node_->get_logger(),
            "[Minigame] game timeout %.1fs → FAILURE", elapsed);
          return BT::NodeStatus::FAILURE;
        }
        return BT::NodeStatus::RUNNING;
      }

      case Phase::UTTER_RESULT: {
        const bool done = utter_done_.load();
        const bool timed_out = elapsed > utter_timeout;
        if (done || timed_out) {
          if (timed_out && !done) {
            RCLCPP_WARN(node_->get_logger(),
              "[Minigame] result utter timeout %.1fs → SUCCESS forced",
              elapsed);
          }
          const bool customer_won =
            last_result_.customer_wins > last_result_.robot_wins;
          double win_delta = 0.4;
          double lose_delta = -0.2;
          getInput<double>("rapport_win_delta", win_delta);
          getInput<double>("rapport_lose_delta", lose_delta);
          const double delta = customer_won ? win_delta : lose_delta;
          setOutput("rapport_delta", delta);
          RCLCPP_INFO(node_->get_logger(),
            "[Minigame] 완료 → SUCCESS (rapport_delta=%+.2f)", delta);
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
      "[Minigame] halted (abort/외부 halt) phase=%d",
      static_cast<int>(phase_));
  }

private:
  enum class Phase { UTTER_INVITE, GAME_RUNNING, UTTER_RESULT };

  void publish_dialog_request(const std::string & stage_id)
  {
    std_msgs::msg::String msg;
    msg.data = stage_id;
    dialog_pub_->publish(msg);
  }

  // 게임 풀 — minigame_runner DEFAULT_GAME_REGISTRY 와 일치해야 함.
  // 새 게임 추가 시 minigame_runner_node.py + 본 풀 양쪽 등록.
  static const std::vector<std::string> & game_pool()
  {
    static const std::vector<std::string> pool = {
      "rps", "speed_counter", "cafe_ninja"
    };
    return pool;
  }

  std::string resolve_game_type()
  {
    std::string requested = "rotate";
    getInput<std::string>("game_type", requested);

    if (requested == "rotate") {
      // process-단위 atomic counter — 각 BT cycle 마다 1 증가.
      // funnel 한 cycle 당 Minigame onStart 1번 → 순서대로 rps → speed → rps ...
      static std::atomic<size_t> counter{0};
      const auto & pool = game_pool();
      const size_t idx = counter.fetch_add(1) % pool.size();
      return pool[idx];
    }
    if (requested == "random") {
      static std::random_device rd;
      static std::mt19937 gen(rd());
      const auto & pool = game_pool();
      std::uniform_int_distribution<size_t> dist(0, pool.size() - 1);
      return pool[dist(gen)];
    }
    // 명시 game_id 그대로 (rps / speed_counter / 미래 추가 게임)
    return requested;
  }

  std::string invite_stage_for_selected() const
  {
    // RPS 는 친숙하므로 generic "minigame_invite" 사용.
    // speed_counter / cafe_ninja 는 룰 설명 필요 → 별도 stage_id.
    if (selected_game_type_ == "speed_counter") {
      return "minigame_invite_speed_counter";
    }
    if (selected_game_type_ == "cafe_ninja") {
      return "minigame_invite_cafe_ninja";
    }
    return "minigame_invite";
  }

  rclcpp::Node::SharedPtr node_;
  Phase phase_;
  std::atomic<bool> utter_done_;
  std::atomic<bool> result_received_;
  dobi_npc_msgs::msg::MinigameResult last_result_;
  rclcpp::Time phase_started_;
  std::string selected_game_type_;  // onStart 에서 resolve, phase 전체에 일관

  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr dialog_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr start_pub_;
  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr utter_done_sub_;
  rclcpp::Subscription<dobi_npc_msgs::msg::MinigameResult>::SharedPtr
    result_sub_;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__MINIGAME_HPP_
