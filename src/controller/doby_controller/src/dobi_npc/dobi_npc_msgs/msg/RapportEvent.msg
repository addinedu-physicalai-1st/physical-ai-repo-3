# 라포 변화 이벤트 — BT의 EmotionMonitor가 받음
# 발행: rapport_tracker_node
# 구독: BT의 emotion_aware_blackboard

std_msgs/Header header

string event_type     # "engagement_up" | "engagement_down" | "abort_trigger" | "neutral_continue"
float32 weight        # -1.0 (강한 부정) ~ +1.0 (강한 긍정)
EmotionState emotion  # 이 이벤트를 일으킨 감정 상태
string reason         # "anger_detected" | "smile_genuine" | "long_silence" | ...
