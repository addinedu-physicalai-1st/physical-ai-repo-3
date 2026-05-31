# 현재 운영 모드 상태 — mode_manager_node 발행 (1Hz)
# 구독: task_orchestrator, debug_monitor, dialog_router(향후), per-mode stack(향후)
#
# 6-state FSM:
#   idle      : home_pose 정차, 다음 명령 대기
#   serving   : 픽업 테이블 → 목표 테이블 배달 후 home 복귀
#   patrol    : 5분 주기 전 테이블 순회 + 점유 감지
#   guiding   : 카운터에서 결제 완료 고객을 빈 테이블로 인솔
#   follow    : 1인 reactive 추종
#   engaging  : 한산 시 모객 (cafe_funnel_v1.xml 6단계 BT)
#
# Legacy alias (M3 종료 2026-07-04 까지만 지원):
#   npc    -> engaging

std_msgs/Header header

string current_mode      # "idle" | "serving" | "patrol" | "guiding" | "follow" | "engaging"
builtin_interfaces/Time entered_at  # 현 모드 진입 시각
string params            # 진입 시 전달된 JSON params (snapshot)

# 가드 상태 — 운영자 UI 디버깅용 + 모드 전환 거부 사유 추적
bool battery_ok          # /battery_state 임계 통과 여부
bool safety_ok           # safety alarm 미발동 여부
string last_reject_reason  # 직전 거부 사유 (없으면 "")
