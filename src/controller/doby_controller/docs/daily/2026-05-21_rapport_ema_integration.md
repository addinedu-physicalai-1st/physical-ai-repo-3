# 2026-05-21 — rapport_tracker EMA 통합

> branch: feat/engaging-analytics-migration
> spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md (d5e7b19)
> plan: docs/superpowers/plans/2026-05-20-rapport-averaging-window.md (d06d351)

## 1. 작업 요약

rapport_tracker_node 에 confidence-weighted EMA layer 도입. EMAState dataclass
pure logic 분리 + 6 단위 테스트 + 회귀 카탈로그 항목 + 라이브 검증 (DOMAIN=99 sim 격리).

8 task TDD 진행 — subagent-driven-development:
- T1 EMAState dataclass + cold start (e7c5f3f + 70dd706 review fix)
- T2 sustained convergence test (345ccdf)
- T3 conf gate skip test (f67df90)
- T4 no_signal preserves (7d4b0ee)
- T5 outlier absorbed (90e3246)
- T6 RapportTrackerNode integration (99c209d + cc6e76c review fix)
- T7 regression catalog (383991b)
- T8 라이브 검증 + 본 회고

## 2. 변경 사항

- `EMAState` dataclass 신규 (rapport_tracker_node.py module level, lines 37-65)
- `__init__` 새 파라미터: `ema_alpha_base=0.5`, `conf_min_gate=0.3` (declare_parameter)
- `_on_emotion` 가 EMA update + smoothed V·A 로 분류
- RapportEvent.emotion.valence/arousal 만 smoothed (confidence/source/flags raw)
- 기존 abort streak 5 frame 그대로 (smoothed V·A 입력)
- weight clamp `min(α*conf, 1.0)` (GEFA 미래 source 발산 방어)
- invariant `assert` → `RuntimeError` (python3 -O 안전)
- 신규 unit test 6 cases (tests/test_rapport_tracker_ema.py)
- 신규 회귀 카탈로그 `rapport_ema_smoke` (perception 카테고리, 20s)

## 3. 검증

### 3.1 단위 테스트

6 cases 모두 PASS (cold_start, sustained, conf gate, no_signal preserve, no_signal cold start, outlier 흡수)

### 3.2 라이브 검증 (DOMAIN=99 sim)

**기동 확인:**
```
[INFO] rapport_tracker_node: rapport_tracker: /emotion/state -> /rapport/event,
  hysteresis on=5 off=5, EMA α_base=0.5 gate=0.3
```
opserver health: HTTP 200 ✓

**WS /ws/v1/engaging smoothed V·A 관측 (5 프레임 연속, sin wave input):**
```
msg1: emo_latest_v_a_conf=[-0.338, -0.102, 0.828]
msg2: emo_latest_v_a_conf=[-0.315, -0.103, 0.826]
msg3: emo_latest_v_a_conf=[-0.290, -0.053, 0.823]
msg4: emo_latest_v_a_conf=[-0.261, -0.095, 0.820]
msg5: emo_latest_v_a_conf=[-0.260, -0.113, 0.817]
```
→ V가 -0.338 → -0.260 로 점진 상승 (raw sin wave 직접 반영이 아닌 EMA 추적 확인).
rapport_counters: engagement_up=7, engagement_down=3, abort_trigger=0 (정상 구간).

**abort burst (V=-0.7, A=+0.6, 5Hz, 5초):**
```
[abort] rapport abort_trigger w=0.92 V=-0.70 A=+0.60
[abort] burst done (5s)
```
rapport_tracker 로그:
```
[INFO]  event: neutral_continue -> engagement_down (V=-0.43, A=0.33, abort_streak=0, reason=negative_valence)
[WARN]  abort streak 5 ≥ 5 → ENTER abort (V=-0.69, A=0.62)
[INFO]  event: engagement_down -> abort_trigger (V=-0.69, A=0.62, conf=0.85, abort_streak=5, reason=negative_high_arousal_sustained)
```
opserver event log (safety 카테고리):
```
[warn] 2026-05-20T15:36:15.815Z abort_trigger weight=-1.00
[warn] 2026-05-20T15:36:16.012Z abort_trigger weight=-1.00
[warn] 2026-05-20T15:36:16.215Z abort_trigger weight=-1.00
[warn] 2026-05-20T15:36:16.415Z abort_trigger weight=-1.00
[warn] 2026-05-20T15:36:16.615Z abort_trigger weight=-1.00
(total safety events: 9)
```

**abort 응답 시간 분석:**
- abort-zone 첫 진입 (engagement_down) → ENTER abort: **1.001초**
  (abort_streak 5 × 0.2s = 1.0s, EMA가 임계값에 도달한 후 streak 카운팅)
- abort_burst.py 첫 publish → ENTER abort: 약 3.87초
  (EMA가 abort-zone 임계값으로 수렴하는 시간 ~2.87s 포함)

### 3.3 코드 리뷰

- T1 + T6 둘 다 spec compliance ✅ + code quality ✅ Approved (Important 2 + Minor 추가 fix 후)

## 4. §0-B / §0-A 정합

rapport_tracker_node.py 단일 파일 + 신규 test + 회귀 항목 + 회고. vic_pinky + RPi
자산 touch 0. 신규 ROS topic 0 (/rapport/event 의미만 변경: valence/arousal smoothed).

## 5. 후속 (별 trake — 본 spec §10)

- Track B 대상자 ID: track_id/group_id 통합 (PersonTrack.msg 이미 존재)
- Track C 시계열 그래프: opserver history 확장 + `<engagement-timeline>`
- Track D audit log: BTAuditEvent.msg + MySQL persistence

## 6. 라이브 운영 튜닝 가이드

EMA α_base / conf_min_gate 라이브 환경 (카페 조명/거리) 에 맞게 튜닝:
- `ema_alpha_base`: 0.5 (기본) → 0.3 (더 부드럽지만 느림) 또는 0.7 (빠르지만 jitter)
- `conf_min_gate`: 0.3 (기본) → 0.5 (더 엄격) 또는 0.2 (관대)
- abort streak: 5 frame 유지 (변경 시 응답 시간 0.5s 비율 변경)
- EMA 수렴 시간 고려: abort-zone 진입 후 EMA 반응까지 약 2-3초 (α=0.5 기준)
  → 빠른 abort 반응이 필요할 경우 α_base=0.7 또는 streak=3 검토
