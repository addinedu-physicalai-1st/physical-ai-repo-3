# 2026-05-29 — scout 일원화 follow 재설계 (Phase-1) 설계 스펙

작업자: 공국진(Stephen) · 베이스: `feat/scout-unified-follow` (off `origin/dev`)

---

## 1. 배경 / 문제

2026-05-29 실차 추종주행 테스트에서 scout-bridge → follow_controller 통합이 **두 가지로 실패**(사용자 e_stop, 안전 idle 정리):

1. **제자리 회전** — scout PTZ 가 추종 루프 안에 있어, 차체 회전 → 서보 절대방향 변화 → call_detector 재중앙정렬 → bridge cx 변화 → 차체 또 회전. + lock jitter 로 방향 진동. 닫힌 루프 미수렴.
2. **후진** — follow_controller 거리제어가 `/scan` 전방 최근접 장애물을 따라가, 사람과 무관하게 후진. scout bridge 는 거리정보 0(합성 bbox 고정 크기).

**근본 원인:** scout bridge 는 bearing(방향)만 제공 + PTZ 가 제어 루프에 결합 + 거리 소스 부재. (SoT 메모리: `project_scout_follow_bearing_behavior`)

---

## 2. 스코프

### 전체 비전 (참고, 본 스펙 밖)
person_tracking(track_id) → 얼굴 ReID(customer_id 영속) → customer_id별 감정 스코어 → 블랙리스트 제외 → max-score 추종. (= "라포 최고 손님 추종")

### 본 스펙 = Phase-1 (follow **실행/제어**)
- **목표 동작**: 최종 (C) 완전추종. Phase-1 = **손든 한 사람을 차체가 회전+전진으로 따라가기** (감정/다중선택/블랙리스트 없음).
- **대상 지정**: 손들기 획득 → track_id. customer_id(scout 얼굴 임베딩)는 다음 단계.
- **핵심 결정 (승인됨)**:
  - **(I) scout 일원화** — 획득·body추적 전부 scout_cam → 카메라 간 association 0.
  - **(B) scout_cam 얼굴 임베딩** — customer_id 도 scout 자급(다음 단계). 노트북 캠은 감정 전용.
  - **(2) 집중형 신규 컨트롤러** — follow_controller 개조 대신 scout 전용 P-제어기 신규.

### 비범위 (별 트랙)
ReID `customer_identity_node`(P0), customer_id 감정 스코어, `target_selector`, 블랙리스트(P2), 노트북 캠 감정분석, moca_opserver 대시보드 통합.

---

## 3. 아키텍처

```
[SEARCH]  call_detector: 서보 sweep, 손들기 탐지 (기존, 무수정)
   │  손들기 lock → /call/state=locked, servo pan=bearing, /call/event(bearing_rad)
   ▼
[HANDOFF] co-rotation: 차체를 bearing 만큼 회전 + 서보 bearing→0 동기 unwind
   │       (네트 카메라 지향=사람 유지, 사람이 전환 내내 화면 중앙) + /call/enable=false
   │       → 종료 시 차체=사람 정면, 서보=0 고정. scout = 고정 정면 카메라
   ▼
[FOLLOW]  person_tracking(@/scout_cam/image_raw) → track_id + bbox[x1,y1,x2,y2]
   │  scout_follow_controller(신규): 대상 track_id 고정(핸드오프 직후 중앙 최근접)
   │    · w = P(cx_err),  cx=(x1+x2)/2      (서보 고정 → 회전 안정)
   │    · v = P(bh_err),  bh=(y2-y1)/H, target_bh 유지, v≥0 (후진 금지)
   │    → /follow/cmd_vel
   ▼  twist_mux(follow@50) → smoother → collision_monitor → /cmd_vel → 바퀴
[LOST]    track 상실/dwell 초과 → 정지 (+ 선택: SEARCH 재진입)
```

---

## 4. 컴포넌트

