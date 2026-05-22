# single_arm_controller 연동 계획

> 서빙 완료 신호 → dwell → Serve action 전송 → 추론 실행 → idle 전환
>
> 작성일: 2026-05-22

---

## 1. 현황 분석

### 1.1 현재 서빙 종료 플로우

```
serving_dispatcher  →  /serving/state {state:'idle'}  (홈 복귀 완료)
        ↓
completion_watcher  →  dwell 3.0s 대기
        ↓
opserver_node       →  SetMode('idle')   ← 여기서 끝
```

**관련 파일**
| 파일 | 역할 |
|------|------|
| `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/serving_dispatcher_node.py` | 홈 복귀 후 `/serving/state state='idle'` 발행 (line 389) |
| `src/moca_opserver/moca_opserver/completion_watcher.py` | `on_serving_state()` → dwell → `_trigger_idle()` (line 67, 136) |
| `src/moca_opserver/moca_opserver/opserver_node.py` | `CompletionWatcher` 보유, `MultiThreadedExecutor` 사용 |

### 1.2 목표 플로우

```
serving_dispatcher  →  /serving/state {state:'idle'}
        ↓
completion_watcher  →  dwell 3.0s 대기
        ↓
opserver_node       →  ActionClient → Serve goal 전송
        ↓
single_arm_controller (serving.py)  →  추론 실행 (카메라·모터·모델)
        ↓
opserver_node       →  result 수신 (success / fail)
        ↓
opserver_node       →  SetMode('idle')
```

### 1.3 `single_arm_controller` 인터페이스

```
# single_arm_controller_interfaces/action/Serve.action
string wrist_cam_path    # 빈 문자열 = 노드 기본값 사용
string realsense_serial  # 빈 문자열 = 노드 기본값 사용
string task              # 빈 문자열 = 노드 기본값 사용
---
bool success
string message
---
string status            # 피드백
```

Action 이름: `serve`  
실행 노드: `ros2 run single_arm_controller serving`  
위치: `src/controller/single_arm_controller/single_arm_controller/single_arm_controller/serving.py`

---

## 2. 구현 항목

### 2.1 `opserver_node.py` — ActionClient 추가

**파일**: `src/moca_opserver/moca_opserver/opserver_node.py`

#### 2.1.1 import 추가

```python
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from single_arm_controller_interfaces.action import Serve
```

#### 2.1.2 `__init__` 에 ActionClient 초기화 추가

`completion_watcher` 초기화 직전(line ~200)에 삽입:

```python
# single_arm_controller Serve action client
self._arm_cb_group = ReentrantCallbackGroup()
self._arm_ac = ActionClient(
    self, Serve, 'serve',
    callback_group=self._arm_cb_group,
)
```

#### 2.1.3 신규 메서드 `send_arm_serve_goal` 추가

`CompletionWatcher` 가 호출하는 퍼블릭 메서드. `node` 계약(`completion_watcher.py` docstring)에 추가한다.

```python
def send_arm_serve_goal(self, done_cb) -> None:
    """Serve action goal 전송.

    Args:
        done_cb: (success: bool, message: str) → None
                 action 완료(성공·실패) 또는 서버 미가동 시 호출된다.
    """
    if not self._arm_ac.wait_for_server(timeout_sec=1.0):
        self.get_logger().warn(
            '[arm] action server not available — skipping, going idle')
        done_cb(False, 'server_unavailable')
        return

    goal = Serve.Goal()  # wrist_cam_path/realsense_serial/task 모두 '' → 노드 기본값 사용

    send_future = self._arm_ac.send_goal_async(
        goal,
        feedback_callback=self._on_arm_feedback,
    )
    send_future.add_done_callback(
        lambda f: self._on_arm_goal_accepted(f, done_cb))

def _on_arm_feedback(self, feedback_msg) -> None:
    self.get_logger().info(
        f'[arm] feedback: {feedback_msg.feedback.status}')

def _on_arm_goal_accepted(self, future, done_cb) -> None:
    goal_handle = future.result()
    if not goal_handle.accepted:
        self.get_logger().warn('[arm] goal rejected')
        done_cb(False, 'goal_rejected')
        return
    self.get_logger().info('[arm] goal accepted, waiting for result...')
    result_future = goal_handle.get_result_async()
    result_future.add_done_callback(
        lambda f: self._on_arm_result(f, done_cb))

def _on_arm_result(self, future, done_cb) -> None:
    result = future.result().result
    self.get_logger().info(
        f'[arm] result: success={result.success} message="{result.message}"')
    done_cb(result.success, result.message)
```

---

### 2.2 `completion_watcher.py` — arm 연동 추가

