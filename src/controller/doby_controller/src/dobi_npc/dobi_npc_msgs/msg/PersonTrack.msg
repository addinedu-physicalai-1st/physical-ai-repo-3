# 단일 사람 추적 결과
# 발행: person_tracking_node
# 구독: group_approach_node

std_msgs/Header header

int32 track_id        # BoT-SORT 추적 ID
int32 group_id        # DBSCAN 그룹 (-1 = solo)
float32[4] bbox       # [x1, y1, x2, y2] pixel 좌표
float32 confidence    # YOLO 검출 신뢰도