- **call_detector** (기존, 무수정) — 손들기 lock 획득. `/call/state`, `/call/event`, `/scout_cam/servo_state`.
- **핸드오프** (신규 로직, 컨트롤러 FSM 흡수) — co-rotation: lock bearing β 읽고 `/call/enable=false`(서보 소유권 인수) → 차체 β 회전(odom yaw 피드백) + 서보 β→0 동기 unwind(네트 지향 사람 유지) → β 도달 시 서보 0 고정 → FOLLOW. *왜 co-rotation: 옆(β=45°) 사람을 서보 0 snap 하면 정면 FOV(±30°) 밖으로 나가 person_tracking 놓침.*
- **person_tracking** (@scout, 파라미터만) — `input_topic:=/scout_cam/image_raw`, `use_compressed`. 무수정. 출력 `/person_tracking/tracks`(PersonTrackArray). **PersonTrack.bbox = float32[4] [x1,y1,x2,y2] 픽셀.** deps: ultralytics/boxmot/yolov8n.pt(확인됨).
- **scout_follow_controller** (신규, mobility_controller) — 구독 `/person_tracking/tracks`,`/call/state`,`/call/event`,`/scout_cam/servo_state`,`/odom`. 발행 `/follow/cmd_vel`,`/scout_cam/cmd_pan_tilt`,`/call/enable`. FSM SEARCH→HANDOFF→FOLLOW→LOST. 제어법 순수함수(cx→w, bh→v 후진금지, co-rotation, 대상선택, FSM)로 분리해 단위테스트.

### 미래 접속점
`/follow/cmd_vel`(twist_mux follow@50) 그대로. 미래 `target_selector`가 customer_id 선택 → 컨트롤러가 customer_id↔track_id 매핑. Phase-1은 track_id 직결.

---

## 5. 안전
저속 cap(max_linear~0.15, max_angular~0.5). **후진 금지(v≥0)**, bh_stop 시 v=0. track/state 상실 시 정지. RPi collision_monitor + e_stop@255 + joy@100 그대로. /follow/cmd_vel 끊기면 mux 0.5s timeout 정지. §0-A(RPi 매세션 허가)·§0-B(vic_pinky 무수정).

## 6. 테스트
1. **벤치-A** (PC, 차체 없음, DOMAIN=99): person_tracking@scout + 컨트롤러 → `/follow/cmd_vel` w/v 부호·크기 sane + track 안정 + 핸드오프 확인. **후진(v<0) 없어야.**
2. **벤치-B**: 손들기→핸드오프(서보 0)→FOLLOW→LOST 정지.
3. **실차** (DOMAIN=22, §0-A 허가+입회, 저속): 회전 안정+전진. joy/e_stop 대기. — **별 세션.**

## 7. dev 베이스 정합 (2026-05-29 재정렬)
- 브랜치 `feat/scout-unified-follow` 를 `origin/dev`(e5b2737) 기준 재설정. feat/mapv6 미커밋 작업(팀원 follow-integration 등)은 stash 보존, Phase-1 엔 불필요.
- dev 에 이미: `person_tracking_pkg`(+PersonTrack/Array msg), `mobility_controller`(C++ 전용), `dobi_npc_msgs`. → Phase-1 self-contained.
- dev `mobility_controller` = ament_cmake C++ 만 → python scripts install 처음부터 추가.
- **(관찰)** dev 에 `run_tracking.sh` + **Astra 컬러캠** 추적 추가됨. Astra(환경캠)로 body추적하는 옵션 II 여지 생김 — 일단 승인된 scout 일원화(I) 유지, 추후 재고 가능.

## 8. 오픈 이슈 / 가정
`/call/enable=false` 서보 소유권 인수 효과 / odom yaw 정확도 / scout 640×480 YOLO 검출·track 안정성 / bh 정규화 H=480 / co-rotation 타이밍 / bearing_sign(차체 회전 부호) — 벤치-A 실측 검증.

## 9. 산출물 (예정)
- 신규: `mobility_controller/scripts/scout_follow_controller_node.py` + `test/test_scout_follow_control.py` + `launch/scout_unified_follow.launch.py`.
- 변경: `mobility_controller/CMakeLists.txt`(python install) + `package.xml`(python deps).
- person_tracking: launch arg `input_topic:=/scout_cam/image_raw` (코드 무수정).
