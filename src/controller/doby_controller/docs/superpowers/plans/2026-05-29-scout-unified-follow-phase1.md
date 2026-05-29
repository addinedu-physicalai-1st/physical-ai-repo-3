# scout 일원화 follow (Phase-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.
>
> **커밋 정책 (사용자 전역 규칙):** 실행자/서브에이전트는 `git add/commit/push` 를 **직접 실행 금지**. commit 블록은 사용자에게 **제시만** 한다.

**Goal:** 손든 사람을 scout_cam 한 카메라로 획득·추적해 차체가 안정적으로 회전+전진 추종 (2026-05-29 실차 실패: 제자리회전·후진 해소).

**Architecture:** call_detector(획득) → co-rotation 핸드오프(차체 정면화 + 서보 정면 고정) → person_tracking(@scout 영상) track_id+bbox → 신규 집중형 `scout_follow_controller` 가 각속도(=cx)·선속도(=bbox높이, 후진금지)로 `/follow/cmd_vel`. 서보가 추종 루프 밖 → PTZ 결합 발산 없음.

**Tech Stack:** ROS 2 Jazzy, rclpy, `dobi_npc_msgs/PersonTrackArray`(PersonTrack.bbox=`float32[4]`), `person_tracking_pkg`(무수정, launch arg만), pytest. 제어 로직은 순수함수로 분리(ROS-free 단위테스트).

**Base:** `feat/scout-unified-follow` off `origin/dev`(e5b2737). **SoT 스펙:** `docs/superpowers/specs/2026-05-29-scout-unified-follow-design.md`

---

## File Structure

- **Create** `src/controller/mobility_controller/scripts/scout_follow_controller_node.py` — 상단 순수함수(ROS 무관) + 하단 `ScoutFollowController(Node)` + main.
- **Create** `src/controller/mobility_controller/test/test_scout_follow_control.py` — 순수함수 단위테스트.
- **Create** `src/controller/mobility_controller/launch/scout_unified_follow.launch.py`.
- **Modify** `src/controller/mobility_controller/CMakeLists.txt` — python 스크립트 install (dev엔 없음 → 처음부터).
- **Modify** `src/controller/mobility_controller/package.xml` — python exec deps.

> 테스트 패턴: 테스트가 `../scripts` 를 `sys.path` 에 넣고 노드 모듈에서 순수함수 import. **Task1~4 시점엔 노드에 ROS import 없음 → ROS 없이 pytest 통과.** Task5에서 ROS import 추가 후엔 모듈 import 가 ROS 필요 → 전체 pytest 는 빌드+소스 후 Task6에서 실행.
> 경로 규약(CLAUDE.md): 절대경로 하드코딩 금지. launch 는 `LaunchConfiguration` arg.

---

### Task 1: `cx_to_angular` — bbox 중심x → 각속도

**Files:** Create `scripts/scout_follow_controller_node.py`, `test/test_scout_follow_control.py`

- [ ] **Step 1: 실패 테스트 작성** — `test/test_scout_follow_control.py`:
```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from scout_follow_controller_node import cx_to_angular  # noqa: E402


def test_cx_center_returns_zero():
    assert cx_to_angular(320.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) == 0.0


def test_cx_within_deadband_returns_zero():
    assert cx_to_angular(327.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) == 0.0


def test_cx_right_of_center_turns_right_when_sign_pos():
    assert cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) < 0.0


def test_cx_left_of_center_turns_left_when_sign_pos():
    assert cx_to_angular(80.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1) > 0.0


def test_cx_sign_flip_inverts_direction():
    a = cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=1)
    b = cx_to_angular(560.0, 640, kp=0.5, max_w=0.5, deadband_px=10.0, sign=-1)
    assert a == -b


def test_cx_clamps_to_max_w():
    w = cx_to_angular(640.0, 640, kp=10.0, max_w=0.5, deadband_px=10.0, sign=1)
    assert w == -0.5
```

- [ ] **Step 2: 실패 확인** — `cd ~/physical-ai-repo-3 && pytest src/controller/mobility_controller/test/test_scout_follow_control.py -q` → ImportError FAIL.

