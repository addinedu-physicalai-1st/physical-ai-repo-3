# MOCA Patrol Mode 설계 문서

> **문서 ID**: `moca_patrol_design.md`
> **버전**: v1.0 (2026-05-16)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2.2.3, §6.3, §6.4
> **관련 문서**: `moca_5state_fsm_spec.md` §2.3 (S_patrol)
> **구현 대상**:
> - `dobi_npc_bringup/patrol_scheduler_node.py` (신규)
> - `dobi_npc_bringup/table_occupancy_detector_node.py` (신규)
> - `dobi_npc_bringup/launch/mode_patrol.launch.py` (신규)

---

## 0. 본 문서의 범위

본 문서는 `patrol` 모드의 두 핵심 노드 — `patrol_scheduler_node`와 `table_occupancy_detector_node` — 의 내부 알고리즘을 명세한다.

### 0.1 본 문서가 다루는 것

1. 두 노드의 책임 분리와 IPC 디자인
2. patrol_scheduler의 내부 상태머신
3. table_occupancy_detector의 추론 파이프라인 (M2: YOLO person만, M3: 식기 검출)
4. tables.yaml 활용 및 sweep_order 정책
5. abort / preempt / 가드 처리
6. 단위/통합 테스트 계획

### 0.2 본 문서가 다루지 않는 것

- mode_manager가 patrol launch를 어떻게 spawn하는지 (`moca_5state_fsm_spec.md`)
- OpServer의 5분 타이머 (`moca_opserver_api_spec.md` §5.2)
- 웹 UI 표시 (`moca_web_dashboard_spec.md`)

---

## 1. 모드 개요와 책임 분리

### 1.1 patrol 모드의 목적

- **무엇**: 영업 중 5분마다 (또는 점주 수동 트리거) 5개 테이블을 1회 순회하면서 각 테이블의 점유 상태를 추정·보고
- **왜**: (1) 동행 안내 시 빈 테이블 즉시 할당, (2) 식사 종료 테이블 청소 알림, (3) 손님 흐름 패턴 데이터 축적
- **어떻게**: Nav2로 각 테이블 앞에 이동 → 2초 정지 → 카메라/LiDAR로 점유 추정 → `TableReport` 발행 → 다음 테이블

### 1.2 노드 분리 원칙

```
┌──────────────────────────────────────────────────┐
│ patrol_scheduler_node                            │
│   - "어디로 갈까" (navigation orchestration)     │
│   - tables.yaml 로드                             │
│   - Nav2 NavigateToPose 호출                     │
│   - sweep_order 관리                             │
│   - dwell timer                                  │
│   - /patrol/state 발행                           │
└────────────────┬─────────────────────────────────┘
                 │ service call /table_occupancy/scan
                 ▼
┌──────────────────────────────────────────────────┐
│ table_occupancy_detector_node                    │
│   - "지금 보이는 것을 분석" (perception)         │
│   - 카메라 프레임 grab                           │
│   - YOLOv8 inference                             │
│   - LiDAR cluster 보조                           │
│   - TableReport 응답                             │
└──────────────────────────────────────────────────┘
```

**왜 분리하는가**:
1. 책임 명확. 한쪽은 mobility, 한쪽은 perception. 디버깅 용이.
2. detector는 patrol 외에도 재사용 가능 (예: 운영자가 특정 테이블만 즉시 확인 — `/tables/T02/scan` REST).
3. detector는 GPU 의존, scheduler는 CPU만. 향후 detector를 노트북에서, scheduler를 RPi에서 분리 배치 가능 (DDS QoS만 잘 맞추면).

### 1.3 IPC 패턴

scheduler ↔ detector 통신은 **ROS 서비스(`Trigger` + table_id 파라미터)** 사용.

토픽 pub/sub 안 쓰는 이유:
- scheduler가 *언제* 분석할지 정확한 시점 제어 필요 (Nav2 도착 직후 → 2초 dwell 시작 → 분석 요청)
- detector는 호출받은 시점의 1프레임만 분석 (지속 분석 X — 부하 줄임)

```python
# patrol_scheduler가 호출
result = self.cli_scan.call(ScanTable.Request(table_id="T03"))
# result: success, occupancy, person_count, confidence, ...

# detector는 호출받으면 1프레임 grab + 추론 + 응답
```

서비스 정의는 §3.3에서.

---

## 2. patrol_scheduler_node 설계

### 2.1 인터페이스

