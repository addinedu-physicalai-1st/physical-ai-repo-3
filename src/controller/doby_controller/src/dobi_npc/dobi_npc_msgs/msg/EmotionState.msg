# 사용자 감정 상태 (Russell 1980 차원 모델 + Salichs 2014 신뢰도)
# 발행: GEFA, GEVA, decision_rule_node
# 구독: rapport_tracker_node, BT EmotionMonitor

std_msgs/Header header

# Russell 차원 모델
float32 valence       # -1.0 (unpleasant) ~ +1.0 (pleasant)
float32 arousal       # -1.0 (calm) ~ +1.0 (active)

# Salichs 신뢰도
float32 confidence    # 0.0 ~ 1.0

# 출처 식별
string source         # "face" | "voice" | "fused"

# 융합 시 발생한 신호
string[] flags        # 예: ["mask_smile", "voice_only", "agree", "conflict"]

# 2026-05-21 Track B — 손님 식별 (PersonTrack 의 closest)
int32 track_id        # BoT-SORT 추적 ID. -1 = unknown (person_tracking 미가동 / no track / stale)
int32 group_id        # DBSCAN 그룹 ID. -1 = solo / 미할당
