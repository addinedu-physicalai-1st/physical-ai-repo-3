# Rapport Averaging Window (Confidence-weighted EMA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rapport_tracker_node 에 confidence-weighted EMA layer 도입 — V·A frame-by-frame jitter 흡수, BT 의사결정 안정화.

**Architecture:**
1. EMA 로직을 `EMAState` dataclass 로 추출 — rclpy 의존 없이 pure unit test 가능.
2. `RapportTrackerNode` 는 `EMAState` 를 멤버로 보유, `_on_emotion` 안에서 update 후 smoothed V·A 로 기존 분류/streak 로직 실행.
3. `/rapport/event.emotion.valence/arousal` = smoothed, `confidence/source/flags` = raw 그대로. `/emotion/state` 자체는 변경 없음.

**Tech Stack:** Python 3.12, rclpy (Jazzy), dobi_npc_msgs (EmotionState/RapportEvent), pytest, colcon symlink-install.

**Spec SoT:** `docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md` (commit d5e7b19).

---

## File Structure

- **Modify**: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py`
  - 신규: `EMAState` dataclass (module level)
  - `__init__`: 새 parameter 2개 + EMAState 인스턴스 생성
  - `_on_emotion`: EMA update + smoothed V·A 로 분류
  - 기존 abort_on_count / abort_off_count / 분류 룰 / no_signal 분기 호환 유지
- **Create**: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`
  - 6 단위 테스트 (cold start, sustained, conf gate, no_signal, outlier, abort streak helper)
- **Create**: `tests/regression/perception/rapport_ema_smoke.md`
  - perception-tester 가 수행할 회귀 항목
- **Modify**: `tests/regression/catalog.yaml`
  - `rapport_ema_smoke` 항목 추가

---

## Task 1: EMAState dataclass + cold start test

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py`
- Create: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`

- [ ] **Step 1: Write failing test**

Create file `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`:

```python
"""rapport_tracker EMA smoothing 단위 테스트.

EMAState 를 pure dataclass 로 분리해 rclpy 의존 없이 검증.
spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md
"""
from dobi_npc_emotion.rapport_tracker_node import EMAState


ALPHA = 0.5
GATE = 0.3


def test_cold_start_adopts_raw():
    """첫 valid frame (no_signal=False, conf>=gate) → smoothed = raw."""
    s = EMAState()
    s.update(v_now=0.4, a_now=-0.2, conf=0.9,
             no_signal=False, alpha_base=ALPHA, conf_min_gate=GATE)
    assert s.v_smooth == 0.4
    assert s.a_smooth == -0.2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py -v
'
```

Expected: `ImportError: cannot import name 'EMAState' from 'dobi_npc_emotion.rapport_tracker_node'`

- [ ] **Step 3: Minimal implementation**

Edit `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py` — module level import 영역 바로 아래 (rclpy import 후, RapportTrackerNode 클래스 정의 직전, 임계값 상수 위) 에 추가:

```python
from dataclasses import dataclass


@dataclass
class EMAState:
    """V·A 의 confidence-weighted EMA 상태.

    spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md §3
    """
    v_smooth: float | None = None
    a_smooth: float | None = None

    def update(self, v_now: float, a_now: float, conf: float,
               no_signal: bool, alpha_base: float,
               conf_min_gate: float) -> None:
        if no_signal:
            return  # 사람 안 보임 — state 보존
        if conf < conf_min_gate:
            return  # 자신없는 frame skip
        if self.v_smooth is None:
            # cold start — 첫 valid frame 그대로 채택
            self.v_smooth = v_now
            self.a_smooth = a_now
            return
        weight = alpha_base * conf
        self.v_smooth = weight * v_now + (1 - weight) * self.v_smooth
        self.a_smooth = weight * a_now + (1 - weight) * self.a_smooth
```

- [ ] **Step 4: Run test to verify it passes**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select dobi_npc_emotion --event-handlers console_cohesion+ 2>&1 | tail -5
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_cold_start_adopts_raw -v
'
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py \
        src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py
