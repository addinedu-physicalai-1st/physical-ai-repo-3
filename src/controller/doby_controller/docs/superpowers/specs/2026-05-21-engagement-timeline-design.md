# 2026-05-21 — Track C: engagement-timeline 시계열 그래프

> branch: `feat/engagement-timeline` (별 cut, base = `feat/engaging-analytics-migration` merge 후 main)
> 작성: 2026-05-21 (Track B 직후, brainstorm 완료)
> 본 spec 의 SoT — implementation plan 은 writing-plans skill 호출 시 생성
> 관련: [[2026-05-20-rapport-averaging-window-design]] §10 Track C, [[2026-05-21-track-id-integration-design]]

---

## 1. 한 줄 정의

modes.html engaging-analytics 안에 신규 `<engagement-timeline>` web component
도입. **V / A / engagement_score** 3 라인 + rapport event 마커 (up/down/abort)
를 X축 시간 (최근 1분), Y축 [-1, +1] 으로 시각화. engagement_score 는 opserver
가 RapportEvent.weight 의 EMA (α=0.1) 로 계산. track_id 변경 시 score cold start.

Track D MySQL audit 의 `audit_event` 테이블 source 자연 연계.

## 2. 사용자 확정 결정 (brainstorm 산물)

| # | 결정 | 채택 |
|---|---|---|
| D1 | 표시 변수 | **V + A + engagement_score** 3 라인 + rapport event 마커 (4 종) |
| D2 | score 계산 | **EMA** (α=0.1, ~10 frame 효과적 윈도우 ≈ 1초). rapport-ema 패턴 정합 |
| D3 | 시간 창 | **1분** (600 frame @10Hz). opserver `_emotion_history` maxlen 60→600 |
| D4 | 컴포넌트 형태 | **web component `<engagement-timeline>`** (기존 components/ 패턴 정합) |
| D5 | logic 위치 | **opserver-only** (rapport_tracker / RapportEvent.msg 변경 X) |
| D6 (도출) | 차트 라이브러리 | **native SVG** (Chart.js 미사용 — 외부 의존 X, circumplex 와 같은 패턴) |
| D7 (도출) | track_id 변경 처리 | score=0.0 cold start, history 는 보존 (vertical divider 표시 선택) |

## 3. Architecture & data flow

```
GEVA → /emotion/state ──→ opserver._on_emotion_state
                              └─ _emotion_history maxlen 60 → 600 (1분)

rapport_tracker → /rapport/event ─→ opserver._on_rapport
                                     ├─ EMA: score = α*weight + (1-α)*prev
                                     ├─ track_id 변경 시 score=0.0 cold start
                                     ├─ _engagement_score_history maxlen 600
                                     └─ _rapport_marker_history maxlen 30
                                        (engagement_up/down/abort 마커)

→ WS /ws/v1/engaging payload 확장:
   emotion.trajectory: 600 frame {ts, v, a, conf}
   engagement.score: 현재 EMA score (single float)
   engagement.score_history: 600 frame {ts, score}
   engagement.rapport_markers: 30 recent {ts, type, weight}

→ engaging-analytics.js 가 payload 받아서:
   - 기존 circumplex / rapport / minigame 렌더 (그대로)
   - 신규 customElements.get('engagement-timeline').render(payload) 호출

→ <engagement-timeline> web component (static/components/engagement-timeline.js)
   - native SVG 라인 그래프
   - V (--pink-soft) / A (--cyan-accent) / score (--success) 3 라인
   - rapport markers (up/down/abort)
   - X 0~60s, Y -1~+1
```

**핵심 원칙**:
- rapport_tracker / RapportEvent.msg / 기존 5 components/ 모두 **변경 X**
- opserver 가 EMA 단일 source (track_id 변경 감지 = rapport_tracker EMA cold start 와 같은 패턴, 다른 state)
- web component 가 자체 SVG 렌더 — engaging-analytics.js 가 payload 전달만

## 4. opserver_node.py 변경

### 4.1 __init__ 추가/갱신

```python
# 기존: maxlen=60 → 600 변경
self._emotion_history: deque = deque(maxlen=600)   # 1분 @ 10Hz

# 신규
self._engagement_score: float = 0.0
self._engagement_score_history: deque = deque(maxlen=600)
self._rapport_marker_history: deque = deque(maxlen=30)
self._last_score_track_id: int = -1

# 파라미터 (config 매핑)
self.declare_parameter('engagement_score_alpha', 0.1)
self._score_alpha: float = float(
    self.get_parameter('engagement_score_alpha').value)
```

