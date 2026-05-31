# 운영자 수동 제어 명령 — 모드 외 미세 제어 (발화, 표정, 비상정지 등)
# 발행: 별도 operator/teleop 도구 또는 CLI
# 구독: mode_manager_node (stop_emergency/resume), 각 모드 dispatcher (utter/express/skip_table)
#
# command_type 종류:
#   utter           : 즉시 발화 (payload: {"text":"...","voice":"...","face_expression":"..."})
#   express         : 표정만 변경 (payload: {"expression":"happy|sad|..."})
#   stop_emergency  : 비상정지 (payload: "") — mode_manager 강제 idle + 5초 dwell
#   resume          : emergency_stop 해제 (payload: "")
#   skip_table      : patrol 중 특정 테이블 건너뛰기 (payload: {"table_id":"T03"})

std_msgs/Header header

string command_type           # "utter" | "express" | "stop_emergency" | "resume" | "skip_table"
string payload                # JSON 또는 빈 문자열