#### 2.1.1 파라미터 (`mode_patrol.launch.py`에서 전달)

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `tables_yaml` | string | (auto) | tables.yaml 절대 경로 |
| `params_json` | string | "" | mode_manager가 전달한 JSON params |
| `sweep_order` | string[] | `["T01","T02","T03","T04","T05"]` | 방문 순서 |
| `dwell_per_table_sec` | float | 2.0 | 도착 후 분석 대기 |
| `arrival_timeout_sec` | float | 30.0 | Nav2 단일 goal 타임아웃 |
| `inter_table_timeout_sec` | float | 60.0 | 한 테이블에 너무 오래 머물면 abort |
| `return_home_after_cycle` | bool | true | 사이클 종료 시 home 복귀 |
| `report_to_opserver` | bool | true | TableReport 발행 활성화 |
| `scan_service_name` | string | `/table_occupancy/scan` | detector 서비스 이름 |

#### 2.1.2 구독

| 토픽 | 타입 | 용도 |
|---|---|---|
| `/odom` | nav_msgs/Odometry | 도착 검증 보조 |
| `/rapport/event` | dobi_npc_msgs/RapportEvent | abort_trigger 감지 (safety alarm) |

#### 2.1.3 발행

| 토픽 | 타입 | 빈도 | 용도 |
|---|---|---|---|
| `/patrol/state` | dobi_npc_msgs/PatrolState | 1Hz | 진행 상황 |
| `/patrol/table_report` | dobi_npc_msgs/TableReport | 이벤트 | 각 테이블 결과 |

#### 2.1.4 액션 클라이언트

| 액션 | 타입 | 용도 |
|---|---|---|
| `/navigate_to_pose` | nav2_msgs/action/NavigateToPose | 테이블/home 이동 |

#### 2.1.5 서비스 클라이언트

| 서비스 | 타입 | 용도 |
|---|---|---|
| `/table_occupancy/scan` | dobi_npc_msgs/srv/ScanTable (신규) | detector 호출 |

### 2.2 내부 상태머신

```
                  ┌─────────┐
                  │  INIT   │
                  └────┬────┘
                       │ params 파싱, sweep_order 결정
                       ▼
                ┌─────────────┐
                │   NEXT      │◀─────────────────────┐
                └──────┬──────┘                      │
                       │ sweep_order 더 있음          │
                       ▼                              │
                ┌─────────────┐                       │
                │   MOVING    │                       │
                └──────┬──────┘                       │
                       │ Nav2 SUCCESS                 │
                       ▼                              │
                ┌─────────────┐                       │
                │   DWELL     │ (2초 대기)            │
                └──────┬──────┘                       │
                       │ dwell 경과                   │
                       ▼                              │
                ┌─────────────┐                       │
                │   SCAN      │ detector 호출        │
                └──────┬──────┘                       │
                       │ scan 응답 수신                │
                       ▼                              │
                ┌─────────────┐                       │
                │   REPORT    │ TableReport 발행      │
                └──────┬──────┘                       │
                       │                              │
                       └──────────────────────────────┘
                       │ sweep_order 소진
                       ▼
                ┌─────────────┐
                │  RETURNING  │ home_pose로 이동
                └──────┬──────┘
                       │ home 도착
                       ▼
                ┌─────────────┐
                │    DONE     │ /patrol/state="done"
                └─────────────┘
                       │
                       ▼
                  (node self-terminate or
                   외부에서 SIGTERM)

  ╔══════════════════════════════════════════════╗
  ║  ABORT 경로 (모든 상태에서 발생 가능)         ║
  ║                                              ║
  ║   /rapport/event abort_trigger 또는           ║
  ║   inter_table_timeout 초과                    ║
  ║      ▼                                       ║
  ║   Nav2 cancel + DONE 전이 + state="aborted"  ║
  ╚══════════════════════════════════════════════╝
```

### 2.3 상태별 행동

| 상태 | entry | during | exit | 다음 상태 트리거 |
|---|---|---|---|---|
| INIT | params 파싱, sweep_order 결정, tables.yaml load | (즉시) | — | → NEXT |
| NEXT | 다음 table_id 선택 | (즉시) | — | sweep 남음 → MOVING / 없음 → RETURNING |
| MOVING | Nav2 NavigateToPose(table_pose) 송신 | timeout 카운터 | active goal cancel (state 떠날 때) | SUCCESS → DWELL / FAIL/TIMEOUT → 그 테이블 skip 후 NEXT |
| DWELL | dwell timer 시작 (2초) | timer tick | — | 타이머 만료 → SCAN |
| SCAN | scan service 비동기 호출 (`call_async`) | future 대기 | — | future done → REPORT |
| REPORT | TableReport 발행 + state 업데이트 | (즉시) | — | → NEXT |
| RETURNING | Nav2 NavigateToPose(home_pose) | — | active goal cancel | SUCCESS → DONE / FAIL → DONE (어쨌든 종료) |
| DONE | /patrol/state="done" 마지막 발행 | (5초간 발행 유지 후 self-terminate) | — | — |