### 4.2 _on_rapport 콜백 확장

기존 `_on_rapport` 의 abort_trigger alarm + counter + recent deque append 그대로 유지. 추가:

```python
def _on_rapport(self, msg: RapportEvent):
    # ... 기존 rec / counters / append (변경 X) ...

    # 2026-05-21 Track C — engagement_score EMA + history
    tid = int(msg.emotion.track_id)
    if tid != self._last_score_track_id and tid != -1:
        # track 전환 → score cold start
        self.get_logger().info(
            f"engagement_score cold start: track_id "
            f"{self._last_score_track_id} → {tid}")
        self._engagement_score = 0.0
        self._last_score_track_id = tid

    self._engagement_score = (
        self._score_alpha * float(msg.weight) +
        (1.0 - self._score_alpha) * self._engagement_score
    )

    now = time.time()
    self._engagement_score_history.append({
        'ts': round(now, 3),
        'score': round(self._engagement_score, 4),
    })

    # rapport marker (engagement_up/down/abort 만, neutral 제외 — 차트 노이즈 회피)
    if msg.event_type in ('engagement_up', 'engagement_down', 'abort_trigger'):
        self._rapport_marker_history.append({
            'ts': round(now, 3),
            'type': msg.event_type,
            'weight': round(float(msg.weight), 2),
        })
```

### 4.3 신규 engagement_snapshot()

```python
def engagement_snapshot(self) -> dict:
    return {
        'score': round(self._engagement_score, 4),
        'score_history': list(self._engagement_score_history),
        'rapport_markers': list(self._rapport_marker_history),
    }
```

기존 `emotion_snapshot()` / `rapport_snapshot()` / `minigame_snapshot()` 그대로 유지.

### 4.4 WS payload 확장

`rest_api.py` 의 `ws_engaging` 핸들러 안 payload dict 에 추가:

```python
payload = {
    'ts': now_iso(),
    'emotion': opserver.emotion_snapshot(),
    'rapport': opserver.rapport_snapshot(),
    'minigame': opserver.minigame_snapshot(),
    'engagement': opserver.engagement_snapshot(),   # NEW
    'mode': {
        'current': opserver.current_mode,
        'entered_at': opserver.mode_entered_at,
    },
}
```

## 5. WS payload 형태 (예시)

```json
{
  "ts": "2026-05-21T...",
  "emotion": {
    "latest": {"v": 0.3, "a": 0.1, "conf": 0.85, "source": "face",
               "flags": [], "track_id": 42, "group_id": 0, "ts": 1234567.89},
    "trajectory": [
      {"t": 1234567.79, "v": 0.28, "a": 0.09, "conf": 0.84, "source": "face"},
      ...
    ]
  },
  "engagement": {
    "score": 0.42,
    "score_history": [
      {"ts": 1234567.79, "score": 0.38},
      {"ts": 1234567.89, "score": 0.42},
      ...
    ],
    "rapport_markers": [
      {"ts": 1234560.12, "type": "engagement_up", "weight": 0.5},
      {"ts": 1234562.45, "type": "abort_trigger", "weight": -1.0},
      ...
    ]
  },
  "rapport": {...},
  "minigame": {...},
  "mode": {...}
}
```

## 6. `<engagement-timeline>` web component

### 6.1 파일 위치

`src/moca_opserver/static/components/engagement-timeline.js` (기존 components/ 패턴 정합 — battery-gauge.js, mode-badge.js 등과 같은 형식).

### 6.2 컴포넌트 구조

