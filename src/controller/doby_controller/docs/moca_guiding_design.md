# MOCA Guiding Mode 설계 문서

> **문서 ID**: `moca_guiding_design.md`
> **버전**: v1.0 (2026-05-16)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2.2.4
> **관련 문서**: `moca_5state_fsm_spec.md` §2.4 (S_guiding)
> **구현 대상**:
> - `dobi_npc_bringup/guiding_controller_node.py` (신규)
> - `dobi_npc_bringup/launch/mode_guiding.launch.py` (신규)
> - `dobi_npc_bringup/launch/mode_follow.launch.py` (deprecation wrapper)

---

## 0. 본 문서의 범위

본 문서는 `guiding` 모드 — 로봇이 결제 완료한 고객을 빈 테이블까지 *앞장서서 안내*하는 행동 — 의 알고리즘과 구현 방침을 정의한다.

### 0.1 본 문서가 다루는 것

1. follow와 guiding의 알고리즘 차이 (왜 신규 노드인가)
2. guiding_controller_node 내부 FSM
3. 고객 lock-on / 추적 / lag 감지 로직
4. Nav2 NavigateToPose 연동
5. 발화/표정 시점 (UtterRequest priority)
6. mode_guiding.launch.py + 기존 mode_follow.launch.py deprecation
7. 테스트 시나리오

### 0.2 본 문서가 다루지 않는 것

- POS가 어떻게 guide 요청을 보내는지 (`moca_opserver_api_spec.md` §2.5.6)
- 빈 테이블 선택 알고리즘 (OpServer table_registry)
- 음성/표정 모듈 내부 (기존 dialog/face_avatar 노드)

---

## 1. follow vs guiding — 방향이 정반대

### 1.1 기존 follow_controller_node (참고)

```
역할:  손님이 앞장서고 로봇이 따라간다 (reactive)

입력:  person_detector 결과 (사람 위치)
출력:  /cmd_vel (P-제어로 사람 따라가기)

알고리즘:
  while True:
      target = nearest_person_in_camera()
      if target.distance > FOLLOW_DIST:
          cmd_vel.linear = K_lin * (distance - FOLLOW_DIST)
          cmd_vel.angular = K_ang * angular_error
      else:
          cmd_vel = 0
      publish(cmd_vel)
```

특징:
- Nav2 미사용 (로컬 reactive control)
- 목적지 모름 (사람이 어디로 가든 따라감)
- 사람 시야 잃으면 멈춤

### 1.2 guiding_controller_node (신규)

```
역할:  로봇이 앞장서고 손님이 따라오는지 확인 (supervised)

입력:  target_table (params), customer_id, person_detector
출력:  Nav2 goal + /utter/request (발화) + /set_emotion (표정)

알고리즘:
  state = LOCK_ON
  send_nav_goal(target_table)
  while True:
      if state == LOCK_ON:
          # 카운터 앞에서 customer bbox 확보
          if found_customer():
              state = MOVING
              utter("저를 따라오세요!")

      elif state == MOVING:
          # Nav2가 알아서 운전. 우리는 customer 추적만.
          if customer_in_view():
              update_customer_pose()
              if customer_lag > LAG_MAX:
                  pause_nav()
                  utter("천천히 따라오세요")
                  state = WAITING

          elif customer_lost_for > LOST_TIMEOUT:
              cancel_nav()
              utter("어디 가셨어요? 다시 와주세요")
              state = ABORTED

      elif state == WAITING:
          if customer_lag < LAG_MIN:
              resume_nav()
              state = MOVING

      elif nav_arrived():
          utter("여기서 편하게 즐기세요")
          set_emotion(happy)
          state = DONE
```

특징:
- **Nav2 NavigateToPose 사용** (목적지 알고 있음)
- **사람을 추적은 하지만 따라가지 않음** (속도 영향만 줌)
- 사람 시야 잃으면 일시정지 → 발화 → 복귀 대기 → 재개

### 1.3 코드 재사용 < 30%

| 컴포넌트 | follow | guiding | 재사용? |
|---|---|---|---|
| person_detector 인터페이스 | ✓ | ✓ | ✓ (양쪽 다 person bbox 구독) |
| /cmd_vel 직접 발행 | ✓ | ✗ (Nav2가 함) | ✗ |
| P-제어 루프 | ✓ | ✗ | ✗ |
| Nav2 클라이언트 | ✗ | ✓ | ✗ |
| 발화 명령 | (적음) | (많음) | △ |
| 안전 가드 | ✓ | ✓ | △ |

→ guiding은 신규 노드로 작성. follow 코드를 import해서 일부 헬퍼만 재사용.

---

## 2. guiding_controller_node 설계

### 2.1 인터페이스