### 2.4 의사 코드 (구현 가이드)

```python
# dobi_npc_bringup/patrol_scheduler_node.py

import json
import time
from enum import Enum
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
import yaml

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from dobi_npc_msgs.msg import PatrolState, TableReport, RapportEvent
from dobi_npc_msgs.srv import ScanTable


class State(str, Enum):
    INIT = 'init'
    NEXT = 'next'
    MOVING = 'moving'
    DWELL = 'dwell'
    SCAN = 'scan'
    REPORT = 'report'
    RETURNING = 'returning'
    DONE = 'done'
    ABORTED = 'aborted'


class PatrolScheduler(Node):
    def __init__(self):
        super().__init__('patrol_scheduler')

        # 파라미터
        self.declare_parameter('tables_yaml', '')
        self.declare_parameter('params_json', '')
        self.declare_parameter('sweep_order', ['T01','T02','T03','T04','T05'])
        self.declare_parameter('dwell_per_table_sec', 2.0)
        self.declare_parameter('arrival_timeout_sec', 30.0)
        self.declare_parameter('inter_table_timeout_sec', 60.0)
        self.declare_parameter('return_home_after_cycle', True)
        self.declare_parameter('report_to_opserver', True)
        self.declare_parameter('scan_service_name', '/table_occupancy/scan')

        # 상태
        self._state = State.INIT
        self._current_table_id: Optional[str] = None
        self._current_table_index = 0
        self._tables_visited = 0
        self._tables_total = 0
        self._started_at = self.get_clock().now()
        self._state_entered_at = self.get_clock().now()
        self._sweep_order = []

        # tables.yaml 로드
        self._tables: dict = {}
        self._home_pose: Optional[PoseStamped] = None
        self._load_tables()

        # ROS
        self.pub_state = self.create_publisher(PatrolState, '/patrol/state', 10)
        self.pub_report = self.create_publisher(
            TableReport, '/patrol/table_report', 10)
        self.sub_rapport = self.create_subscription(
            RapportEvent, '/rapport/event', self._on_rapport, 10)

        self.act_nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.cli_scan = self.create_client(
            ScanTable, self.get_parameter('scan_service_name').value)

        # 1Hz state publish + 50Hz tick (FSM 처리)
        self.create_timer(1.0, self._publish_state)
        self.create_timer(0.02, self._tick)

        self.get_logger().info(f'patrol_scheduler ready, sweep={self._sweep_order}')
        self._transition(State.NEXT)

    # ---- tables.yaml ----
    def _load_tables(self):
        path = self.get_parameter('tables_yaml').value
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        for t in data['tables']:
            self._tables[t['id']] = t
        # home_pose
        hp = data['home_pose']
        ps = PoseStamped()
        ps.header.frame_id = hp['frame_id']
        ps.pose.position.x = float(hp['x'])
        ps.pose.position.y = float(hp['y'])
        # yaw → quaternion
        from math import sin, cos
        yaw = float(hp.get('yaw', 0.0))
        ps.pose.orientation.z = sin(yaw / 2.0)
        ps.pose.orientation.w = cos(yaw / 2.0)
        self._home_pose = ps

        # sweep_order 결정 — params_json 우선, 없으면 파라미터
        params_json = self.get_parameter('params_json').value
        sweep_mode = 'all'
        if params_json:
            try:
                d = json.loads(params_json)
                sweep_mode = d.get('sweep_mode', 'all')
            except json.JSONDecodeError:
                pass

        if sweep_mode == 'all':
            self._sweep_order = list(self.get_parameter('sweep_order').value)
        elif sweep_mode == 'priority_only':
            # TODO M3: 직전 사이클에서 occupied였던 테이블만
            self._sweep_order = list(self.get_parameter('sweep_order').value)
        else:
            self._sweep_order = list(self.get_parameter('sweep_order').value)

        self._tables_total = len(self._sweep_order)

    # ---- FSM ----
    def _transition(self, new_state: State):
        if new_state == self._state:
            return
        prev = self._state
        self._state = new_state
        self._state_entered_at = self.get_clock().now()
        self.get_logger().info(f'state: {prev} → {new_state}')
        # entry actions
        if new_state == State.NEXT:
            self._on_enter_next()
        elif new_state == State.MOVING:
            self._on_enter_moving()
        elif new_state == State.DWELL:
            pass  # 타이머는 _tick에서 dwell elapsed 체크
        elif new_state == State.SCAN:
            self._on_enter_scan()
        elif new_state == State.REPORT:
            self._on_enter_report()
        elif new_state == State.RETURNING:
            self._on_enter_returning()
        elif new_state == State.DONE:
            self._on_enter_done()
        elif new_state == State.ABORTED:
            self._on_enter_aborted()

    def _on_enter_next(self):
        if self._current_table_index >= len(self._sweep_order):
            # 모두 방문
            if self.get_parameter('return_home_after_cycle').value:
                self._transition(State.RETURNING)
            else:
                self._transition(State.DONE)
            return
        self._current_table_id = self._sweep_order[self._current_table_index]
        self._current_table_index += 1
        self._transition(State.MOVING)

    def _on_enter_moving(self):
        table = self._tables.get(self._current_table_id)
        if table is None:
            self.get_logger().warn(f'unknown table {self._current_table_id} skip')
            self._transition(State.NEXT)
            return
        pose = self._build_pose(table)
        self._send_nav_goal(pose)

    def _on_enter_scan(self):
        if not self.cli_scan.wait_for_service(timeout_sec=2.0):
            self.get_logger().warn('scan service unavailable, emit unknown')
            self._emit_report_unknown()
            self._transition(State.NEXT)
            return
        req = ScanTable.Request()
        req.table_id = self._current_table_id
        future = self.cli_scan.call_async(req)
        future.add_done_callback(self._on_scan_done)

    def _on_scan_done(self, future):
        try:
            res = future.result()
            self._last_scan_result = res
        except Exception as e:
            self.get_logger().warn(f'scan error: {e}')
            self._last_scan_result = None
        self._transition(State.REPORT)

    def _on_enter_report(self):
        msg = TableReport()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.table_id = self._current_table_id
        if self._last_scan_result is not None and self._last_scan_result.success:
            msg.occupancy = self._last_scan_result.occupancy
            msg.person_count = self._last_scan_result.person_count
            msg.dishes_detected = self._last_scan_result.dishes_detected
            msg.confidence = self._last_scan_result.confidence
        else:
            msg.occupancy = 'unknown'
            msg.person_count = 0
            msg.dishes_detected = False
            msg.confidence = 0.0
        self.pub_report.publish(msg)
        self._tables_visited += 1
        self._transition(State.NEXT)

    def _on_enter_returning(self):
        self._send_nav_goal(self._home_pose)

    def _on_enter_done(self):
        # 5초간 publish 유지 후 self-terminate
        # (mode_manager가 SIGTERM 보내는 것이 정상이지만, dispatcher가 idle 시그널을
        #  보내는 패턴을 채택했으므로 self-terminate는 안 함; OpServer가 SetMode('idle')
        #  호출하면 mode_manager가 SIGTERM 보냄.)
        pass

    def _on_enter_aborted(self):
        # active nav cancel
        self._cancel_nav()

    # ---- Nav2 핸들링 ----
    def _send_nav_goal(self, pose: PoseStamped):
        self._nav_started_at = self.get_clock().now()
        goal = NavigateToPose.Goal()
        goal.pose = pose
        self._nav_future = self.act_nav.send_goal_async(goal)
        self._nav_future.add_done_callback(self._on_nav_accepted)

    def _on_nav_accepted(self, future):
        gh = future.result()
        if not gh.accepted:
            self.get_logger().warn('nav goal rejected')
            self._nav_state = 'rejected'
            return
        self._nav_goal_handle = gh
        self._result_future = gh.get_result_async()
        self._result_future.add_done_callback(self._on_nav_result)

    def _on_nav_result(self, future):
        result = future.result()
        # status: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
        if result.status == 4:
            if self._state == State.MOVING:
                self._transition(State.DWELL)
            elif self._state == State.RETURNING:
                self._transition(State.DONE)
        else:
            self.get_logger().warn(f'nav failed status={result.status} skip')
            if self._state == State.MOVING:
                self._emit_report_unknown()
                self._transition(State.NEXT)
            elif self._state == State.RETURNING:
                self._transition(State.DONE)  # home 실패해도 종료

    def _cancel_nav(self):
        if hasattr(self, '_nav_goal_handle') and self._nav_goal_handle is not None:
            self._nav_goal_handle.cancel_goal_async()

    # ---- 보조 ----
    def _build_pose(self, table: dict) -> PoseStamped:
        from math import sin, cos
        ps = PoseStamped()
        ps.header.frame_id = table['pose']['frame_id']
        ps.header.stamp = self.get_clock().now().to_msg()
        x = float(table['pose']['x'])
        y = float(table['pose']['y'])
        yaw = float(table['pose'].get('yaw', 0.0))
        approach = float(table.get('approach_dist', 0.5))
        # 테이블 면에서 approach_dist만큼 후방 좌표 계산
        ps.pose.position.x = x - approach * cos(yaw)
        ps.pose.position.y = y - approach * sin(yaw)
        ps.pose.orientation.z = sin(yaw / 2.0)
        ps.pose.orientation.w = cos(yaw / 2.0)
        return ps

    def _emit_report_unknown(self):
        msg = TableReport()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.table_id = self._current_table_id or ''
        msg.occupancy = 'unknown'
        msg.person_count = 0
        msg.dishes_detected = False
        msg.confidence = 0.0
        self.pub_report.publish(msg)

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type == 'abort_trigger':
            self.get_logger().warn('rapport abort_trigger → aborting patrol')
            self._transition(State.ABORTED)

    def _tick(self):
        """50Hz FSM timer — dwell/timeout 체크"""
        now = self.get_clock().now()
        elapsed = (now - self._state_entered_at).nanoseconds / 1e9

        if self._state == State.DWELL:
            if elapsed >= self.get_parameter('dwell_per_table_sec').value:
                self._transition(State.SCAN)

        elif self._state == State.MOVING:
            if elapsed >= self.get_parameter('arrival_timeout_sec').value:
                self.get_logger().warn(
                    f'nav timeout at {self._current_table_id}, cancel + skip')
                self._cancel_nav()
                self._emit_report_unknown()
                self._transition(State.NEXT)

    def _publish_state(self):
        msg = PatrolState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.current_state = self._state.value
        msg.current_table = self._current_table_id or ''
        msg.tables_visited = self._tables_visited
        msg.tables_total = self._tables_total
        msg.progress = (
            self._tables_visited / self._tables_total
            if self._tables_total > 0 else 0.0
        )
        msg.started_at = self._started_at.to_msg()
        self.pub_state.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PatrolScheduler()
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

### 2.5 sweep_order 정책

#### 2.5.1 기본: 좌→우 일정 순서

`["T01","T02","T03","T04","T05"]` — `tables.yaml`의 좌표상 좌→우 순.

**왜**: 단순. 동선 짧음 (T01 카운터 정남 → T02/T03 중앙 그룹 → T04/T05 서쪽 그룹 순서로 매장 내 직선 이동).

#### 2.5.2 priority_only (M3)

직전 사이클의 `TableReport`를 캐시. occupied였던 테이블만 다음 사이클에서 우선.

**왜**: 점유 중인 테이블은 식사 종료 시점 빠르게 감지하는 게 청소 효율에 유리. 빈 테이블은 변화 가능성 낮음.

**구현 위치**: scheduler가 직접 캐시하지 않고, OpServer의 `table_registry`에 조회 (REST). 또는 patrol 진입 시 params로 sweep_order 직접 받기. 후자가 단순 — OpServer가 알아서 정렬해서 넘김.

#### 2.5.3 사용자 정의 순서 (M3)

웹 UI 설정에서 드래그로 순서 변경 → opserver_config.yaml에 저장 → patrol 진입 시 params로 전달.

---

## 3. table_occupancy_detector_node 설계

### 3.1 인터페이스

#### 3.1.1 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `yolo_weights_path` | string | `models/yolo/yolov8n.pt` | 모델 경로 |
| `confidence_threshold` | float | 0.5 | bbox confidence 최소 |
| `person_class_id` | int | 0 | COCO person class |
| `image_topic` | string | `/camera/image_raw` | RGB 카메라 토픽 |
| `dishes_enabled` | bool | false | M3에서 true, custom weights 사용 |
| `dishes_weights_path` | string | `models/yolo/table_dishes.pt` | 식기 모델 (M3) |
| `lidar_enabled` | bool | false | M3에서 LiDAR cluster 보조 |
| `scan_topic` | string | `/scan` | LiDAR |

#### 3.1.2 구독

| 토픽 | 타입 | 용도 |
|---|---|---|
| `/camera/image_raw` | sensor_msgs/Image | 최근 프레임 cache (last-1) |
| `/scan` | sensor_msgs/LaserScan | (M3) 보조 |

#### 3.1.3 서비스 서버

`/table_occupancy/scan` — `dobi_npc_msgs/srv/ScanTable`

### 3.2 추론 파이프라인

```
┌──────────────────────────────────────────────────────────────┐
│ on_scan_request(table_id)                                    │
│                                                              │
│  1. 최근 카메라 프레임 가져오기 (image_cache)                  │
│     ─ 없으면 1초 대기, 그래도 없으면 unknown 응답              │
│                                                              │
│  2. YOLOv8 inference (person)                                │
│     ─ persons = model(frame, classes=[0], conf=0.5)          │
│     ─ person_count = len(persons)                            │
│                                                              │
│  3. (M3) 식기 detector inference                              │
│     ─ dishes = dish_model(frame, conf=0.5)                   │
│     ─ dishes_detected = len(dishes) > 0                      │
│                                                              │
│  4. (M3) LiDAR cluster 보조                                  │
│     ─ 테이블 영역 ROI 내 점군 밀도 → 시야 가림 검증           │
│                                                              │
│  5. 최종 occupancy 분류:                                      │
│     person_count >= 1                  → "occupied"          │
│     person_count == 0 ∧ dishes==True   → "finished" (M3)    │
│     person_count == 0 ∧ dishes==False  → "empty"             │
│     (frame 없음/추론 실패)              → "unknown"           │
│                                                              │
│  6. confidence 계산 (M2):                                     │
│     ─ person 검출이 있으면 max(bbox.conf)                    │
│     ─ 없으면 1.0 - inference_uncertainty (단순 0.9)           │
│                                                              │
│  7. 응답: success, occupancy, person_count,                  │
│            dishes_detected, confidence                       │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 서비스 정의

