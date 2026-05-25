# 테이블 점유 추정 결과 — table_occupancy_detector_node 발행 (테이블 방문 시 이벤트)
# 구독: moca_opserver(table_registry), web dashboard
#
# occupancy 분류 (M2: empty/occupied 만, M3: finished 추가)
#   empty    : 의자에 사람 없음, 테이블 위 식기 없음
#   occupied : YOLO person 검출 >= 1
#   finished : 사람 없음 + 빈 컵/접시 감지 (M3 dishes_detected=true)
#   unknown  : confidence < 0.5 또는 인식 실패

std_msgs/Header header

string table_id               # "T01" ~ "T05"
string occupancy              # "empty" | "occupied" | "finished" | "unknown"
uint8 person_count            # YOLO person 검출 수
bool dishes_detected          # 빈 컵/접시 감지 여부 (M3)
float32 confidence            # 0.0 ~ 1.0
sensor_msgs/CompressedImage snapshot  # 디버깅용 스냅샷 1장 (M3에서 선택적, M2 비어있음)