```javascript
class EngagementTimeline extends HTMLElement {
  static get observedAttributes() { return []; }

  connectedCallback() {
    this.innerHTML = `
      <svg class="engagement-timeline" viewBox="0 0 600 200" preserveAspectRatio="none">
        <!-- 축 + 그리드 -->
        <line class="et-axis" x1="0" y1="100" x2="600" y2="100"/>
        <line class="et-grid" x1="0" y1="0" x2="600" y2="0"/>
        <line class="et-grid" x1="0" y1="200" x2="600" y2="200"/>
        <line class="et-grid" x1="0" y1="50" x2="600" y2="50"/>
        <line class="et-grid" x1="0" y1="150" x2="600" y2="150"/>

        <!-- Y 라벨 -->
        <text class="et-legend" x="5" y="12">+1</text>
        <text class="et-legend" x="5" y="105">0</text>
        <text class="et-legend" x="5" y="198">-1</text>

        <!-- 시간 라벨 -->
        <text class="et-legend" x="0" y="215">60s</text>
        <text class="et-legend" x="290" y="215">30s</text>
        <text class="et-legend" x="570" y="215">now</text>

        <!-- 라인 + 마커 (JS 동적) -->
        <polyline class="et-line-v" id="et-line-v" points=""/>
        <polyline class="et-line-a" id="et-line-a" points=""/>
        <polyline class="et-line-score" id="et-line-score" points=""/>
        <g id="et-markers"></g>

        <!-- 범례 -->
        <g class="et-legend-row">
          <rect x="450" y="5" width="8" height="2" class="et-line-v" fill="currentColor"/>
          <text class="et-legend" x="463" y="10">V</text>
          <rect x="485" y="5" width="8" height="2" class="et-line-a" fill="currentColor"/>
          <text class="et-legend" x="498" y="10">A</text>
          <rect x="520" y="5" width="8" height="2" class="et-line-score" fill="currentColor"/>
          <text class="et-legend" x="533" y="10">score</text>
        </g>
      </svg>
    `;
    this._lineV = this.querySelector('#et-line-v');
    this._lineA = this.querySelector('#et-line-a');
    this._lineScore = this.querySelector('#et-line-score');
    this._markers = this.querySelector('#et-markers');
  }

  /** payload = WS /ws/v1/engaging.data */
  render(payload) {
    if (!payload) return;
    const traj = (payload.emotion && payload.emotion.trajectory) || [];
    const score = (payload.engagement && payload.engagement.score_history) || [];
    const marks = (payload.engagement && payload.engagement.rapport_markers) || [];

    // 시간 범위 — 가장 늦은 ts 가 right edge, 60s 전이 left edge
    const now = (traj.length ? traj[traj.length-1].t : 0)
              || (score.length ? score[score.length-1].ts : 0);
    if (!now) { this._clear(); return; }
    const start = now - 60.0;

    const tx = (ts) => Math.max(0, Math.min(600, ((ts - start) / 60.0) * 600));
    const ty = (val) => 100 - Math.max(-1, Math.min(1, val)) * 100;

    this._lineV.setAttribute('points',
      traj.map(p => `${tx(p.t).toFixed(1)},${ty(p.v).toFixed(1)}`).join(' '));
    this._lineA.setAttribute('points',
      traj.map(p => `${tx(p.t).toFixed(1)},${ty(p.a).toFixed(1)}`).join(' '));
    this._lineScore.setAttribute('points',
      score.map(p => `${tx(p.ts).toFixed(1)},${ty(p.score).toFixed(1)}`).join(' '));

    const cls = {
      engagement_up: 'et-marker-up',
      engagement_down: 'et-marker-down',
      abort_trigger: 'et-marker-abort',
    };
    this._markers.innerHTML = marks
      .filter(m => m.ts >= start)
      .map(m => `<circle class="${cls[m.type] || ''}" cx="${tx(m.ts).toFixed(1)}" cy="${ty(m.weight).toFixed(1)}" r="3"/>`)
      .join('');
  }

  _clear() {
    this._lineV.setAttribute('points', '');
    this._lineA.setAttribute('points', '');
    this._lineScore.setAttribute('points', '');
    this._markers.innerHTML = '';
  }
}

customElements.define('engagement-timeline', EngagementTimeline);
```

## 7. engaging-analytics.js 통합

기존 WS onmessage 핸들러 확장 — payload 받아서 engagement-timeline 호출:

```javascript
this.ws.onmessage = (e) => {
  try {
    const j = JSON.parse(e.data);
    renderEmotion(j.emotion);
    renderRapport(j.rapport);
    renderMinigame(j.minigame);
    // 2026-05-21 Track C — engagement-timeline 렌더
    const tl = document.querySelector('engagement-timeline');
    if (tl && tl.render) tl.render(j);
  } catch (err) { /* ignore */ }
};
```

## 8. modes.html 통합

