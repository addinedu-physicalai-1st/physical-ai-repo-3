// bt_executor_node.cpp
// Phase 1 W2 (Step A): launch 인자 ↔ cpp 연동 + tick 루프 (ROS2 Timer 10Hz).
//
// === 변경 (W1 → W2 Step A) ===
//   + declare_parameter("bt_xml_path", "")  — 빈 값이면 패키지 share 기본값
//   + declare_parameter("tick_period_ms", 100)  — BT tick 주기
//   - tickOnce() 1회 → ROS2 WallTimer 기반 주기적 tick
//   + 상태 변화 시에만 INFO 로깅 (스팸 방지)
//
// === Phase 진화 ===
//   W2 Step B+: Approach를 Nav2 Action Client로 변환
//   Phase 2: EmotionMonitor Parallel 통합

#include <chrono>
#include <filesystem>

#include "rclcpp/rclcpp.hpp"
#include "behaviortree_cpp/bt_factory.h"
#include "ament_index_cpp/get_package_share_directory.hpp"

// Phase 2 W4 후속: BT 로그 noise 정리 (IDLE 관련 전이 필터)
#include "dobi_npc_bt/filtered_cout_logger.hpp"

// Phase 0-B sentinel
#include "dobi_npc_bt/dummy_action.hpp"

// Phase 1 W1: 5-stage funnel
#include "dobi_npc_bt/safety_check.hpp"
#include "dobi_npc_bt/idle_scan.hpp"
#include "dobi_npc_bt/approach.hpp"
#include "dobi_npc_bt/ice_break.hpp"
#include "dobi_npc_bt/minigame.hpp"
#include "dobi_npc_bt/offer.hpp"
#include "dobi_npc_bt/lead_in.hpp"

// Phase 2 W4: emotion-aware alarm
#include "dobi_npc_bt/emotion_monitor.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("bt_executor");
  auto logger = node->get_logger();

  RCLCPP_INFO(logger, "Dobi NPC BT Executor (Phase 1 W2 / Step A)");

  // === 0. 파라미터 선언 ===
  node->declare_parameter<std::string>("bt_xml_path", "");
  node->declare_parameter<int>("tick_period_ms", 100);

  const std::string xml_param = node->get_parameter("bt_xml_path").as_string();
  const int tick_period_ms = node->get_parameter("tick_period_ms").as_int();

  // === 1. Factory 구성 ===
  BT::BehaviorTreeFactory factory;
  const size_t builtin_count = factory.builders().size();

  factory.registerNodeType<dobi_npc_bt::DummyAction>("DummyAction");
  factory.registerNodeType<dobi_npc_bt::SafetyCheck>("SafetyCheck", node);
  factory.registerNodeType<dobi_npc_bt::IdleScan>("IdleScan");
  // ROS 노드 핸들이 필요한 노드는 가변 인자 템플릿 등록 (BT 4.x)
  factory.registerNodeType<dobi_npc_bt::Approach>("Approach", node);
  factory.registerNodeType<dobi_npc_bt::IceBreak>("IceBreak", node);
  factory.registerNodeType<dobi_npc_bt::Minigame>("Minigame", node);
  factory.registerNodeType<dobi_npc_bt::Offer>("Offer", node);
  factory.registerNodeType<dobi_npc_bt::LeadIn>("LeadIn", node);
  factory.registerNodeType<dobi_npc_bt::EmotionMonitor>("EmotionMonitor", node);

  const size_t user_count = factory.builders().size() - builtin_count;
  RCLCPP_INFO(logger, "Registered: %zu user + %zu builtin nodes",
              user_count, builtin_count);

  // === 2. XML 경로 해석 ===
  std::string xml_path;
  if (xml_param.empty()) {
    const std::string share_dir =
      ament_index_cpp::get_package_share_directory("dobi_npc_bt");
    xml_path = share_dir + "/bt_xml/cafe_funnel_v1.xml";
    RCLCPP_INFO(logger, "Using default BT XML: %s", xml_path.c_str());
  } else {
    xml_path = xml_param;
    RCLCPP_INFO(logger, "Using bt_xml_path param: %s", xml_path.c_str());
  }

  if (!std::filesystem::exists(xml_path)) {
    RCLCPP_ERROR(logger, "BT XML not found: %s", xml_path.c_str());
    rclcpp::shutdown();
    return 1;
  }

  // === 3. 트리 생성 ===
  BT::Tree tree;
  try {
    tree = factory.createTreeFromFile(xml_path);
  } catch (const std::exception & e) {
    RCLCPP_ERROR(logger, "Failed to create tree: %s", e.what());
    rclcpp::shutdown();
    return 2;
  }

  // === 4. 콘솔 로거 부착 — IDLE 관련 noise 필터링 (Phase 2 W4 후속) ===
  dobi_npc_bt::FilteredCoutLogger cout_logger(tree.rootNode());

  // === 5. Tick 루프 (ROS2 WallTimer 기반) ===
  RCLCPP_INFO(logger, "Starting BT tick loop @ %d ms (%.1f Hz)",
              tick_period_ms, 1000.0 / tick_period_ms);

  // 콜백에서 캡처할 상태 변수 (lambda 외부 lifetime 보장)
  auto last_status = std::make_shared<BT::NodeStatus>(BT::NodeStatus::IDLE);
  auto tick_count = std::make_shared<size_t>(0);

  auto timer = node->create_wall_timer(
    std::chrono::milliseconds(tick_period_ms),
    [&tree, last_status, tick_count, logger]() {
      const BT::NodeStatus status = tree.tickOnce();
      ++(*tick_count);

      if (status != *last_status) {
        RCLCPP_INFO(logger, "[tick %zu] BT status: %s -> %s",
                    *tick_count,
                    BT::toStr(*last_status).c_str(),
                    BT::toStr(status).c_str());
        *last_status = status;
      }
    });

  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