`dobi_npc_msgs/srv/ScanTable.srv`:
```
# 특정 테이블에 대한 즉시 점유 분석 요청
string table_id              # 결과 라벨링용
---
bool success
string occupancy             # "empty" | "occupied" | "finished" | "unknown"
uint8 person_count
bool dishes_detected
float32 confidence           # 0.0 ~ 1.0
string error                 # success=false 시 사유
```

> **주의**: 마스터 계획서 §4.2에서 `TableReport`만 정의했고 `ScanTable.srv`는 새로 정의해야 한다. M0 작업 시 함께 추가.

### 3.4 의사 코드

```python
# dobi_npc_bringup/table_occupancy_detector_node.py

import threading
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
import cv2
import numpy as np

from sensor_msgs.msg import Image, LaserScan
from cv_bridge import CvBridge
from dobi_npc_msgs.srv import ScanTable

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class TableOccupancyDetector(Node):
    def __init__(self):
        super().__init__('table_occupancy_detector')

        self.declare_parameter('yolo_weights_path', 'models/yolo/yolov8n.pt')
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('person_class_id', 0)
        self.declare_parameter('image_topic', '/camera/image_raw')
        self.declare_parameter('dishes_enabled', False)

        self.bridge = CvBridge()
        self.last_frame: np.ndarray | None = None
        self.last_frame_ts = None
        self._frame_lock = threading.Lock()

        if YOLO_AVAILABLE:
            weights = self.get_parameter('yolo_weights_path').value
            self.model = YOLO(weights)
            self.get_logger().info(f'YOLO loaded: {weights}')
        else:
            self.model = None
            self.get_logger().warn('YOLO unavailable, returning unknown')

        self.sub_image = self.create_subscription(
            Image, self.get_parameter('image_topic').value,
            self._on_image, 10)
        self.srv_scan = self.create_service(
            ScanTable, '/table_occupancy/scan', self._on_scan)

    def _on_image(self, msg: Image):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with self._frame_lock:
                self.last_frame = frame
                self.last_frame_ts = self.get_clock().now()
        except Exception as e:
            self.get_logger().warn(f'image conversion failed: {e}')

    def _on_scan(self, request, response):
        table_id = request.table_id
        self.get_logger().info(f'scan request: {table_id}')

        with self._frame_lock:
            frame = self.last_frame.copy() if self.last_frame is not None else None

        if frame is None or self.model is None:
            response.success = True
            response.occupancy = 'unknown'
            response.person_count = 0
            response.dishes_detected = False
            response.confidence = 0.0
            response.error = 'no_frame' if frame is None else 'no_model'
            return response

        try:
            conf = self.get_parameter('confidence_threshold').value
            person_class = self.get_parameter('person_class_id').value
            results = self.model(frame, classes=[person_class],
                                 conf=conf, verbose=False)
            persons = results[0].boxes if results else []
            person_count = len(persons)
            max_conf = (
                float(persons.conf.max().item()) if person_count > 0 else 0.9
            )

            # M2: dishes 미지원
            dishes_detected = False
            if self.get_parameter('dishes_enabled').value:
                pass  # M3에서 구현

            if person_count >= 1:
                occupancy = 'occupied'
            elif dishes_detected:
                occupancy = 'finished'
            else:
                occupancy = 'empty'

            response.success = True
            response.occupancy = occupancy
            response.person_count = person_count
            response.dishes_detected = dishes_detected
            response.confidence = max_conf
            response.error = ''
        except Exception as e:
            self.get_logger().error(f'inference error: {e}')
            response.success = False
            response.occupancy = 'unknown'
            response.person_count = 0
            response.dishes_detected = False
            response.confidence = 0.0
            response.error = f'inference_error:{type(e).__name__}'

        return response


def main(args=None):
    rclpy.init(args=args)
    node = TableOccupancyDetector()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
```