**파일**: `src/moca_opserver/moca_opserver/completion_watcher.py`

#### 2.2.1 arm 실행 중 플래그 추가

`__init__` 에:
```python
# arm action 진행 중 플래그 (dwell 재진입 차단)
self._arm_running: dict[str, bool] = {
    mode: False for mode in _DONE_SIGNALS
}
```

#### 2.2.2 `tick()` 재진입 방지

`tick()` 의 트리거 직전에 `_arm_running` 체크 추가:

```python
# 기존 코드 (dwell 만료 트리거 부분):
# self._dwell_start[mode] = None
# self._last_trigger_at[mode] = now
# ...
# self._trigger_idle(mode)

# 변경 후:
if self._arm_running[mode]:
    continue   # arm 실행 중 → tick 무시
self._dwell_start[mode] = None
self._last_trigger_at[mode] = now
self._arm_running[mode] = True
self.node.get_logger().info(
    f'CompletionWatcher[{mode}]: dwell {dwell:.1f}s 만료 — arm serve 요청')
self._trigger_arm_then_idle(mode)
```

#### 2.2.3 `_trigger_idle` → `_trigger_arm_then_idle` + `_do_set_idle` 분리

```python
def _trigger_arm_then_idle(self, completed_mode: str) -> None:
    """serving 완료 시: arm Serve action → 완료 후 idle 전환."""
    if completed_mode != 'serving':
        # serving 외 모드는 기존처럼 바로 idle
        self._arm_running[completed_mode] = False
        self._trigger_idle(completed_mode)
        return

    def _after_arm(success: bool, msg: str) -> None:
        self._arm_running[completed_mode] = False
        self.node.get_logger().info(
            f'[arm] {"성공" if success else "실패"}: {msg} — idle 전환')
        self._trigger_idle(completed_mode)

    try:
        self.node.send_arm_serve_goal(_after_arm)
    except Exception as e:
        self.node.get_logger().error(f'[arm] goal send 실패: {e} — idle 전환')
        self._arm_running[completed_mode] = False
        self._trigger_idle(completed_mode)

def _trigger_idle(self, completed_mode: str) -> None:
    """기존 로직 그대로 유지 — orchestrator.request_mode_change('idle')."""
    try:
        result = self.node.orchestrator.request_mode_change(
            target_mode='idle',
            params={},
            trigger_source=f'completion_watcher:{completed_mode}',
            override_priority=True,
        )
    except Exception as e:
        self.node.get_logger().error(
            f'CompletionWatcher SetMode("idle") 실패: {e}')
        return

    try:
        self.node.publish_op_event(
            source='timer',
            event_type='completion_idle',
            payload={'completed_mode': completed_mode, 'result': result},
            outcome=('accepted' if result.get('ok') else
                     f'rejected:{result.get("code","")}'),
        )
    except Exception:
        pass
```

**변경 요약 (completion_watcher.py)**:
- 기존 `_trigger_idle` → 이름 유지, 내용 그대로 (idle 전환 로직)
- 신규 `_trigger_arm_then_idle` → serving 모드에서 arm action 먼저, 완료 후 `_trigger_idle` 호출
- `tick()` 트리거 시 `_trigger_arm_then_idle` 호출로 변경
- `_arm_running` 플래그로 중복 트리거 방지

---

### 2.3 `moca_opserver/package.xml` — 의존성 추가

**파일**: `src/moca_opserver/package.xml`

`<exec_depend>` 에 추가:
```xml
<exec_depend>single_arm_controller_interfaces</exec_depend>
```

---

### 2.4 `ui_to_robot_comm_flow.html` — 시퀀스 다이어그램 수정

**파일**: `ui_to_robot_comm_flow.html` (프로젝트 루트)

`2. mode_serving` 섹션 participant에 `ARM` 추가, dwell 이후 단계 삽입.

#### 변경 전 (line 153~196, 다이어그램 끝부분):
```
    D-)O: /serving/state (Topic)<br/>state='idle' (서빙 종료 신호)
    O->>O: completion_watcher tick<br/>dwell 만료 시
    O->>M: SetMode.Request('idle')
    M->>SUP: kill() — serving launch 종료
    SUP-->>L: killpg SIGTERM (전 자식 일괄)
    M-)WS: /mode/state current_mode='idle'
    WS-)B: WS broadcast → UI 갱신
```