#### 2.1.1 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `tables_yaml` | string | (auto) | tables.yaml 경로 |
| `params_json` | string | "" | mode_manager가 전달한 JSON |
| `customer_init_position` | string | "counter" | "counter" \| "current_robot_pose" |
| `lock_on_timeout_sec` | float | 10.0 | customer 초기 lock-on 제한 시간 |
| `lag_distance_max_m` | float | 1.5 | 이거 넘으면 WAITING |
| `lag_distance_min_m` | float | 1.0 | WAITING에서 이거 미만이면 재개 |
| `customer_lost_timeout_sec` | float | 8.0 | 시야 안 보인 채로 이 시간 지나면 ABORTED |
| `arrival_dwell_sec` | float | 5.0 | DONE 진입 후 발화/표정 dwell |
| `utter_cooldown_sec` | float | 5.0 | 같은 발화 재호출 방지 |
| `face_when_idle` | string | "neutral" | 도착 후 표정 |
| `face_when_guiding` | string | "happy" | 안내 중 표정 |
| `nav_overall_timeout_sec` | float | 90.0 | 전체 Nav2 진행 제한 |

#### 2.1.2 구독

| 토픽 | 타입 | 용도 |
|---|---|---|
| `/person_detector/persons` | (TBD: vision_msgs/Detection2DArray 또는 custom) | customer 추적 |
| `/odom` | nav_msgs/Odometry | 로봇 위치 → 고객과의 거리 계산 |
| `/rapport/event` | dobi_npc_msgs/RapportEvent | abort_trigger |

> **주의**: `person_detector` 인터페이스는 기존 코드에서 정확한 타입 확인이 필요하다. M2 작업 시 follow_controller_node.py에서 참고. 본 문서는 `vision_msgs/Detection2DArray`를 가정한다.

#### 2.1.3 발행

| 토픽 | 타입 | 빈도 | 용도 |
|---|---|---|---|
| `/guiding/state` | dobi_npc_msgs/GuidingState (신규) | 1Hz | 진행 상황 |
| `/utter/request` | dobi_npc_msgs/UtterRequest | event | 발화 |
| `/set_emotion` | dobi_npc_msgs/EmotionState | event | 표정 |

#### 2.1.4 액션 클라이언트

| 액션 | 타입 | 용도 |
|---|---|---|
| `/navigate_to_pose` | nav2_msgs/action/NavigateToPose | 테이블 이동 |

### 2.2 신규 메시지

#### 2.2.1 `dobi_npc_msgs/msg/GuidingState.msg`

```
# Guiding 모드 진행 상황
std_msgs/Header header
string current_state          # "lock_on"|"moving"|"waiting"|"arrived"|"aborted"
string target_table           # "T01"~"T05"
string customer_id            # 외부 발급된 ID

# 고객 추적 정보
bool customer_in_sight        # 현 프레임에서 보이는지
float32 customer_distance_m   # 로봇 → 고객 거리 (시야 내일 때만)
float32 customer_lag_m        # 로봇 진행방향 기준 뒤처짐 (음수면 앞섬)
builtin_interfaces/Time customer_last_seen

# Nav2 진행 정보
float32 distance_to_target    # 로봇 → target_table
float32 progress              # 0.0~1.0 (목적지까지 진행률 추정)

# Timing
builtin_interfaces/Time started_at
string last_utter_text        # 마지막 발화 (디버깅)
```

### 2.3 내부 FSM

```
       ┌─────────┐
       │  INIT   │
       └────┬────┘
            │ params 파싱, target_table 검증
            ▼
       ┌────────────┐
       │  LOCK_ON   │ 카운터 앞에서 customer bbox 확보
       └─────┬──────┘
             │ customer 검출
             ▼
       ┌────────────┐
       │   MOVING   │◀──────┐ Nav2 goal 송신, 추적 시작
       └─────┬──────┘       │
             │ customer_lag │ customer_lag
             │  > MAX        │  < MIN
             ▼               │
       ┌────────────┐        │
       │  WAITING   ├────────┘ Nav2 pause + 발화
       └─────┬──────┘
             │ customer_lost
             │ for > LOST_TIMEOUT
             ▼
       ┌────────────┐
       │  ABORTED   │ Nav2 cancel + 발화 + 5초 dwell
       └────────────┘

       ┌────────────┐
       │  MOVING    │
       └─────┬──────┘
             │ nav_arrived
             ▼
       ┌────────────┐
       │  ARRIVED   │ 발화 "여기서 즐기세요" + 표정 happy
       └─────┬──────┘
             │ 5초 dwell
             ▼
       ┌────────────┐
       │   DONE     │ /guiding/state="arrived" 유지 발행
       └────────────┘
              │
              ▼
       (OpServer가 SetMode('idle') 호출 → mode_manager가 SIGTERM)
```

