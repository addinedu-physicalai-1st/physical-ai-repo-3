# 순회 모드 진행 상태 — patrol_scheduler_node 발행 (1Hz)
# 구독: moca_opserver (CompletionWatcher, KPI 집계), web dashboard, mode_manager(참고)

std_msgs/Header header

string current_state          # "scanning" | "moving" | "report" | "returning" | "done"
string current_table          # 현재 방문 중/직전 테이블 ID (예: "T03"), 없으면 ""
uint32 tables_visited         # 이번 사이클 누적 방문 수
uint32 tables_total           # 5 (T01~T05)
float32 progress              # 0.0 ~ 1.0
builtin_interfaces/Time started_at
