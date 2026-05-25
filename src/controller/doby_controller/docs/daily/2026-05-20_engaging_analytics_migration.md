# 2026-05-20 (이어 작업) — engaging-analytics M3 dashboard 마이그레이션

> branch: `feat/engaging-analytics-migration`
> base: `feat/bt-engagement` ← `2406458` (person_tracking ↔ 모객 BT funnel)
> SoT spec: `docs/superpowers/specs/2026-05-20-engaging-analytics-migration-design.md` (35d2bff)
> 진행: Task 1 (브랜치) ✓ → Task 2~9 본 세션 → Task 10 (본 회고 + commit)

## 1. 작업 요약

operator.html (legacy localhost:8765, 619 line) 의 engaging 모드 한정 분석 콘텐츠 —
V/A circumplex + rapport 타임라인 + 미니게임 결과 + 강제 발화 form — 를
`localhost:8800` M3 dashboard (`src/moca_opserver/`) 의 modes.html engaging 컨텍스트
expand 섹션 (옵션 E) 으로 이전. operator.html 자체 삭제는 본 trake 후속.

## 2. 백엔드 변경 (moca_opserver)

### 2.1 `opserver_node.py` — Task 2

신규 import: `EmotionState`, `MinigameResult` (dobi_npc_msgs.msg).

신규 ROS 구독 2 개 (`/rapport/event` 기존 유지):
- `/emotion/state` (EmotionState) → `_on_emotion_state` 콜백
- `/minigame/result` (MinigameResult) → `_on_minigame_result` 콜백

state cache (engaging-analytics 섹션):
- `_emotion_state: dict | None` (최신 1 개)
- `_emotion_history: deque(maxlen=60)` (6s @ 10Hz)
- `_rapport_events: deque(maxlen=20)`
- `_rapport_counters: dict` (engagement_up/down/abort_trigger/neutral_continue)
- `_last_minigame_result: dict | None`
- `_minigame_recent: deque(maxlen=5)`

`_on_rapport` 확장: 기존 abort_trigger alarm broadcast 유지 + deque append +
카운터 증가.

스냅샷 메서드 3 개:
- `emotion_snapshot() → {latest, trajectory[]}`
- `rapport_snapshot() → {counters, recent[]}`
- `minigame_snapshot() → {latest, recent[]}`

teleop_server.py:1201-1290 패턴 그대로 포팅 (필드명/round 정밀도/구조 동일).

### 2.2 `opserver_node.py` — Task 4 (`/dialog/router_in` publisher)

신규 publisher: `pub_router_in` (UtterRequest, `/dialog/router_in`).

신규 메서드 `publish_dialog_router_in(text, persona='')` —
operator priority=10 + preempt=True 로 즉시 발화. persona_id 만 채우고
voice/rate/pitch 는 dialog_router 가 페르소나 YAML 에서 매핑.

### 2.3 `rest_api.py` — Task 3 + 4

- `Body` import 추가 (FastAPI dict body parsing).
- `POST /api/v1/dialog/utter` — body `{text, persona?}` →
  `opserver.publish_dialog_router_in(text, persona)` + op_event 기록.
- `@app.websocket('/ws/v1/engaging')` — 5Hz throttle (asyncio.sleep(0.2)).
  payload: `{ts, emotion, rapport, minigame, mode}`. ws_dashboard 옆에 신규.

## 3. 프론트엔드 변경 (static/)

### 3.1 신규 `static/js/engaging-analytics.js` — Task 5

IIFE 모듈. `EngagingWS` 클래스 (자동 재연결 1s→15s 지수 백오프).
`store.on('mode')` 으로 engaging 모드 진입/이탈 감지 → 섹션 show/hide +
WS 토글. operator.html 의 V/A SVG 변환 (cx=V*100, cy=-A*100) +
trajectory fade + rapport counter/recent + minigame card 렌더 그대로 포팅.
강제 발화 폼은 REST `POST /api/v1/dialog/utter` 호출.

### 3.2 `static/css/components.css` 확장 — Task 6

