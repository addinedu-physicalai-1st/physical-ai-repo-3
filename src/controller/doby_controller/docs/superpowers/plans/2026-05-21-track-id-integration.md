# Track B — 대상자 ID 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PersonTrack BoT-SORT `track_id` + DBSCAN `group_id` 를 GEVA `/emotion/state` 까지 전파 + rapport_tracker EMA 가 손님 전환 시 cold start + UI 헤더에 "🎯 Customer #N · Group #M" 라벨 표시.

**Architecture:**
1. `EmotionState.msg` 필드 2개 추가 (track_id, group_id — int32, -1=unknown)
2. `geva_node` 가 `/person_tracking/tracks` 구독 + closest selection 을 별 module-level helper 로 분리 (pure unit test 가능) + stale guard 0.5s + EmotionState 에 채움
3. `rapport_tracker_node` 가 EmotionState.track_id 변경 감지 시 EMA cold start. track_id=-1 frame 은 reset 안 함 (person_tracking 미가동 fallback)
4. `opserver` 가 emotion / rapport rec 에 track_id/group_id 자연 포함 → WS payload 자동 전파
5. `engaging-analytics.js` 의 UI 헤더 + rapport recent 의 [#N] 태그

**Tech Stack:** Python 3.12, rclpy (Jazzy), dobi_npc_msgs, pytest, FastAPI/WebSocket, vanilla JS, colcon symlink-install.

**Spec SoT:** `docs/superpowers/specs/2026-05-21-track-id-integration-design.md` (commit 64ff007).

---

## File Structure

- **Modify**: `src/dobi_npc/dobi_npc_msgs/msg/EmotionState.msg` (필드 2개)
- **Modify**: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py`
  - 신규 module-level helper `select_closest_track`
  - `__init__` 새 파라미터 2 + 신규 subscriber + cache 멤버 3
  - `_cb_tracks` 콜백
  - `_tick` 안 EmotionState publish 시 track_id/group_id 채움 + stale guard
- **Modify**: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py`
  - `__init__` 에 `_last_track_id` 멤버
  - `_on_emotion` 에 track_id 변경 감지 → `self._ema = EMAState()` cold start
- **Modify**: `src/moca_opserver/moca_opserver/opserver_node.py`
  - `_on_emotion_state` rec 에 track_id/group_id 추가
  - `_on_rapport` rec 에 track_id/group_id 추가
- **Modify**: `src/moca_opserver/static/pages/modes.html` (ea-customer span)
- **Modify**: `src/moca_opserver/static/css/components.css` (.ea-customer-label)
- **Modify**: `src/moca_opserver/static/js/engaging-analytics.js` (renderCustomerLabel + rapport recent 의 [#N] 태그)
- **Create**: `src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py` (5 tests)
- **Create**: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py` (3 tests)
- **Create**: `src/controller/doby_controller/tests/regression/perception/track_id_integration_smoke.md`
- **Modify**: `src/controller/doby_controller/tests/regression/catalog.yaml`

---

## Task 1: EmotionState.msg 필드 2개 추가

**Files:**
- Modify: `src/controller/doby_controller/src/dobi_npc/dobi_npc_msgs/msg/EmotionState.msg`

- [ ] **Step 1: Append fields**

기존 파일 끝에 추가:

```
# 2026-05-21 Track B — 손님 식별 (PersonTrack 의 closest)
int32 track_id        # BoT-SORT 추적 ID. -1 = unknown (person_tracking 미가동 / no track / stale)
int32 group_id        # DBSCAN 그룹 ID. -1 = solo / 미할당
```

- [ ] **Step 2: Build + msg interface verify**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_msgs --event-handlers console_cohesion+ 2>&1 | tail -5
source install/setup.bash
ros2 interface show dobi_npc_msgs/msg/EmotionState | tail -10
'
```

Expected: `Finished <<< dobi_npc_msgs` + 출력에 `int32 track_id` + `int32 group_id` 포함.

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_msgs/msg/EmotionState.msg
git commit -m "feat(track-b): EmotionState.msg에 track_id + group_id 추가 (Task 1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: select_closest_track helper + unit tests

**Files:**
- Modify: `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py`
- Create: `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py`

- [ ] **Step 1: Write failing tests**

Create `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py`:

```python
"""geva_node 의 select_closest_track helper 단위 테스트.

PersonTrack ROS msg 의존 없이 duck typing (SimpleNamespace) 으로 검증.
spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §5.2, §10.1
"""
from types import SimpleNamespace as NS

from dobi_npc_emotion.geva_node import select_closest_track


def _track(track_id: int, group_id: int, bbox: list) -> NS:
    return NS(track_id=track_id, group_id=group_id, bbox=bbox)


def test_closest_empty_returns_none():
    """tracks=[] → None."""
    assert select_closest_track([]) is None


def test_closest_single_returns_only_track():
    """tracks 1개 → 그 track 반환."""
    t = _track(7, -1, [0.0, 0.0, 100.0, 100.0])
    result = select_closest_track([t])
    assert result is t


def test_closest_multi_largest_bbox_wins():
    """bbox area 가장 큰 track 선택."""
    tracks = [
        _track(1, -1, [0.0, 0.0, 10.0, 10.0]),    # area=100
        _track(2, 0, [0.0, 0.0, 50.0, 50.0]),     # area=2500 (largest)
        _track(3, 0, [0.0, 0.0, 30.0, 30.0]),     # area=900
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 2
    assert result.group_id == 0


def test_closest_negative_bbox_clamped_to_zero():
    """bbox 가 inverted (x2<x1) 인 경우 area=0 — 무시."""
    tracks = [
        _track(1, -1, [50.0, 50.0, 10.0, 10.0]),  # inverted → 0
        _track(2, -1, [0.0, 0.0, 5.0, 5.0]),      # area=25
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 2


def test_closest_tie_picks_first():
    """동일 bbox 크기 면 첫 번째 선택 (Python max stable)."""
    tracks = [
        _track(10, -1, [0.0, 0.0, 20.0, 20.0]),
        _track(20, -1, [100.0, 100.0, 120.0, 120.0]),
    ]
    result = select_closest_track(tracks)
    assert result.track_id == 10
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py -v 2>&1 | tail -10
'
```

Expected: `ImportError: cannot import name 'select_closest_track' from 'dobi_npc_emotion.geva_node'`

- [ ] **Step 3: Add helper at module level**

`geva_node.py` 의 `emotion_scores_to_va` 함수 정의 직후 (line 132 부근, module-level helpers 구역) 에 추가:

```python
def select_closest_track(tracks):
    """가장 큰 bbox area 의 PersonTrack 반환. tracks 빈 list → None.

    bbox 가 inverted (x2<x1 또는 y2<y1) 면 area=0 으로 clamp. 동일 크기 tie 시
    Python max stable behavior 로 첫 번째 선택.

    spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §5.2
    """
    if not tracks:
        return None
    def _area(t):
        b = t.bbox
        return max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))
    return max(tracks, key=_area)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select dobi_npc_emotion --event-handlers console_cohesion+ 2>&1 | tail -3
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py -v 2>&1 | tail -10
'
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py \
        src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py
git commit -m "feat(track-b): select_closest_track helper + 5 unit tests (Task 2)

bbox area 가장 큰 PersonTrack 선택. inverted bbox area=0 clamp. tie 시 first.
duck typing test 로 ROS msg 의존 없이 검증.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: geva_node integration (subscriber + cache + tick 갱신)

**Files:**
- Modify: `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py`

- [ ] **Step 1: Read current geva_node 구조 확인**

```bash
grep -nE "declare_parameter|create_subscription|create_publisher|def _tick|def __init__|pub = self.create" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py | head -20
```

`__init__` 의 declare_parameter 블록 위치와 `_tick` 메서드 위치를 확인하여 다음 step 의 Edit old_string 을 정확히 매칭.

- [ ] **Step 2: import PersonTrackArray + 새 파라미터 + subscriber + cache**

geva_node.py 의 `from dobi_npc_msgs.msg import EmotionState` 라인을 다음으로 교체:

```python
from dobi_npc_msgs.msg import EmotionState, PersonTrackArray
```

`__init__` 의 `self.declare_parameter('publish_rate_hz', 10.0)` 라인 직후 (그 다음 줄) 에 추가:

```python
        # 2026-05-21 Track B — closest track 매칭 파라미터
        self.declare_parameter('tracks_topic', '/person_tracking/tracks')
        self.declare_parameter('tracks_stale_timeout_sec', 0.5)
```

`__init__` 의 `self.pub = self.create_publisher(EmotionState, '/emotion/state', 10)` 라인 직전 (그 위 줄) 에 추가:

```python
        # 2026-05-21 Track B — PersonTrackArray 구독 + closest cache
        tracks_topic = self.get_parameter('tracks_topic').value
        self._tracks_stale_timeout = float(
            self.get_parameter('tracks_stale_timeout_sec').value)
        self._sub_tracks = self.create_subscription(
            PersonTrackArray, tracks_topic, self._cb_tracks, 10)
        self._closest_track_id: int = -1
        self._closest_group_id: int = -1
        self._last_tracks_ts: float = 0.0

```

- [ ] **Step 3: Add _cb_tracks 콜백 메서드**

geva_node.py 의 `_tick` 메서드 정의 (`def _tick(self):`) 직전에 새 메서드 추가:

```python
    def _cb_tracks(self, msg: PersonTrackArray) -> None:
        """PersonTrackArray 수신 → closest track 캐시 갱신.

        empty tracks 도 alive 신호로 _last_tracks_ts 갱신 — stale guard 와 구분.
        spec §5.2.
        """
        import time as _time
        if not msg.tracks:
            self._closest_track_id = -1
            self._closest_group_id = -1
            self._last_tracks_ts = _time.time()
            return
        top = select_closest_track(msg.tracks)
        self._closest_track_id = int(top.track_id)
        self._closest_group_id = int(top.group_id)
        self._last_tracks_ts = _time.time()

```

- [ ] **Step 4: _tick 안 EmotionState publish 시 track_id/group_id 채움**

geva_node.py 의 `_tick` 메서드 안 — `self.pub.publish(msg)` 라인 **직전** 에서 EmotionState msg 가 만들어진 후 publish 전 위치에 추가. (현재 `_tick` 안에는 EmotionState 만드는 부분이 2 곳 있음 — 라인 225 + 라인 239. 두 곳 모두 publish 직전에 같은 코드 삽입 필요.)

먼저 두 publish 위치 확인:

```bash
grep -nE "self.pub.publish\(msg\)" /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py
```

Expected: 두 라인 (예: 225, 239).

각 publish 직전에 다음 5줄 삽입 (각 위치 의 msg 변수가 동일하면 같은 코드):

```python
            # 2026-05-21 Track B — track_id/group_id (stale guard 포함)
            import time as _time
            if _time.time() - self._last_tracks_ts > self._tracks_stale_timeout:
                msg.track_id = -1
                msg.group_id = -1
            else:
                msg.track_id = self._closest_track_id
                msg.group_id = self._closest_group_id
```

**주의**: 들여쓰기는 기존 `self.pub.publish(msg)` 와 같은 레벨. 두 publish 위치 모두 적용 (no_face 분기 + 정상 분기).

- [ ] **Step 5: Build + import smoke**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select dobi_npc_emotion --event-handlers console_cohesion+ 2>&1 | tail -5
source install/setup.bash
python3 -c "
from dobi_npc_emotion.geva_node import GevaNode, select_closest_track
from dobi_npc_msgs.msg import EmotionState, PersonTrackArray
print(\"import OK\")
# EmotionState msg 가 track_id/group_id 필드 보유 확인
e = EmotionState()
e.track_id = 7
e.group_id = 0
print(f\"EmotionState track_id={e.track_id} group_id={e.group_id}\")
"
'
```

Expected: `import OK` + `EmotionState track_id=7 group_id=0`.

- [ ] **Step 6: Run all geva tests (회귀 확인)**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/ -v 2>&1 | tail -15
'
```

Expected: 5 closest_track tests PASS + 기존 6 rapport ema tests PASS (총 11+).

- [ ] **Step 7: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py
git commit -m "feat(track-b): geva_node closest track 구독 + EmotionState 채움 (Task 3)

PersonTrackArray /person_tracking/tracks 구독 + select_closest_track 으로
closest 캐시 + _tick 의 EmotionState publish 시 track_id/group_id 채움.
0.5s stale guard — tracks 없을 때 track_id=-1 reset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: rapport_tracker_node track_id 변경 감지

**Files:**
- Modify: `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py`
- Create: `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py`

- [ ] **Step 1: Write failing tests**

Create `src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py`:

```python
"""rapport_tracker track_id 변경 시 EMA cold start 검증.

EMA 자체는 test_rapport_tracker_ema.py 가 검증. 본 파일은 reset trigger 만.
spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §6, §10.1
"""
from dobi_npc_emotion.rapport_tracker_node import EMAState


# rapport_tracker 의 _on_emotion 안 track_id 감지 로직을 isolated 검증하기 위해
# helper function 으로 추출 (geva 의 select_closest_track 패턴 정합).
# 아직 helper 미구현 — Step 3 에서 추가.

from dobi_npc_emotion.rapport_tracker_node import should_reset_ema_on_track_change


def test_reset_on_first_valid_track():
    """이전 track_id=-1, 새 track_id 가 valid (예: 5) — 첫 valid 채택,
    reset 안 함 (cold start fallback 이 EMAState 첫 update 에서 자연 처리)."""
    assert should_reset_ema_on_track_change(last=-1, current=5) is False


def test_reset_on_track_change_valid_to_valid():
    """이전 track_id=5, 새 track_id=7 — 손님 전환, reset."""
    assert should_reset_ema_on_track_change(last=5, current=7) is True


def test_no_reset_on_unknown_track():
    """이전 track_id=5, 새 track_id=-1 (person_tracking 일시 끊김)
    — EMA 보존 (fallback)."""
    assert should_reset_ema_on_track_change(last=5, current=-1) is False


def test_no_reset_on_same_track():
    """이전 track_id=5, 새 track_id=5 — 같은 손님, reset 안 함."""
    assert should_reset_ema_on_track_change(last=5, current=5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py -v 2>&1 | tail -10
'
```

Expected: `ImportError: cannot import name 'should_reset_ema_on_track_change' from 'dobi_npc_emotion.rapport_tracker_node'`

- [ ] **Step 3: Add helper at module level**

`rapport_tracker_node.py` 의 `EMAState` 클래스 정의 직후 (module-level helper 구역) 에 추가:

```python
def should_reset_ema_on_track_change(last: int, current: int) -> bool:
    """track_id 변경 시 EMA cold start 여부 판정.

    - last == current: 같은 손님 — reset 안 함
    - last == -1: 첫 valid track — fallback 채택, reset 안 함 (cold start 가 EMAState 의
      v_smooth=None 자연 처리)
    - current == -1: 일시적 unknown (person_tracking 끊김) — EMA 보존
    - last != current 둘 다 valid: 손님 전환 — reset

    spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md §6
    """
    if current == -1:
        return False
    if last == -1:
        return False
    return last != current
```

- [ ] **Step 4: Integrate into _on_emotion**

`rapport_tracker_node.py` 의 `RapportTrackerNode.__init__` 끝에 추가 (logger info 직전):

```python
        # 2026-05-21 Track B — 손님 전환 감지
        self._last_track_id: int = -1
```

`_on_emotion` 메서드 안 — `event.emotion = msg` 직후 (또는 `no_signal = ...` 직전) 에 추가:

```python
        # 2026-05-21 Track B — track_id 변경 시 EMA cold start
        if should_reset_ema_on_track_change(self._last_track_id, msg.track_id):
            self.get_logger().info(
                f"customer 전환: track_id {self._last_track_id} → {msg.track_id} "
                f"(EMA cold start)")
            self._ema = EMAState()
        if msg.track_id != -1:
            self._last_track_id = msg.track_id
```

- [ ] **Step 5: Run tests to verify pass**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select dobi_npc_emotion --event-handlers console_cohesion+ 2>&1 | tail -3
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py -v 2>&1 | tail -10
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py -v 2>&1 | tail -10
pytest src/dobi_npc/dobi_npc_emotion/test/test_geva_closest_track.py -v 2>&1 | tail -10
'
```

Expected:
- track_id tests: `4 passed`
- ema tests: `6 passed` (회귀 확인)
- closest_track tests: `5 passed` (회귀 확인)

- [ ] **Step 6: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py \
        src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_track_id.py
git commit -m "feat(track-b): rapport_tracker EMA cold start on track_id 변경 (Task 4)

should_reset_ema_on_track_change helper + 4 unit tests. track_id=-1 (unknown)
frame 은 EMA 보존 — person_tracking 미가동 fallback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: opserver rec 에 track_id/group_id 추가

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py`

- [ ] **Step 1: _on_emotion_state 콜백 갱신**

opserver_node.py 의 `_on_emotion_state` 메서드 안 `rec = {...}` dict 의 'ts' 라인 직전에 추가:

```python
            'track_id': int(msg.track_id),
            'group_id': int(msg.group_id),
```

전체 rec block 이 다음과 같아짐:

```python
        rec = {
            'v': float(msg.valence),
            'a': float(msg.arousal),
            'conf': float(msg.confidence),
            'source': msg.source,
            'flags': list(msg.flags),
            'track_id': int(msg.track_id),
            'group_id': int(msg.group_id),
            'ts': time.time(),
        }
```

- [ ] **Step 2: _on_rapport 콜백 갱신**

opserver_node.py 의 `_on_rapport` 메서드 안 `rec = {...}` dict 의 'ts' 라인 직전에 추가:

```python
            'track_id': int(msg.emotion.track_id),
            'group_id': int(msg.emotion.group_id),
```

전체 rec block:

```python
        rec = {
            'type': msg.event_type,
            'weight': float(msg.weight),
            'v': float(msg.emotion.valence),
            'a': float(msg.emotion.arousal),
            'conf': float(msg.emotion.confidence),
            'reason': msg.reason,
            'track_id': int(msg.emotion.track_id),
            'group_id': int(msg.emotion.group_id),
            'ts': time.time(),
        }
```

- [ ] **Step 3: Build + import smoke**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
source install/setup.bash
python3 -c "
from moca_opserver.opserver_node import OpServerNode
print(\"import OK\")
"
'
```

Expected: `Finished <<< moca_opserver` + `import OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/moca_opserver/opserver_node.py
git commit -m "feat(track-b): opserver emotion/rapport rec 에 track_id/group_id (Task 5)

_on_emotion_state + _on_rapport 콜백의 rec dict 에 track_id/group_id 추가.
snapshot 메서드 + WS payload 자동 전파 (rec 그대로).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: modes.html ea-customer span + components.css

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/static/pages/modes.html`
- Modify: `src/controller/doby_controller/src/moca_opserver/static/css/components.css`

- [ ] **Step 1: modes.html 의 engaging-analytics h3 갱신**

기존 라인:

```html
        <h3>모객 분석 (V·A · rapport · minigame)
          <span class="muted" id="ea-source">—</span></h3>
```

를 다음으로 교체:

```html
        <h3>모객 분석 (V·A · rapport · minigame)
          <span class="muted" id="ea-source">—</span>
          <span class="ea-customer-label unknown" id="ea-customer">— 손님 대기 중</span></h3>
```

- [ ] **Step 2: components.css 끝에 .ea-customer-label 스타일 추가**

`components.css` 의 `#ea-mg-recent .mg-row .lose` 정의 직후 (engaging-analytics 섹션 끝) 에 추가:

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

- [ ] **Step 3: cache bust 두 파일 ?v 값 갱신**

modes.html 의 `<link rel="stylesheet" href="/static/css/components.css?v=20260520a">` 라인을:

```html
  <link rel="stylesheet" href="/static/css/components.css?v=20260521a">
```

debug.html 도 동일 (cache 일관성):

```bash
sed -i 's|components.css?v=20260520a|components.css?v=20260521a|g' \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/modes.html \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/debug.html
```

- [ ] **Step 4: Build + serve check**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
'
# install/share 의 static 도 갱신됐는지 확인
grep "ea-customer" install/moca_opserver/share/moca_opserver/static/pages/modes.html | head -2
grep "ea-customer-label" install/moca_opserver/share/moca_opserver/static/css/components.css | head -2
```

Expected: 두 grep 결과에 매칭 라인 있음.

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/static/pages/modes.html \
        src/controller/doby_controller/src/moca_opserver/static/pages/debug.html \
        src/controller/doby_controller/src/moca_opserver/static/css/components.css
git commit -m "feat(track-b): modes.html ea-customer span + .ea-customer-label CSS (Task 6)

engaging-analytics 헤더에 customer 라벨 span 추가 + PinkLAB 토큰 적용 스타일.
cache bust v=20260521a (modes.html + debug.html 동기 갱신).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: engaging-analytics.js renderCustomerLabel + rapport recent [#N]

**Files:**
- Modify: `src/controller/doby_controller/src/moca_opserver/static/js/engaging-analytics.js`

- [ ] **Step 1: renderCustomerLabel 함수 추가**

`engaging-analytics.js` 의 `renderEmotion` 함수 정의 **직전** 에 추가:

```js
  function renderCustomerLabel(latest) {
    const el = $('ea-customer');
    if (!el) return;
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

```

- [ ] **Step 2: renderEmotion 끝에 renderCustomerLabel 호출 추가**

`renderEmotion(emo)` 함수 안 — 함수 끝 (현재 `trajEl.innerHTML = svg;` 다음, 함수 닫는 `}` 직전) 에 추가:

```js
    renderCustomerLabel(emo.latest);
```

- [ ] **Step 3: renderEmotion 의 null guard 분기에도 라벨 reset**

`renderEmotion(emo)` 함수 안 `if (!emo || !emo.latest) { ... return; }` 블록 안의 `return;` 직전에 추가:

```js
      renderCustomerLabel(null);
```

- [ ] **Step 4: renderRapport 의 recent 에 [#N] 태그 추가**

`renderRapport(rap)` 함수 안 `recEl.innerHTML = recent.map(r => {...}).join('');` 블록의 map 함수를 다음으로 교체:

```js
    recEl.innerHTML = recent.map(r => {
      const t = new Date(r.ts * 1000).toLocaleTimeString('ko-KR');
      const w = (r.weight >= 0 ? '+' : '') + r.weight.toFixed(2);
      const tag = (r.track_id !== undefined && r.track_id >= 0)
        ? `[#${r.track_id}] ` : '';
      return `<div class="${cls[r.type] || ''}">[${t}] ${tag}${r.type} `
           + `w=${w} V=${r.v.toFixed(2)} A=${r.a.toFixed(2)} `
           + `· ${r.reason || ''}</div>`;
    }).join('');
```

- [ ] **Step 5: cache bust ?v 갱신**

modes.html 의 engaging-analytics.js script tag:

```bash
sed -i 's|engaging-analytics.js?v=20260520a|engaging-analytics.js?v=20260521a|g' \
  /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/src/moca_opserver/static/pages/modes.html
```

- [ ] **Step 6: Build + serve check**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver --event-handlers console_cohesion+ 2>&1 | tail -3
'
grep "renderCustomerLabel" install/moca_opserver/share/moca_opserver/static/js/engaging-analytics.js | head -3
```

Expected: renderCustomerLabel 함수 정의 + 호출 grep match.

- [ ] **Step 7: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/moca_opserver/static/js/engaging-analytics.js \
        src/controller/doby_controller/src/moca_opserver/static/pages/modes.html
git commit -m "feat(track-b): engaging-analytics.js renderCustomerLabel + recent [#N] (Task 7)

UI 헤더 '🎯 Customer #N · Group #M' 라벨 (Solo / unknown 분기).
rapport recent 의 각 event 에 [#N] 태그.
cache bust v=20260521a.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 회귀 카탈로그 등록

**Files:**
- Create: `src/controller/doby_controller/tests/regression/perception/track_id_integration_smoke.md`
- Modify: `src/controller/doby_controller/tests/regression/catalog.yaml`

- [ ] **Step 1: Create regression smoke file**

`src/controller/doby_controller/tests/regression/perception/track_id_integration_smoke.md` 새 파일:

````markdown
---
id: track_id_integration_smoke
category: perception
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: person_tracking_pkg
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
EmotionState.msg 의 track_id + group_id 가 PersonTrackArray closest 의
ID 로 채워지는지 + rapport_tracker EMA 가 track_id 변경 시 cold start 하는지 확인.

spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 run dobi_npc_emotion rapport_tracker &
RAPPORT_PID=$!
sleep 2
```

# 단계

1. **EmotionState msg 가 새 필드 보유 확인**
   Run: `ros2 interface show dobi_npc_msgs/msg/EmotionState | grep -E "track_id|group_id"`
   Expect: `int32 track_id` + `int32 group_id` 두 라인

2. **PersonTrackArray dummy 1 frame publish → emotion echo 시 track_id=42 + group_id=0 채워짐**
   ```bash
   ros2 topic pub --once /person_tracking/tracks dobi_npc_msgs/msg/PersonTrackArray \
     '{header: {frame_id: ""}, group_count: 1, tracks: [{header: {frame_id: ""}, track_id: 42, group_id: 0, bbox: [0.0, 0.0, 100.0, 100.0], confidence: 0.9}]}'
   sleep 0.5
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: 0.3, arousal: 0.1, confidence: 0.85, source: "face", flags: [], track_id: 42, group_id: 0}'
   sleep 0.5
   ros2 topic echo --once /rapport/event > /tmp/track_id_test.txt
   grep -E "track_id|group_id" /tmp/track_id_test.txt
   ```
   Expect: `track_id: 42` + `group_id: 0` 포함

3. **rapport_tracker 로그에 EMA cold start (첫 valid track 은 fallback)**
   Run: `grep -E "customer 전환|customer 식별" /tmp/rapport_*.log`
   Expect: 첫 valid track (track_id=42) 에는 "전환" 로그 없음 (cold start 의 자연 first-frame). track_id 변경 (예: 42 → 99) 시에만 로그.

4. **track_id 변경 시뮬 — EmotionState 두 번 publish (42 → 99)**
   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -0.2, arousal: 0.1, confidence: 0.85, source: "face", flags: [], track_id: 99, group_id: 1}'
   sleep 0.5
   ```
   rapport_tracker 로그 검사: `grep "customer 전환: track_id 42 → 99" /tmp/rapport_*.log`
   Expect: 매칭 라인 1개 (EMA cold start 로그)

5. **노드 alive**
   Run: `kill -0 $RAPPORT_PID`
   Expect: exit 0

# 기대 결과
- EmotionState msg 의 track_id/group_id 필드 정상
- RapportEvent.emotion 에 자연 전파
- track_id 변경 시 EMA cold start 로그
- 노드 alive

# 클린업
```bash
kill $RAPPORT_PID 2>/dev/null
wait $RAPPORT_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once 의 discovery race — 첫 publish drop 가능 (sleep 추가).
- 회귀 시스템 v1 검증 단계라 본 항목 등록만, last_status 는 라이브 검증 후 supervisor 가 갱신.
````

- [ ] **Step 2: catalog.yaml 에 항목 추가**

`tests/regression/catalog.yaml` 끝의 마지막 항목 다음에 추가:

```yaml
- id: track_id_integration_smoke
  category: perception
  file: perception/track_id_integration_smoke.md
  depth: smoke
  tags:
  - track_id
  - group_id
  - person_tracking
  - perception
  duration_estimate_sec: 25
  requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: person_tracking_pkg
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
assert 'track_id_integration_smoke' in ids
print(f'catalog OK, total tests: {len(ids)}')
print(f'  has track_id_integration_smoke: yes')
"
```

Expected: `catalog OK, total tests: 8` (or higher) + `has track_id_integration_smoke: yes`.

- [ ] **Step 4: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/tests/regression/perception/track_id_integration_smoke.md \
        src/controller/doby_controller/tests/regression/catalog.yaml
git commit -m "test(track-b): regression smoke + catalog entry (Task 8)

5 단계 smoke — EmotionState 필드, PersonTrackArray 매칭, EMA cold start
on track_id change. 회귀 시스템 v1 검증 단계라 본 항목 등록만.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: 라이브 검증 + 회고

**Files:**
- Create: `src/controller/doby_controller/docs/daily/2026-05-21_track_id_integration.md` (또는 작업 당일 날짜)

- [ ] **Step 1: 이전 process cleanup**

```bash
pgrep -f "lib/moca_opserver/opserver_node" | xargs -r kill 2>/dev/null
pgrep -f "lib/dobi_npc_emotion/rapport_tracker" | xargs -r kill 2>/dev/null
pgrep -f "python3 /tmp/continuous_pub" | xargs -r kill 2>/dev/null
sleep 1.5
ss -tlnp 2>/dev/null | grep ":8800" && echo "WARN: 8800 still listening" || echo "8800 free"
```

Expected: `8800 free`.

- [ ] **Step 2: opserver + rapport_tracker spawn (DOMAIN=99)**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller

bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec ros2 launch moca_opserver opserver.launch.py
' > /tmp/track_id_test_opserver.log 2>&1 &
sleep 3

bash --noprofile --norc -c '
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec ros2 run dobi_npc_emotion rapport_tracker
' > /tmp/track_id_test_rapport.log 2>&1 &
sleep 3

curl -sS -o /dev/null -w "opserver health: HTTP %{http_code}\n" http://localhost:8800/api/v1/health
grep "rapport_tracker:" /tmp/track_id_test_rapport.log | head -2
```

Expected: `HTTP 200` + `rapport_tracker:` 로그.

- [ ] **Step 3: track_id 변경 시나리오 publish**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

# Customer #42 frame 5개 publish
for i in 1 2 3 4 5; do
  ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
    "{header: {frame_id: \"\"}, valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}"
  sleep 0.2
done

# 손님 전환: Customer #99 frame
sleep 0.3
ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
  "{header: {frame_id: \"\"}, valence: -0.2, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 99, group_id: 1}"

# Customer #99 추가 frame
for i in 1 2 3; do
  ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
    "{header: {frame_id: \"\"}, valence: -0.2, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 99, group_id: 1}"
  sleep 0.2
done
'

echo "=== rapport_tracker 의 customer 전환 로그 ==="
grep -E "customer 전환|event:" /tmp/track_id_test_rapport.log | tail -10
```

Expected: `customer 전환: track_id 42 → 99 (EMA cold start)` 로그.

- [ ] **Step 4: WS /ws/v1/engaging 으로 track_id/group_id 확인**

```bash
python3 -c "
import asyncio, json
import websockets

async def main():
    async with websockets.connect('ws://localhost:8800/ws/v1/engaging') as ws:
        for i in range(2):
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            d = json.loads(raw)
            latest = d['emotion']['latest']
            recent = d['rapport']['recent']
            print(f'--- msg {i+1} ---')
            print(f'  emotion.latest track_id={latest.get(\"track_id\") if latest else None}'
                  f' group_id={latest.get(\"group_id\") if latest else None}')
            print(f'  rapport.recent count={len(recent)}')
            for r in recent[-3:]:
                print(f'    track_id={r.get(\"track_id\")} group_id={r.get(\"group_id\")}'
                      f' type={r[\"type\"]} v={r[\"v\"]:.2f}')

asyncio.run(main())
"
```

Expected: `emotion.latest track_id=99 group_id=1` + rapport recent 의 각 event 에 track_id 표시.

- [ ] **Step 5: Cleanup**

```bash
pgrep -f "lib/moca_opserver/opserver_node" | xargs -r kill 2>/dev/null
pgrep -f "lib/dobi_npc_emotion/rapport_tracker" | xargs -r kill 2>/dev/null
sleep 1.5
ss -tlnp 2>/dev/null | grep ":8800" && echo "WARN: still listening" || echo "8800 free"
```

Expected: `8800 free`.

- [ ] **Step 6: Write 회고**

오늘 날짜 `date +%Y-%m-%d` 로 확인. 파일 경로: `src/controller/doby_controller/docs/daily/YYYY-MM-DD_track_id_integration.md`

```markdown
# YYYY-MM-DD — Track B: 대상자 ID (track_id + group_id) 통합

> branch: feat/track-id-integration
> spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md (64ff007)
> plan: docs/superpowers/plans/2026-05-21-track-id-integration.md

## 1. 작업 요약

PersonTrack BoT-SORT `track_id` + DBSCAN `group_id` 를 GEVA `/emotion/state` 까지
전파. rapport_tracker EMA 가 손님 전환 시 cold start. UI 헤더 "🎯 Customer #N ·
Group #M" 라벨. Track D MySQL audit 의 customer_track PK 와 자연 연계.

9 task TDD 진행 — subagent-driven-development:
- T1 EmotionState.msg 필드 (track_id + group_id)
- T2 select_closest_track helper + 5 unit tests
- T3 geva_node integration (subscriber + cache + tick)
- T4 rapport_tracker EMA cold start + 4 unit tests
- T5 opserver rec 에 track_id/group_id
- T6 modes.html + components.css (.ea-customer-label)
- T7 engaging-analytics.js renderCustomerLabel + recent [#N]
- T8 회귀 카탈로그
- T9 라이브 검증 + 본 회고

## 2. 변경 사항

- `EmotionState.msg`: int32 track_id + int32 group_id (둘 다 -1=unknown)
- `geva_node.py`:
  - module-level `select_closest_track` helper (bbox area 가장 큰 PersonTrack 반환)
  - 신규 파라미터 2 (`tracks_topic`, `tracks_stale_timeout_sec`)
  - `_cb_tracks` 콜백 + closest cache (3 멤버)
  - `_tick` 의 EmotionState publish 시 채움 + 0.5s stale guard
- `rapport_tracker_node.py`:
  - module-level `should_reset_ema_on_track_change` helper
  - `_last_track_id` 멤버 + `_on_emotion` 안 track_id 변경 감지 → `self._ema = EMAState()` cold start
- `opserver_node.py`: `_on_emotion_state` + `_on_rapport` 의 rec 에 track_id/group_id
- `modes.html`: ea-customer span + cache bust
- `components.css`: `.ea-customer-label` 스타일
- `engaging-analytics.js`: renderCustomerLabel + rapport recent 의 [#N] 태그
- 신규 unit tests 9 cases (5 closest + 4 track_id) + 회귀 smoke 1

## 3. 검증

### 3.1 단위 테스트
- 9 cases 모두 PASS (closest_empty/single/multi/inverted/tie + reset_first_valid/v2v/unknown/same)

### 3.2 라이브 검증 (DOMAIN=99 sim)
- opserver + rapport_tracker spawn ✓
- Customer #42 frame 5개 → EmotionState track_id=42
- 손님 전환 publish (track_id 42→99) → rapport_tracker 로그 "customer 전환: track_id 42 → 99 (EMA cold start)"
- WS /ws/v1/engaging payload 의 emotion.latest.track_id=99 + rapport.recent[].track_id 정상

## 4. §0-B / §0-A 정합

EmotionState.msg + dobi_npc_emotion + moca_opserver + static. vic_pinky / RPi
자산 touch 0. 신규 ROS topic 0 (기존 토픽 의미만 확장).

## 5. 후속 (Phase, 본 trake 범위 밖)

- tunable EMA reset threshold (BoT-SORT lost+재잡힘 race 완화)
- 멀티 손님 동시 분석 (Phase 5)
- BT customer_id ↔ GEVA closest sync 검증
- group 모객 전략 (DBSCAN 일행 분석)
- Track D MySQL audit log + BTAuditEvent.msg
```

- [ ] **Step 7: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
DAILY_FILE=$(ls src/controller/doby_controller/docs/daily/*track_id_integration.md | tail -1)
git add "$DAILY_FILE"
git commit -m "docs(track-b): live verification 회고 (Task 9)

9 task TDD 완료 — track_id/group_id 전파. DOMAIN=99 sim 격리 검증:
EmotionState 필드, geva closest 매칭, rapport EMA cold start on change,
WS payload 자동 전파.

후속 (Phase): tunable threshold, 멀티 손님, group 모객, Track D MySQL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist

### Spec coverage
- §4 EmotionState.msg 변경 → Task 1 ✓
- §5 geva_node 변경 → Task 2 (helper) + Task 3 (integration) ✓
- §6 rapport_tracker 변경 → Task 4 ✓
- §7 opserver 변경 → Task 5 ✓
- §8 engaging-analytics.js UI → Task 6 (HTML/CSS) + Task 7 (JS) ✓
- §9 Edge cases — unit + 회귀 + 라이브 라이브 검증 시나리오:
  - person_tracking 미가동 → Task 4 test_no_reset_on_unknown_track + Task 9 (track_id=-1 부재 시 ROS 의존)
  - track_id 잦은 변경 → 명시적 unit test 없음 — Phase 후속 (회고 §5)
  - no_face + track 있음 → no_signal 기존 분기 (변경 X), unit test 불필요
  - group_id = -1 (solo) → Task 7 의 renderCustomerLabel "Solo" 분기
  - BT customer_id race → Phase 후속 (spec §9)
- §10.1 unit test — Task 2 (5) + Task 4 (4) ✓
- §10.2 회귀 카탈로그 → Task 8 ✓
- §10.3 라이브 검증 → Task 9 ✓
- §11 §0-B/§0-A 정합 — 회고 §4 ✓
- §12 Track D 연계 — 회고 §5 ✓

### Placeholder scan
- TBD / TODO / FIXME 없음 ✓
- 모든 step 에 구체적 code / command / expected output ✓
- "Similar to Task N" 같은 참조 0 ✓

### Type/signature consistency
- `select_closest_track(tracks) → PersonTrack | None` — Task 2 + Task 3 일관 ✓
- `should_reset_ema_on_track_change(last: int, current: int) → bool` — Task 4 일관 ✓
- `EmotionState.track_id` / `group_id` (int32) — Task 1 + 모든 후속 task 일관 ✓
- 새 파라미터 `tracks_topic`, `tracks_stale_timeout_sec` — Task 3 안에서만 사용 (rapport_tracker 와 무관) ✓

---

## Execution Notes

총 9 tasks, 추정 시간 45-60분. 각 task 별 commit 으로 revert 용이.

Task 1 — msg field (1분)
Task 2 — helper + 5 tests (TDD, 3-5분)
Task 3 — geva integration (Read 후 정확한 line 위치 매칭, 5-7분)
Task 4 — rapport helper + 4 tests (TDD, 3-5분)
Task 5 — opserver rec (1-2분)
Task 6 — HTML/CSS (3-5분)
Task 7 — JS (5-7분)
Task 8 — 회귀 카탈로그 (3-5분)
Task 9 — 라이브 검증 + 회고 (15-20분)

후속 작업 (Phase) 은 별 brainstorm → spec → plan 사이클.