### 3.5 카메라 ROI 정책 (M2 vs M3)

#### M2: 전체 프레임

YOLO를 전체 프레임에 적용. 로봇이 테이블 정면에 있을 때 person bbox가 잡히면 occupied로 판단.

**문제**: 옆 테이블의 사람도 잡힐 가능성. 

**완화**: 로봇이 approach_dist만큼 후퇴해서 정차하기 때문에 대상 테이블이 화면 중앙. 옆 테이블은 가장자리. 일단 M2에선 무시.

#### M3: bbox 중심 거리 가중치

대상 테이블 중심 픽셀(`tables.yaml`의 좌표를 카메라 외부보정으로 픽셀 매핑)과 person bbox 중심의 거리로 가중. 거리 < threshold만 카운트.

또는 LiDAR cluster를 보조로 사용. 카메라 person bbox 위치와 LiDAR 점군 클러스터를 매칭해서 거리 추정.

---

## 4. mode_patrol.launch.py 설계

```python
"""mode_patrol.launch.py — 순회 모드 stack.

mode_manager가 SetMode("patrol", params) 요청 시 spawn.
Nav2 (vicpinky_navigation)는 별도 가동 가정.

노드 구성:
  - patrol_scheduler (dobi_npc_bringup)
  - table_occupancy_detector (dobi_npc_bringup)

launch 인자:
  params_json: mode_manager가 전달한 JSON params
  sweep_mode: "all" | "priority_only"
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='SetMode 서비스로 받은 JSON params')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), 'config', 'tables.yaml'])

    yolo_weights = PathJoinSubstitution([
        FindPackageShare('dobi_npc_bringup'), '..', '..', '..',
        'models', 'yolo', 'yolov8n.pt'])

    return LaunchDescription([
        params_arg,
        Node(
            package='dobi_npc_bringup',
            executable='table_occupancy_detector',
            name='table_occupancy_detector',
            output='screen',
            parameters=[{
                'yolo_weights_path': yolo_weights,
                'confidence_threshold': 0.5,
                'person_class_id': 0,
                'image_topic': '/camera/image_raw',
                'dishes_enabled': False,
            }],
        ),
        Node(
            package='dobi_npc_bringup',
            executable='patrol_scheduler',
            name='patrol_scheduler',
            output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'sweep_order': ['T01','T02','T03','T04','T05'],
                'dwell_per_table_sec': 2.0,
                'arrival_timeout_sec': 30.0,
                'return_home_after_cycle': True,
                'report_to_opserver': True,
            }],
        ),
    ])
```

