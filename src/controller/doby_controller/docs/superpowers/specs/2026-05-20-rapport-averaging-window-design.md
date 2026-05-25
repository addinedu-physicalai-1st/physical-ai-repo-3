# 2026-05-20 — rapport 평균 윈도우 (Confidence-weighted EMA) 도입

> branch: `feat/engaging-analytics-migration` (또는 후속 trake 위해 `feat/rapport-ema` 별 cut)
> base: `2406458` (person_tracking ↔ 모객 BT funnel 통합)
> 작성: 2026-05-20 (brainstorm 완료 후 spec 단계)
> 본 spec 의 SoT — implementation plan 은 본 문서 이후 writing-plans skill 호출 시 생성

---

## 1. 한 줄 정의

`rapport_tracker_node` 의 V·A frame-by-frame jitter 를 흡수하기 위한 **confidence-weighted
EMA smoothing layer** 도입. GEVA raw 출력 (`/emotion/state`) 은 변경 없이 유지하고,
rapport_tracker 가 EMA 처리한 V·A 로 4 분류 (`engagement_up/down/neutral_continue/abort_trigger`)
를 수행. 결과 `/rapport/event.emotion` 필드에 smoothed V·A 발행 → BT 의사결정 안정화.

## 2. 사용자 확정 결정 (brainstorm 산물)

| # | 결정 | 채택 |
|---|---|---|
| D1 | 도입 목적 | **BT 의사결정 안정화** (false positive 감소). UI 표시는 raw 그대로 유지 |
| D2 | 구현 layer | **rapport_tracker_node 내부 (옵션 A)**. GEVA / BT EmotionMonitor 변경 X |
| D3 | 알고리즘 | **Confidence-weighted EMA** (`weight = α_base × conf`, conf<gate frame skip) |
| D4 | abort streak (hysteresis) | **유지** (5 frame ≈ 0.5초). EMA 가 추가 직렬 필터로 자동 작동 |
| D5 | 대상자 ID + 시간 추이 그래프 + audit log | **별 trake 로 분리** — 본 spec 후속 §10 Track B/C/D 명시. Track D 의 영구 저장은 MySQL ([[project_team_db_mysql]]) |

## 3. 알고리즘 상세

매 `/emotion/state` 콜백 `_on_emotion(msg)` 진입 시:

```python
no_signal = (msg.confidence <= 0.0) or ("no_face" in msg.flags)

if no_signal:
    # EMA / streak 모두 보존 (사람 안 보일 때 자동 abort 해제 방지 — 기존 동작 정합)
    pass
elif msg.confidence < self._conf_min_gate:
    # 자신없는 frame — EMA update skip (gate)
    pass
else:
    weight = self._ema_alpha_base * msg.confidence
    if self._v_smooth is None:
        # cold start — 첫 valid frame 그대로 채택 (보수적 init)
        self._v_smooth = msg.valence
        self._a_smooth = msg.arousal
    else:
        self._v_smooth = weight * msg.valence + (1 - weight) * self._v_smooth
        self._a_smooth = weight * msg.arousal + (1 - weight) * self._a_smooth

# 기존 분류 / abort streak 로직의 입력만 smoothed V·A 로 교체
v = self._v_smooth if self._v_smooth is not None else msg.valence
a = self._a_smooth if self._a_smooth is not None else msg.arousal
# (이후 raw_abort 평가, streak 갱신, event_type 결정 — 기존 코드 그대로)
```

**왜 confidence weighting**:
- 분류기가 자신있는 frame (정면 얼굴, 명확한 표정 → conf≈0.9) → weight≈0.45 → **빠른 반응**
- 자신없는 frame (옆 얼굴, 마스크, 조명 변화 → conf≈0.4) → weight≈0.2 → **자동 보수적**
- CLAUDE.md TODO 의 `min_confidence 임계 (rapport_tracker GEVA 신뢰도 게이팅)` 항목 본 설계로 자연 해결

## 4. Architecture & data flow

```
GEVA 10Hz raw V·A + conf
  └─→ /emotion/state ───────────────────────┐
       (raw, 변경 없음 — 모든 subscriber 그대로) │
                                             │
       rapport_tracker_node (본 trake 변경)    │ subscribe
         ├─ EMA state (_v_smooth, _a_smooth)  <┘
         ├─ confidence-weighted update
         ├─ smoothed V·A → raw_abort 평가 + streak (기존)
         ├─ smoothed V·A → up/down/neutral 분류 (기존)
         └─→ /rapport/event
                ├─ event.emotion.valence/arousal = smoothed
                ├─ event.emotion.confidence/source/flags = raw 그대로
                └─→ BT EmotionMonitor (abort latch — 변경 없음)
                └─→ opserver._rapport_events (UI rapport recent — smoothed V·A 표시)

opserver._emotion_state  ←─ /emotion/state  (raw, circumplex cur-pt 는 그대로 표시)
```