engaging-analytics 섹션 안, `<h4 class="card__subtitle">미니게임 결과</h4>` **직전** (rapport recent 다음, 미니게임 직전) 에:

```html
<h4 class="card__subtitle">시계열 추이 (최근 1분)</h4>
<engagement-timeline id="ea-timeline"></engagement-timeline>
```

modes.html `<script>` 영역에 components/engagement-timeline.js 로드:

```html
<script src="/static/components/engagement-timeline.js?v=20260521b"></script>
```

cache bust `?v=20260521b` (Track B 의 `20260521a` 다음).

## 9. components.css 추가

```css
/* engagement-timeline web component */
engagement-timeline {
  display: block;
  width: 100%;
  max-width: 720px;
  margin: var(--space-3) auto;
}
.engagement-timeline {
  display: block;
  width: 100%;
  height: 220px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.engagement-timeline .et-axis {
  stroke: var(--border-strong);
  stroke-width: 0.5;
}
.engagement-timeline .et-grid {
  stroke: var(--border);
  stroke-width: 0.3;
  stroke-dasharray: 2 3;
}
.engagement-timeline .et-line-v {
  stroke: var(--pink-soft);
  fill: none;
  stroke-width: 1.5;
}
.engagement-timeline .et-line-a {
  stroke: var(--cyan-accent);
  fill: none;
  stroke-width: 1.5;
}
.engagement-timeline .et-line-score {
  stroke: var(--success);
  fill: none;
  stroke-width: 2;
}
.engagement-timeline .et-marker-up   { fill: var(--success); }
.engagement-timeline .et-marker-down { fill: var(--warning); }
.engagement-timeline .et-marker-abort { fill: var(--danger); }
.engagement-timeline .et-legend {
  fill: var(--text-muted);
  font-size: 10px;
  font-family: var(--font-mono);
}
```

## 10. Edge cases

| 상황 | 동작 |
|---|---|
| 첫 RapportEvent 전 | score=0.0, history 비어있음. 차트 빈 SVG (라인 미 표시). `_clear()` |
| track_id=-1 (unknown) | score 그대로 유지 (cold start 안 함). 차트 score 라인 계속 그려짐 |
| track_id 변경 | score=0.0 reset. score 라인 이 0 까지 떨어졌다가 새 추세 시작 (자연 시각화) |
| no_signal 지속 | RapportEvent.weight=0 → EMA 가 score=0 으로 천천히 수렴. 차트에 0 근처 평탄 |
| 1분 초과 history | deque maxlen=600 자동 drop. polyline points 가 60s 윈도우만 |
| 재연결 시 client | opserver 가 trajectory + score_history 전체 broadcast (5Hz) → 즉시 채워짐 |
| trajectory 와 score_history ts 차이 | emotion 10Hz vs rapport 10Hz — 같은 frame rate. ts mismatch 시 차트 분리 라인 (V/A 는 emotion ts, score 는 rapport ts) |
| rapport_markers 가 1분 밖 | filter(m.ts >= start) 로 제외 |

## 11. Testing

### 11.1 단위 테스트 (신규)

`src/moca_opserver/test/test_engagement_score.py`:

- `test_engagement_score_cold_start_initial_zero` — 첫 RapportEvent 전 score=0
- `test_engagement_score_ema_accumulates_positive` — weight=+0.5 5번 → score → 0.5 근접 수렴
- `test_engagement_score_ema_accumulates_negative` — weight=-1.0 5번 → score → -1.0 근접
- `test_engagement_score_reset_on_track_change` — track_id 42→99 변경 → score=0.0 reset
- `test_engagement_score_no_reset_on_unknown_track` — track_id=-1 frame → score 유지
- `test_rapport_marker_history_maxlen` — 31개 publish → 30 만 유지 (engagement_up 30 + abort 1 등)
- `test_rapport_marker_excludes_neutral` — neutral_continue 는 marker history 에 안 들어감

opserver 테스트는 기존 `test/test_orchestrator.py`, `test/test_completion_and_timer.py` 패턴 따라 — `_on_rapport` 콜백을 직접 호출 + RapportEvent mock 입력.

### 11.2 회귀 카탈로그

`tests/regression/perception/engagement_timeline_smoke.md` (신규):
- opserver + rapport_tracker spawn
- dummy weight 시퀀스 publish (engagement_up × 5 → abort_trigger × 1)
- WS payload `engagement.score_history` 길이 검증
- WS payload `engagement.rapport_markers` 의 type 분포 검증
- 브라우저 modes.html 진입 → SVG 라인 + 마커 시각 확인 (수동)

