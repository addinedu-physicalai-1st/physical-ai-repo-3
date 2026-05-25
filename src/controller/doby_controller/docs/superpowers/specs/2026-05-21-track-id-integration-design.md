# 2026-05-21 — Track B: 대상자 ID (track_id + group_id) 통합

> branch: `feat/track-id-integration` (별 cut, base = `feat/engaging-analytics-migration` merge 후 main)
> 작성: 2026-05-21 (brainstorm 완료 후 spec 단계)
> 본 spec 의 SoT — implementation plan 은 writing-plans skill 호출 시 생성
> 관련: [[2026-05-20-rapport-averaging-window-design]] §10 Track B

---

## 1. 한 줄 정의

`person_tracking_node` 의 BoT-SORT `track_id` + DBSCAN `group_id` 를 GEVA 의
`/emotion/state` 까지 전파 → 모객 BT 가 분석 중인 손님 식별. rapport_tracker EMA
state 가 손님 전환 시 cold start (V·A 누적이 다음 손님으로 새지 않음). UI 에
"🎯 Customer #N · Group #M" 라벨 표시 → 운영자가 어떤 손님 데이터인지 즉시 파악.

Track D MySQL audit log 의 `customer_track` 테이블 PK 가 본 `track_id` — 자연 연계.

## 2. 사용자 확정 결정 (brainstorm 산물)

| # | 결정 | 채택 |
|---|---|---|
| D1 | 범위 | **closest 단일 손님** (현재 BT IdleScan top track_id 패턴 정합). 멀티 동시 분석은 Phase 5 후속 |
| D2 | 전파 경로 | **EmotionState.msg 에 track_id + group_id 필드 추가** (single source of truth, 모든 downstream 자연 전파) |
| D3 | GEVA 매칭 | **Single face = closest 가정** (mediapipe single face = closest customer 신뢰. ROI crop 안 함) |
| D4 | group_id | **EmotionState 에 함께 추가** (Track D MySQL 정합, 일행 읽명 분석 대비) |
| D5 (도출) | track_id=-1 (unknown) 처리 | rapport_tracker EMA cold start 안 함 (person_tracking 미가동 fallback) |

## 3. Architecture & data flow

```
카메라 1 (노트북 내장, webcam_master 마스터) → /webcam/image_raw
  ├─→ person_tracking_node (YOLOv8 + BoT-SORT + DBSCAN, 변경 X)
  │     → /person_tracking/tracks (PersonTrackArray)
  │       tracks: [PersonTrack{track_id, group_id, bbox, confidence}, ...]
  │
  └─→ geva_node (변경)
        ├─ /person_tracking/tracks 구독 (신규)
        ├─ closest track 선택 (bbox area 가장 큰)
        ├─ stale guard (0.5s 초과 → -1 reset)
        ├─ mediapipe single face 분석 (기존 — single = closest 가정)
        └─ EmotionState 발행 (NEW: track_id + group_id 채움)

→ /emotion/state (EmotionState — track_id/group_id 필드 신규)
   │
   └─→ rapport_tracker_node (변경)
        ├─ msg.track_id ≠ last_track_id ∧ ≠ -1 → EMA cold start
        ├─ 기존 EMA update + smoothed 분류 (변경 X)
        └─ RapportEvent.emotion 에 track_id/group_id 자연 전파

→ /rapport/event (RapportEvent.emotion = EmotionState — 자연 전파)
   │
   └─→ opserver._emotion_state / _rapport_events 캐시
        └─ WS /ws/v1/engaging payload emotion.latest 에 track_id/group_id 포함

→ engaging-analytics.js (변경)
   └─ UI 헤더 "🎯 Customer #N · Group #M" 또는 "— 손님 인식 X"
```

**핵심 원칙**:
- 카메라 1 공유 (webcam_master) 라 GEVA + person_tracking 가 같은 frame source → 매칭 자연.
- BT IdleScan 의 `customer_id` (blackboard) 와 GEVA closest 가 둘 다 "가장 큰 bbox" 기준 → 자연 일치 (1-frame race 가능, BT stable 5-frame 으로 흡수).
- track_id 는 EmotionState 부터 시작해 RapportEvent / opserver / WS / UI / (향후) MySQL 까지 single source of truth.

