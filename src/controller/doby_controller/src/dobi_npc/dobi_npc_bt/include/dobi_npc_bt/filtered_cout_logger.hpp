// filtered_cout_logger.hpp
// Phase 2 W4 후속: BT 상태 전이 로그에서 IDLE 관련 noise 제거.
//
// 문제: BT::StdCoutLogger는 ReactiveFallback의 ConditionNode가 매 100ms tick마다
//   IDLE → FAILURE → IDLE 토글하는 것을 모두 출력 → 한 사이클에 60+ 라인 폭발.
//   abort/utter_done 같은 핵심 라인이 묻힘.
//
// 해결:
//   1) enableTransitionToIdle(false) — X → IDLE cleanup 전이는 자동 skip
//      (StatusChangeLogger 베이스 기능)
//   2) IDLE → FAILURE 추가 필터 — alarm ConditionNode "tick → 정상 FAILURE"
//      반복도 noise라 skip
//
// 결과: alarm 발동(IDLE → SUCCESS), stage 시작(IDLE → RUNNING),
//   stage 완료(RUNNING → SUCCESS), funnel 종료, root 전이만 출력.

#ifndef DOBI_NPC_BT__FILTERED_COUT_LOGGER_HPP_
#define DOBI_NPC_BT__FILTERED_COUT_LOGGER_HPP_

#include <chrono>
#include <iomanip>
#include <iostream>

#include "behaviortree_cpp/loggers/abstract_logger.h"

namespace dobi_npc_bt
{

class FilteredCoutLogger : public BT::StatusChangeLogger
{
public:
  explicit FilteredCoutLogger(BT::TreeNode * root_node)
  : BT::StatusChangeLogger(root_node)
  {
    // X → IDLE 전이는 callback 호출 자체를 skip (StatusChangeLogger 베이스).
    this->enableTransitionToIdle(false);
  }

  void callback(
    BT::Duration timestamp, const BT::TreeNode & node,
    BT::NodeStatus prev_status, BT::NodeStatus status) override
  {
    // ConditionNode의 "tick → 정상 FAILURE" 반복 noise:
    // ReactiveFallback이 매 tick마다 ConditionNode를 reset(IDLE)하고
    // 다시 evaluate(FAILURE/SUCCESS). FAILURE는 정상 동작이라 noise.
    // SUCCESS(alarm 발동)는 prev_status==IDLE이어도 출력해야 함.
    if (prev_status == BT::NodeStatus::IDLE &&
        status == BT::NodeStatus::FAILURE)
    {
      return;
    }

    const auto sec =
      std::chrono::duration_cast<std::chrono::milliseconds>(timestamp).count() / 1000.0;
    std::cout << "[bt " << std::fixed << std::setprecision(3) << sec << "] "
              << node.name() << ": "
              << BT::toStr(prev_status, true)
              << " -> "
              << BT::toStr(status, true)
              << std::endl;
  }

  void flush() override
  {
    std::cout << std::flush;
  }
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__FILTERED_COUT_LOGGER_HPP_