### 2.4 상태별 행동

| 상태 | entry | during | exit | 다음 상태 트리거 |
|---|---|---|---|---|
| INIT | params 파싱, table_id 검증 | (즉시) | — | → LOCK_ON |
| LOCK_ON | 카메라 ROI 설정, utter "잠시만요" | person_detector 결과에서 가장 가까운 사람을 customer로 lock | — | 검출 성공 → MOVING / 10초 무검출 → ABORTED |
| MOVING | Nav2 goal 송신, utter "저를 따라오세요!", face=happy | customer 거리/lag 계산, Nav2 status 모니터 | — | nav SUCCEEDED → ARRIVED / lag > MAX → WAITING / lost > 8초 → ABORTED |
| WAITING | Nav2 active goal cancel, utter "천천히 따라오세요" | customer lag 모니터, lost 카운터 | — | lag < MIN → MOVING(goal 재송신) / lost > 8초 → ABORTED |
| ARRIVED | utter "여기서 즐기세요" + emotion happy | 5초 dwell | — | dwell 종료 → DONE |
| DONE | /guiding/state="arrived" 발행 유지 | — | — | (외부 SIGTERM 대기) |
| ABORTED | Nav2 cancel, utter "어디 가셨어요" + emotion sad, 5초 dwell | — | — | (외부 SIGTERM 대기) |

### 2.5 customer lock-on 알고리즘

```python
def find_customer_candidate(persons, robot_pose) -> Optional[dict]:
    """
    LOCK_ON 상태에서 가장 가까운 사람을 customer로 선택.

    person: {bbox: ..., distance: ..., x_world: ..., y_world: ...}
    """
    if not persons:
        return None

    # 카운터 영역 ROI 필터 (옵션 — M3): 카운터 근접만
    # candidates = [p for p in persons if is_near_counter(p)]
    candidates = persons

    if not candidates:
        return None

    # 가장 가까운 사람
    candidate = min(candidates, key=lambda p: p['distance'])
    return candidate
```

lock-on 성공 시 `customer_track_id`로 그 사람의 ID를 보존하고, 이후 프레임에서는 같은 ID만 추적. ID 추정은 person_detector가 BYTE-track 또는 단순 IOU 매칭으로 제공한다고 가정 (M2 단순화: ID 추적 안 하고 매 프레임 최근접 사람으로 갱신 — 단점: 다른 손님이 끼어들면 헷갈림).

### 2.6 lag 계산

```python
def compute_customer_lag(customer_world_xy, robot_pose, target_pose) -> float:
    """
    로봇 진행방향 축에 customer 위치를 투영. 음수면 앞섬, 양수면 뒤처짐.

    direction = (target - robot).normalized()
    lag = -dot(customer - robot, direction)
    """
    import math
    dx_target = target_pose.x - robot_pose.x
    dy_target = target_pose.y - robot_pose.y
    norm = math.hypot(dx_target, dy_target)
    if norm < 1e-3:
        return 0.0
    dirx, diry = dx_target / norm, dy_target / norm

    dx_cust = customer_world_xy[0] - robot_pose.x
    dy_cust = customer_world_xy[1] - robot_pose.y
    lag = -(dx_cust * dirx + dy_cust * diry)
    return lag  # >0: 뒤처짐, <0: 앞섬
```

### 2.7 의사 코드