## 4. EmotionState.msg 변경

```diff
 std_msgs/Header header

 # Russell 차원 모델
 float32 valence       # -1.0 (unpleasant) ~ +1.0 (pleasant)
 float32 arousal       # -1.0 (calm) ~ +1.0 (active)

 # Salichs 신뢰도
 float32 confidence    # 0.0 ~ 1.0

 # 출처 식별
 string source         # "face" | "voice" | "fused"

 # 융합 시 발생한 신호
 string[] flags        # 예: ["mask_smile", "voice_only", "agree", "conflict"]
+
+# 2026-05-21 Track B — 손님 식별 (PersonTrack 의 closest)
+int32 track_id        # BoT-SORT 추적 ID. -1 = unknown (person_tracking 미가동 / no track / stale)
+int32 group_id        # DBSCAN 그룹 ID. -1 = solo / 미할당
```

**backward compat**: 필드 추가만 — 기존 subscriber 가 새 필드 무시. msg API 호환 (rebuild 필요).

## 5. geva_node 변경

### 5.1 신규 import + 멤버

```python
from dobi_npc_msgs.msg import EmotionState, PersonTrackArray

class GevaNode(Node):
    def __init__(self):
        # ... 기존 ...
        self.declare_parameter('tracks_topic', '/person_tracking/tracks')
        self.declare_parameter('tracks_stale_timeout_sec', 0.5)
        tracks_topic = self.get_parameter('tracks_topic').value
        self._tracks_stale_timeout = float(
            self.get_parameter('tracks_stale_timeout_sec').value)

        self._sub_tracks = self.create_subscription(
            PersonTrackArray, tracks_topic, self._cb_tracks, 10)

        # closest track 캐시
        self._closest_track_id: int = -1
        self._closest_group_id: int = -1
        self._last_tracks_ts: float = 0.0
```

### 5.2 `_cb_tracks` 콜백

```python
def _cb_tracks(self, msg: PersonTrackArray):
    if not msg.tracks:
        self._closest_track_id = -1
        self._closest_group_id = -1
        # _last_tracks_ts 는 갱신 — "empty 메시지 받음" 도 alive 신호
        self._last_tracks_ts = time.time()
        return
    # bbox area 가장 큰 track 선택 (BT IdleScan 패턴 정합)
    def _area(t):
        b = t.bbox
        return max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))
    top = max(msg.tracks, key=_area)
    self._closest_track_id = int(top.track_id)
    self._closest_group_id = int(top.group_id)
    self._last_tracks_ts = time.time()
```

### 5.3 `_tick` 의 EmotionState publish 시 채움

```python
def _tick(self):
    # ... 기존 mediapipe 처리 + V/A 계산 ...
    msg = EmotionState()
    msg.header.stamp = self.get_clock().now().to_msg()
    # ... 기존 valence/arousal/confidence/source/flags 채움 ...

    # 2026-05-21 Track B — track_id/group_id (stale guard 포함)
    if time.time() - self._last_tracks_ts > self._tracks_stale_timeout:
        msg.track_id = -1
        msg.group_id = -1
    else:
        msg.track_id = self._closest_track_id
        msg.group_id = self._closest_group_id

    self.pub.publish(msg)
```

### 5.4 새 파라미터

| 이름 | 기본 | 의미 |
|---|---|---|
| `tracks_topic` | `/person_tracking/tracks` | PersonTrackArray 입력 토픽 |
| `tracks_stale_timeout_sec` | `0.5` | 이 시간 동안 tracks 미수신 시 track_id=-1 reset (idle_scan 정합) |

## 6. rapport_tracker_node 변경

### 6.1 신규 멤버

```python
class RapportTrackerNode(Node):
    def __init__(self):
        # ... 기존 ...
        self._last_track_id: int = -1   # 손님 전환 감지용
```

### 6.2 `_on_emotion` 안 track_id 변경 감지

