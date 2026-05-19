# MOCA Serving Mode 설계 문서

> **문서 ID**: `moca_serving_design.md`
> **버전**: v1.0 (2026-05-17)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2.2.1
> **관련 문서**:
> - `moca_5state_fsm_spec.md` §2.2 (S_serving)
> - `cafe_npc_serving_mode.md` (학술 트랙 SoT — 본 문서는 운영 트랙 spec, cross-reference)
> **구현 대상**:
> - `dobi_npc_bringup/serving_dispatcher_node.py` (실 구현, 422 줄)
> - `dobi_npc_bringup/launch/mode_serving.launch.py` (실 구현, 60 줄)
> - `dobi_npc_bringup/config/tables.yaml` (테이블 waypoint SoT)

---

## 0. 본 문서의 범위

본 문서는 `serving` 모드 — 운영자가 지정한 픽업 테이블 또는 목표 테이블 시퀀스로 자율 주행한 후 home 으로 복귀하는 행동 — 의 알고리즘과 구현 방침을 정의한다.

### 0.1 본 문서가 다루는 것

1. serving 모드의 책임과 다른 모드와의 경계 (특히 patrol 과의 차이)
2. `serving_dispatcher_node` 내부 FSM (4 state: IDLE / NAVIGATING / DWELL / RETURNING)
3. tables.yaml 스키마와 waypoint 추가 큐 정책
4. Nav2 NavigateToPose action 연동 + dwell 관리 + home 복귀
5. 안전 가드 (placeholder 좌표 거부, nav timeout, cmd_vel 직접 발행 금지)
6. 라이브 갱신 (`/serving/reload_tables` 서비스) 와 운영자 UI 연동

### 0.2 본 문서가 다루지 않는 것

- Nav2 stack 자체의 설정 (별 문서: `cafe_npc_rpi_live_amcl_checklist.md`)
- AMCL drift 와 cmd_vel pipeline 안전 (별 문서: `cafe_npc_safety_zone.md`)
- 다중 픽업/배달 큐 최적화 (S-B 후속 — §6.2)
- 발화/표정 (engaging 모드 외 dialog 전용 — 본 모드는 dispatcher 로직만, dialog_router 가 priority 큐 처리)

---

## 1. 모드 개요와 책임

### 1.1 serving 모드의 목적

운영자 또는 POS 가 "T02 픽업 후 T05 배달" 같은 1~N 회 waypoint 순회를 요청. 로봇이:
1. 큐의 첫 waypoint 로 Nav2 NavigateToPose 단발
2. 도착 후 dwell `N` 초 (음식 픽업/하차 대기)
3. 큐에 남은 waypoint 있으면 다음 nav, 없으면 home_pose 자동 복귀
4. 모두 종료 시 자체 종료 신호 발행 → mode_manager 가 idle 전이

### 1.2 priority — 최상 (1)

`moca_5state_fsm_spec.md` 의 priority 매트릭스 기준, serving 은 **priority 1** (최상). 운영자가 serving 시작하면 진행 중인 engaging / patrol / guiding 모두 즉시 abort 되고 serving 진입.

### 1.3 patrol 과의 차이

| 항목 | serving | patrol |
|---|---|---|
| 트리거 | 운영자/POS 명시 1회 명령 | 자동 5분 주기 또는 운영자 수동 |
| 큐 | 외부 명시 (waypoint id) | 내부 자동 (sweep_order) |
| dwell | 음식 픽업/하차 (5~30s) | 점유 감지 + 보고 (3~5s) |
| home 복귀 | 큐 종료 시 자동 | sweep 종료 시 자동 |
| priority | 1 (최상) | 3 |
| 발화 | 없음 (dispatcher 무관) | 있음 (도착 시 "OOO 테이블 확인 중") |

핵심: serving 은 **business 데이터 우선** (테이블별 OO 분 미수신 시 알람 등), patrol 은 **점유 상태 수집 우선**.

### 1.4 노드 분리 정책

serving 모드는 **단일 노드 (`serving_dispatcher_node`)** 로 구현. patrol 의 두 노드 (scheduler + detector) 분리와 달리 serving 은 detection 책임 없음 — Nav2 외 senso 의존 X.