```python
# dobi_npc_bringup/guiding_controller_node.py

import json
import math
import threading
from enum import Enum
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
import yaml

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav2_msgs.action import NavigateToPose
from vision_msgs.msg import Detection2DArray   # 가정

from dobi_npc_msgs.msg import (
    GuidingState, RapportEvent, UtterRequest, EmotionState,
)


class State(str, Enum):
    INIT = 'init'
    LOCK_ON = 'lock_on'
    MOVING = 'moving'
    WAITING = 'waiting'
    ARRIVED = 'arrived'
    DONE = 'done'
    ABORTED = 'aborted'


class GuidingController(Node):
    def __init__(self):
        super().__init__('guiding_controller')

        # 파라미터 (선언 생략 — §2.1.1 참조)
        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter('lag_distance_max_m', 1.5)
        self.declare_parameter('lag_distance_min_m', 1.0)
        self.declare_parameter('customer_lost_timeout_sec', 8.0)
        self.declare_parameter('lock_on_timeout_sec', 10.0)
        self.declare_parameter('arrival_dwell_sec', 5.0)
        self.declare_parameter('utter_cooldown_sec', 5.0)

        # 상태
        self._state = State.INIT
        self._target_table_id: Optional[str] = None
        self._customer_id: Optional[str] = None
        self._state_entered_at = self.get_clock().now()
        self._last_utter_at: dict[str, rclpy.time.Time] = {}
        self._last_seen_at: Optional[rclpy.time.Time] = None
        self._customer_xy: Optional[tuple] = None
        self._robot_pose: Optional[tuple] = None  # (x, y, yaw)
        self._target_pose: Optional[PoseStamped] = None
        self._tables: dict = {}
        self._nav_goal_handle = None

        # tables.yaml + params 파싱
        self._load_tables()
        self._parse_params()
        if self._target_table_id is None:
            self.get_logger().error('No target_table in params; aborting')
            rclpy.shutdown()
            return

        # ROS
        self.pub_state = self.create_publisher(GuidingState, '/guiding/state', 10)
        self.pub_utter = self.create_publisher(UtterRequest, '/utter/request', 10)
        self.pub_emo = self.create_publisher(EmotionState, '/set_emotion', 10)
        self.sub_persons = self.create_subscription(
            Detection2DArray, '/person_detector/persons',
            self._on_persons, 10)
        self.sub_odom = self.create_subscription(
            Odometry, '/odom', self._on_odom, 10)
        self.sub_rapport = self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)

        self.act_nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')

        # 1Hz state publish + 20Hz tick
        self.create_timer(1.0, self._publish_state)
        self.create_timer(0.05, self._tick)

        self.get_logger().info(
            f'guiding_controller ready, target={self._target_table_id}, '
            f'customer={self._customer_id}')
        self._transition(State.LOCK_ON)

    def _parse_params(self):
        params_json = self.get_parameter('params_json').value
        if not params_json:
            return
        try:
            d = json.loads(params_json)
            self._target_table_id = d.get('target_table')
            self._customer_id = d.get('customer_id', '')
        except json.JSONDecodeError as e:
            self.get_logger().error(f'params parse failed: {e}')

    def _load_tables(self):
        path = self.get_parameter('tables_yaml').value
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        for t in data['tables']:
            self._tables[t['id']] = t

    # ---- FSM ----
    def _transition(self, new_state: State):
        if new_state == self._state:
            return
        prev = self._state
        self._state = new_state
        self._state_entered_at = self.get_clock().now()
        self.get_logger().info(f'state: {prev} → {new_state}')

        if new_state == State.LOCK_ON:
            self._utter('잠시만요, 안내해 드릴게요')
            self._set_emotion('neutral')
        elif new_state == State.MOVING:
            self._utter('저를 따라오세요!')
            self._set_emotion('happy')
            self._send_nav_goal_to_table()
        elif new_state == State.WAITING:
            self._utter('천천히 따라오세요')
            self._cancel_nav()
        elif new_state == State.ARRIVED:
            self._utter('여기서 편하게 즐기세요')
            self._set_emotion('happy')
        elif new_state == State.DONE:
            pass
        elif new_state == State.ABORTED:
            self._utter('어디 가셨어요? 카운터로 다시 와주세요')
            self._set_emotion('sad')
            self._cancel_nav()

    def _tick(self):
        now = self.get_clock().now()
        elapsed = (now - self._state_entered_at).nanoseconds / 1e9

        if self._state == State.LOCK_ON:
            if self._customer_xy is not None:
                self._transition(State.MOVING)
            elif elapsed > self.get_parameter('lock_on_timeout_sec').value:
                self.get_logger().warn('lock_on timeout')
                self._transition(State.ABORTED)

        elif self._state == State.MOVING:
            # customer 시야 잃음 체크
            if (self._last_seen_at is not None
                and (now - self._last_seen_at).nanoseconds / 1e9
                    > self.get_parameter('customer_lost_timeout_sec').value):
                self.get_logger().warn('customer lost > timeout')
                self._transition(State.ABORTED)
                return

            # lag 체크
            if self._robot_pose and self._customer_xy and self._target_pose:
                lag = self._compute_lag()
                if lag > self.get_parameter('lag_distance_max_m').value:
                    self._transition(State.WAITING)

        elif self._state == State.WAITING:
            if (self._last_seen_at is not None
                and (now - self._last_seen_at).nanoseconds / 1e9
                    > self.get_parameter('customer_lost_timeout_sec').value):
                self._transition(State.ABORTED)
                return
            # lag 회복 확인
            if self._robot_pose and self._customer_xy and self._target_pose:
                lag = self._compute_lag()
                if lag < self.get_parameter('lag_distance_min_m').value:
                    self.get_logger().info(f'lag recovered ({lag:.2f}), resume')
                    self._transition(State.MOVING)

        elif self._state == State.ARRIVED:
            if elapsed > self.get_parameter('arrival_dwell_sec').value:
                self._transition(State.DONE)

    # ---- Nav2 ----
    def _send_nav_goal_to_table(self):
        if self._target_table_id not in self._tables:
            self.get_logger().error(f'unknown table: {self._target_table_id}')
            self._transition(State.ABORTED)
            return
        t = self._tables[self._target_table_id]
        ps = PoseStamped()
        ps.header.frame_id = t['pose']['frame_id']
        ps.header.stamp = self.get_clock().now().to_msg()
        x = float(t['pose']['x'])
        y = float(t['pose']['y'])
        yaw = float(t['pose'].get('yaw', 0.0))
        approach = float(t.get('approach_dist', 0.5))
        ps.pose.position.x = x - approach * math.cos(yaw)
        ps.pose.position.y = y - approach * math.sin(yaw)
        ps.pose.orientation.z = math.sin(yaw / 2.0)
        ps.pose.orientation.w = math.cos(yaw / 2.0)
        self._target_pose = ps

        goal = NavigateToPose.Goal()
        goal.pose = ps
        f = self.act_nav.send_goal_async(goal)
        f.add_done_callback(self._on_nav_accepted)

    def _on_nav_accepted(self, future):
        gh = future.result()
        if not gh.accepted:
            self.get_logger().warn('nav goal rejected')
            self._transition(State.ABORTED)
            return
        self._nav_goal_handle = gh
        rf = gh.get_result_async()
        rf.add_done_callback(self._on_nav_result)

    def _on_nav_result(self, future):
        result = future.result()
        # 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
        if result.status == 4 and self._state == State.MOVING:
            self._transition(State.ARRIVED)
        elif result.status == 5:
            pass  # cancel은 우리가 의도한 경우 (WAITING 진입 시)
        else:
            if self._state == State.MOVING:
                self.get_logger().warn(f'nav failed status={result.status}')
                self._transition(State.ABORTED)

    def _cancel_nav(self):
        if self._nav_goal_handle is not None:
            self._nav_goal_handle.cancel_goal_async()
            self._nav_goal_handle = None

    # ---- 감지 콜백 ----
    def _on_persons(self, msg: Detection2DArray):
        if not msg.detections:
            return
        # M2 단순화: 가장 가까운 사람 = customer
        # (M3: ID tracking으로 lock-on 안정화)
        # 가까운 사람 = bbox 면적 큰 사람 가정 (depth 미사용 시)
        # 또는 카메라 보정 + ground projection으로 거리 추정
        closest = self._find_closest_person(msg.detections)
        if closest is None:
            return
        # ground projection (간이): bbox 하단 픽셀 → 카메라 외부보정 → world
        xy_world = self._project_to_world(closest)
        if xy_world is None:
            return
        self._customer_xy = xy_world
        self._last_seen_at = self.get_clock().now()

    def _on_odom(self, msg: Odometry):
        from tf_transformations import euler_from_quaternion
        q = msg.pose.pose.orientation
        _, _, yaw = euler_from_quaternion([q.x, q.y, q.z, q.w])
        self._robot_pose = (
            msg.pose.pose.position.x,
            msg.pose.pose.position.y,
            yaw,
        )

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type == 'abort_trigger':
            self.get_logger().warn('rapport abort')
            self._transition(State.ABORTED)

    def _find_closest_person(self, detections) -> Optional[object]:
        """가장 큰 bbox = 가장 가까운 사람 (depth 미사용 휴리스틱)"""
        return max(
            detections,
            key=lambda d: d.bbox.size_x * d.bbox.size_y,
            default=None,
        )

    def _project_to_world(self, detection) -> Optional[tuple]:
        """간이 ground projection. M2 placeholder, M3 정밀화."""
        # TODO: TF + camera_info + bbox 하단 중심 픽셀 → 지면 평면 교차 → map frame
        # 임시: 로봇 바로 뒤 1m 가정 (의미는 없으나 lag 계산이 동작은 함)
        if self._robot_pose is None:
            return None
        rx, ry, yaw = self._robot_pose
        return (rx - 1.0 * math.cos(yaw), ry - 1.0 * math.sin(yaw))

    def _compute_lag(self) -> float:
        rx, ry, _ = self._robot_pose
        tx = self._target_pose.pose.position.x
        ty = self._target_pose.pose.position.y
        norm = math.hypot(tx - rx, ty - ry)
        if norm < 1e-3:
            return 0.0
        dirx, diry = (tx - rx) / norm, (ty - ry) / norm
        cx, cy = self._customer_xy
        return -((cx - rx) * dirx + (cy - ry) * diry)

    # ---- 발화/표정 ----
    def _utter(self, text: str, priority: int = 7):
        cd = self.get_parameter('utter_cooldown_sec').value
        now = self.get_clock().now()
        last = self._last_utter_at.get(text)
        if last is not None and (now - last).nanoseconds / 1e9 < cd:
            return
        msg = UtterRequest()
        msg.text = text
        msg.priority = priority
        self.pub_utter.publish(msg)
        self._last_utter_at[text] = now

    def _set_emotion(self, expression: str):
        msg = EmotionState()
        msg.expression = expression
        self.pub_emo.publish(msg)

    # ---- state publish ----
    def _publish_state(self):
        msg = GuidingState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.current_state = self._state.value
        msg.target_table = self._target_table_id or ''
        msg.customer_id = self._customer_id or ''
        msg.customer_in_sight = self._customer_xy is not None
        if (self._customer_xy is not None and self._robot_pose is not None):
            rx, ry, _ = self._robot_pose
            cx, cy = self._customer_xy
            msg.customer_distance_m = float(math.hypot(cx - rx, cy - ry))
        else:
            msg.customer_distance_m = -1.0
        if (self._customer_xy is not None and self._robot_pose is not None
                and self._target_pose is not None):
            msg.customer_lag_m = float(self._compute_lag())
        else:
            msg.customer_lag_m = 0.0
        if self._last_seen_at is not None:
            msg.customer_last_seen = self._last_seen_at.to_msg()
        msg.distance_to_target = self._distance_to_target()
        msg.progress = 0.0  # M3: Nav2 feedback에서 추정
        self.pub_state.publish(msg)

    def _distance_to_target(self) -> float:
        if self._target_pose is None or self._robot_pose is None:
            return -1.0
        rx, ry, _ = self._robot_pose
        tx = self._target_pose.pose.position.x
        ty = self._target_pose.pose.position.y
        return float(math.hypot(tx - rx, ty - ry))


def main(args=None):
    rclpy.init(args=args)
    node = GuidingController()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node._cancel_nav()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
```