`setup.py`에 entry point 추가:
```python
entry_points={
    'console_scripts': [
        # 기존
        'mode_manager = dobi_npc_bringup.mode_manager_node:main',
        'serving_dispatcher = dobi_npc_bringup.serving_dispatcher_node:main',
        # 신규
        'patrol_scheduler = dobi_npc_bringup.patrol_scheduler_node:main',
        'table_occupancy_detector = dobi_npc_bringup.table_occupancy_detector_node:main',
    ],
},
```

---

## 5. 안전 / 가드 통합

### 5.1 SafetyCheck

기존 `cafe_funnel_v1.xml`의 SafetyCheck BT 노드는 engaging 모드 전용. patrol에서는:
- Nav2의 `local_costmap` + `collision_monitor`가 충돌 회피 책임
- `/rapport/event abort_trigger`는 scheduler가 직접 구독 → ABORTED 전이

### 5.2 배터리

mode_manager가 진입 시점에 가드. patrol 진행 중 배터리 낮아져도 scheduler는 모름 (cycle 끝까지 진행). 다음 사이클에서 mode_manager가 차단.

**개선안 (M3 stretch)**: scheduler가 `/battery_state` 구독해서 < battery_min 감지 시 ABORTED 전이. 단, 너무 자주 abort되지 않게 hysteresis 5초.