```python
def _on_emotion(self, msg: EmotionState):
    event = RapportEvent()
    event.header.stamp = self.get_clock().now().to_msg()
    event.header.frame_id = msg.header.frame_id
    event.emotion = msg   # raw — track_id/group_id 자연 복사

    # 2026-05-21 Track B — 손님 전환 감지 → EMA cold start
    # track_id=-1 (unknown) 인 frame 은 cold start 안 함 (fallback)
    if msg.track_id != self._last_track_id and msg.track_id != -1:
        if self._last_track_id != -1:
            # 새 손님 등장 (-1 → valid 또는 valid → 다른 valid)
            self.get_logger().info(
                f"customer 전환: track_id {self._last_track_id} → {msg.track_id} "
                f"(EMA cold start)")
        self._ema = EMAState()   # cold start (v_smooth/a_smooth = None)
        self._last_track_id = msg.track_id

    # ... 기존 no_signal / EMA update / 분류 / streak (변경 X) ...
```

**왜 track_id=-1 일 때 cold start 안 함**: person_tracking 미가동 환경 (개발 노트북 단독) 에서도 GEVA single face fallback 으로 정상 작동. EMA 누적이 끊기지 않음.

**EMA reset 자주 발생 위험** (BoT-SORT lost + 재잡힘 시 track_id 가 새로 부여) — Phase 후속에서 tunable threshold (예: 같은 track_id 가 N frame 안에 다시 들어오면 reset 안 함) 검토. 본 spec 은 단순 정책.

## 7. opserver 변경

### 7.1 `_on_emotion_state` 콜백 — track_id/group_id 캐시

```python
def _on_emotion_state(self, msg: EmotionState):
    rec = {
        'v': float(msg.valence),
        'a': float(msg.arousal),
        'conf': float(msg.confidence),
        'source': msg.source,
        'flags': list(msg.flags),
        'track_id': int(msg.track_id),     # NEW
        'group_id': int(msg.group_id),     # NEW
        'ts': time.time(),
    }
    self._emotion_state = rec
    self._emotion_history.append(
        (rec['ts'], rec['v'], rec['a'], rec['conf'], rec['source']))
```

### 7.2 `_on_rapport` 콜백 — rec 에 track_id/group_id 포함

```python
def _on_rapport(self, msg: RapportEvent):
    rec = {
        'type': msg.event_type,
        'weight': float(msg.weight),
        'v': float(msg.emotion.valence),
        'a': float(msg.emotion.arousal),
        'conf': float(msg.emotion.confidence),
        'reason': msg.reason,
        'track_id': int(msg.emotion.track_id),    # NEW
        'group_id': int(msg.emotion.group_id),    # NEW
        'ts': time.time(),
    }
    # ... 기존 deque append + counter (변경 X) ...
```

### 7.3 snapshot 메서드 — track_id/group_id 노출

`emotion_snapshot()` 의 `latest` dict 가 자동으로 track_id/group_id 포함 (rec 그대로). `rapport_snapshot()` 의 recent dict 도 자연 포함.

WS `/ws/v1/engaging` payload 의 `emotion.latest` 와 `rapport.recent[i]` 에 track_id/group_id 자동 노출.

## 8. engaging-analytics.js UI 변경

### 8.1 HTML 헤더 — Customer 라벨

modes.html 의 engaging-analytics 섹션 h3:

```html
<h3>모객 분석 (V·A · rapport · minigame)
  <span class="muted" id="ea-source">—</span>
  <span class="ea-customer-label" id="ea-customer">— 손님 대기 중</span></h3>
```

CSS `.ea-customer-label` (components.css):

```css
.ea-customer-label {
  margin-left: var(--space-3);
  padding: 2px var(--space-2);
  font-size: var(--fs-sm);
  background: var(--bg-tertiary);
  border-radius: var(--radius-sm);
  color: var(--pink-soft);
  font-family: var(--font-mono);
}
.ea-customer-label.unknown {
  color: var(--text-muted);
}
```

### 8.2 JS — renderCustomerLabel

`renderEmotion(emo)` 안에 추가:

