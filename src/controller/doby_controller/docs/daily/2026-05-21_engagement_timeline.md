# 2026-05-21 — Track C: engagement-timeline 시계열 그래프

> branch: feat/engaging-analytics-migration
> spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md (4b0bac9)
> plan: docs/superpowers/plans/2026-05-21-engagement-timeline.md (df383ac)

## 1. 작업 요약

modes.html engaging-analytics 안에 `<engagement-timeline>` web component 도입.
V / A / engagement_score 3 라인 + rapport event 마커 시계열 (최근 1분).
opserver 가 RapportEvent.weight 의 EMA (α=0.1) 로 engagement_score 단일 source.

7 task TDD — subagent-driven-development:
- T1 opserver helpers + 8 unit tests (86c90ec)
- T2 opserver __init__ + _on_rapport EMA + history (e1467c2)
- T3 engagement_snapshot + WS payload (6e7e247)
- T4 engagement-timeline web component (39bc8cc)
- T5 engaging-analytics.js + modes.html + components.css (1a92be9)
- T6 회귀 카탈로그 (f1764e3)
- T7 라이브 검증 + 본 회고

## 2. 변경 사항

- `opserver_node.py`:
  - module-level 3 helpers (compute_engagement_ema / should_reset_engagement_score / is_marker_eligible)
  - __init__ : _emotion_history maxlen 60→600, 신규 4 멤버 + engagement_score_alpha param
  - _on_rapport: should_reset → compute_ema → score_history append + is_marker_eligible filter → marker_history append
  - engagement_snapshot() 메서드
- `rest_api.py`: ws_engaging payload 의 'engagement' 필드 추가
- 신규 `static/components/engagement-timeline.js` (native SVG, viewBox 0 0 600 220)
- `engaging-analytics.js`: WS onmessage 에 tl.render(j) 호출
- `modes.html`: engagement-timeline custom element + script + cache bust v=20260521b
- `components.css`: .engagement-timeline + .et-* 9 클래스 (PinkLAB 토큰)
- 신규 unit tests 8 cases + 회귀 smoke 1

## 3. 검증

### 3.1 단위 테스트
- 8 cases PASS (3 EMA + 4 reset + 1 marker filter)

### 3.2 라이브 검증 (DOMAIN=99 sim)

**Step 1 — 사전 cleanup**
```
8800 free
```

**Step 2 — opserver spawn**
```
opserver health: HTTP 200
```

**Step 3 — RapportEvent 시퀀스 + 검증**

opserver cold start 로그:
```
[INFO] [1779314132.306780967] [moca_opserver]: engagement_score cold start: track_id 42 → 99
```

WS `/ws/v1/engaging` payload:
```
--- msg 1 ---
  score: -0.2048
  score_history len: 16
  rapport_markers count: 16
  marker type distribution: {'engagement_up': 10, 'abort_trigger': 1, 'engagement_down': 5}
--- msg 2 ---
  score: -0.2048
  score_history len: 16
  rapport_markers count: 16
  marker type distribution: {'engagement_up': 10, 'abort_trigger': 1, 'engagement_down': 5}
```

**Step 4 — cleanup**
```
8800 free
```

검증 항목 | 기대값 | 실측값 | 결과
--- | --- | --- | ---
opserver health | HTTP 200 | HTTP 200 | PASS
cold start 로그 | track_id 42→99 1건 | 1건 확인 | PASS
WS engagement.score | 5x down 후 약 -0.20 | -0.2048 | PASS
score_history len | ≈ 16 | 16 | PASS
rapport_markers count | 16 | 16 | PASS
marker type 분포 | up:10 abort:1 down:5 | up:10 abort:1 down:5 | PASS
port cleanup | 8800 free | 8800 free | PASS

### 3.3 코드 리뷰
- T1-T6 모두 Approved

## 4. §0-B / §0-A 정합

opserver_node.py + rest_api.py + static. vic_pinky / RPi / dobi_npc_msgs /
rapport_tracker 모두 touch 0. 신규 ROS topic 0.

## 5. 후속 (Phase, 본 track 범위 밖)

- tunable α — 라이브 환경 맞춤
- dynamic Y range — 자동 zoom (±0.3 범위면 Y 축 축소)
- 다중 손님 비교 — track_id 별 multi-line
- BT rapport_delta input — EmotionMonitor 의 신규 출력 포트
- 차트 zoom/pan, marker hover tooltip