git commit -m "feat(rapport-ema): EMAState dataclass + cold start (Task 1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Sustained high-conf update test

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`

- [ ] **Step 1: Write failing test**

Append to `test_rapport_tracker_ema.py`:

```python
def test_sustained_high_conf_reaches_90pct_within_4_frames():
    """V=0.5 conf=1.0 sustained — α=0.5 EMA 가 4 frame 안에 90% 도달.

    수식: 1 - (1-0.5)^4 = 0.9375 (4 frame 누적 후 v_smooth ≈ 0.469).
    """
    s = EMAState()
    # cold start (frame 0): v_smooth = 0.5
    s.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # frame 1-3
    for _ in range(3):
        s.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # cold start 이미 0.5 라 frame 1-3 도 0.5 (변화 없음)
    assert abs(s.v_smooth - 0.5) < 1e-6

    # 다른 target 으로 변화 검증 — cold start 후 4 frame 동안 0 → 0.5 추적
    s2 = EMAState()
    s2.update(0.0, 0.0, 1.0, False, ALPHA, GATE)   # cold start at 0
    for _ in range(4):
        s2.update(0.5, 0.3, 1.0, False, ALPHA, GATE)
    # 1 - (1-0.5)^4 = 0.9375 → v_smooth ≈ 0.4688
    assert s2.v_smooth > 0.46
    assert s2.v_smooth < 0.48
```

- [ ] **Step 2: Run test to verify it passes**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_sustained_high_conf_reaches_90pct_within_4_frames -v
'
```

Expected: `1 passed` (Task 1 의 update 구현으로 이미 충분).

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py
git commit -m "test(rapport-ema): sustained high-conf 4-frame convergence (Task 2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Confidence gate skip test

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`

- [ ] **Step 1: Write failing test**

Append to `test_rapport_tracker_ema.py`:

```python
def test_conf_gate_skips_low_confidence():
    """conf=0.2 (gate=0.3 미만) frame → EMA update 안 됨."""
    s = EMAState()
    # cold start
    s.update(0.4, -0.2, 0.9, False, ALPHA, GATE)
    assert s.v_smooth == 0.4

    # low conf frame — 새 값 무시
    s.update(-0.9, 0.9, 0.2, False, ALPHA, GATE)
    assert s.v_smooth == 0.4    # 변경 없음
    assert s.a_smooth == -0.2

    # gate 경계 (conf=0.3) — gate 미만 X (>=0.3 OK)
    s.update(0.6, 0.0, 0.3, False, ALPHA, GATE)
    # weight = 0.5 * 0.3 = 0.15
    # v_smooth = 0.15*0.6 + 0.85*0.4 = 0.43
    assert abs(s.v_smooth - 0.43) < 1e-6
```

- [ ] **Step 2: Run test to verify it passes**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_conf_gate_skips_low_confidence -v
'
```

Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py
git commit -m "test(rapport-ema): conf gate skip below 0.3 (Task 3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: no_signal preserves state test

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`

- [ ] **Step 1: Write failing test**

Append to `test_rapport_tracker_ema.py`:

```python
def test_no_signal_preserves_state():
    """no_signal=True (conf=0 또는 no_face flag) → EMA 변경 없음."""
    s = EMAState()
    s.update(0.4, -0.2, 0.9, False, ALPHA, GATE)   # cold start
    assert s.v_smooth == 0.4

    # no_signal — 새 값 완전 무시
    s.update(-1.0, 1.0, 0.0, True, ALPHA, GATE)
    assert s.v_smooth == 0.4
    assert s.a_smooth == -0.2

    # no_signal 후에도 다음 valid frame 정상 처리
    s.update(0.6, 0.0, 1.0, False, ALPHA, GATE)
    # weight = 0.5 * 1.0 = 0.5
    # v_smooth = 0.5*0.6 + 0.5*0.4 = 0.5
    assert s.v_smooth == 0.5


def test_no_signal_before_cold_start():
    """첫 frame 부터 no_signal — smoothed 가 None 유지."""
    s = EMAState()
    s.update(0.4, -0.2, 0.0, True, ALPHA, GATE)
    assert s.v_smooth is None
    assert s.a_smooth is None
```

- [ ] **Step 2: Run test to verify it passes**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_no_signal_preserves_state src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_no_signal_before_cold_start -v
'
```

