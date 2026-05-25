# 전체 추적 결과 배열
# 발행: person_tracking_node
# 구독: group_approach_node

std_msgs/Header header

PersonTrack[] tracks
int32 group_count     # DBSCAN 감지 그룹 수 (solo 제외)