#### 변경 후:
```
    participant ARM as single_arm_controller<br/>(serving.py)
    ...
    D-)O: /serving/state (Topic)<br/>state='idle' (서빙 종료 신호)
    O->>O: completion_watcher tick<br/>dwell 3.0s 만료
    O->>ARM: ROS2 Action send_goal<br/>Serve.Goal{} (빈 = 노드 기본값)
    Note over ARM: 모델 추론 시작<br/>(카메라·Dynamixel·SmolVLA)
    ARM-)O: Serve.Feedback (status='Serve in progress')
    ARM-->>O: Serve.Result<br/>success=true/false, message
    O->>M: SetMode.Request('idle')
    M->>SUP: kill() — serving launch 종료
    SUP-->>L: killpg SIGTERM (전 자식 일괄)
    M-)WS: /mode/state current_mode='idle'
    WS-)B: WS broadcast → UI 갱신
```

---

## 3. 빌드 및 검증

### 3.1 빌드

```bash
cd /home/jr/ws/physical-ai-repo-3
source /opt/ros/jazzy/setup.bash
colcon build --packages-select single_arm_controller_interfaces single_arm_controller moca_opserver
source install/setup.bash
```

### 3.2 검증 시나리오 (하드웨어 없이)

**Step 1 — serving.py 노드 시작**
```bash
source install/setup.bash
ros2 run single_arm_controller serving
# → "[INFO] Starting model worker process (loading model)..." 출력 후 대기
```

**Step 2 — opserver 노드 시작**
```bash
ros2 run moca_opserver opserver_node
```

**Step 3 — serving 완료 신호 직접 inject**
```bash
# serving 모드 진입 시뮬레이션
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode "{mode: 'serving'}"

# serving 종료 신호 inject
ros2 topic pub --once /serving/state std_msgs/msg/String \
  "{data: '{\"state\": \"idle\", \"queue_size\": 0}'}"
```

**Step 4 — 기대 동작 확인**
```
[completion_watcher] serving: done signal received — dwell 시작
(3초 경과)
[completion_watcher] serving: dwell 3.0s 만료 — arm serve 요청
[arm] goal accepted, waiting for result...
[arm] feedback: Serve in progress
[arm] result: success=True/False message="..."
[arm] 성공/실패: ... — idle 전환
[completion_watcher] serving: dwell 3.0s 만료 — SetMode("idle") 호출
```

**Step 5 — arm 서버 미가동 시 fallback 확인**
```bash
# serving.py 없이 Step 3 실행
# 기대: "[arm] action server not available — skipping, going idle"
# 기대: dwell 후 정상 idle 전환 (arm 없어도 시스템 중단 없음)
```

---

## 4. 설계 결정 및 주의사항

### 4.1 arm 실패 시에도 idle 전환

arm action 이 실패(하드웨어 오류, 취소 등)해도 `_trigger_idle` 은 반드시 호출된다.
serving 모드가 영구 대기 상태에 빠지는 것을 방지한다.

### 4.2 arm 서버 미가동 시 fallback

`wait_for_server(timeout_sec=1.0)` 이 실패하면 즉시 `done_cb(False, 'server_unavailable')` 를 호출한다.
`single_arm_controller` 가 꺼져 있어도 기존 서빙 플로우는 정상 동작한다.

### 4.3 serving 모드만 arm 연동

`_trigger_arm_then_idle` 은 `completed_mode == 'serving'` 일 때만 arm action 을 전송한다.
patrol/guiding/engaging 은 기존 즉시 idle 로직을 그대로 사용한다.

### 4.4 `ReentrantCallbackGroup`

`ActionClient` 에 `ReentrantCallbackGroup` 을 부여해 timer callback 과 action result callback 이
`MultiThreadedExecutor` 안에서 교착 없이 실행되도록 한다.
`opserver_node.py` 는 이미 `MultiThreadedExecutor` 를 사용하므로 추가 executor 변경 불필요.

### 4.5 `_arm_running` 플래그

dwell 만료 후 arm action 이 진행 중인 동안 `tick()` 이 반복 호출되어도 중복 트리거를 방지한다.
arm result callback 또는 예외 처리에서 반드시 `False` 로 리셋한다.

---

## 5. 변경 파일 요약

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `src/moca_opserver/moca_opserver/opserver_node.py` | 수정 | `ActionClient(Serve)` 초기화, `send_arm_serve_goal` 메서드 3개 추가 |
| `src/moca_opserver/moca_opserver/completion_watcher.py` | 수정 | `_arm_running` 플래그, `_trigger_arm_then_idle` 추가, `tick()` 분기 |
| `src/moca_opserver/package.xml` | 수정 | `<exec_depend>single_arm_controller_interfaces</exec_depend>` 추가 |
| `ui_to_robot_comm_flow.html` | 수정 | mode_serving 다이어그램에 `ARM` participant + action 단계 추가 |