`.engaging-analytics` (grid-column: 1/-1, border-strong) + `.ea-grid`
(240px + 1fr, 720px breakpoint) + `.circumplex` (PinkLAB 토큰 적용:
abort-zone rgba(255,77,109), cur-pt --pink-primary) + `.ea-rap-counter`
4 종 색 (success/warning/danger/muted) + `.console-log` 4 색 (debug.html 용).

### 3.3 `static/pages/modes.html` 확장 — Task 7

modes-grid 닫힘 직후 `<section class="card engaging-analytics" id="engaging-analytics" hidden>`
추가:
- V·A circumplex SVG (operator.html 247-269 그대로 포팅, ea- prefix)
- 라포 4 카운터 + recent list
- 미니게임 recent
- 강제 발화 form (text + persona dropdown + 발송 버튼)
script tag: `engaging-analytics.js?v=20260520a` + `components.css?v=20260520a`
(cache bust).

### 3.4 `static/pages/debug.html` 확장 — Task 8

신규 "Console Log (client-side)" 섹션 + console.log/info/warn/error
intercept + ws:open/ws:close/alarm 이벤트 capture. 최근 50 건 ring buffer.
브라우저 콘솔 안 열어도 운영자가 페이지에서 클라이언트 사이드 로그 확인 가능
(operator.html line 351 의 #log 패턴 포팅).

## 4. 검증 (Task 9 부분)

본 세션 검증:
- `python3 -m py_compile` opserver_node.py + rest_api.py — SYNTAX_OK
- `colcon build --symlink-install --packages-select moca_opserver` —
  Finished 1.71s (1 stderr = unrelated easy_install warning)
- import smoke — `OpServerNode.{emotion,rapport,minigame}_snapshot`,
  `publish_dialog_router_in`, `EmotionState`, `MinigameResult` 모두 OK
- 정적 자산 install symlink — engaging-analytics.js, components.css,
  modes.html, debug.html 모두 install/share 에 노출

라이브 검증 (사용자 위임):
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging &
ros2 launch moca_opserver opserver.launch.py &
'
# 브라우저: http://localhost:8800/static/pages/modes.html
# - engaging 진입 → 분석 패널 auto show
# - V/A circumplex 라이브 emotion → 점 + 궤적
# - rapport 이벤트 list 누적
# - 미니게임 결과 카드 (RPS 종료 시)
# - 강제 발화 form → TTS 발화
# - http://localhost:8800/static/pages/debug.html
#   브라우저 콘솔 메시지 + WS open/close + alarm 표시
```

## 5. §0-B / §0-A 영향

변경 대상 = `src/moca_opserver/` (Python + static) 만. 모두 PC 단독 자산.
`src/shared/vic_pinky/`, `scripts/run_*.sh`, RPi `~/vicpinky_ws/` — touch 0.
WebSocket + REST 추가만, 신규 ROS publish 는 `/dialog/router_in` (기존 토픽).

## 6. 후속 (별 trake)

1. **operator.html 삭제** — 본 마이그레이션 confirm 후 별 commit.
   `web/static/operator.html` + `web/teleop_server.py` 의 emotion/rapport/minigame
   subscriber + snapshot 코드 (line 1201-1290) 정리 가능 (단,
   teleop_server.py 의 다른 기능 — joystick + camera — 은 그대로 유지).
2. **operator.html 로 라우팅하는 link 정리** — debug.html 의 "외부 서버 안내"
   섹션 (line 76-91) 의 `localhost:8765/operator` 링크 갱신 또는 제거.
3. **engaging-analytics.js 의 강제 발화 결과 표시** — 현재는 toast 만, dialog_router
   가 utter_done 발행하면 그것도 표시.
4. **cache busting 자동화** — modes.html / debug.html 의 ?v 일괄 bump
   (CLAUDE.md TODO §"cache busting 자동화").

## 7. 시간 기록

- 21:39 (전 세션) 중단 — spec 작성 + brainstorm
- 22:40~22:45 (본 세션) — Task 2~9 코드 작업
- 22:45 commit (사용자 push 위임)