향후 S-D (호객 trigger): serving 도착 후 dwell 중 EmotionMonitor 감지하면 engaging 모드 spawn 검토. 현 분리 유지 — engaging spawn 은 mode_manager 의 책임이지 serving_dispatcher 의 책임이 아님.

---

## 2. serving_dispatcher_node 설계

### 2.1 인터페이스

**파라미터** (`mode_serving.launch.py` 에서 주입):

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `tables_yaml` | str | (FindPackageShare) `config/tables.yaml` | tables 정의 yaml 경로 |
| `params_json` | str | `""` | SetMode 의 JSON params 그대로 (waypoint 첫 명령) |
| `dwell_sec` | float | `5.0` | 도착 후 대기 시간 |
| `return_home_after_dwell` | bool | `True` | dwell 후 home 자동 복귀 |
| `nav_action_name` | str | `navigate_to_pose` | Nav2 action 이름 |
| `nav_timeout_sec` | float | `60.0` | nav goal 타임아웃 |

**구독**:
| 토픽 | 타입 | 용도 |
|---|---|---|
| `/serving/goto_table` | `std_msgs/String` | 진입 후 추가 명령 — table id 큐 append |

**발행**:
| 토픽 | 타입 | 주기 | 용도 |
|---|---|---|---|
| `/serving/state` | `std_msgs/String` (JSON) | 1Hz | dispatcher 상태 (state/current_table/queue/dwell_sec/return_home/home_registered) |

**액션 클라이언트**:
| 액션 | 타입 | 용도 |
|---|---|---|
| `navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 단발 nav 호출 |

**서비스 서버**:
| 서비스 | 타입 | 용도 |
|---|---|---|
| `/serving/reload_tables` | `std_srvs/Trigger` | tables.yaml 라이브 재로드 (운영자 UI 좌표 갱신 후 호출) |

### 2.2 신규 메시지

없음. `/serving/state` 는 `std_msgs/String` 으로 JSON 시리얼라이즈. 향후 S-B 에서 `dobi_npc_msgs/ServingState` 신규 검토.

### 2.3 내부 FSM

```
        ┌──────────┐  큐 비어있음 + return_home=false 또는 home_pose 없음
   ┌───→│   IDLE   │←────────────────────────────────────┐
   │    └────┬─────┘                                       │
   │         │ 큐에 table id 있음                            │
   │         ↓                                              │
   │    ┌────────────┐ nav fail              ┌─────────┐   │
   │    │ NAVIGATING │──────────────────────→│  DWELL  │   │
   │    └────┬───────┘ (또는 timeout)         └────┬────┘   │
   │         │ nav SUCCEEDED                        │        │
   │         ↓                                       │ dwell  │
   │    ┌─────────┐                                  │ 만료   │
   │    │  DWELL  │──── 큐에 남은 table 있음 ────────┐│        │
   │    └────┬────┘                                  ↓│        │
   │         │ 큐 비었음 + return_home=true            └────────┤
   │         │ + home_pose 등록됨                              │
   │         ↓                                                 │
   │    ┌───────────┐ nav fail/SUCCEEDED                       │
   │    │ RETURNING │ ────────────────────────────────────────┤
   │    └───────────┘                                          │
   │                                                            │
   └────────────────────────────────────────────────────────────┘