---

## 3. mode_guiding.launch.py 설계

```python
"""mode_guiding.launch.py — 동행 안내 모드 stack."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='JSON params with target_table and customer_id')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        # person_detector를 별도 노드로 실행 (기존 follow에서 사용하던 것 재사용 가정)
        # 만약 별도 검출기가 없다면 여기서 함께 spawn
        # Node(
        #     package='person_detector_pkg',
        #     executable='person_detector',
        #     name='person_detector',
        #     output='screen',
        # ),

        Node(
            package='dobi_npc_bringup',
            executable='guiding_controller',
            name='guiding_controller',
            output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'lag_distance_max_m': 1.5,
                'lag_distance_min_m': 1.0,
                'customer_lost_timeout_sec': 8.0,
                'lock_on_timeout_sec': 10.0,
                'arrival_dwell_sec': 5.0,
                'utter_cooldown_sec': 5.0,
            }],
        ),
    ])
```

`setup.py`:
```python
entry_points={
    'console_scripts': [
        # ... 기존 ...
        'guiding_controller = dobi_npc_bringup.guiding_controller_node:main',
    ],
},
```

---

## 4. mode_follow.launch.py — Deprecation Wrapper

기존 `follow` 모드는 점진적 폐기. 호환을 위해 wrapper 유지 (M3 종료까지).