Expected: `2 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py
git commit -m "test(rapport-ema): no_signal preserves state (Task 4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Outlier absorption test

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py`

- [ ] **Step 1: Write failing test**

Append to `test_rapport_tracker_ema.py`:

```python
def test_outlier_absorbed_one_frame_does_not_reach_abort_zone():
    """정상 4 frame + outlier 1 frame — smoothed 가 abort-zone 미달.

    abort-zone: V<-0.5 ∧ A>+0.4.
    정상 frame V=0.0 A=0.0 sustained → smoothed 가 0 근처.
    outlier 1 frame V=-1.0 A=+1.0 conf=1.0 → weight=0.5 → smoothed 가 절반만 이동.
    """
    s = EMAState()
    # cold start at neutral
    s.update(0.0, 0.0, 1.0, False, ALPHA, GATE)
    # 정상 3 frame 더
    for _ in range(3):
        s.update(0.0, 0.0, 1.0, False, ALPHA, GATE)
    assert s.v_smooth == 0.0

    # outlier 1 frame
    s.update(-1.0, 1.0, 1.0, False, ALPHA, GATE)
    # weight=0.5 → v_smooth = 0.5*-1.0 + 0.5*0 = -0.5
    # abort-zone 경계: V<-0.5 (strict less than), A>+0.4 — V=-0.5 미달
    assert s.v_smooth == -0.5
    assert s.a_smooth == 0.5
    # raw_abort 조건 (rapport_tracker_node.py 의 ABORT_VALENCE_MAX=-0.5) — v<-0.5 가 strict
    # v_smooth == -0.5 면 raw_abort=False
    assert not (s.v_smooth < -0.5 and s.a_smooth > 0.4)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py::test_outlier_absorbed_one_frame_does_not_reach_abort_zone -v
'
```

Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py
git commit -m "test(rapport-ema): outlier 1-frame absorbed below abort-zone (Task 5)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Integrate EMAState into RapportTrackerNode

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py`

- [ ] **Step 1: Add new parameters in `__init__`**

`rapport_tracker_node.py` 의 `__init__` 메서드 — 기존 `declare_parameter` block 끝 (`abort_off_count` 다음) 에 추가:

```python
        # 2026-05-20 — confidence-weighted EMA 파라미터 (spec §5)
        self.declare_parameter('ema_alpha_base', 0.5)
        self.declare_parameter('conf_min_gate', 0.3)
        self._ema_alpha_base = float(self.get_parameter('ema_alpha_base').value)
        self._conf_min_gate = float(self.get_parameter('conf_min_gate').value)
        self._ema = EMAState()
```

기존 `self.get_logger().info(...)` 호출 부분도 확장:

```python
        self.get_logger().info(
            f"rapport_tracker: {in_topic} -> {out_topic}, "
            f"hysteresis on={self._abort_on_count} off={self._abort_off_count}, "
            f"EMA α_base={self._ema_alpha_base} gate={self._conf_min_gate}"
        )
```

- [ ] **Step 2: Modify `_on_emotion` to use smoothed V·A**

기존 `_on_emotion` 메서드 — `no_signal` 계산 직후 (`raw_abort = (...)` 직전) 에 EMA update 호출 + smoothed V·A 추출:

```python
        no_signal = (msg.confidence <= 0.0) or ("no_face" in msg.flags)

        # 2026-05-20 EMA update (spec §3) — smoothed V·A 로 분류
        self._ema.update(
            v_now=msg.valence, a_now=msg.arousal, conf=msg.confidence,
            no_signal=no_signal,
            alpha_base=self._ema_alpha_base,
            conf_min_gate=self._conf_min_gate,
        )
        # smoothed 가 아직 없으면 (전부 no_signal/low_conf) raw 사용 — cold start fallback
        v = self._ema.v_smooth if self._ema.v_smooth is not None else msg.valence
        a = self._ema.a_smooth if self._ema.a_smooth is not None else msg.arousal

        raw_abort = (
            (not no_signal) and
            (v < ABORT_VALENCE_MAX) and (a > ABORT_AROUSAL_MIN)
        )