```

**4 상태:**

| 상태 | 의미 | entry action | during | exit |
|---|---|---|---|---|
| IDLE | 큐 처리 대기 | `current_table=None`, `dwell_start_ns=None` | tick 마다 큐 검사 | 큐 발견 → NAVIGATING |
| NAVIGATING | Nav2 단발 nav 진행 중 | `_send_nav_goal()`, `_nav_started_ns 기록` | nav_timeout 체크 | 결과 callback (SUCCESS/CANCELED/ABORTED) |
| DWELL | 도착 후 대기 | `dwell_start_ns 기록` | tick 마다 경과 시간 비교 | dwell_sec 도달 → `_after_dwell()` |
| RETURNING | home 복귀 진행 중 | `_send_nav_goal(home)`, `current_table=__home__` | nav_timeout 체크 | 결과 callback → IDLE |

### 2.4 큐 관리 (FIFO)

- `queue: deque[str]` — table id 만 저장 (PoseStamped 는 매번 tables dict 에서 조회)
- 진입 시: `params_json` 의 `waypoint` 필드 → 첫 큐 append
- 진입 후: `/serving/goto_table` 토픽 → 큐 append (mode 진입 후 동적 명령)
- S-B 후속 hook: `/serving/clear_queue` 서비스, 우선순위 큐, `/serving/empty_tables` 자동 push (구현 대기)

### 2.5 dwell 정책

- `dwell_sec=5.0` 기본. 픽업 (테이블 → 카운터): 짧음. 배달 (카운터 → 테이블): 길음 (고객이 음식 받을 시간).
- S-D 호객 trigger 검토: dwell 중 EmotionMonitor 가 abort_trigger 받으면 즉시 dwell 종료 + idle 전이. 현재 미구현 — dwell 은 단순 timer.

### 2.6 home_pose 자동 복귀 정책

- `home_pose` 가 tables.yaml 에 `frame_id: map / x / y / yaw` 명시되어 있어야 함
- placeholder (0, 0, 0) 감지 시 자동 복귀 비활성 + WARN log
- `return_home_after_dwell=true` 인 경우 큐 종료 + dwell 종료 후 자동 home nav

### 2.7 nav timeout

- `nav_timeout_sec=60.0` 기본. 초과 시 `_cancel_active_goal()` → 결과 callback 에 ABORTED 처리
- timeout 사유 예: Nav2 path planning 실패 (AMCL drift), 가구 충돌 회피 stuck

### 2.8 placeholder 좌표 거부 (안전)

- table 의 pose 가 `(0, 0, yaw=0)` 이면 placeholder 로 간주 → `_start_next_nav()` 에서 nav 거부 + ERROR log
- 이유: tables.yaml 미등록 상태에서 잘못 nav 보내면 robot 가 origin (-51, -6) 방향으로 가다 충돌

### 2.9 의사 코드 (메인 tick — `_tick()`)

```python
def _tick(self):
    if self.state == IDLE:
        if self.queue:
            self._start_next_nav()  # → NAVIGATING

    elif self.state == NAVIGATING:
        if nav_timeout_exceeded():
            self._cancel_active_goal()  # → 결과 callback 에서 _on_nav_finished(success=False)

    elif self.state == DWELL:
        if dwell_elapsed >= self.dwell_sec:
            self._after_dwell()  # → 큐 남으면 NAVIGATING, 아니면 RETURNING 또는 IDLE

    elif self.state == RETURNING:
        if nav_timeout_exceeded():
            self._cancel_active_goal()  # → 결과 callback 에서 IDLE 강제
```

---

## 3. tables.yaml 스키마

### 3.1 파일 위치

`src/dobi_npc/dobi_npc_bringup/config/tables.yaml` (colcon install 후 share dir).

### 3.2 구조

```yaml
home_pose:
  frame_id: map
  x: -36.887
  y: 2.809
  yaw: -1.5708          # -π/2, 카운터 정면 향함
  description: "pinky_home — bar_counter 옆 idle 위치"

tables:
- id: T01
  pose:
    frame_id: map
    x: -37.12
    y: 0.543
    yaw: -1.57
  approach_dist: 0.0    # 2026-05-17: pose 자체가 정차 좌표 (offset 0)
  description: "T01"
- id: T02
  pose: {frame_id: map, x: -40.303, y: -0.591, yaw: 1.571}
  approach_dist: 0.0
  description: "T02"