- [ ] **Step 3: 최소 구현** — `scripts/scout_follow_controller_node.py`:
```python
#!/usr/bin/env python3
"""scout_follow_controller — scout 일원화 follow 집중형 컨트롤러.

순수 제어함수(상단, ROS 무관) + ScoutFollowController FSM(하단).
스펙: docs/superpowers/specs/2026-05-29-scout-unified-follow-design.md
"""
from __future__ import annotations

import math


def cx_to_angular(cx: float, image_width: int, kp: float, max_w: float,
                  deadband_px: float, sign: int = 1) -> float:
    """bbox 중심x(px) → base 각속도(rad/s). +w=CCW(좌회전).
    err=cx-W/2 (>0: 사람 오른쪽). sign 라이브 1회 검증."""
    half = image_width / 2.0
    err = cx - half
    if abs(err) < deadband_px:
        return 0.0
    w = sign * (-kp) * (err / half)
    return max(-max_w, min(max_w, w))
```

- [ ] **Step 4: 통과 확인** — 같은 pytest → 6 passed.

- [ ] **Step 5: 커밋 (사용자에게 제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/scripts/scout_follow_controller_node.py src/controller/mobility_controller/test/test_scout_follow_control.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): cx_to_angular 순수함수 + 테스트"
```

---

### Task 2: `bh_to_linear` — bbox 높이 → 선속도 (후진 금지)

**Files:** Modify both files.

- [ ] **Step 1: 실패 테스트 추가** — import 줄을 `from scout_follow_controller_node import cx_to_angular, bh_to_linear` 로 바꾸고 추가:
```python
def test_bh_far_goes_forward():
    assert bh_to_linear(0.20, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) > 0.0


