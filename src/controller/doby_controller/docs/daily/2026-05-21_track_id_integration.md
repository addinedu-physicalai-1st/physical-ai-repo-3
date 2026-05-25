# 2026-05-21 - Track B: 대상자 ID (track_id + group_id) 통합

> branch: feat/engaging-analytics-migration
> spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md (64ff007)
> plan: docs/superpowers/plans/2026-05-21-track-id-integration.md (231c57f)

## 1. 작업 요약

PersonTrack BoT-SORT `track_id` + DBSCAN `group_id` 를 GEVA `/emotion/state` 까지
전파. rapport_tracker EMA 가 손님 전환 시 cold start. UI 헤더 "Customer #N ·
Group #M" 라벨. Track D MySQL audit 의 customer_track PK 와 자연 연계.

9 task TDD 진행 — subagent-driven-development:
- T1 EmotionState.msg 필드 (b5ca72d)
- T2 select_closest_track helper + 5 unit tests (274b201)
- T3 geva_node integration (8a261d2) + import time fix (7c31a8b)
- T4 should_reset_ema_on_track_change + 4 unit tests (9b3330c)
- T5 opserver rec (f2f5dd0)
- T6 modes.html + components.css (3b55396)
- T7 engaging-analytics.js (b0f1750)
- T8 회귀 카탈로그 (7e54cd0)
- T9 라이브 검증 + 본 회고

## 2. 변경 사항

- `EmotionState.msg`: int32 track_id + int32 group_id (-1=unknown)
- `geva_node.py`:
  - module-level `select_closest_track` helper (5 unit tests)
  - 신규 파라미터 2 (`tracks_topic`, `tracks_stale_timeout_sec`)
  - `_cb_tracks` 콜백 + closest cache (3 멤버)
  - `_tick` 의 EmotionState publish 시 채움 + 0.5s stale guard (no_face + 정상 분기)
- `rapport_tracker_node.py`:
  - module-level `should_reset_ema_on_track_change` helper (4 unit tests)
  - `_last_track_id` 멤버 + `_on_emotion` 안 track_id 변경 감지 -> cold start
- `opserver_node.py`: `_on_emotion_state` + `_on_rapport` 의 rec dict 에 track_id/group_id
  - **T9 버그 fix**: `rapport_snapshot()` 의 recent 직렬화에 track_id/group_id 누락 발견 -> 추가
- `modes.html`: ea-customer span + cache bust
- `components.css`: `.ea-customer-label` 스타일 (+ unknown 상태)
- `engaging-analytics.js`: renderCustomerLabel + rapport recent [#N] 태그
- 신규 unit tests 9 cases (5 closest + 4 track_id) + 회귀 smoke 1

## 3. 검증

### 3.1 단위 테스트
- 15 cases 모두 PASS (5 closest + 4 track_id + 6 기존 EMA 회귀 X)

### 3.2 라이브 검증 (DOMAIN=99 sim)

**환경**: DOMAIN=99, ROS_LOCALHOST_ONLY=1, 실 ROS2 Jazzy + 빌드된 install/

**Step 2 - 프로세스 spawn:**
- opserver 시작: `HTTP 200` 확인
- rapport_tracker 시작: `rapport_tracker: /emotion/state -> /rapport/event, hysteresis on=5 off=5, EMA alpha_base=0.5 gate=0.3` 확인

**Step 3 - customer 전환 시나리오 (실측 로그 발췌):**

```
[INFO] [rapport_tracker_node]: event: None -> engagement_up (V=0.30, A=0.10, conf=0.85,
    abort_streak=0, normal_streak=1, reason=positive_valence)
[INFO] [rapport_tracker_node]: customer 전환: track_id 42 -> 99 (EMA cold start)
[INFO] [rapport_tracker_node]: event: engagement_up -> neutral_continue (V=-0.20, A=0.10,
    conf=0.85, abort_streak=0, normal_streak=3, reason=within_neutral_band)
```

- Customer #42 5 frame publish -> `engagement_up` 이벤트 정상 발행
- track_id 42->99 전환 -> `customer 전환: track_id 42 -> 99 (EMA cold start)` 로그 확인
- track_id=-1 (unknown) publish 후 -> 추가 전환 로그 없음 (EMA 보존, 의도된 fallback)

**Step 4 - WS /ws/v1/engaging payload (실측 출력 발췌):**

```
--- msg 1 ---
  emotion.latest track_id=-1 group_id=-1
  rapport.recent count=8
    track_id=42 group_id=0 type=engagement_up v=0.30
    track_id=99 group_id=1 type=neutral_continue v=-0.20
    track_id=99 group_id=1 type=neutral_continue v=-0.20
    track_id=99 group_id=1 type=neutral_continue v=-0.20
    track_id=99 group_id=1 type=neutral_continue v=-0.20
```

- `emotion.latest.track_id=-1, group_id=-1`: 마지막 publish (track_id=-1) 정상 전파
- `rapport.recent[].track_id`: Customer #42 -> #99 전환 이력이 각 event 에 올바르게 태깅

**T9 발견 및 수정:**
- `opserver_node.py` `rapport_snapshot()` 의 recent 직렬화에서 track_id/group_id 필드 누락 발견
- `r.get('track_id')`, `r.get('group_id')` 추가로 fix
- `_on_rapport` 에서 rec dict 에는 올바르게 저장되었으나, snapshot 직렬화 시 누락된 것

**Step 5 - Cleanup:**
- pgrep kill 후 port 8800 free 확인

### 3.3 코드 리뷰 결과
- T1-T8 모두 Approved (spec compliance + code quality 양 단계)
- T3 review fix 1건 (중복 import time 정리, 7c31a8b)
- T9 라이브 검증 중 rapport_snapshot 직렬화 누락 1건 발견 및 수정

## 4. SS0-B / SS0-A 정합

EmotionState.msg + dobi_npc_emotion + moca_opserver + static. vic_pinky / RPi
자산 touch 0. 신규 ROS topic 0 (기존 토픽 의미만 확장).

## 5. 후속 (Phase, 본 track 범위 밖)

- tunable EMA reset threshold (BoT-SORT lost+재잡힘 race 완화)
- 멀티 손님 동시 분석 (Phase 5)
- BT customer_id <-> GEVA closest sync 검증
- group 모객 전략 (DBSCAN 일행 분석)
- Track D MySQL audit log + BTAuditEvent.msg