**핵심 원칙**:
- `/emotion/state` (raw) 는 BT 와 무관한 모든 subscriber 가 그대로 받음 (face_avatar 같은 향후 노드 호환)
- `/rapport/event.emotion` 만 smoothed → BT 의사결정 layer + UI 의 "BT 가 본 값" 표시 일관

## 5. 새 파라미터

| 이름 | 기본 | 의미 | 라이브 튜닝 범위 |
|---|---|---|---|
| `ema_alpha_base` | **0.5** | EMA 기본 가중치. 실 weight = base × conf | 0.3 ~ 0.7 |
| `conf_min_gate` | **0.3** | 이하 frame 의 EMA update skip | 0.2 ~ 0.5 |

기존 파라미터 모두 유지:
- `input_topic` = `/emotion/state`
- `output_topic` = `/rapport/event`
- `abort_on_count` = 5 (0.5s @ 10Hz)
- `abort_off_count` = 5

## 6. RapportEvent.emotion 필드

| 필드 | 발행 값 |
|---|---|
| `valence` / `arousal` | **smoothed** — BT 의사결정과 일관, UI rapport recent 도 같은 값 표시 |
| `confidence` | **raw 그대로** — 운영자가 신뢰도 추세 디버깅 가능 |
| `source` / `flags` | **raw 그대로** — face / voice / fused / no_face 추적 |
| `header` | rapport_tracker 가 새 stamp 채움 (기존 동작) |

`/rapport/event.weight` 와 `event.event_type`, `event.reason` 은 기존 분류 룰 그대로 (smoothed V·A 기반).

## 7. Edge cases

| 상황 | 동작 |
|---|---|
| **cold start** (첫 valid frame) | EMA state 가 raw V·A 그대로 채택 — 첫 분류부터 자연 |
| **장기 no_signal** | EMA + streak 모두 보존 (기존 동작 유지) |
| **지속 conf<gate** | EMA stale — `no_face` flag 발행으로 곧 처리. TTL 도입은 후속 |
| **outlier conf=1.0 frame** | weight=0.5 → 한 frame 영향 50%. 다음 정상 frame 에서 빠르게 회복. abort streak 가 추가 보호 |
| **bt_executor restart** | rapport_tracker 재시작 시 EMA state 초기화 (cold start) — 의도된 동작 |
| **abort streak ON 중 EMA 가 정상 영역으로 빠짐** | normal_streak 5 frame 누적 → LEAVE abort. 기존 동작 정합 |

## 8. 응답 시간 (high conf 가정, α_base=0.5)

| 분류 | 응답 시간 | 비고 |
|---|---|---|
| engagement_up/down | **~0.4초** | EMA 90% 도달 (4 frame @ 10Hz) |
| neutral_continue | **~0.4초** | 같이 |
| abort_trigger | **~0.9초** | EMA 0.4s + streak 0.5s 직렬 |
| LEAVE abort | **~0.5초** | streak 만 (EMA 는 정상 방향 빠르게 따라옴) |
| no_signal | **즉시** | 기존 동작 |

## 9. Testing

### 9.1 단위 테스트 (신규)

`tests/unit/test_rapport_tracker_ema.py`:

- **cold start**: 첫 valid frame 입력 → smoothed = raw, event_type 즉시 분류
- **sustained high conf**: V=0.5 conf=1.0 5 frame 연속 → smoothed V → 0.5 도달 검증 (90% 기준)
- **conf gate skip**: conf=0.2 frame 입력 → smoothed 변경 없음 + RapportEvent.emotion 의 V·A 가 이전 smoothed
- **no_signal 보존**: conf=0 frame 입력 → smoothed/streak 모두 그대로
- **smoothed abort streak**: smoothed V=-0.7 A=+0.6 5 frame 연속 → event_type='abort_trigger'
- **outlier 흡수**: 정상 frame 4 + V=-1.0 A=+1.0 (conf=1.0) 1 frame → smoothed 가 abort-zone 미달
- **abort 회복**: abort 활성 상태 + 정상 frame 5 연속 → normal_streak >= 5 → LEAVE abort