```python
"""mode_follow.launch.py — DEPRECATED.

This launch file is a thin wrapper that forwards to mode_guiding.launch.py.
The 'follow' mode is being renamed to 'guiding'. Please update callers to
use SetMode('guiding', ...) directly.

Removal target: 2026-07-04 (end of M3 phase)
"""
import logging

from launch import LaunchDescription
from launch.actions import (
    IncludeLaunchDescription, LogInfo, DeclareLaunchArgument,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='JSON params (forwarded to guiding)')

    guiding_launch = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'),
        'launch', 'mode_guiding.launch.py',
    ])

    return LaunchDescription([
        LogInfo(msg=(
            '\033[33m[DEPRECATED]\033[0m mode_follow.launch.py is deprecated. '
            'Use mode_guiding.launch.py directly. '
            'This wrapper will be removed at the end of M3 phase (2026-07-04).'
        )),
        params_arg,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(guiding_launch),
            launch_arguments={
                'params_json': LaunchConfiguration('params_json'),
            }.items(),
        ),
    ])
```

mode_manager의 LEGACY_MODE_ALIAS 처리와 별개로, launch 호출 측에서 직접 `mode_follow.launch.py`를 띄우는 코드(외부 스크립트)도 호환되도록 한다.

---

## 5. 발화 정책

### 5.1 우선순위

`UtterRequest.priority` 필드 사용. 기존 코드의 dialog manager가 우선순위 큐로 처리한다고 가정.

| 발화 | priority | 설명 |
|---|---|---|
| "잠시만요" (lock_on) | 7 | 일반 안내 |
| "저를 따라오세요!" (moving 시작) | 8 | 행동 지시 |
| "천천히 따라오세요" (waiting) | 8 | 행동 지시 |
| "여기서 편하게 즐기세요" (arrived) | 7 | 일반 안내 |
| "어디 가셨어요?" (aborted) | 9 | 긴급 호출 |

