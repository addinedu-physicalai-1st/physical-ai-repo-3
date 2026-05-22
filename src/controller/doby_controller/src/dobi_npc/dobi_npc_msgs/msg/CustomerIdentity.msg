# 단일 손님 식별 결과 — customer_identity_node 발행
# blocklisted / outcome 는 P0 에선 고정값(false / "untouched"), P1 에서 채움

int32   track_id          # 현재 프레임의 person_tracking track_id (-1 = track 없음)
string  customer_id       # 얼굴 ReID 영속 식별자 (12-hex). "" = 미부여
float32 reid_confidence   # 0.0~1.0 얼굴 매칭 유사도 (track 캐시 적중 시 1.0)
bool    blocklisted       # 재접근 금지 여부 (P1)
string  outcome           # untouched|in_progress|positive|lukewarm|rejected|rejected_angry|guided (P1)