### 9.2 회귀 카탈로그 추가

`tests/regression/perception/rapport_ema_smoke.md` (perception-tester 가 수행):
- ROS_DOMAIN_ID=99 sim 격리
- continuous_pub 패턴 + abort burst 시나리오 → EMA 가 abort 0.9s 안에 trigger 확인
- conf<0.3 burst → EMA 변경 없음 확인

### 9.3 라이브 검증

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging &
ros2 launch moca_opserver opserver.launch.py &
'
# 브라우저 http://localhost:8800/static/pages/modes.html
# - circumplex cur-pt: raw V·A jitter 그대로 (GEVA 직접)
# - rapport recent 의 V·A 값: smoothed (rapport_tracker 출력)
# - jitter 가 큰데 분류가 깜빡거리지 않음 검증
# - 의도적으로 angry 표정 0.5초 → abort_trigger 약 0.9s 안에 발화
```

## 10. 후속 trake (별 spec) — "누굴 / 왜 / 무슨 수치 근거" 운영 가시성

본 spec 은 평균 윈도우만. 사용자 요구 추가 항목 = **운영자가 BT 의사결정을 사후 검증할 수
있어야** ("누굴 호객했는지 / 왜 그 손님을 선택했는지 / 어떤 수치 근거로 abort 했는지").
세 가지 trake 자연 묶음:

| Track | 질문 | 핵심 산출물 |
|---|---|---|
| **B — 대상자 ID** | "누굴" | track_id 별 EMA + UI 라벨 |
| **C — 시계열 그래프** | "어떻게 변했는지" | 시간 축 V/A/conf/score 라인 그래프 |
| **D — 의사결정 audit log** | "왜 + 무슨 수치 근거" | 전이 시점 snapshot + reason chain |

본 spec implementation 완료 후 통합 brainstorm 또는 개별 진행 권장.

### Track B — 대상자 ID 통합

- **목표**: engaging-analytics 패널에 현재 BT 가 분석 중인 손님의 `track_id` (BoT-SORT) 표시.
- **현 상태**: `PersonTrack.msg` 에 `track_id` + `group_id` 존재 (`person_tracking_pkg`). GEVA 는 person_track 미사용.
- **작업 범위**:
  - GEVA 가 `/person_tracks` 구독 + 가장 가까운 track 의 bbox 안 얼굴만 분석
  - `EmotionState.msg` 에 `track_id` 필드 추가 (msg 변경)
  - rapport_tracker EMA state 를 `track_id` 별로 dict 분리 (다른 손님으로 전환 시 state 재시작)
  - opserver `_rapport_events` 에 track_id 표시 + UI 라벨
- **상호작용**: 본 spec 의 EMA 는 track_id 별 dict 로 자연 확장 가능. interface 호환 OK.

### Track C — 시간 추이 그래프

- **목표**: V/A/conf/engagement_score 의 시계열 그래프 (X축 시간, Y축 값). modes.html engaging-analytics 안에 SVG 또는 Chart.js 컴포넌트.
- **현 상태**: opserver `_emotion_history` deque(maxlen=60) — 6초만. circumplex trajectory 위 점 자국 형태로만 표시.
- **작업 범위**:
  - opserver history maxlen 확장 (예: 600 = 60초) + track_id 별 분리
  - WS payload 에 시계열 데이터 포함
  - 프론트 새 컴포넌트 `<engagement-timeline>` — SVG 라인 그래프
  - engagement_score (rapport weight 누적 합산) 도입 시 별 데이터 채널 — Track D 의 score chain 과 공유
- **상호작용**: 본 spec 의 smoothed V·A 가 추세 그래프의 primary 데이터로 자연. raw 도 보조 라인으로 표시 가능.

### Track D — 의사결정 audit log ("왜 + 무슨 수치 근거") + 영구 저장

- **목표**: BT 가 특정 손님에게 한 모든 의사결정 (호객 시작 / 단계 전이 / abort / 단계 abort 후 회복) 의 **trace 를 사후 재현 가능하게 기록 + 영구 저장**. 운영자가 "왜 이 손님을 abort 했지?" 같은 질문에 정확한 수치 근거로 답 가능. 분석/리플레이 가능.
- **영구 저장**: 모든 audit event + 손님 track 데이터 (`track_id`, `group_id`, 호객 시작/종료 시각, 최종 outcome) → **MySQL** (팀 공용 DB, 2026-05-20 사용자 명시 — [[project_team_db_mysql]]).
- **이벤트 종류**:
  - `target_selected`: 호객 대상 손님 선택 시점 — `track_id`, 선택 이유 (예: closest_within_3m / front_facing / longest_dwell), 그 시점 candidate track 들의 distance/orientation/dwell
  - `stage_enter`: BT funnel 단계 진입 (idle_scan → approach → ice_break → minigame → offer → lead_in) — 진입 시점 V/A/conf snapshot
  - `engagement_transition`: event_type 전이 (예: neutral → engagement_up) — 전이 시점 smoothed V/A + raw V/A + conf + abort_streak + reason
  - `abort_trigger`: abort 발동 — V/A trajectory 마지막 N frame, abort_streak 누적, 처음 raw_abort 발생 시점, EMA state
  - `mode_decision_reject`: SetMode 거부 사유 (battery / safety / busy) — 거부 시점 모든 가드 상태
- **로깅 layer (이중 — runtime + 영구)**:
  - **runtime — ROS topic** `/bt/audit_event` (신규 msg `BTAuditEvent.msg`) — JSON payload 또는 strongly-typed 필드
  - **runtime — opserver `_audit_events` deque** (예: maxlen=500) + WS broadcast `audit_event`
  - **runtime — modes.html / debug.html** "의사결정 추적" 섹션 — 최근 이벤트 list + 클릭 시 상세 (snapshot dict)
  - **영구 — 파일** `~/.ros/log/moca/audit_<date>.jsonl` — 1 line per event, 후처리/리플레이 + DB 적재 source
  - **영구 — MySQL** (팀 공용) — 스키마 (초안, 별 spec 에서 확정):
    - `customer_track` (track_id PK, group_id, session_start, session_end, outcome, persona, final_engagement_score)
    - `audit_event` (id PK, track_id FK, ts, event_type, stage, v_raw, a_raw, v_smooth, a_smooth, conf, abort_streak, reason, payload_json)
    - `mode_decision` (id PK, ts, requested_mode, source, accepted, reject_reason, gate_snapshot_json)
  - DB 적재 worker (별 노드 또는 opserver `_audit_db_writer` thread) — jsonl tail → MySQL INSERT batch (예: 1초 마다)
- **데이터 source 매핑**:
  - 호객 대상 선택 → `group_approach_node` (또는 신규 audit publisher)
  - 단계 전이 → BT 노드 (IceBreak, Approach, Offer 등) 의 onHalted/tick 안에서 audit publish
  - abort → EmotionMonitor 가 abort_active 전이 시점에 audit publish
  - mode reject → mode_manager 가 SetMode 거부 시점 audit publish
- **상호작용**:
  - Track B (대상자 ID) → audit event 의 핵심 키 = track_id
  - Track C (시계열 그래프) → audit event 의 timestamp 와 시계열 그래프 위에 마커 (annotation) 로 overlay 표시 — "이 시점에 abort 됐다" 시각화
  - 본 spec EMA → audit event payload 에 smoothed V/A + raw V/A 둘 다 기록 (사후 분석에 둘 다 필요)
- **참조 학술**: Iovino 2022 BT 서베이 의 "XAI / 학습 기반 BT" 미해결 과제 (CLAUDE.md §2 Layer 6). audit log 가 그 토대.

각 Track 은 본 spec implementation 완료 후 별 brainstorm → spec → plan 사이클로 진행 권장. Track D 는 가장 큰 작업이라 별도 phase (Phase 5 XAI 단계) 와 정합 가능.

## 11. §0-B / §0-A 정합

변경 대상 = `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py` (단일 Python 파일) + 신규 test 파일.

`src/shared/vic_pinky/`, `scripts/run_*.sh`, RPi `~/vicpinky_ws/`, GEVA C++ — **touch 0**.

ROS topic publish 신규 X (`/rapport/event` 기존 발행, 필드 의미만 변경).

## 12. 다음 세션 이어 시작 가이드

```bash
cd ~/physical-ai-repo-3
git checkout feat/engaging-analytics-migration   # 또는 별 cut
git log --oneline -3                              # 본 spec commit 확인
# writing-plans skill 호출 — 본 spec 기반 implementation plan 작성
```

## 13. 시간 기록

- 22:30~22:50 brainstorm (사용자 D1-D5 확정 + 추가 요구 scope 분리)
- 22:55 spec 작성 + commit
- 다음 단계: writing-plans skill → implementation plan → 코드 작업