### 5.3 카메라 미수신

detector가 첫 1초 내 프레임 없으면 `unknown` 응답. scheduler는 unknown 받으면 그 테이블 skip하지 않고 정상 다음 진행 (점유 불명 정보도 가치 있음).

---

## 6. 단계별 구현

### 6.1 M2 Week 1 — scheduler skeleton

- [ ] PatrolState.msg 정의 + 빌드
- [ ] patrol_scheduler_node.py: FSM 코어, NEXT/MOVING/DWELL/REPORT 전이
- [ ] mode_patrol.launch.py
- [ ] mode_manager VALID_MODES에 'patrol' 추가
- [ ] dummy detector (항상 occupancy='unknown' 반환)로 통합 시뮬

검증: `ros2 service call /mode/request ... patrol` → /patrol/state 1Hz + 5테이블 sweep 완료 → home 복귀

### 6.2 M2 Week 2 — detector 실 구현

- [ ] ScanTable.srv 정의 + 빌드
- [ ] TableReport.msg 정의 + 빌드
- [ ] table_occupancy_detector_node.py: YOLO person 추론
- [ ] mode_patrol.launch.py에 detector 추가
- [ ] scheduler ↔ detector 서비스 통합

검증: 사람 1명 앞에서 patrol 시작 → TableReport(occupancy='occupied') 발행 확인

