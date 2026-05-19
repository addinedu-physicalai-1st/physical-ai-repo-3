# 동행 안내 모드 진행 상태 — guiding_controller_node 발행 (1Hz)
# 구독: moca_opserver (CompletionWatcher, KPI), web dashboard
#
# current_state 의미 (docs/moca_guiding_design.md §2.3 7-state FSM):
#   init    : 진입 직후 (params 파싱 + table 검증)
#   lock_on : 카운터 앞에서 customer person bbox lock-on 시도 (10s timeout)
#   moving  : Nav2 NavigateToPose 진행 + 카메라로 customer 추적
#   waiting : customer lag > 1.5m → Nav2 cancel + 발화 + 대기 (lag < 1.0m 시 재개)
#   arrived : 목표 테이블 도착 — "여기서 즐기세요" 발화 + 5s dwell
#   done    : OpServer SetMode('idle') 대기 (다른 모드와 일관)
#   aborted : customer_lost > 8s 또는 rapport abort_trigger 또는 invalid target_table

std_msgs/Header header

string current_state          # "init" | "lock_on" | "moving" | "waiting" | "arrived" | "done" | "aborted"
string target_table           # 목표 테이블 ID (예: "T02")
string customer_id            # POS가 부여한 고객 식별자

# 고객 추적 정보
bool customer_in_sight        # 현 프레임에서 person bbox 보이는지
float32 distance_to_customer  # 로봇 → 고객 거리 (m, 시야 내일 때만, -1.0 = unknown)
float32 customer_lag_m        # 로봇 진행방향 기준 뒤처짐 (m, 음수=앞섬, 양수=뒤처짐)
builtin_interfaces/Time customer_last_seen  # 마지막 bbox 감지 시각

# Nav2 진행 정보
float32 distance_to_target    # 로봇 → target_table (m, -1.0 = nav 미시작)
float32 progress              # 0.0 ~ 1.0 (목적지까지 진행률 추정, M3에서 정밀화)

# Timing / debug
builtin_interfaces/Time started_at
string last_utter_text        # 마지막 발화 (디버깅용)