```js
function renderCustomerLabel(latest) {
  const el = $('ea-customer');
  if (!latest) {
    el.textContent = '— 손님 대기 중';
    el.classList.add('unknown');
    return;
  }
  const tid = latest.track_id;
  const gid = latest.group_id;
  if (tid === undefined || tid < 0) {
    el.textContent = '— 손님 인식 X';
    el.classList.add('unknown');
  } else {
    const group = (gid === undefined || gid < 0) ? 'Solo' : `Group #${gid}`;
    el.textContent = `🎯 Customer #${tid} · ${group}`;
    el.classList.remove('unknown');
  }
}

function renderEmotion(emo) {
  // ... 기존 ...
  renderCustomerLabel(emo.latest);
}
```

### 8.3 rapport recent 의 track_id 표시 (선택)

`renderRapport` 의 recent list 안 각 event 에 track_id 작게 표시:

```js
recEl.innerHTML = recent.map(r => {
  const t = new Date(r.ts * 1000).toLocaleTimeString('ko-KR');
  const w = (r.weight >= 0 ? '+' : '') + r.weight.toFixed(2);
  const tag = (r.track_id !== undefined && r.track_id >= 0)
    ? `[#${r.track_id}]` : '';
  return `<div class="${cls[r.type] || ''}">[${t}]${tag} ${r.type} `
       + `w=${w} V=${r.v.toFixed(2)} A=${r.a.toFixed(2)} `
       + `· ${r.reason || ''}</div>`;
}).join('');
```

## 9. Edge cases

| 상황 | 동작 |
|---|---|
| person_tracking 미가동 (`/person_tracking/tracks` 없음) | GEVA `_last_tracks_ts` 영구 0 → EmotionState.track_id=-1. rapport_tracker EMA cold start 안 함 (기존 single state 유지). UI "— 손님 인식 X" |
| no_face + track 있음 | EmotionState.confidence=0 (기존 no_face flag). rapport_tracker no_signal 분기 — EMA 보존. UI 라벨은 track_id 표시 OK |
| no_face + no_track | 둘 다 unknown. UI "— 손님 인식 X" |
| track_id 잦은 변경 (BoT-SORT lost + 재잡힘) | EMA cold start 자주. Phase 후속에서 tunable threshold |
| group_id = -1 (solo) | UI "Solo" 라벨 |
| BoT-SORT track_id 가 매우 큰 정수 (long session) | int32 범위 안 — 표시 OK |
| GEVA 가 mediapipe 에서 face 못 잡음 (얼굴 가려짐) | confidence=0 + no_face flag. track_id 는 person_tracking 으로 채워질 수 있음 (몸 인식). rapport_tracker no_signal 분기 |
| BT customer_id 와 GEVA closest track_id 불일치 | 가능 (1 frame race). BT 가 stable 5-frame 후 SUCCESS 라 실 운영 영향 X. UI 표시 차이 가능 — Phase 후속에서 BT customer_id 도 WS 에 노출 검토 |

## 10. Testing

### 10.1 단위 테스트 (신규)

`tests/unit/test_geva_closest_track.py` (또는 `src/dobi_npc/dobi_npc_emotion/test/`):

- `test_closest_selection_single` — tracks=[1 개] → 선택
- `test_closest_selection_multi` — tracks 3개 bbox 크기 차이 → 가장 큰 선택
- `test_closest_empty_tracks` — tracks=[] → track_id=-1
- `test_stale_guard` — tracks 못 받은 채 0.5s 경과 → track_id=-1
- `test_alive_signal_on_empty` — empty PersonTrackArray 도 _last_tracks_ts 갱신 (alive)

`src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py` (rapport ema test 와 별 파일):

- `test_rapport_ema_reset_on_track_change` — track_id 1 → 2 → EMA cold start
- `test_rapport_ema_no_reset_on_unknown_track` — track_id 5 → -1 → EMA 보존
- `test_rapport_ema_no_reset_first_valid_track` — track_id -1 → 5 (첫 valid) → EMA 보존 (cold start 안 함, 첫 valid 채택)

### 10.2 회귀 카탈로그

`tests/regression/perception/track_id_integration_smoke.md` (신규):

- person_tracking_node + geva_node + rapport_tracker_node spawn
- 카메라 1 입력 (모의 또는 라이브) → `/emotion/state` echo → track_id ≥ 0 + group_id 확인
- BoT-SORT track_id 변경 시뮬 (사람 frame out + 재입장) → rapport_tracker 로그 "customer 전환" 확인

### 10.3 라이브 검증

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging &
ros2 launch moca_opserver opserver.launch.py &
'
# 브라우저 http://localhost:8800/static/pages/modes.html
# - 모객 모드 자동 진입 → engaging-analytics 패널 show
# - 사람 입장 → UI 헤더 "🎯 Customer #N · Group #M" 표시
# - 손님 다른 사람으로 전환 → UI 라벨 변경 + rapport_tracker 로그 "customer 전환"
# - 사람 없어짐 → "— 손님 인식 X" 0.5s 후
```

