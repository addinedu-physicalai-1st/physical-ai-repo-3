# Track C — engagement-timeline 시계열 그래프 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** modes.html engaging-analytics 안에 `<engagement-timeline>` web component 도입 — V/A/engagement_score 3 라인 + rapport event 마커 시계열 (최근 1분). opserver 가 EMA score 단일 source.

**Architecture:**
1. opserver `_on_rapport` 콜백에서 EMA score 계산 (α=0.1) + track_id 변경 시 cold start. EMA + reset logic 은 module-level pure function 으로 분리 → unit test.
2. opserver `_emotion_history` maxlen 60→600 + 신규 2 deque (score_history 600 / marker_history 30).
3. `<engagement-timeline>` web component (native SVG) 가 WS payload 받아 polyline + circle 렌더. engaging-analytics.js 는 단순 위임.

**Tech Stack:** Python 3.12, rclpy (Jazzy), pytest, FastAPI/WebSocket, vanilla JS web component, native SVG.

**Spec SoT:** `docs/superpowers/specs/2026-05-21-engagement-timeline-design.md` (commit 4b0bac9).

---

## File Structure

- **Modify**: `src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py`
  - module-level helpers: `compute_engagement_ema`, `should_reset_engagement_score`, `is_marker_eligible`
  - `__init__`: 새 파라미터 1 (`engagement_score_alpha`), 멤버 (deque maxlen 600 변경 + 신규 3 멤버 + last_score_track_id)
  - `_on_rapport` 콜백 확장 (track_id 감지 + EMA + history + marker)
  - 신규 `engagement_snapshot()` 메서드
- **Modify**: `src/controller/doby_controller/src/moca_opserver/moca_opserver/rest_api.py` (ws_engaging payload `engagement` 필드)
- **Create**: `src/controller/doby_controller/src/moca_opserver/test/test_engagement_score.py` (8 unit tests)
- **Create**: `src/controller/doby_controller/src/moca_opserver/static/components/engagement-timeline.js`
- **Modify**: `src/controller/doby_controller/src/moca_opserver/static/js/engaging-analytics.js` (timeline.render 호출)
- **Modify**: `src/controller/doby_controller/src/moca_opserver/static/pages/modes.html` (custom element + script + cache bust)
- **Modify**: `src/controller/doby_controller/src/moca_opserver/static/css/components.css` (.engagement-timeline 스타일)
- **Create**: `src/controller/doby_controller/tests/regression/perception/engagement_timeline_smoke.md`
- **Modify**: `src/controller/doby_controller/tests/regression/catalog.yaml`

---

## Task 1: opserver helpers + 8 unit tests (TDD)

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py`
- Create: `src/controller/doby_controller/src/moca_opserver/test/test_engagement_score.py`

- [ ] **Step 1: Write failing tests**

Create `src/controller/doby_controller/src/moca_opserver/test/test_engagement_score.py`:

```python
"""opserver engagement_score helpers 단위 테스트.

ROS 노드 의존 없이 pure function 검증.
spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §4
"""
from moca_opserver.opserver_node import (
    compute_engagement_ema,
    should_reset_engagement_score,
    is_marker_eligible,
)


ALPHA = 0.1


def test_compute_ema_cold_start_first_update():
    """첫 update (prev=0.0) — weight 의 alpha 비율만 반영."""
    result = compute_engagement_ema(prev=0.0, weight=0.5, alpha=ALPHA)
    # 0.1*0.5 + 0.9*0.0 = 0.05
    assert abs(result - 0.05) < 1e-9


def test_compute_ema_accumulate_positive():
    """weight=+0.5 sustained — score 가 0.5 로 점근."""
    score = 0.0
    for _ in range(50):
        score = compute_engagement_ema(score, weight=0.5, alpha=ALPHA)
    # 50 frame 후 90% 도달 이상 — 0.45 < score < 0.5
    assert 0.45 < score < 0.5


def test_compute_ema_accumulate_negative():
    """weight=-1.0 sustained — score 가 -1.0 로 점근."""
    score = 0.0
    for _ in range(50):
        score = compute_engagement_ema(score, weight=-1.0, alpha=ALPHA)
    assert -1.0 < score < -0.9


def test_should_reset_on_first_valid_track():
    """last=-1, current=5 — first valid track, reset 안 함."""
    assert should_reset_engagement_score(last=-1, current=5) is False


def test_should_reset_on_track_change():
    """last=42, current=99 — 손님 전환, reset."""
    assert should_reset_engagement_score(last=42, current=99) is True


def test_should_reset_no_reset_on_unknown():
    """last=42, current=-1 — 일시 unknown, EMA 보존."""
    assert should_reset_engagement_score(last=42, current=-1) is False


def test_should_reset_no_reset_on_same():
    """last=42, current=42 — 같은 손님, reset 안 함."""
    assert should_reset_engagement_score(last=42, current=42) is False