운영자 수동 utter는 priority=10 (모두 압도).

### 5.2 쿨다운

같은 텍스트 발화는 `utter_cooldown_sec`(기본 5초) 안에 재발화 금지. WAITING 상태에서 customer가 들어왔다 나갔다 진동 시에도 같은 문구 반복 안 되도록.

쿨다운 키는 text 문자열 자체. M3에서 카테고리(`utter_category`) 기반으로 개선 검토.

### 5.3 표정 매핑

| state | expression |
|---|---|
| LOCK_ON | neutral |
| MOVING | happy |
| WAITING | confused |
| ARRIVED | happy |
| ABORTED | sad |

`EmotionState.expression`은 기존 8종 (`neutral, happy, sad, surprised, confused, excited, sleepy, focused`) 중 사용.

---

## 6. 안전 / 가드 통합

### 6.1 Nav2 collision_monitor 의존

guiding은 자체 충돌 회피 로직 없다. Nav2의 `collision_monitor` 패키지가 활성화되어 있다고 가정 (Vic Pinky 표준 stack).

### 6.2 customer 너무 가까이 (< 0.3m)

M2: 처리 안 함 (Nav2 본인이 알아서 감속).
M3: customer_distance < 0.3 → 즉시 stop + utter "잠시 비켜주세요" + 5초 후 재개.

### 6.3 비상정지

mode_manager가 `OperatorCommand{command_type:"stop_emergency"}` 받으면 SIGTERM. guiding_controller는 cleanup 시 `_cancel_nav()` 수행.

### 6.4 rapport abort_trigger

`/rapport/event abort_trigger` 수신 시 ABORTED 전이. 발화/cancel.

---

## 7. ground projection의 한계와 M3 개선

### 7.1 M2 현재: 휴리스틱 사용

가장 큰 bbox = 가장 가까운 사람으로 가정. customer xy는 로봇 뒤쪽 1m 픽스(plaeholder).

**문제**:
- lag 계산이 의미 없음 (항상 거의 1.0m)
- WAITING 진입/해제 trigger가 신뢰성 없음

**완화**: M2는 *손님이 따라오는 것을 가정*하고 단순 진행. customer_lost_timeout 8초만 신뢰성 확보 → 8초간 person bbox 안 보이면 abort.

### 7.2 M3 개선 옵션

| 방법 | 정확도 | 구현 난이도 |
|---|---|---|
| RGBD 카메라 depth 사용 | 높음 | 중 (카메라 변경) |
| TF + bbox 하단 → 지면 ray projection | 중 | 중 (camera_info + tf 처리) |
| LiDAR + 카메라 fusion | 매우 높음 | 높음 |
| Wi-Fi RSSI of customer 휴대폰 | 낮음 | 매우 높음 (앱 필요) |
| 그냥 follow 모드처럼 reactive (방향 반대) | 중 | 낮음 (다음 옵션) |

**M3 권장 경로**: TF + ray projection. Vic Pinky의 USB 카메라 (단안)에서 시작.

### 7.3 fallback: reactive guiding

ground projection 정확도가 낮으면 *Nav2를 portion으로만 사용*하고 reactive 부분 추가:

```
세부 알고리즘:
  Nav2 target → waypoint 추출 (5m 간격)
  로봇은 다음 waypoint로 진행하되, 매 1초 customer 보이는지 체크
  customer_in_sight=False > 3초 → 정지 + utter
```

이 경우 Nav2 NavigateToPose가 아닌 NavigateThroughPoses + manual waypoint pause 처리. 복잡도 ↑.

**판단**: M2는 ground projection 정확도 떨어져도 진행, M3에서 RGBD 또는 TF projection 정밀화. 그래도 부족하면 M4에서 reactive guiding 검토.

---

## 8. 단계별 구현

### 8.1 M1 후반 — 인터페이스 준비

- [ ] GuidingState.msg 정의 + 빌드
- [ ] mode_manager에 'guiding' 추가 + LEGACY_MODE_ALIAS('follow':'guiding')
- [ ] mode_follow.launch.py를 deprecation wrapper로 교체
- [ ] mode_guiding.launch.py skeleton (controller만 spawn)

### 8.2 M2 Week 3 — controller 기본

- [ ] guiding_controller_node.py: FSM INIT → LOCK_ON → MOVING → ARRIVED → DONE
- [ ] Nav2 NavigateToPose 클라이언트 동작
- [ ] tables.yaml에서 target_table pose 조회
- [ ] /utter/request 발행
- [ ] 단순 Mock detector로 customer xy 임의 발행해서 lag 계산 검증

### 8.3 M2 Week 4 — customer 추적