# T03~T05 동상
```

### 3.3 좌표 의미 — robot 정차 pose

2026-05-17 회고 §3.4 결정: tables T01~T05 좌표 = **robot 정차 pose** (가구 cafe_table 위치 아님).

`approach_dist=0.0` — dispatcher 가 pose 자체를 Nav2 goal 로 직접 사용. 이전 (가구 중심 + 0.5m offset) 정책 폐기.

장점: 점주가 yaml 보고 robot 어디 정차하는지 직관. 단점: 가구 cafe_table 위치는 별 데이터 (`cafe_layout.yaml` 의 `tables` 섹션) — 두 의미 분리 명확하게 관리 필요.

### 3.4 라이브 갱신 절차

1. 운영자가 RViz `2D Pose Estimate` 로 테이블 앞 정차 pose 클릭
2. 새 좌표를 `tables.yaml` 에 수동 갱신 (또는 `place_furniture_picker.py` 의 `T01_wp~T05_wp` waypoint entry 사용)
3. `ros2 service call /serving/reload_tables std_srvs/Trigger` 호출
4. dispatcher 가 home_pose + tables 만 다시 로드 (큐 + 진행 중 nav 보존)

### 3.5 frame_id 정책

모든 pose `frame_id: map` (mapv5_mocamap 기준). RPi 라이브와 sim 모두 동일 frame.

---

## 4. mode_serving.launch.py 설계

### 4.1 노드 구성

```python
Node(
    package='dobi_npc_bringup', executable='serving_dispatcher',
    name='serving_dispatcher', output='screen',
    parameters=[{
        'tables_yaml': PathJoinSubstitution([
            FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml']),
        'params_json': ParameterValue(
            LaunchConfiguration('params_json'), value_type=str),
        'dwell_sec': ParameterValue(
            LaunchConfiguration('dwell_sec'), value_type=float),
        'return_home_after_dwell': ParameterValue(
            LaunchConfiguration('return_home_after_dwell'), value_type=bool),
    }],
),
```

### 4.2 ParameterValue value_type 강제

⚠ `params_json` 은 JSON 문자열 (예: `{"waypoint": "T01"}`). 그대로 launch arg 로 받으면 `ros2 launch` 가 dict 자동 파싱 시도 → `"Got dict for params_json"` 에러.

해결: `ParameterValue(..., value_type=str)` 강제 — 항상 str 로 받음.

### 4.3 mode_manager 와의 spawn 패턴

```bash
# mode_manager 가 subprocess.Popen 로 호출
ros2 launch dobi_npc_bringup mode_serving.launch.py \
    params_json:='{"waypoint":"T01"}' \
    dwell_sec:=10.0 \
    return_home_after_dwell:=true
```

mode_manager 가 SIGTERM 던지면 launch process tree 종료 → dispatcher `on_shutdown()` → active nav goal cancel.

### 4.4 Nav2 stack 의존

mode_serving.launch.py 는 Nav2 stack 을 **스폰하지 않음**. dev_common 또는 별 launch (`vicpinky_navigation/launch/bringup_launch.xml`) 가 Nav2 를 먼저 띄워야 함.

`navigate_to_pose` action server 미응답 시 dispatcher 가 ERROR 로그 후 IDLE 복귀:
```python
if not self._ac.wait_for_server(timeout_sec=2.0):
    self.get_logger().error(f'Nav2 action server 미응답 — {context} skip')
    self.state = State.IDLE
```

---

## 5. 안전 / 가드 통합

### 5.1 cmd_vel 직접 발행 금지

dispatcher 는 cmd_vel 직접 발행 X. Nav2 controller_server 가 발행하고, Phase B pipeline (twist_mux + velocity_smoother + collision_monitor) 가 OS 레벨로 차단/감속.

설계 의도: dispatcher 가 안전 책임 분리 — Nav2 stack 이 path planning + collision avoidance 책임, Phase B 가 emergency stop 책임. dispatcher 는 "어디로 갈지" 만.

### 5.2 placeholder 좌표 가드

```python
if entry['placeholder']:
    self.get_logger().error(
        f'테이블 {tid!r} 좌표 placeholder(0,0,0) — nav 거부.')
    return
```

tables.yaml 의 좌표가 `(0, 0, 0)` 이면 nav 거부 — 초기 빈 yaml 상태에서 origin 방향으로 잘못 가는 사고 회피.

### 5.3 home_pose 누락 가드

```python
if home_pose 가 placeholder 또는 누락:
    self.home_pose = None
    self.get_logger().warn('home_pose 누락 — 자동 복귀 비활성')
```

home_pose 없으면 자동 복귀 disable. dwell 종료 후 IDLE 진입만.

### 5.4 nav timeout

`nav_timeout_sec=60.0` 초과 시 cancel. AMCL drift 또는 가구 stuck 회피.

### 5.5 SafetyCheck / rapport_event 무관

serving 은 BT 가 아니라 단순 dispatcher — SafetyCheck (배터리/scan alarm) + EmotionMonitor (V/A abort) 무관. 안전 alarm 발생 시 mode_manager 가 별 trigger 로 idle 강제 (mode_manager_node.py 의 `/rapport/event` 가드).

### 5.6 비상정지 (`/operator/command`)

mode_manager 가 emergency_stop 명령 받으면 SIGTERM 던짐 → dispatcher `on_shutdown()` → active nav goal cancel → robot 정지.

추가 정지 latency = SIGTERM 전달 + cancel 전송 + Nav2 controller 정지 = ~0.5~1.0s. 더 빠른 정지 필요 시 e_stop_pub 의 별 토픽 사용.

---

## 6. 단계별 구현

### 6.1 Phase S-A — 본 문서 SoT (현재 구현, 2026-05-16~17)

✓ serving_dispatcher_node 422 줄 — IDLE/NAVIGATING/DWELL/RETURNING 4 state FSM
✓ tables.yaml 로드 + reload 서비스
✓ Nav2 NavigateToPose action 연동
✓ /serving/goto_table 추가 명령 큐
✓ /serving/state 1Hz JSON 발행
✓ placeholder 좌표 가드 + nav timeout
✓ home 자동 복귀

### 6.2 Phase S-B — 큐 확장 (M3~M4 후속)

- `/serving/empty_tables` 자동 push (중앙 서버가 KPI 기반 빈 테이블 추천)
- `/serving/clear_queue` 서비스 (운영자 수동 큐 초기화)
- 우선순위 큐 — 운영자 manual override 가 자동 push 보다 우선
- 큐 visualization — dashboard 의 modes 페이지에 큐 표시

### 6.3 Phase S-C — POS 연동 (M4)

- POS 시스템 → 결제 완료 이벤트 → opserver → `/serving/goto_table` 자동 발행
- 픽업/배달 분리: pickup_queue + delivery_queue 두 deque
- 시각화: dashboard 에서 픽업/배달 큐 별 표시

### 6.4 Phase S-D — engaging trigger (M4 이후 검토)

- serving 도착 후 dwell 중 EmotionMonitor 의 abort_trigger (예: 손님이 손 들고 부름) 감지
- mode_manager 에 engaging 전이 요청 → engaging spawn 후 serving 큐 보존
- engaging 종료 후 serving 큐 resume — mode_manager 의 stack 보존 로직 필요

---

## 7. 테스트 계획

### 7.1 단위 테스트 (`src/dobi_npc/dobi_npc_bringup/test/`)

| 케이스 | 검증 |
|---|---|
| tables.yaml 정상 로드 | tables dict 구성 + home_pose 등록 |
| placeholder 좌표 거부 | _is_placeholder 가 (0,0,0) true |
| _parse_first_waypoint | params_json 의 waypoint 필드 추출 + tables 검증 |
| _dict_to_pose | yaw → quaternion 변환 (z/w 만 사용, x/y=0) |
| reload_tables | 신규 tables 반영 + 실패 시 이전 상태 복원 |

### 7.2 시뮬 통합 (`scripts/run_sim.sh` + scenario)

1. `bash scripts/run_sim.sh --no-rviz --cleanup` 가동
2. dashboard 에서 mode → serving, params: `{"waypoint":"T02"}`
3. 확인:
   - Gazebo robot 가 T02 좌표로 이동
   - AMCL pose 가 robot 따라 update
   - dwell 5s 후 home 복귀
   - `/serving/state` 1Hz JSON 발행 확인 (state 변화 추적)

⚠ 현재 sim AMCL drift 한계 — `cafe_npc_rpi_live_amcl_checklist.md` 참조. 가구 PGM 추가 + 5 patches 적용해도 wrong basin lock-in 잔존. 라이브 검증 우선.

### 7.3 라이브 검증 (RPi)

`docs/cafe_npc_rpi_live_amcl_checklist.md` §6.3 "NavigateToPose 단발 T01" 와 동일 패턴.

성공 기준:
- Goal SUCCEEDED + robot 실제 T01 도달 (오차 0.3m 안)
- AMCL pose vs robot 실 위치 일치
- cmd_vel chain 정상 (controller_server → twist_mux → smoother → collision_monitor → zlac)

### 7.4 회귀 테스트 (시나리오)

`scripts/run_scenarios.sh` (또는 `run_demo_scenario.sh`) 에서 serving 1회 호출 + 결과 검증. M3 dashboard 자동 시나리오 17 개 중 serving 관련 케이스 우선.

---

## 8. 운영자 UI 연동

### 8.1 dashboard modes 페이지

- "서빙 시작" 버튼 — waypoint dropdown (T01~T05) + dwell_sec input + return_home checkbox
- POST `/api/v1/mode` body: `{"mode":"serving","params":{"waypoint":"T02"},"override_priority":true}`
- 진행 중 상태: `/serving/state` 토픽 → WebSocket → dashboard 실시간 갱신 (state/current_table/queue)

### 8.2 floorplan 시각화

- robot 마커가 NavigateToPose path 따라 이동 (AMCL pose + odom)
- 현재 target table 강조 (T02 사각형 색상 변경)
- 큐의 남은 table 도 시각 표시 (대기열 색)

### 8.3 events 페이지

- `mode_transition` 이벤트: idle → serving / serving → idle (자동 종료 시)
- `/serving/state` 의 state 변화 (NAVIGATING → DWELL → RETURNING → IDLE) → events log

---

## 9. mode_manager 인터페이스

### 9.1 SetMode 호출

```bash
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
    '{requested_mode: "serving",
      params: "{\"waypoint\":\"T01\",\"dwell_sec\":10}"}'
```

- mode_manager 가 mode_serving.launch.py spawn
- `params` JSON 문자열 → launch arg `params_json` 으로 전달
- dispatcher 가 `params_json` 파싱 → 첫 큐 append

### 9.2 종료 흐름

| 트리거 | mode_manager 동작 | dispatcher 동작 |
|---|---|---|
| 큐 모두 처리 + home 복귀 완료 | (현재 자동 idle 전이 X) | IDLE 진입, /serving/state state=idle |
| 운영자 명시 idle | SIGTERM → launch tree 종료 | on_shutdown → active goal cancel |
| safety alarm | SIGTERM (위와 동일) | 동상 |
| 다른 모드 spawn 명령 | SIGTERM → 새 mode spawn | 동상 |

⚠ 현재 dispatcher 가 자체 mode 종료 신호 발행 X. mode_manager 의 `/serving/state` 구독 추가하면 자동 idle 전이 가능 — S-B 후속.

---

## 10. 미해결 / 후속

### 10.1 자동 idle 전이

`/serving/state.state == 'idle'` 1회 발행 시 mode_manager 가 자동 idle 전이. 현재 운영자 수동 또는 시간 경과만 가능.

### 10.2 다중 픽업/배달 큐 분리

pickup_queue + delivery_queue 두 별 deque. POS 연동 시 필수.

### 10.3 dwell 중 emergency abort

dwell 중 운영자 emergency_stop → 즉시 idle 전이. 현 SIGTERM 으로 처리되긴 함, dwell timer 도 별 abort 처리 명세.

### 10.4 home_pose 의 dock plate 모델

cafe_layout.yaml 의 `pinky_home` 좌표 (-36.903, 2.693) 가 NE 코너. 현재 Gazebo 시뮬 world 에 dock plate 모델 없음 (좌표만). 시각 확인 어려움.

후속: `src/moca_gazebo/models/dock_plate/model.sdf` 신규 + world 에 include + visual 만 (collision X — robot 가 그 위에 정차).

### 10.5 AMCL drift 시 nav 실패 처리

현재 nav timeout 60s 후 cancel. AMCL drift 로 path 실패 반복 시 운영자에게 알람 — `/rapport/event` 또는 별 event 발행 검토.

---

## 11. 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1.0 | 2026-05-17 | 초안 — Phase S-A 실 구현 기반 |

---

## 12. 부록 — 코드 SoT 매핑

| 섹션 | 코드 위치 | 라인 |
|---|---|---|
| §2.1 인터페이스 | `serving_dispatcher_node.py` | 62-98 |
| §2.3 FSM | `serving_dispatcher_node.py` | 48-53, 212-242 |
| §2.4 큐 관리 | `serving_dispatcher_node.py` | 83, 100-104, 197-208 |
| §2.5 dwell | `serving_dispatcher_node.py` | 228-233, 244-254 |
| §2.6 home 복귀 | `serving_dispatcher_node.py` | 130-138, 249-251, 273-276 |
| §2.7 nav timeout | `serving_dispatcher_node.py` | 219-225, 237-241, 355-362 |
| §2.8 placeholder | `serving_dispatcher_node.py` | 170-174, 264-268 |
| §3 tables.yaml | `dobi_npc_bringup/config/tables.yaml` | 전체 |
| §4 launch | `mode_serving.launch.py` | 전체 |