def test_marker_eligible_filters_neutral_and_no_signal():
    """engagement_up/down/abort_trigger 만 marker. neutral_continue/no_signal 제외."""
    assert is_marker_eligible('engagement_up') is True
    assert is_marker_eligible('engagement_down') is True
    assert is_marker_eligible('abort_trigger') is True
    assert is_marker_eligible('neutral_continue') is False
    assert is_marker_eligible('') is False
    assert is_marker_eligible('unknown_type') is False
```

- [ ] **Step 2: Run tests to verify fail**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/moca_opserver/test/test_engagement_score.py -v 2>&1 | tail -15
'
```

Expected: `ImportError: cannot import name 'compute_engagement_ema' from 'moca_opserver.opserver_node'`.

- [ ] **Step 3: Add helpers at module level**

`src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py` 의 `OpServerConfig` dataclass 정의 **직후** (`# ---------- 메인 노드 ----------` 주석 **위**) 에 추가:

```python
# ---------- Track C engagement-timeline helpers ----------
# spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §4

_MARKER_ELIGIBLE_TYPES = frozenset(
    {'engagement_up', 'engagement_down', 'abort_trigger'})


def compute_engagement_ema(prev: float, weight: float, alpha: float) -> float:
    """RapportEvent.weight 의 EMA — 다음 score 반환.

    score = alpha * weight + (1 - alpha) * prev
    """
    return alpha * weight + (1.0 - alpha) * prev


def should_reset_engagement_score(last: int, current: int) -> bool:
    """track_id 변경 시 engagement_score cold start 여부.

    - current == -1: unknown frame — 보존 (False)
    - last == -1: first valid — 보존 (cold start fallback, False)
    - 같은 track: False
    - 다른 valid track: True
    """
    if current == -1:
        return False
    if last == -1:
        return False
    return last != current


def is_marker_eligible(event_type: str) -> bool:
    """rapport_marker_history 에 append 할 event_type 만 True.

    engagement_up / engagement_down / abort_trigger 만 — neutral / no_signal 제외.
    """
    return event_type in _MARKER_ELIGIBLE_TYPES
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
source install/setup.bash
pytest src/moca_opserver/test/test_engagement_score.py -v 2>&1 | tail -15
'
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py \
        src/controller/doby_controller/src/moca_opserver/test/test_engagement_score.py
git commit -m "feat(track-c): opserver helpers + 8 unit tests (Task 1)

compute_engagement_ema / should_reset_engagement_score / is_marker_eligible
module-level pure helpers. ROS 의존 없이 pytest 검증.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: opserver __init__ + _on_rapport 통합

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py`

- [ ] **Step 1: 현재 구조 확인**

```bash
grep -nE "_emotion_history|_engagement_score|declare_parameter|def _on_rapport|def _on_emotion_state" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py | head -20
```

본 plan 이 의존하는 라인:
- `_emotion_history` deque 멤버 (현재 maxlen=60)
- `_rapport_events` deque (Track A 산물)
- `_last_score_track_id` 또는 다른 score 멤버 (없음 — 본 task 가 추가)

- [ ] **Step 2: __init__ 변경 — maxlen + 신규 멤버 + 파라미터**

`__init__` 의 `self._emotion_history: deque = deque(maxlen=600)` 와 `self._engagement_score: float = 0.0` 같은 라인 찾기:

```bash
grep -nE "self\._emotion_history|self\._rapport_events" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py
```

기존 라인 (현재 maxlen 60):
```python
        self._emotion_history: deque = deque(maxlen=60)  # 6s @ 10Hz
```

를 다음으로 교체:
```python
        # 2026-05-21 Track C — engagement-timeline 시간 창 60→600 (1분 @ 10Hz)
        self._emotion_history: deque = deque(maxlen=600)
```

`self._rapport_events: deque = deque(maxlen=20)` 라인 **직후** 에 추가:
```python
        # 2026-05-21 Track C — engagement_score (EMA) + history
        self._engagement_score: float = 0.0
        self._engagement_score_history: deque = deque(maxlen=600)
        self._rapport_marker_history: deque = deque(maxlen=30)
        self._last_score_track_id: int = -1
```

`__init__` 의 `self.declare_parameter('alarm_dwell_sec', 5.0)` 라인 **직후** 에 추가:
```python
        # 2026-05-21 Track C
        self.declare_parameter('engagement_score_alpha', 0.1)
```

`__init__` 의 `self.config = OpServerConfig(...)` 호출 **직후** 에 추가:
```python
        # 2026-05-21 Track C — score EMA alpha
        self._score_alpha: float = float(
            self.get_parameter('engagement_score_alpha').value)
```

- [ ] **Step 3: _on_rapport 콜백 확장**

먼저 _on_rapport 위치 확인:
```bash
grep -nE "def _on_rapport" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py
```

`_on_rapport` 메서드의 기존 `rec = {...}` block + `self._rapport_events.append(rec)` 직후 에 추가 (deque append 다음, abort_trigger 분기 직전):

