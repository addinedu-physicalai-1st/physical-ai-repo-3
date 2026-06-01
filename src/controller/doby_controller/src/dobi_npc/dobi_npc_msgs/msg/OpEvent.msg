# 외부/운영 이벤트를 ROS 도메인에 echo (디버깅/로깅용)
# 발행: task_orchestrator
# 토픽: /doby/event
# 구독: debug_monitor, 로깅 노드, rosbag2 기록
#
# source 종류:
#   pos       : POS 단말 (POST /order, /guide)
#   openarm   : 제조로봇 (POST /pickup)
#   operator  : 운영자 웹 UI (POST /mode, /command, /emergency_stop)
#   timer     : task_orchestrator 내부 타이머 (5분 patrol 자동 트리거 등)
#   guard     : 안전 가드 발동 echo (배터리/안전 알람)
#
# outcome:
#   accepted          : SetMode 호출 성공
#   rejected:<reason> : 거부 (가드/priority/duplicate 등)

std_msgs/Header header

string event_id               # UUID 또는 외부에서 받은 event_id
string source                 # "pos" | "openarm" | "operator" | "timer" | "guard"
string event_type             # "order_placed" | "pickup_ready" | "guide_request" | "manual_mode" | "patrol_timer" | "emergency_stop" | ...
string payload                # JSON 원본 (REST body 또는 내부 trigger 표현)
string outcome                # "accepted" | "rejected:<reason>"