### 6.3 M3 — priority_only + 식기 검출

- [ ] priority_only sweep_mode 구현
- [ ] 식기 detector (custom YOLO weights)
- [ ] LiDAR cluster 보조
- [ ] table_occupancy_detector_node에 dishes 분기

### 6.4 M4 — 실기 통합

- [ ] 매장 실 환경 1주 운영 데이터 수집
- [ ] occupancy 정확도 검증 (수동 vs 자동 매칭)
- [ ] 동선 효율 (sweep 평균 시간 < 90초 목표)

---

## 7. 테스트 계획

### 7.1 단위 테스트 (test_patrol_scheduler.py)

- FSM 전이: INIT → NEXT → MOVING → DWELL → SCAN → REPORT → NEXT ...
- Nav2 실패 시 NEXT로 skip
- arrival_timeout 동작
- rapport abort 시 ABORTED 전이
- sweep_order 빈 리스트 시 즉시 DONE

### 7.2 단위 테스트 (test_table_occupancy_detector.py)

- 프레임 없음 → unknown
- YOLO 로드 실패 → unknown + error="no_model"
- mock YOLO로 person 1명 → occupied
- mock YOLO로 0명 → empty
- mock YOLO로 0명 + dishes_enabled=true (M3) → finished

### 7.3 통합 시나리오

**시나리오 P1: 정상 사이클**
```bash
# Gazebo + Nav2 + 5 tables + dummy frame publisher
ros2 launch dobi_npc_bringup mode_patrol.launch.py &
sleep 90  # 5 tables × 18초 추정
ros2 topic echo /patrol/state --once
# expected: current_state='done', tables_visited=5
```

**시나리오 P2: T03 Nav2 실패 (대상 점유)**
```bash
# T03 앞에 장애물 추가 (Gazebo)
# patrol 실행 → T03만 unknown TableReport, 나머지 4개 정상 → done
```

**시나리오 P3: 중간에 serving 선점**
```bash
# patrol 진행 중 T02 도착 시점에 SetMode('serving')
# mode_manager가 SIGTERM patrol → scheduler가 cleanup → serving 진행
# 검증: /patrol/state 발행 중단, /mode/state='serving'
```

---

## 8. 미해결 이슈

| # | 이슈 | M2/M3 결정 |
|---|---|---|
| P1 | scheduler self-terminate 시점 | (a) DONE 진입 5초 후 자동 (b) OpServer가 SetMode('idle') 호출까지 wait |
| P2 | dwell 중 운영자 skip_table 명령 처리 | (a) M2 무시 (b) M3 OperatorCommand 구독 |
| P3 | YOLO weights 위치 | `models/yolo/yolov8n.pt` (현 디렉토리). git lfs 또는 download_models.sh 활용 |
| P4 | LiDAR ROI 좌표계 변환 (M3) | TF 사용: `map` → `base_link` → laser frame |
| P5 | confidence 미달 시 (e.g. < 0.7) 재시도? | (a) 그대로 보고 (b) 5초 후 1회 재시도 |
| P6 | occupancy 'finished' 확정 임계 | dishes 검출 conf > 0.6 + 마지막 1분 내 person=0 (M3) |
| P7 | scheduler가 OpServer의 priority_only를 어떻게 받나 | params_json에 `sweep_order` 직접 (override) |

---

**End of Document**