```python
        # 2026-05-21 Track C — engagement_score EMA + marker history
        tid = int(msg.emotion.track_id)
        if should_reset_engagement_score(self._last_score_track_id, tid):
            self.get_logger().info(
                f"engagement_score cold start: track_id "
                f"{self._last_score_track_id} → {tid}")
            self._engagement_score = 0.0
        if tid != -1:
            self._last_score_track_id = tid

        self._engagement_score = compute_engagement_ema(
            self._engagement_score, float(msg.weight), self._score_alpha)

        now = time.time()
        self._engagement_score_history.append({
            'ts': round(now, 3),
            'score': round(self._engagement_score, 4),
        })
        if is_marker_eligible(msg.event_type):
            self._rapport_marker_history.append({
                'ts': round(now, 3),
                'type': msg.event_type,
                'weight': round(float(msg.weight), 2),
            })
```

기존 abort_trigger alarm 분기 + counter / recent deque append 모두 변경 없음.

- [ ] **Step 4: Build + import smoke**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -5
source install/setup.bash
python3 -c "
from moca_opserver.opserver_node import OpServerNode, compute_engagement_ema
print(\"import OK\")
"
'
```

Expected: `Finished <<< moca_opserver` + `import OK`.

- [ ] **Step 5: Run unit tests (회귀 확인)**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/moca_opserver/test/test_engagement_score.py -v 2>&1 | tail -15
'
```

Expected: 8 passed (Task 1 의 helpers 그대로).

- [ ] **Step 6: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py
git commit -m "feat(track-c): opserver _on_rapport 에 engagement_score EMA + marker history (Task 2)

_emotion_history maxlen 60→600 (1분). 신규 3 멤버: _engagement_score (float),
_engagement_score_history (deque 600), _rapport_marker_history (deque 30).
새 파라미터 engagement_score_alpha (기본 0.1).

_on_rapport 콜백에 should_reset_engagement_score 호출 + compute_engagement_ema
+ is_marker_eligible filter. track_id 변경 시 score=0.0 cold start.

spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: engagement_snapshot + WS payload

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py`
- Modify: `src/controller/doby_controller/src/moca_opserver/moca_opserver/rest_api.py`

- [ ] **Step 1: opserver 에 engagement_snapshot 메서드 추가**

`opserver_node.py` 의 기존 `minigame_snapshot(self) -> dict:` 메서드 **직후** 에 추가:

```python
    def engagement_snapshot(self) -> dict:
        """Track C — engagement-timeline 의 WS payload 데이터."""
        return {
            'score': round(self._engagement_score, 4),
            'score_history': list(self._engagement_score_history),
            'rapport_markers': list(self._rapport_marker_history),
        }
```

- [ ] **Step 2: rest_api 의 ws_engaging payload 확장**

`rest_api.py` 의 `ws_engaging` 함수 안 `payload = {...}` dict 의 `'rapport': opserver.rapport_snapshot(),` 라인 직후에 추가:

```python
                    'engagement': opserver.engagement_snapshot(),
```

전체 payload 가 다음과 같아짐:

```python
                payload = {
                    'ts': now_iso(),
                    'emotion': opserver.emotion_snapshot(),
                    'rapport': opserver.rapport_snapshot(),
                    'engagement': opserver.engagement_snapshot(),
                    'minigame': opserver.minigame_snapshot(),
                    'mode': {
                        'current': opserver.current_mode,
                        'entered_at': opserver.mode_entered_at,
                    },
                }
```

먼저 payload block 위치 확인:
```bash
grep -nE "'emotion': opserver.emotion_snapshot|'rapport': opserver.rapport_snapshot" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/moca_opserver/rest_api.py
```

- [ ] **Step 3: Build + payload 형태 검증**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
source install/setup.bash
python3 -c "
from moca_opserver.opserver_node import OpServerNode
# engagement_snapshot 메서드 존재 + 기본 값 확인
print(\"engagement_snapshot method:\", hasattr(OpServerNode, \"engagement_snapshot\"))
"
'
```

Expected: `engagement_snapshot method: True`.

- [ ] **Step 4: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py \
        src/controller/doby_controller/src/moca_opserver/moca_opserver/rest_api.py
git commit -m "feat(track-c): engagement_snapshot + WS payload 확장 (Task 3)

opserver.engagement_snapshot() 신규 메서드 — score / score_history /
rapport_markers. rest_api ws_engaging payload 에 'engagement' 필드 추가.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: engagement-timeline web component (native SVG)

**Files:**
- Create: `src/controller/doby_controller/src/moca_opserver/static/components/engagement-timeline.js`

- [ ] **Step 1: 신규 web component 파일 생성**

Create `src/controller/doby_controller/src/moca_opserver/static/components/engagement-timeline.js`:

```javascript
/* engagement-timeline.js — Track C 시계열 그래프 web component
 *
 * V / A / engagement_score 3 라인 + rapport event 마커.
 * X 0~60s, Y -1~+1. native SVG (Chart.js 미사용).
 *
 * 사용: <engagement-timeline></engagement-timeline>
 *      const el = document.querySelector('engagement-timeline');
 *      el.render(wsPayload);
 *
 * spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §6
 */
class EngagementTimeline extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <svg class="engagement-timeline" viewBox="0 0 600 220"
           preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
        <line class="et-axis" x1="0" y1="100" x2="600" y2="100"></line>
        <line class="et-grid" x1="0" y1="0" x2="600" y2="0"></line>
        <line class="et-grid" x1="0" y1="200" x2="600" y2="200"></line>
        <line class="et-grid" x1="0" y1="50" x2="600" y2="50"></line>
        <line class="et-grid" x1="0" y1="150" x2="600" y2="150"></line>

        <text class="et-legend" x="5" y="12">+1</text>
        <text class="et-legend" x="5" y="105">0</text>
        <text class="et-legend" x="5" y="198">-1</text>
        <text class="et-legend" x="0" y="215">60s</text>
        <text class="et-legend" x="290" y="215">30s</text>
        <text class="et-legend" x="570" y="215">now</text>

        <polyline class="et-line-v" id="et-line-v" points=""></polyline>
        <polyline class="et-line-a" id="et-line-a" points=""></polyline>
        <polyline class="et-line-score" id="et-line-score" points=""></polyline>
        <g id="et-markers"></g>

        <g class="et-legend-row">
          <line class="et-line-v" x1="450" y1="8" x2="458" y2="8"></line>
          <text class="et-legend" x="463" y="11">V</text>
          <line class="et-line-a" x1="485" y1="8" x2="493" y2="8"></line>
          <text class="et-legend" x="498" y="11">A</text>
          <line class="et-line-score" x1="520" y1="8" x2="528" y2="8"></line>
          <text class="et-legend" x="533" y="11">score</text>
        </g>
      </svg>
    `;
    this._lineV = this.querySelector('#et-line-v');
    this._lineA = this.querySelector('#et-line-a');
    this._lineScore = this.querySelector('#et-line-score');
    this._markers = this.querySelector('#et-markers');
  }

  /**
   * WS /ws/v1/engaging payload 받아서 SVG 갱신.
   * payload = {emotion: {trajectory: [{t, v, a, conf}]}, engagement: {score_history: [{ts, score}], rapport_markers: [{ts, type, weight}]}}
   */
  render(payload) {
    if (!payload || !this._lineV) return;

    const traj = (payload.emotion && payload.emotion.trajectory) || [];
    const scoreHistory = (payload.engagement && payload.engagement.score_history) || [];
    const markers = (payload.engagement && payload.engagement.rapport_markers) || [];

    // 시간 기준 — 가장 최근 ts 가 right edge, 60s 전이 left edge
    let now = 0;
    if (traj.length) now = traj[traj.length - 1].t;
    else if (scoreHistory.length) now = scoreHistory[scoreHistory.length - 1].ts;

    if (!now) {
      this._clear();
      return;
    }
    const start = now - 60.0;

    const tx = (ts) => Math.max(0, Math.min(600, ((ts - start) / 60.0) * 600));
    const ty = (val) => 100 - Math.max(-1, Math.min(1, val)) * 100;

    this._lineV.setAttribute('points',
      traj
        .filter(p => p.t >= start)
        .map(p => `${tx(p.t).toFixed(1)},${ty(p.v).toFixed(1)}`)
        .join(' '));
    this._lineA.setAttribute('points',
      traj
        .filter(p => p.t >= start)
        .map(p => `${tx(p.t).toFixed(1)},${ty(p.a).toFixed(1)}`)
        .join(' '));
    this._lineScore.setAttribute('points',
      scoreHistory
        .filter(p => p.ts >= start)
        .map(p => `${tx(p.ts).toFixed(1)},${ty(p.score).toFixed(1)}`)
        .join(' '));

    const cls = {
      engagement_up: 'et-marker-up',
      engagement_down: 'et-marker-down',
      abort_trigger: 'et-marker-abort',
    };
    this._markers.innerHTML = markers
      .filter(m => m.ts >= start)
      .map(m => `<circle class="${cls[m.type] || ''}" cx="${tx(m.ts).toFixed(1)}" cy="${ty(m.weight).toFixed(1)}" r="3"></circle>`)
      .join('');
  }

  _clear() {
    if (!this._lineV) return;
    this._lineV.setAttribute('points', '');
    this._lineA.setAttribute('points', '');
    this._lineScore.setAttribute('points', '');
    this._markers.innerHTML = '';
  }
}