```

기존 line 82-83 의 `v = msg.valence` / `a = msg.arousal` 제거 (위 코드가 대체).

기존 abort streak / 분류 코드는 변경 없음 (이미 v, a 변수 사용).

- [ ] **Step 3: Publish smoothed V·A in RapportEvent.emotion**

기존 `_on_emotion` 시작 부분에서 `event.emotion = msg` 가 raw 그대로 복사함. 이를 smoothed V·A 로 갱신 (단, confidence/source/flags 는 raw 유지):

`event.emotion = msg` 다음 줄에 추가:

```python
        # 2026-05-20 — RapportEvent.emotion.valence/arousal 만 smoothed (spec §6)
        # confidence/source/flags 는 raw 그대로 (운영자 디버깅)
        event.emotion.valence = v
        event.emotion.arousal = a
```

(`v`/`a` 가 위 EMA update 후 결정된 smoothed 값.)

주의: `_on_emotion` 안에서 `event.emotion = msg` 가 `raw_abort` 계산 전에 실행되므로, v/a 계산 후에 event.emotion.valence/arousal 갱신해야 함. 순서:

1. `event.emotion = msg` (기존)
2. `no_signal = ...`
3. `self._ema.update(...)`
4. `v = ... a = ...` (smoothed 또는 raw fallback)
5. `event.emotion.valence = v; event.emotion.arousal = a`  ← 신규 (smoothed 발행)
6. `raw_abort = ...` (이미 v/a 사용)
7. 이하 streak / 분류 (변경 없음)

- [ ] **Step 4: Build + import smoke**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select dobi_npc_emotion --event-handlers console_cohesion+ 2>&1 | tail -10
source install/setup.bash
python3 -c "
from dobi_npc_emotion.rapport_tracker_node import RapportTrackerNode, EMAState
print(\"import OK\")
print(\"  EMAState in __init__:\", \"_ema\" in [a for a in dir(RapportTrackerNode) if not a.startswith(\"__\")])
"
'
```

Expected: `Finished <<< dobi_npc_emotion` + `import OK`.