### 11.3 라이브 검증

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging &
ros2 launch moca_opserver opserver.launch.py &
'
# 브라우저 http://localhost:8800/static/pages/modes.html
# - engaging 모드 진입 → 분석 패널 + 시계열 추이 차트 표시
# - 카메라 앞에서 표정 변화 → V/A 라인 + score 라인 부드럽게 움직임
# - 5초 angry 표정 유지 → abort_trigger 마커 + score 라인 -1 까지 떨어짐
```

## 12. §0-B / §0-A 정합

**변경 대상**:
- `src/moca_opserver/moca_opserver/opserver_node.py` (EMA + history)
- `src/moca_opserver/moca_opserver/rest_api.py` (WS payload 확장)
- `src/moca_opserver/static/components/engagement-timeline.js` (신규)
- `src/moca_opserver/static/js/engaging-analytics.js` (timeline.render 호출)
- `src/moca_opserver/static/pages/modes.html` (custom element + script)
- `src/moca_opserver/static/css/components.css` (스타일)
- `src/moca_opserver/test/test_engagement_score.py` (신규)
- `tests/regression/perception/engagement_timeline_smoke.md` (신규)
- `tests/regression/catalog.yaml` (등록)

**무영향**:
- `src/dobi_npc/dobi_npc_msgs/*` (msg 변경 0)
- `src/dobi_npc/dobi_npc_emotion/*` (rapport_tracker / geva_node 변경 0)
- `src/dobi_npc/dobi_npc_bt/*` (BT 변경 0)
- `src/shared/vic_pinky/*` (vic_pinky touch 0)
- RPi `~/vicpinky_ws/` (touch 0)
- 신규 ROS topic 0

## 13. Track D 와의 연계

본 spec 의 `_engagement_score_history` + `_rapport_marker_history` 가 Track D
MySQL audit log 의 자연 source:

| Track D 산물 | 본 spec 의 source |
|---|---|
| MySQL `audit_event` 의 `weight` / `score_smooth` 필드 | `RapportEvent.weight` + opserver `_engagement_score` |
| MySQL `audit_event` 의 `track_id` FK | `msg.emotion.track_id` (Track B 산물) |
| MySQL `engagement_score_log` 테이블 (선택) | `_engagement_score_history` deque 그대로 적재 |
| MySQL audit 의 `event_type` (engagement_up/down/abort) | `_rapport_marker_history` 그대로 |

본 spec implementation 완료 후 Track D brainstorm 진입 시 데이터 source 가
이미 준비된 상태.

## 14. 다음 세션 이어 시작 가이드

```bash
cd ~/physical-ai-repo-3
git checkout main          # feat/engaging-analytics-migration merge 후
git pull
git checkout -b feat/engagement-timeline
git log --oneline -3
# writing-plans skill 호출 — 본 spec 기반 implementation plan 작성
```

## 15. 시간 기록

- 2026-05-21 brainstorm — 사용자 D1-D7 결정 (표시 변수 / score EMA / 시간 창 / web component / opserver-only)
- spec 작성 + commit
- 다음 단계: writing-plans skill → implementation plan

## 16. 후속 (Phase, 본 spec 범위 밖)

- **tunable score α**: 라이브 환경 (카페 손님 평균 머무는 시간) 에 맞게 α 조정. 기본 0.1 → 0.05 (더 부드러움) 또는 0.2 (빠른 반응)
- **score Y 축 dynamic range**: 손님 호객 마지막에 score 값이 ±0.3 정도라면 Y 축 자동 zoom (-1~+1 보다 좁게)
- **다중 손님 동시 비교**: track_id 별 score 라인 (멀티 라인) — Phase 5
- **score → BT 의사결정 입력**: BT EmotionMonitor 의 신규 출력 포트 `rapport_delta` (spec §10 의 rapport-ema spec line 14) — 본 spec 의 score 가 자연 source
- **차트 zoom / pan**: 운영자가 1분 → 30초 / 5분 등 동적 변경. SVG 의 viewBox 변경
- **markers 호버 툴팁**: SVG 의 `<title>` 또는 별 div — type / weight / ts 상세 표시