customElements.define('engagement-timeline', EngagementTimeline);
```

- [ ] **Step 2: Build + serve check**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
'
ls -la install/moca_opserver/share/moca_opserver/static/components/engagement-timeline.js
head -5 install/moca_opserver/share/moca_opserver/static/components/engagement-timeline.js
```

Expected: symlink 존재 + 첫 줄 "/* engagement-timeline.js — Track C 시계열 그래프 web component".

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/static/components/engagement-timeline.js
git commit -m "feat(track-c): engagement-timeline web component (Task 4)

native SVG, V/A/score 3 polyline + rapport markers. viewBox 0 0 600 220.
render(payload) public method.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: engaging-analytics.js + modes.html + components.css

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/static/js/engaging-analytics.js`
- Modify: `src/controller/doby_controller/src/moca_opserver/static/pages/modes.html`
- Modify: `src/controller/doby_controller/src/moca_opserver/static/css/components.css`

- [ ] **Step 1: engaging-analytics.js WS onmessage 핸들러에 timeline.render 호출**

`engaging-analytics.js` 의 `this.ws.onmessage = (e) => {` 블록 안 `renderMinigame(j.minigame);` 라인 직후에 추가:

```javascript
        // 2026-05-21 Track C — engagement-timeline 갱신
        const tl = document.querySelector('engagement-timeline');
        if (tl && typeof tl.render === 'function') tl.render(j);
```

- [ ] **Step 2: modes.html 에 custom element + script + cache bust**

modes.html 의 engaging-analytics 섹션 안 — 기존 `<h4 class="card__subtitle">미니게임 결과</h4>` 라인 **직전** 에 추가:

```html
          <h4 class="card__subtitle">시계열 추이 (최근 1분)</h4>
          <engagement-timeline id="ea-timeline"></engagement-timeline>

```

modes.html 의 `<script>` 영역 — 기존 `<script src="/static/js/engaging-analytics.js?v=20260521a"></script>` 라인 **직전** 에 추가:

```html
  <script src="/static/components/engagement-timeline.js?v=20260521b"></script>
```

cache bust — engaging-analytics.js 의 `?v=20260521a` → `?v=20260521b` 갱신:

```bash
sed -i 's|engaging-analytics.js?v=20260521a|engaging-analytics.js?v=20260521b|g' \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/modes.html
```

components.css 도 cache bust (UI 변경):
```bash
sed -i 's|components.css?v=20260521a|components.css?v=20260521b|g' \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/modes.html \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/debug.html
```

- [ ] **Step 3: components.css 끝에 .engagement-timeline 스타일 추가**

`components.css` 의 `.ea-customer-label.unknown { color: var(--text-muted); }` 다음 (Track B 산물 끝) 에 추가:

```css

/* engagement-timeline web component */
engagement-timeline {
  display: block;
  width: 100%;
  max-width: 720px;
  margin: var(--space-3) auto 0;
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

- [ ] **Step 4: Build + serve check**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
'
grep "engagement-timeline" install/moca_opserver/share/moca_opserver/static/pages/modes.html | head -3
grep "engagement-timeline" install/moca_opserver/share/moca_opserver/static/css/components.css | head -3
grep "tl.render" install/moca_opserver/share/moca_opserver/static/js/engaging-analytics.js | head -2
```

Expected: 세 grep 모두 매칭 라인 있음.

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/static/js/engaging-analytics.js \
        src/controller/doby_controller/src/moca_opserver/static/pages/modes.html \
        src/controller/doby_controller/src/moca_opserver/static/pages/debug.html \
        src/controller/doby_controller/src/moca_opserver/static/css/components.css
git commit -m "feat(track-c): engaging-analytics.js timeline.render + modes.html + CSS (Task 5)

WS onmessage 핸들러에 engagement-timeline.render(j) 호출. modes.html 의
engaging-analytics 섹션 안 미니게임 직전에 <engagement-timeline> 추가.
components.css 의 PinkLAB 토큰 적용 (V=pink-soft / A=cyan-accent / score=success).
cache bust v=20260521b (3 파일 동기).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 회귀 카탈로그

**Files:**
- Create: `src/controller/doby_controller/tests/regression/perception/engagement_timeline_smoke.md`
- Modify: `src/controller/doby_controller/tests/regression/catalog.yaml`

- [ ] **Step 1: smoke .md 신규**

`src/controller/doby_controller/tests/regression/perception/engagement_timeline_smoke.md` 신규:

````markdown
---
id: engagement_timeline_smoke
category: perception
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: moca_opserver
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
opserver 의 engagement_score EMA 가 RapportEvent.weight 누적 + track_id 변경 시
cold start + WS payload 에 'engagement' 필드 정상 전파 확인.

spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 launch moca_opserver opserver.launch.py &
OPS_PID=$!
sleep 3
```

# 단계

1. **opserver 준비**
   Run: `curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8800/api/v1/health`
   Expect: `200`

2. **engagement.score = 0 (초기, RapportEvent 없음)**
   Run:
   ```bash
   python3 -c "
   import asyncio, json
   import websockets
   async def main():
       async with websockets.connect('ws://localhost:8800/ws/v1/engaging') as ws:
           raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
           d = json.loads(raw)
           print('score:', d['engagement']['score'])
           print('score_history:', len(d['engagement']['score_history']))
           print('rapport_markers:', len(d['engagement']['rapport_markers']))
   asyncio.run(main())
   "
   ```
   Expect: `score: 0.0` + `score_history: 0` + `rapport_markers: 0`.

3. **RapportEvent 시퀀스 publish — engagement_up × 5 + abort_trigger × 1**
   ```bash
   for i in 1 2 3 4 5; do
     ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
       "{header: {frame_id: \"\"}, event_type: \"engagement_up\", weight: 0.5, reason: \"test\", emotion: {valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
     sleep 0.1
   done
   sleep 0.3
   ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
     "{header: {frame_id: \"\"}, event_type: \"abort_trigger\", weight: -1.0, reason: \"test\", emotion: {valence: -0.7, arousal: 0.6, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
   sleep 0.5
   ```
   WS 재확인:
   ```bash
   python3 -c "
   import asyncio, json
   import websockets
   async def main():
       async with websockets.connect('ws://localhost:8800/ws/v1/engaging') as ws:
           raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
           d = json.loads(raw)
           print('score:', d['engagement']['score'])
           print('score_history:', len(d['engagement']['score_history']))
           print('rapport_markers:', len(d['engagement']['rapport_markers']))
           print('marker types:', [m['type'] for m in d['engagement']['rapport_markers']])
   asyncio.run(main())
   "
   ```
   Expect: `score` ≈ -0.05 ~ 0.1 (EMA α=0.1 + abort_trigger weight 영향) + `score_history: 6` + `rapport_markers: 6` + `marker types: [engagement_up × 5, abort_trigger × 1]`.

4. **track_id 변경 (42 → 99) → score cold start**
   ```bash
   ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
     "{header: {frame_id: \"\"}, event_type: \"engagement_up\", weight: 0.5, reason: \"test\", emotion: {valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 99, group_id: 1}}"
   sleep 0.5
   grep "engagement_score cold start" /tmp/track*opserver*.log 2>&1 | tail -2 || echo "log path unknown — opserver stdout 확인"
   ```
   Expect: opserver stdout 에 `engagement_score cold start: track_id 42 → 99` 로그.

5. **노드 alive**
   Run: `kill -0 $OPS_PID`
   Expect: exit 0

# 기대 결과
- engagement_snapshot 의 3 필드 (score / score_history / rapport_markers) 정상 노출
- engagement_up/abort_trigger marker 만 누적 (neutral_continue 제외)
- track_id 변경 시 cold start 로그
- opserver alive

# 클린업
```bash
kill $OPS_PID 2>/dev/null
wait $OPS_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once discovery race — sleep 적용
- track_id=0 vs -1 구분 주의 (msg 기본값 0 일 수도 — 실제 publish 시 -1 명시)
````

- [ ] **Step 2: catalog.yaml 항목 추가**

`tests/regression/catalog.yaml` 마지막 test 항목 (`track_id_integration_smoke`) **직후** 에 추가:

```yaml
- id: engagement_timeline_smoke
  category: perception
  file: perception/engagement_timeline_smoke.md
  depth: smoke
  tags:
  - engagement_timeline
  - opserver
  - ws_payload
  - perception
  duration_estimate_sec: 25
  requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: moca_opserver
  policy:
    blocks: []
  added: '2026-05-21'
  last_status: null
  last_run: null
```

- [ ] **Step 3: YAML parse 검증**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
python3 -c "
import yaml
d = yaml.safe_load(open('tests/regression/catalog.yaml'))
ids = [t['id'] for t in d['tests']]
assert 'engagement_timeline_smoke' in ids
print(f'catalog OK, total: {len(ids)}')
"
```

Expected: `catalog OK, total: 9` (or higher).

- [ ] **Step 4: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/tests/regression/perception/engagement_timeline_smoke.md \
        src/controller/doby_controller/tests/regression/catalog.yaml
git commit -m "test(track-c): regression smoke + catalog entry (Task 6)

5 단계 smoke — engagement.score 초기 0, RapportEvent 시퀀스 publish 후 score
변화, track_id 42→99 변경 시 cold start, marker filter. 회귀 시스템 v1
검증 단계라 본 항목 등록만 (spec 승인으로 commit OK).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 라이브 검증 + 회고

**Files:**
- Create: `src/controller/doby_controller/docs/daily/2026-05-21_engagement_timeline.md` (또는 작업 당일 날짜)

- [ ] **Step 1: 이전 process cleanup**

```bash
pgrep -f "lib/moca_opserver/opserver_node" | xargs -r kill 2>/dev/null
pgrep -f "lib/dobi_npc_emotion/rapport_tracker" | xargs -r kill 2>/dev/null
sleep 1.5
ss -tlnp 2>/dev/null | grep ":8800" && echo "WARN: 8800 still listening" || echo "8800 free"
```

Expected: `8800 free`.

- [ ] **Step 2: opserver 만 spawn (rapport_tracker 는 본 검증 X — 직접 RapportEvent publish)**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec ros2 launch moca_opserver opserver.launch.py
' > /tmp/track_c_test_opserver.log 2>&1 &
sleep 3
curl -sS -o /dev/null -w "opserver health: HTTP %{http_code}\n" http://localhost:8800/api/v1/health
```

Expected: `HTTP 200`.

- [ ] **Step 3: RapportEvent 시퀀스 publish + WS 확인**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

# engagement_up × 10 (Customer #42)
for i in $(seq 1 10); do
  ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
    "{header: {frame_id: \"\"}, event_type: \"engagement_up\", weight: 0.5, reason: \"test\", emotion: {valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
  sleep 0.1
done

# abort_trigger × 1
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{header: {frame_id: \"\"}, event_type: \"abort_trigger\", weight: -1.0, reason: \"test\", emotion: {valence: -0.7, arousal: 0.6, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
sleep 0.5

# 손님 전환 — Customer #99
for i in $(seq 1 5); do
  ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
    "{header: {frame_id: \"\"}, event_type: \"engagement_down\", weight: -0.5, reason: \"test\", emotion: {valence: -0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 99, group_id: 1}}"
  sleep 0.1
done
sleep 0.5
'

echo "=== opserver 로그 (cold start 확인) ==="
grep -E "engagement_score cold start" /tmp/track_c_test_opserver.log | tail -5

echo "=== WS engagement 확인 ==="
python3 -c "
import asyncio, json
import websockets
async def main():
    async with websockets.connect('ws://localhost:8800/ws/v1/engaging') as ws:
        for i in range(2):
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            d = json.loads(raw)
            e = d['engagement']
            print(f'--- msg {i+1} ---')
            print(f'  score: {e[\"score\"]}')
            print(f'  score_history len: {len(e[\"score_history\"])}')
            print(f'  rapport_markers: {[(m[\"type\"], m[\"weight\"]) for m in e[\"rapport_markers\"][-5:]]}')
asyncio.run(main())
"
```

Expected:
- opserver 로그에 `engagement_score cold start: track_id 42 → 99` 1건
- WS engagement.score 변화 (10 up → 약 +0.32 → 1 abort 후 약 +0.17 → 99 전환 cold start → 5 down 후 약 -0.20)
- score_history len ≈ 16 (전체 시퀀스)
- rapport_markers 의 type 분포 (engagement_up, abort_trigger, engagement_down)

- [ ] **Step 4: Cleanup**

```bash
pgrep -f "lib/moca_opserver/opserver_node" | xargs -r kill 2>/dev/null
sleep 1.5
ss -tlnp 2>/dev/null | grep ":8800" && echo "WARN: still listening" || echo "8800 free"
```

Expected: `8800 free`.

- [ ] **Step 5: Write 회고**

오늘 날짜 `date +%Y-%m-%d` 로 확인. 파일: `src/controller/doby_controller/docs/daily/YYYY-MM-DD_engagement_timeline.md`

```markdown
# YYYY-MM-DD — Track C: engagement-timeline 시계열 그래프

> branch: feat/engaging-analytics-migration (또는 별 feat/engagement-timeline)
> spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md (4b0bac9)
> plan: docs/superpowers/plans/2026-05-21-engagement-timeline.md

## 1. 작업 요약

modes.html engaging-analytics 안에 `<engagement-timeline>` web component 도입.
V / A / engagement_score 3 라인 + rapport event 마커 시계열 (최근 1분).
opserver 가 RapportEvent.weight 의 EMA (α=0.1) 로 engagement_score 단일 source.

7 task TDD — subagent-driven-development:
- T1 opserver helpers (compute_ema / should_reset / is_marker_eligible) + 8 unit tests
- T2 opserver __init__ + _on_rapport EMA + history
- T3 engagement_snapshot + WS payload
- T4 engagement-timeline web component (native SVG)
- T5 engaging-analytics.js + modes.html + components.css
- T6 회귀 카탈로그
- T7 라이브 검증 + 본 회고

## 2. 변경 사항

- `opserver_node.py`:
  - module-level 3 helpers (pure logic, ROS 의존 X)
  - `__init__`: `_emotion_history` maxlen 60→600, 신규 4 멤버 (score / score_history / marker_history / last_score_track_id), 새 파라미터 `engagement_score_alpha`
  - `_on_rapport` 콜백: should_reset → compute_ema → score_history append + is_marker_eligible filter → marker_history append
  - 신규 `engagement_snapshot()` 메서드
- `rest_api.py`: ws_engaging payload 의 `engagement` 필드 추가
- 신규 `static/components/engagement-timeline.js`: native SVG, viewBox 0 0 600 220, V/A/score polyline + markers
- `engaging-analytics.js`: WS onmessage 핸들러에 `tl.render(j)` 호출
- `modes.html`: engagement-timeline custom element + script + cache bust ?v=20260521b
- `components.css`: .engagement-timeline 스타일 (PinkLAB 토큰)
- 신규 unit tests 8 cases + 회귀 smoke 1

## 3. 검증

### 3.1 단위 테스트
- 8 cases PASS (3 EMA + 4 reset + 1 marker filter)

### 3.2 라이브 검증 (DOMAIN=99 sim)
- opserver spawn ✓
- engagement_up × 10 publish → score 약 +0.32 (EMA α=0.1 수렴)
- abort_trigger × 1 publish → score 약 +0.17 (-1.0 영향 반영)
- track_id 42→99 publish → opserver 로그 `engagement_score cold start: track_id 42 → 99` 1건
- engagement_down × 5 publish → score 약 -0.20
- WS engagement.score_history 길이 ≈ 16, rapport_markers 의 type 분포 정상

(실측 출력 발췌는 Step 3 의 실제 결과 첨부)

### 3.3 코드 리뷰
- T1-T6 모두 ✅ Approved

## 4. §0-B / §0-A 정합

opserver_node.py + rest_api.py + static. vic_pinky / RPi / dobi_npc_msgs /
rapport_tracker 모두 touch 0. 신규 ROS topic 0.

## 5. 후속 (Phase, 본 trake 범위 밖)

- tunable α — 라이브 환경 (카페 손님 평균 머무는 시간) 맞춤
- dynamic Y range — 자동 zoom (score ±0.3 범위면 Y 축 축소)
- 다중 손님 비교 — track_id 별 multi-line
- BT rapport_delta input — EmotionMonitor 의 신규 출력 포트
- 차트 zoom/pan, marker hover tooltip
```

라이브 검증 결과 (Step 3 의 실제 출력) 을 회고 §3.2 의 "실측 출력 발췌" 부분에 첨부.

- [ ] **Step 6: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
DAILY_FILE=$(ls src/controller/doby_controller/docs/daily/*engagement_timeline.md | tail -1)
git add "$DAILY_FILE"
git commit -m "docs(track-c): live verification 회고 (Task 7)

7 task TDD 완료 — engagement-timeline 시계열 그래프. DOMAIN=99 sim 격리 검증:
opserver EMA score 시퀀스, track_id cold start, WS payload engagement 필드.

후속 (Phase): tunable α, dynamic Y, 다중 손님, BT rapport_delta input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist

### Spec coverage
- §3 Architecture (data flow): opserver EMA → WS payload → web component → engaging-analytics 위임 — Task 1-5 ✓
- §4 opserver_node.py 변경 — Task 1 (helpers) + Task 2 (__init__ + _on_rapport) + Task 3 (snapshot) ✓
- §5 WS payload 형태 — Task 3 ✓
- §6 engagement-timeline web component — Task 4 ✓
- §7 engaging-analytics.js 통합 — Task 5 ✓
- §8 modes.html 통합 — Task 5 ✓
- §9 components.css — Task 5 ✓
- §10 Edge cases — Task 1 unit tests (cold start / unknown / same) + Task 4 web component _clear + 회고
- §11 Testing — Task 1 (8 unit) + Task 6 (회귀) + Task 7 (라이브) ✓
- §12 §0-B/§0-A 정합 — 회고 §4 ✓
- §13 Track D 연계 — 회고 §5 ✓

### Placeholder scan
- TBD / TODO / FIXME / "fill in" 없음 ✓
- 모든 step 에 구체적 code / command / expected output ✓
- "Similar to Task N" 참조 0 ✓

### Type/signature consistency
- `compute_engagement_ema(prev: float, weight: float, alpha: float) -> float` — Task 1 정의 + Task 2 호출 일관 ✓
- `should_reset_engagement_score(last: int, current: int) -> bool` — Task 1 정의 + Task 2 호출 일관 ✓
- `is_marker_eligible(event_type: str) -> bool` — Task 1 정의 + Task 2 호출 일관 ✓
- `engagement_snapshot() -> dict` ({score, score_history, rapport_markers}) — Task 3 정의 + Task 3 호출 + Task 4 payload 사용 일관 ✓
- WS payload `engagement.score / score_history / rapport_markers` — spec §5 + Task 3 + Task 4 일관 ✓
- 새 파라미터 `engagement_score_alpha` (default 0.1) — Task 2 + spec §4 일관 ✓

---

## Execution Notes

총 7 task, 추정 시간 45-60분. 각 task 별 commit.

Task 1 — helpers + 8 tests (TDD, 5-7분)
Task 2 — opserver 통합 (Read 후 정확 매칭, 7-10분)
Task 3 — snapshot + WS payload (3-5분)
Task 4 — web component (10-15분)
Task 5 — engaging-analytics.js + HTML + CSS (10-15분)
Task 6 — 회귀 카탈로그 (5-7분)
Task 7 — 라이브 검증 + 회고 (10-15분)

후속 작업 (Phase) 은 별 brainstorm → spec → plan 사이클.