- [ ] **Step 5: Re-run all unit tests (regression check)**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/dobi_npc/dobi_npc_emotion/test/test_rapport_tracker_ema.py -v
'
```

Expected: 모든 EMAState 테스트 통과 (Task 1-5 누적 6 tests). RapportTrackerNode 변경이 EMAState 로직 깨뜨리지 않음 확인.

- [ ] **Step 6: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py
git commit -m "feat(rapport-ema): integrate EMAState into RapportTrackerNode (Task 6)

Smoothed V·A 로 abort/up/down/neutral 분류. RapportEvent.emotion.valence/
arousal 만 smoothed, confidence/source/flags 는 raw 유지. 새 파라미터
ema_alpha_base=0.5, conf_min_gate=0.3.

spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Regression catalog entry

**Files:**
- Create: `tests/regression/perception/rapport_ema_smoke.md`
- Modify: `tests/regression/catalog.yaml`

- [ ] **Step 1: Create regression smoke file**

Create `tests/regression/perception/rapport_ema_smoke.md`:

```markdown
---
id: rapport_ema_smoke
category: perception
depth: smoke
duration_sec: 20
requires:
  - package: dobi_npc_emotion
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (RPi 미사용, DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
rapport_tracker_node 의 confidence-weighted EMA 가 V·A jitter 흡수 + smoothed
V·A 를 RapportEvent.emotion 에 발행하는지 확인.

spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 run dobi_npc_emotion rapport_tracker_node &
RAPPORT_PID=$!
sleep 2
```

# 단계

1. **노드 alive + 토픽 등록**
   Run: `ros2 topic list | grep -q /rapport/event`
   Expect: exit 0

2. **outlier 흡수 — single frame V=-1.0 A=+1.0 conf=1.0 publish → abort_trigger 안 발생**

   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -1.0, arousal: 1.0, confidence: 1.0, source: "face", flags: []}'
   sleep 0.5
   ros2 topic echo --once /rapport/event > /tmp/rapport_outlier.txt
   ```
   Expect: `/tmp/rapport_outlier.txt` 안 `event_type: neutral_continue` 또는 `engagement_down` (abort_trigger 아님)

3. **sustained abort — 10 frame V=-0.7 A=+0.6 conf=1.0 publish → abort_trigger 발생**

   ```bash
   for i in $(seq 1 10); do
     ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
       '{header: {frame_id: ""}, valence: -0.7, arousal: 0.6, confidence: 1.0, source: "face", flags: []}'
     sleep 0.1
   done
   sleep 0.3
   ros2 topic echo --once /rapport/event > /tmp/rapport_abort.txt
   ```
   Expect: `/tmp/rapport_abort.txt` 안 `event_type: abort_trigger`

4. **conf gate skip — conf=0.2 frame 후 smoothed 변경 없음**

   ```bash
   # 먼저 sustained neutral 로 EMA 안정화
   for i in $(seq 1 5); do
     ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
       '{header: {frame_id: ""}, valence: 0.0, arousal: 0.0, confidence: 1.0, source: "face", flags: []}'
     sleep 0.1
   done
   # outlier with low conf
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -1.0, arousal: 1.0, confidence: 0.2, source: "face", flags: []}'
   sleep 0.3
   ros2 topic echo --once /rapport/event > /tmp/rapport_gate.txt
   ```
   Expect: `/tmp/rapport_gate.txt` 안 `event_type: neutral_continue` (low conf 무시)

5. **노드 alive 확인**
   Run: `kill -0 $RAPPORT_PID`
   Expect: exit 0

# 기대 결과
- outlier 1 frame 흡수 (single frame V=-1.0 → abort_trigger 안 발생)
- sustained abort 10 frame → abort_trigger
- low confidence frame skip
- 노드 alive

# 클린업
```bash
kill $RAPPORT_PID 2>/dev/null
wait $RAPPORT_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once 의 discovery race — 첫 publish 가 drop 될 수 있음 (sleep 추가).
- abort streak 5 frame 임계 — 9 frame 미만이면 trigger 안 됨.
```

- [ ] **Step 2: Add catalog entry**

Edit `tests/regression/catalog.yaml` — `tests:` 리스트 끝 (또는 `geva_webcam_smoke` 다음) 에 추가:

```yaml
- id: rapport_ema_smoke
  category: perception
  file: perception/rapport_ema_smoke.md
  depth: smoke
  tags:
  - rapport
  - ema
  - smoothing
  - perception
  duration_estimate_sec: 20
  requires:
  - package: dobi_npc_emotion
  policy:
    blocks: []
  added: '2026-05-20'
  last_status: null
  last_run: null
```

- [ ] **Step 3: Verify YAML parse**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('tests/regression/catalog.yaml'))
ids = [t['id'] for t in d['tests']]
assert 'rapport_ema_smoke' in ids, f'rapport_ema_smoke not in {ids}'
print('catalog OK:', ids)
"
```

Expected: `catalog OK: [..., 'rapport_ema_smoke']`

- [ ] **Step 4: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/tests/regression/perception/rapport_ema_smoke.md \
        src/controller/doby_controller/tests/regression/catalog.yaml
git commit -m "test(rapport-ema): regression smoke + catalog entry (Task 7)

Note: 회귀 시스템 v1 검증 단계 — Stephen 명시 해제 전까진 catalog.yaml 변경
commit X 정책이지만 본 trake 의 신규 항목 등록은 사용자가 spec 단계에서
승인. 별 commit 으로 분리해 revert 용이.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(이 step 의 `feedback_test_supervisor_v1_no_commit` 메모리 정합 — 단순 신규 회귀 카탈로그 등록은 본 trake spec 의 일부로 사용자 승인. 별 commit 분리 권장.)

---

## Task 8: Live verification (DOMAIN=99 sim) + 회고

**Files:**
- Create: `docs/daily/2026-05-21_rapport_ema_integration.md` (또는 작업 당일 날짜)

- [ ] **Step 1: opserver + dummy publisher 검증 (기존 trake 의 검증 인프라 재사용)**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller

# 1. opserver 띄우기 (DOMAIN=99 격리, 백그라운드)
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec ros2 launch moca_opserver opserver.launch.py
' > /tmp/opserver_ema.log 2>&1 &

# 2. rapport_tracker_node 띄우기
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec ros2 run dobi_npc_emotion rapport_tracker_node
' > /tmp/rapport_ema.log 2>&1 &

sleep 4

# 3. continuous publisher (sin wave V/A) — 기존 /tmp/continuous_pub.py
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
exec python3 /tmp/continuous_pub.py
' > /tmp/cont_pub_ema.log 2>&1 &

sleep 5

# 4. WS /ws/v1/engaging 에서 smoothed V·A 가 raw 보다 부드러운지 확인
python3 /tmp/ws_engaging_test.py 5 2>&1 | grep emo_latest

# 5. rapport recent (smoothed) 와 emotion latest (raw) 비교
curl -sS http://localhost:8800/api/v1/status | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
# (status snapshot 안 _rapport_events 노출 안 됨 — WS 사용)
print('mode:', d['mode']['current'])
"
```