- [ ] person_detector 토픽 (또는 기존 follow에서 사용했던 것) 연동
- [ ] customer_lost_timeout → ABORTED 시나리오 작동
- [ ] lag → WAITING 전이 (heuristic projection 기반)

### 8.4 M3 — 정밀화

- [ ] TF + ray projection으로 customer ground pose 정확화
- [ ] customer ID tracking (BYTE-track 등)
- [ ] 멀티 손님 시나리오 (party_size > 1) 검토 — 한 명만 lock-on
- [ ] 음성 인식 보조 ("앞으로 가세요" 같은 응답)

### 8.5 M4 — 실 손님 시나리오

- [ ] 매장 카운터 위치 보정
- [ ] 실 손님 1주 운영 결과 분석
- [ ] 안내 평균 시간 / abort 비율 / customer 만족도 (수동)

---

## 9. 테스트 시나리오

### 9.1 단위 테스트 (test_guiding_controller.py)

- LOCK_ON 10초 무검출 → ABORTED
- MOVING 중 customer_lost > 8초 → ABORTED
- MOVING 중 lag > 1.5m → WAITING
- WAITING 중 lag < 1.0m → MOVING (재goal 송신)
- Nav2 status SUCCEEDED → ARRIVED → 5초 dwell → DONE
- rapport abort_trigger → ABORTED + Nav2 cancel
- 잘못된 target_table → 즉시 ABORTED

### 9.2 통합 시나리오

**시나리오 G1: 정상 안내**
```
1. customer 카운터 앞에 위치 (Mock detector 발행)
2. SetMode('guiding', {"target_table":"T02","customer_id":"C-test"})
3. 검증: state=lock_on → moving (1초 내)
4. customer가 로봇 따라감 (Mock detector가 로봇 뒤 1m 유지)
5. Nav2가 T02 도착 → state=arrived → 5초 dwell → done
6. OpServer가 SetMode('idle') 호출 → 종료
총 예상 시간: 20-30초
```

**시나리오 G2: 손님 미아**
```
1. customer 카운터 앞 위치
2. SetMode('guiding', ...)
3. moving 시작
4. 5초 후 customer Mock 발행 중단 (시야 잃음 시뮬)
5. 8초 경과 → state=aborted, utter "어디 가셨어요"
```

**시나리오 G3: 손님 천천히**
```
1. moving 시작
2. customer가 로봇보다 천천히 (lag 점진 증가)
3. lag > 1.5m → state=waiting, Nav2 cancel, utter "천천히"
4. customer 따라잡음 → lag < 1.0m → state=moving 재진입
5. Nav2 새 goal 송신
6. arrived → done
```

**시나리오 G4: 비상정지**
```
1. moving 중
2. /operator/command stop_emergency
3. mode_manager가 SIGTERM
4. guiding_controller cleanup → Nav2 cancel
```

**시나리오 G5: serving 선점**
```
1. guiding moving 진행 중
2. POS에서 pickup_ready (다른 손님)
3. OpServer가 priority 비교 (serving 1 < guiding 2) → 선점 가능
   ※ 운영 정책: 실제 매장에서 안내 중 선점은 부적절. OpServer가 큐잉.
4. → 선점 안 함, guiding 완료 후 serving 처리
```

→ 시나리오 G5에서 운영 정책상 안내 중 선점은 *큐잉만* 한다는 결정이 필요. mode_orchestrator의 정책 분기로 처리. 이슈 G3 (§10) 참고.

---

## 10. 미해결 이슈

| # | 이슈 | M2/M3 결정 |
|---|---|---|
| G1 | customer ground projection 정확도 (M2 어느 수준?) | (a) 휴리스틱 (현 설계) (b) M2부터 TF projection 필수 |
| G2 | customer ID tracking 도입 시점 | (a) M3 (b) M2부터 BYTE-track |
| G3 | guiding 중 serving 선점 허용? | (a) priority 우선 (1 < 2) → 선점 (b) 운영 정책상 큐잉만. OpServer 정책 토글로 |
| G4 | customer_lost 후 자동 idle vs ABORTED 유지 | (a) 5초 dwell 후 OpServer가 idle 호출 (현 설계) (b) ABORTED 상태 stuck하고 운영자 수동 처리 |
| G5 | 한 손님 안내 중 다른 손님 lock-on 변경 | (a) 첫 lock 유지 (현 설계) (b) 더 가까운 사람으로 자동 전환 |
| G6 | 다인 일행 (party_size > 1) 처리 | (a) M2 무시, 1명만 추적 (b) M3에서 그룹 추적 |
| G7 | 안내 중 customer가 다른 방향으로 가버림 | (a) 무시 (Nav2 계속 진행) (b) 일정 거리 이상 벗어나면 abort |

---

**End of Document**