def test_bh_at_target_returns_zero():
    assert bh_to_linear(0.45, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_within_deadband_returns_zero():
    assert bh_to_linear(0.47, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_closer_than_target_never_reverses():
    assert bh_to_linear(0.60, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_too_close_stop():
    assert bh_to_linear(0.80, target_bh=0.45, kp=0.8, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.0


def test_bh_clamps_to_max_v():
    assert bh_to_linear(0.0, target_bh=0.45, kp=10.0, max_v=0.15, bh_stop=0.75, deadband=0.03) == 0.15
```

- [ ] **Step 2: 실패 확인** — pytest → ImportError FAIL.

- [ ] **Step 3: 최소 구현** — 노드에 추가:
```python
def bh_to_linear(bh: float, target_bh: float, kp: float, max_v: float,
                 bh_stop: float, deadband: float) -> float:
    """bbox 높이비율(0..1, 클수록 가까움) → 전진 선속도(>=0, 절대 후진 X).
    bh>=bh_stop: 너무 가까움→0. err=target_bh-bh(>0: 멀다→전진)."""
    if bh >= bh_stop:
        return 0.0
    err = target_bh - bh
    if abs(err) < deadband:
        return 0.0
    v = kp * err
    return max(0.0, min(max_v, v))
```

- [ ] **Step 4: 통과 확인** — pytest → 12 passed.

- [ ] **Step 5: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/scripts/scout_follow_controller_node.py src/controller/mobility_controller/test/test_scout_follow_control.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): bh_to_linear (후진 금지 거리제어) + 테스트"
```

---

### Task 3: 핸드오프 수학 — `yaw_from_quat`, `handoff_servo_pan`, `handoff_done`

- [ ] **Step 1: 실패 테스트 추가** — import 에 세 함수 추가 + 테스트(파일 상단 `import math` 추가):
```python
import math
from scout_follow_controller_node import (
    cx_to_angular, bh_to_linear, yaw_from_quat, handoff_servo_pan, handoff_done,
)


def test_yaw_from_quat_identity_is_zero():
    assert abs(yaw_from_quat(0.0, 0.0, 0.0, 1.0)) < 1e-9


def test_yaw_from_quat_90deg():
    z, w = math.sin(math.pi / 4), math.cos(math.pi / 4)
    assert abs(yaw_from_quat(0.0, 0.0, z, w) - math.pi / 2) < 1e-6


def test_handoff_servo_pan_unwinds_with_base():
    assert abs(handoff_servo_pan(0.6, 0.2, servo_limit=1.0) - 0.4) < 1e-9


def test_handoff_servo_pan_clamps():
    assert handoff_servo_pan(2.0, 0.0, servo_limit=0.8) == 0.8
    assert handoff_servo_pan(-2.0, 0.0, servo_limit=0.8) == -0.8


def test_handoff_done_true():
    assert handoff_done(0.58, 0.6, tol_rad=0.05) is True


def test_handoff_done_false():
    assert handoff_done(0.2, 0.6, tol_rad=0.05) is False
```

- [ ] **Step 2: 실패 확인** — pytest → ImportError FAIL.

- [ ] **Step 3: 최소 구현** — 노드에 추가(`import math` 는 Task1 에서 이미 상단에 있음):
```python
def yaw_from_quat(x: float, y: float, z: float, w: float) -> float:
    """쿼터니언 → yaw(rad)."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def handoff_servo_pan(lock_bearing: float, base_yaw_delta: float,
                      servo_limit: float) -> float:
    """co-rotation: 네트 지향(base_yaw+servo_pan)=lock_bearing 유지.
    servo_pan = lock_bearing - base_yaw_delta (clamp)."""
    pan = lock_bearing - base_yaw_delta
    return max(-servo_limit, min(servo_limit, pan))


def handoff_done(base_yaw_delta: float, lock_bearing: float,
                 tol_rad: float) -> bool:
    """차체가 lock_bearing(±tol) 회전 완료 → 서보 0 도달."""
    return abs(base_yaw_delta - lock_bearing) <= tol_rad
```

- [ ] **Step 4: 통과 확인** — pytest → 18 passed.

- [ ] **Step 5: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/scripts/scout_follow_controller_node.py src/controller/mobility_controller/test/test_scout_follow_control.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): co-rotation 핸드오프 수학 + 테스트"
```

---

### Task 4: 대상 선택 + FSM — `select_target_track`, `next_state`

- [ ] **Step 1: 실패 테스트 추가** — import 에 두 함수 추가 + 테스트:
```python
from scout_follow_controller_node import (
    cx_to_angular, bh_to_linear, yaw_from_quat, handoff_servo_pan, handoff_done,
    select_target_track, next_state,
)


def test_select_target_track_picks_centermost():
    tracks = [(3, 100.0, 240, 50, 200), (7, 330.0, 240, 50, 200), (9, 600.0, 240, 50, 200)]
    assert select_target_track(tracks, image_width=640) == 7


def test_select_target_track_empty_returns_none():
    assert select_target_track([], image_width=640) is None


def test_fsm_search_to_handoff_on_locked():
    assert next_state('SEARCH', 'locked', False, False, 0.0, 2.0) == 'HANDOFF'


def test_fsm_search_stays():
    assert next_state('SEARCH', 'searching', False, False, 0.0, 2.0) == 'SEARCH'


def test_fsm_handoff_to_follow():
    assert next_state('HANDOFF', 'locked', True, True, 0.0, 2.0) == 'FOLLOW'


def test_fsm_follow_to_lost():
    assert next_state('FOLLOW', 'locked', False, True, 0.0, 2.0) == 'LOST'


def test_fsm_lost_back_to_follow():
    assert next_state('LOST', 'locked', True, True, 0.5, 2.0) == 'FOLLOW'


def test_fsm_lost_to_search_after_dwell():
    assert next_state('LOST', 'searching', False, True, 2.5, 2.0) == 'SEARCH'
```

- [ ] **Step 2: 실패 확인** — pytest → ImportError FAIL.

- [ ] **Step 3: 최소 구현** — 노드에 추가:
```python
def select_target_track(tracks, image_width: int):
    """tracks: [(track_id, cx, cy, w, h)]. 화면 중앙 최근접 track_id (없으면 None)."""
    if not tracks:
        return None
    center = image_width / 2.0
    return min(tracks, key=lambda t: abs(t[1] - center))[0]


def next_state(state: str, call_state: str, target_visible: bool,
               handoff_complete: bool, lost_elapsed: float,
               lost_dwell: float) -> str:
    """순수 FSM. SEARCH→HANDOFF→FOLLOW→LOST."""
    if state == 'SEARCH':
        return 'HANDOFF' if call_state == 'locked' else 'SEARCH'
    if state == 'HANDOFF':
        return 'FOLLOW' if handoff_complete else 'HANDOFF'
    if state == 'FOLLOW':
        return 'FOLLOW' if target_visible else 'LOST'
    if state == 'LOST':
        if target_visible:
            return 'FOLLOW'
        return 'SEARCH' if lost_elapsed >= lost_dwell else 'LOST'
    return 'SEARCH'
```

- [ ] **Step 4: 통과 확인** — pytest → 26 passed.

- [ ] **Step 5: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/scripts/scout_follow_controller_node.py src/controller/mobility_controller/test/test_scout_follow_control.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): 대상선택 + FSM 순수함수 + 테스트"
```

---

### Task 5: `ScoutFollowController` ROS 노드 (FSM 배선)

**Files:** Modify `scripts/scout_follow_controller_node.py` (순수함수 아래 추가).

> dev `PersonTrack.bbox = float32[4] [x1,y1,x2,y2] 픽셀` — vision_msgs 안 씀. cx=(x1+x2)/2, bh=(y2-y1)/image_height.

- [ ] **Step 1: ROS 노드 + main 추가** — 파일 끝에:
```python
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from geometry_msgs.msg import Twist
from sensor_msgs.msg import JointState
from std_msgs.msg import String, Bool
from nav_msgs.msg import Odometry
from dobi_npc_msgs.msg import PersonTrackArray


class ScoutFollowController(Node):
    """scout 일원화 follow FSM. SEARCH→HANDOFF(co-rotation)→FOLLOW→LOST."""

    def __init__(self):
        super().__init__('scout_follow_controller')
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)
        self.declare_parameter('kp_angular', 0.5)
        self.declare_parameter('max_angular', 0.5)
        self.declare_parameter('angular_deadband_px', 24.0)
        self.declare_parameter('angular_sign', 1)
        self.declare_parameter('kp_linear', 0.8)
        self.declare_parameter('max_linear', 0.15)
        self.declare_parameter('target_bh', 0.45)
        self.declare_parameter('bh_stop', 0.75)
        self.declare_parameter('linear_deadband', 0.03)
        self.declare_parameter('ema_alpha', 0.5)
        self.declare_parameter('servo_limit_rad', 0.8)
        self.declare_parameter('handoff_yaw_tol_rad', 0.06)
        self.declare_parameter('handoff_base_w', 0.4)
        self.declare_parameter('lost_dwell_sec', 2.0)
        self.declare_parameter('rate_hz', 20.0)
        self.declare_parameter('cmd_topic', '/follow/cmd_vel')
        self.declare_parameter('servo_cmd_topic', '/scout_cam/cmd_pan_tilt')

        g = self.get_parameter
        self.W = int(g('image_width').value)
        self.H = int(g('image_height').value)
        self.kp_w = float(g('kp_angular').value)
        self.max_w = float(g('max_angular').value)
        self.dead_px = float(g('angular_deadband_px').value)
        self.sign = int(g('angular_sign').value)
        self.kp_v = float(g('kp_linear').value)
        self.max_v = float(g('max_linear').value)
        self.target_bh = float(g('target_bh').value)
        self.bh_stop = float(g('bh_stop').value)
        self.dead_bh = float(g('linear_deadband').value)
        self.alpha = float(g('ema_alpha').value)
        self.servo_limit = float(g('servo_limit_rad').value)
        self.yaw_tol = float(g('handoff_yaw_tol_rad').value)
        self.handoff_w = float(g('handoff_base_w').value)
        self.lost_dwell = float(g('lost_dwell_sec').value)
        rate = float(g('rate_hz').value)

        self.state = 'SEARCH'
        self.call_state = 'searching'
        self.lock_bearing = 0.0
        self.base_yaw = None
        self.base_yaw_at_lock = None
        self.tracks = []            # [(track_id, cx, cy, w, h)]
        self.target_track_id = None
        self.lost_since = None
        self._v = 0.0
        self._w = 0.0

        self.pub_cmd = self.create_publisher(Twist, g('cmd_topic').value, 10)
        self.pub_servo = self.create_publisher(JointState, g('servo_cmd_topic').value, 10)
        self.pub_enable = self.create_publisher(Bool, '/call/enable', 10)

        self.create_subscription(String, '/call/state', self._on_call_state, 10)
        self.create_subscription(String, '/call/event', self._on_call_event, 10)
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.create_subscription(PersonTrackArray, '/person_tracking/tracks', self._on_tracks, 10)

        self.timer = self.create_timer(1.0 / max(1.0, rate), self._tick)
        self.get_logger().info(
            f'scout_follow_controller ready: {self.W}x{self.H} sign={self.sign:+d} '
            f'max_v={self.max_v} max_w={self.max_w} target_bh={self.target_bh}')

    def _on_call_state(self, m: String):
        self.call_state = m.data.strip()

    def _on_call_event(self, m: String):
        import json
        try:
            self.lock_bearing = float(json.loads(m.data).get('bearing_rad', self.lock_bearing))
        except (ValueError, KeyError, TypeError):
            pass

    def _on_odom(self, m: Odometry):
        q = m.pose.pose.orientation
        self.base_yaw = yaw_from_quat(q.x, q.y, q.z, q.w)

    def _on_tracks(self, m: PersonTrackArray):
        out = []
        for t in m.tracks:
            if len(t.bbox) < 4:
                continue
            x1, y1, x2, y2 = (float(t.bbox[0]), float(t.bbox[1]),
                              float(t.bbox[2]), float(t.bbox[3]))
            out.append((int(t.track_id), (x1 + x2) / 2.0, (y1 + y2) / 2.0,
                        x2 - x1, y2 - y1))
        self.tracks = out

    def _base_yaw_delta(self) -> float:
        if self.base_yaw is None or self.base_yaw_at_lock is None:
            return 0.0
        d = self.base_yaw - self.base_yaw_at_lock
        return math.atan2(math.sin(d), math.cos(d))

    def _target_bbox(self):
        for (tid, cx, cy, w, h) in self.tracks:
            if tid == self.target_track_id:
                return (cx, cy, w, h)
        return None

    def _publish_cmd(self, v: float, w: float):
        self._v = self.alpha * v + (1 - self.alpha) * self._v
        self._w = self.alpha * w + (1 - self.alpha) * self._w
        msg = Twist()
        msg.linear.x = self._v
        msg.angular.z = self._w
        self.pub_cmd.publish(msg)

    def _publish_servo(self, pan: float):
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = ['pan', 'tilt']
        js.position = [float(pan), 0.0]
        self.pub_servo.publish(js)

    def _tick(self):
        now = self.get_clock().now()

        if self.state == 'SEARCH' and self.call_state == 'locked':
            self.base_yaw_at_lock = self.base_yaw if self.base_yaw is not None else 0.0
            self.pub_enable.publish(Bool(data=False))

        target_visible = (self.target_track_id is not None
                          and self._target_bbox() is not None)
        if target_visible:
            self.lost_since = None
        elif self.lost_since is None and self.state in ('FOLLOW', 'LOST'):
            self.lost_since = now
        lost_elapsed = 0.0 if self.lost_since is None else \
            (now - self.lost_since).nanoseconds * 1e-9

        hdone = handoff_done(self._base_yaw_delta(), self.lock_bearing, self.yaw_tol)
        new = next_state(self.state, self.call_state, target_visible,
                         hdone, lost_elapsed, self.lost_dwell)

        if new == 'SEARCH':
            self._publish_cmd(0.0, 0.0)
            self.target_track_id = None
            if self.state != 'SEARCH':
                self.pub_enable.publish(Bool(data=True))
        elif new == 'HANDOFF':
            delta = self._base_yaw_delta()
            w = self.handoff_w * (1.0 if self.lock_bearing >= delta else -1.0)
            self._publish_cmd(0.0, max(-self.max_w, min(self.max_w, w)))
            self._publish_servo(handoff_servo_pan(self.lock_bearing, delta, self.servo_limit))
        elif new == 'FOLLOW':
            if self.target_track_id is None:
                self.target_track_id = select_target_track(self.tracks, self.W)
                self._publish_servo(0.0)
            bbox = self._target_bbox()
            if bbox is None:
                self._publish_cmd(0.0, 0.0)
            else:
                cx, cy, bw, bh_px = bbox
                bh = bh_px / max(1.0, float(self.H))
                w = cx_to_angular(cx, self.W, self.kp_w, self.max_w, self.dead_px, self.sign)
                v = bh_to_linear(bh, self.target_bh, self.kp_v, self.max_v, self.bh_stop, self.dead_bh)
                self._publish_cmd(v, w)
        elif new == 'LOST':
            self._publish_cmd(0.0, 0.0)

        self.state = new


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ScoutFollowController()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 구문 검사** (ROS 빌드 전이라 import 실행 안 되는 py_compile 로) — `cd ~/physical-ai-repo-3 && python3 -m py_compile src/controller/mobility_controller/scripts/scout_follow_controller_node.py && echo OK` → `OK`.

> 전체 pytest 는 ROS import(rclpy/dobi_npc_msgs) 가 필요하므로 빌드+소스 후 Task6 에서 실행한다.

- [ ] **Step 3: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/scripts/scout_follow_controller_node.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): ScoutFollowController ROS 노드 (FSM)"
```

---

### Task 6: CMakeLists/package.xml python install + 빌드 + 전체 테스트

**Files:** Modify `CMakeLists.txt`, `package.xml`.

> dev `mobility_controller` 는 C++ 전용(ament_cmake, scripts install 없음) → 처음부터 추가.

- [ ] **Step 1: CMakeLists.txt 수정** — `install(DIRECTORY config launch ...)` 블록 **앞**에 추가:
```cmake
install(PROGRAMS
  scripts/scout_follow_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME scout_follow_controller
)
```

- [ ] **Step 2: package.xml 수정** — `<depend>std_msgs</depend>` 아래에 python exec deps 추가:
```xml
  <exec_depend>rclpy</exec_depend>
  <exec_depend>geometry_msgs</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>nav_msgs</exec_depend>
  <exec_depend>dobi_npc_msgs</exec_depend>
```

- [ ] **Step 3: 빌드** — `cd ~/physical-ai-repo-3 && colcon build --packages-up-to mobility_controller --symlink-install 2>&1 | tail -6` → `dobi_npc_msgs` + `mobility_controller` 성공(에러 0).

- [ ] **Step 4: 실행파일 등록 확인** — `ls ~/physical-ai-repo-3/install/mobility_controller/lib/mobility_controller/scout_follow_controller && echo REGISTERED` → `REGISTERED`.

- [ ] **Step 5: 전체 단위테스트 (빌드+소스 후)** — `cd ~/physical-ai-repo-3 && source install/setup.bash && pytest src/controller/mobility_controller/test/test_scout_follow_control.py -q` → 26 passed (이제 모듈의 ROS import 해결됨).

- [ ] **Step 6: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/CMakeLists.txt src/controller/mobility_controller/package.xml
git -C ~/physical-ai-repo-3 commit -m "build(scout-follow): scout_follow_controller python install + deps"
```

---

### Task 7: launch — person_tracking(@scout) + scout_follow_controller

**Files:** Create `launch/scout_unified_follow.launch.py`

- [ ] **Step 1: launch 작성**
```python
"""scout_unified_follow — person_tracking(@scout 영상) + scout_follow_controller.

scout 스택(scout_cam+scout_servo+call_detector)은 ~/scout_reactor 별 터미널.
person_tracking_pkg(doby_controller) + 본 패키지 모두 source 필요. 동일 ROS_DOMAIN_ID.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    scout_image = DeclareLaunchArgument(
        'scout_image_topic', default_value='/scout_cam/image_raw')
    use_compressed = DeclareLaunchArgument('use_compressed', default_value='true')
    angular_sign = DeclareLaunchArgument(
        'angular_sign', default_value='1',
        description='차체 회전 부호 — 라이브 1회 검증 후 확정')

    person_tracking = Node(
        package='person_tracking_pkg', executable='person_tracking_node',
        name='person_tracking_node', output='screen',
        parameters=[{
            'input_topic': LaunchConfiguration('scout_image_topic'),
            'use_compressed': LaunchConfiguration('use_compressed'),
            'publish_visualization': True,
        }],
    )
    controller = Node(
        package='mobility_controller', executable='scout_follow_controller',
        name='scout_follow_controller', output='screen',
        parameters=[{
            'image_width': 640,
            'image_height': 480,
            'angular_sign': LaunchConfiguration('angular_sign'),
            'max_linear': 0.15,
            'max_angular': 0.5,
            'target_bh': 0.45,
            'bh_stop': 0.75,
        }],
    )
    return LaunchDescription([scout_image, use_compressed, angular_sign,
                              person_tracking, controller])
```

- [ ] **Step 2: 구문 검사** — `python3 -m py_compile src/controller/mobility_controller/launch/scout_unified_follow.launch.py && echo OK` → `OK`.

- [ ] **Step 3: 빌드 + 파싱 스모크** — `cd ~/physical-ai-repo-3 && colcon build --packages-select mobility_controller --symlink-install >/dev/null 2>&1; source install/setup.bash && ros2 launch mobility_controller scout_unified_follow.launch.py --show-args 2>&1 | head` → 인자 표시, 파싱 에러 없음.

- [ ] **Step 4: 커밋 (제시)**
```bash
git -C ~/physical-ai-repo-3 add src/controller/mobility_controller/launch/scout_unified_follow.launch.py
git -C ~/physical-ai-repo-3 commit -m "feat(scout-follow): scout_unified_follow launch"
```

---

### Task 8: 벤치 검증 (PC, 차체 없음, DOMAIN=99) — 수동

> ⚠ 실차(DOMAIN=22)는 별도. §0-A RPi 명시 허가 + 입회 + joy/e_stop 대기. 본 태스크는 PC 벤치 `/follow/cmd_vel` 관찰까지만. by-id 로 scout PTZ(=`USB 2.0 Camera`) 디바이스 확인 후 진행.

- [ ] **Step 1: scout 스택** (터미널 A, ~/scout_reactor) — `v4l2-ctl --list-devices` 로 scout 디바이스 확인 → `export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1; bash scripts/run_palm.sh --device=<scout>`
- [ ] **Step 2: follow** (터미널 B) — 두 워크스페이스 source: `source install/setup.bash; source src/controller/doby_controller/install/setup.bash; export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1; ros2 launch mobility_controller scout_unified_follow.launch.py`
- [ ] **Step 3: 신호 관찰** — `ros2 topic echo /person_tracking/tracks --once`(track_id+bbox), `ros2 topic echo /follow/cmd_vel`. 사람 좌/우/원근 이동 → w 부호(angular_sign 검증), 멀면 v>0, 가까우면 v→0, **후진 절대 X**. 핸드오프(손들기→서보 0→FOLLOW) 확인.
- [ ] **Step 4: 결과 기록** — `docs/daily/2026-05-29_scout_unified_follow_bench.md` 에 신호·부호·target_bh/bh_stop 캘리브.

---

## Self-Review
- **스펙 커버리지**: HANDOFF(co-rotation)=T3+T5 / person_tracking@scout=T7 / 컨트롤러(cx→w, bh→v 후진금지, 가드)=T1·T2·T5 / 안전·후진금지=T2·T5 / 테스트=T8. 실차는 의도적 플랜 밖.
- **dev 정합**: PersonTrack.bbox=float[4] 파싱(T5 `_on_tracks`) ✓ / mobility_controller python install 처음부터(T6) ✓ / vision_msgs 제거 ✓.
- **플레이스홀더**: 없음. target_bh/bh_stop 은 T8 캘리브 명시.
- **타입 일관성**: 순수함수 시그니처 T1~4 정의 ↔ T5 호출 1:1, `tracks` 튜플 `(track_id,cx,cy,w,h)` 일관. ROS import 는 T5 에서만 → T1~4 ROS-free pytest, 전체 pytest 는 T6 빌드 후.