Expected: WS 의 emo_latest_v_a_conf 가 시간에 따라 부드럽게 변화 (raw sin wave 보다 진폭 작음). rapport_tracker 로그 (`/tmp/rapport_ema.log`) 에서 event_type 전이가 raw 대비 적은 빈도.

- [ ] **Step 2: abort burst 검증 — outlier 흡수 + sustained abort**

```bash
# pause continuous (PID 정확히)
CONT_PID=$(pgrep -f "python3 /tmp/continuous_pub.py")
[ -n "$CONT_PID" ] && kill "$CONT_PID"
sleep 1

# abort burst (기존 /tmp/abort_burst.py — V=-0.7 A=+0.6 5초간 5Hz)
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
python3 /tmp/abort_burst.py
' 2>&1 | grep abort

# rapport_tracker 로그에서 abort_trigger 발생 확인
grep -E "abort streak|ENTER abort|abort_trigger" /tmp/rapport_ema.log | tail -10

# event log 에서 abort 이벤트 확인
curl -sS "http://localhost:8800/api/v1/events?limit=3&category=safety" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
for e in d['events'][:3]:
    print(f'[{e[\"level\"]}] {e[\"ts\"]} {e[\"msg\"]}')
"
```

Expected:
- `/tmp/rapport_ema.log` 에 `ENTER abort` 로그 (V=-0.7 A=+0.6 5 frame 이상 streak 후)
- event log 에 `[warn] abort_trigger weight=...` 항목
- EMA + streak 직렬 → 약 ~0.9s 응답 시간 (시각 확인)

- [ ] **Step 3: Cleanup**

```bash
pgrep -f "python3 /tmp/continuous_pub.py" | xargs -r kill 2>/dev/null
pgrep -f rapport_tracker_node | xargs -r kill 2>/dev/null
pgrep -f opserver_node | xargs -r kill 2>/dev/null
sleep 1
ss -tlnp 2>/dev/null | grep ":8800" && echo "WARN: 8800 still listening" || echo "8800 free"
```

Expected: `8800 free`

- [ ] **Step 4: Write 회고**

Create `docs/daily/$(date +%Y-%m-%d)_rapport_ema_integration.md`:

```markdown
# YYYY-MM-DD — rapport_tracker EMA 통합

> branch: feat/engaging-analytics-migration (또는 별 cut)
> spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md
> plan: docs/superpowers/plans/2026-05-20-rapport-averaging-window.md

## 1. 작업 요약

rapport_tracker_node 에 confidence-weighted EMA layer 도입. EMAState dataclass
pure logic 분리 + 6 단위 테스트 + 회귀 카탈로그 항목 + 라이브 검증.

## 2. 변경 사항

- `EMAState` dataclass 신규 (rapport_tracker_node.py module level)
- `__init__` 에 ema_alpha_base=0.5, conf_min_gate=0.3 파라미터
- `_on_emotion` 가 EMA update + smoothed V·A 로 분류
- RapportEvent.emotion.valence/arousal 만 smoothed (confidence/source/flags raw)
- 기존 abort streak 5 frame 그대로 (smoothed V·A 가 입력)

## 3. 검증

- 단위 테스트 6 (cold start / sustained / conf gate / no_signal / outlier / no_signal cold start) ✓
- import smoke ✓
- 회귀 카탈로그 rapport_ema_smoke 등록
- 라이브 검증 — DOMAIN=99 sim:
  - continuous sin wave publisher → WS 의 smoothed V·A 가 raw 보다 부드러움 ✓
  - outlier 1 frame burst → abort_trigger 발생 안 함 ✓
  - sustained abort 5초 burst → ~0.9s 안에 abort_trigger ✓

## 4. §0-B / §0-A 정합

rapport_tracker_node.py 단일 파일 + 신규 test + 회귀 항목. vic_pinky + RPi
자산 touch 0. 신규 ROS topic 0 (/rapport/event 의미만 변경).

## 5. 후속 (별 trake — 본 spec §10)

- Track B 대상자 ID: track_id/group_id 통합
- Track C 시계열 그래프: opserver history 확장 + <engagement-timeline>
- Track D audit log: BTAuditEvent.msg + MySQL persistence

## 6. 라이브 운영 튜닝 가이드

EMA α_base / conf_min_gate 라이브 환경 (카페 조명/거리) 에 맞게 튜닝:
- α_base 0.5 → 0.3 (더 부드럽지만 느림) 또는 0.7 (빠르지만 jitter)
- conf_min_gate 0.3 → 0.5 (더 엄격) 또는 0.2 (관대)
```

- [ ] **Step 5: Commit**

```bash
cd /home/gjkong/physical-ai-repo-3
git add src/controller/doby_controller/docs/daily/$(date +%Y-%m-%d)_rapport_ema_integration.md
git commit -m "docs(rapport-ema): live verification 회고 (Task 8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist (실행 전 확인)

### Spec coverage
- §2 D1 (목적) → Task 1-6 의 EMA 도입 자체 ✓
- §2 D2 (rapport_tracker 내부) → Task 6 통합 ✓
- §2 D3 (Confidence-weighted EMA) → Task 1 EMAState.update ✓
- §2 D4 (abort streak 유지) → Task 6 의 기존 streak 코드 변경 X ✓
- §3 알고리즘 상세 (cold start / conf gate / no_signal) → Task 1, 3, 4 ✓
- §5 새 파라미터 (ema_alpha_base=0.5, conf_min_gate=0.3) → Task 6 step 1 ✓
- §6 RapportEvent.emotion smoothed → Task 6 step 3 ✓
- §7 Edge cases — 모두 단위 테스트 + 회귀 커버:
  - cold start ✓ (Task 1)
  - 장기 no_signal ✓ (Task 4 + step 2)
  - 지속 conf<gate ✓ (Task 3)
  - outlier conf=1.0 ✓ (Task 5)
  - bt_executor restart → 자동 cold start (테스트 불필요)
  - abort streak ON 중 정상 회복 → 기존 동작, 라이브 검증으로 (Task 8)
- §8 응답 시간 — 라이브 검증 (Task 8 step 2) 시각 확인 ✓
- §9 Testing — 모든 단위 + 회귀 + 라이브 절차 ✓
- §10 후속 trake — 회고 §5 에 명시 ✓
- §11 §0-B 정합 — 회고 §4 ✓

### Placeholder scan
- 모든 step 에 구체적 code/command/expected output 포함 ✓
- TBD / TODO / FIXME 없음 ✓

### Type/signature consistency
- `EMAState` 의 update signature: `(v_now, a_now, conf, no_signal, alpha_base, conf_min_gate) -> None` — Task 1, 2, 3, 4, 5, 6 모두 일관 ✓
- 파라미터 명 `ema_alpha_base`, `conf_min_gate` — spec §5 + Task 6 + 회귀 .md 모두 일관 ✓
- `rapport_tracker_node` 모듈 path `dobi_npc_emotion.rapport_tracker_node` — Task 1 import + Task 6 build + 회귀 .md 모두 일관 ✓

---

## Execution Notes

본 plan 8 task. 각 task 별 commit 으로 revert 용이. Task 1-5 = pure Python TDD (1-2분/task), Task 6 = ROS 통합 (5분), Task 7 = 회귀 카탈로그 (3분), Task 8 = 라이브 검증 + 회고 (15분). 총 30~45분 추정.

후속 작업 (Track B/C/D) 은 별 brainstorm → spec → plan 사이클.