## 11. §0-B / §0-A 정합

**변경 대상**:
- `src/dobi_npc/dobi_npc_msgs/msg/EmotionState.msg` (msg 필드 2개 추가)
- `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py` (+ 신규 subscriber + cache + tick 갱신)
- `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py` (+ track_id 변경 감지)
- `src/moca_opserver/moca_opserver/opserver_node.py` (+ rec 에 track_id/group_id)
- `src/moca_opserver/static/pages/modes.html` (+ ea-customer span)
- `src/moca_opserver/static/css/components.css` (+ .ea-customer-label)
- `src/moca_opserver/static/js/engaging-analytics.js` (+ renderCustomerLabel)
- 신규 unit tests + 회귀 카탈로그 + 회고

**무영향**:
- `src/shared/vic_pinky/` — touch 0
- `scripts/run_*.sh` — touch 0
- RPi `~/vicpinky_ws/` — touch 0
- 신규 ROS topic 0 (기존 토픽 의미만 확장)

## 12. Track D 와의 연계

본 spec 으로 EmotionState/RapportEvent 가 track_id/group_id 보유 → Track D 의 audit log 가 자연 활용:

| Track D 산물 | 본 spec 의 source |
|---|---|
| `BTAuditEvent.msg` 의 track_id 필드 | RapportEvent.emotion.track_id 그대로 |
| MySQL `customer_track` PK | track_id (session 시작 ~ end) |
| MySQL `audit_event.track_id` FK | 각 emotion/rapport 이벤트마다 자동 결정 |
| MySQL `customer_track.group_id` | RapportEvent.emotion.group_id |

본 spec implementation 완료 후 Track D brainstorm 진입 시 데이터 source 가 이미 준비된 상태.

## 13. 다음 세션 이어 시작 가이드

```bash
cd ~/physical-ai-repo-3
git checkout main          # feat/engaging-analytics-migration merge 후
git pull
git checkout -b feat/track-id-integration
git log --oneline -3       # base commit 확인
# writing-plans skill 호출 — 본 spec 기반 implementation plan 작성
```

## 14. 시간 기록

- 2026-05-21 brainstorm — 사용자 D1-D5 결정
- spec 작성 + commit
- 다음 단계: writing-plans skill → implementation plan → 코드 작업

## 15. 후속 (Phase 후속, 본 spec 범위 밖)

- **tunable EMA reset threshold**: BoT-SORT lost+재잡힘 race 완화. 같은 track_id 가 N frame 안에 다시 들어오면 reset 안 함 (예: 3 frame).
- **멀티 손님 동시 분석** (Phase 5): EMAState 를 dict[track_id, EMAState] 로 확장. UI 가 멀티 V/A circumplex 또는 손님 선택 dropdown.
- **BT customer_id 와 GEVA closest 명시적 sync**: BT blackboard customer_id 가 GEVA 의 PersonTrackArray closest 와 다를 때 (race) 명시적 reconcile. 운영자 디버그 UI 후속.
- **group 모객 전략**: DBSCAN group_id 가 동일한 다중 손님 인지 시 BT funnel 의 stage 분기 (예: group 모객 vs solo 모객).
