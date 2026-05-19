# A2 mode_manager — 4상태 FSM 골격 (운영자 service + 가드 검증 통과)

**작성일**: 2026-05-04 (밤 트랙, A1 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**선행 트랙**: `2026-05-04_dialog_router_a1.md` (멀티 모드 단일 출력 채널 게이트)
**메모리**: `project_mode_architecture.md` (vic_pinky 4상태 FSM, A1 트랙에서 저장)
**상태**: A2 (mode_manager) 신설 + 라이브 검증 완료. 4상태 FSM + service + 가드(배터리/safety) 정확 동작. launch spawn/kill 은 stub (로그만, B 단계 이월).

---

## 0. 시작 컨텍스트

A1 직후. dialog_router 가 단일 출력 채널을 직렬화하는 인터페이스 안정성을 확보했으니, A2 는 **모드 결정 로직 자체** — vic_pinky 가 어느 시점에 어느 모드로 전환할지 결정하는 중앙 FSM.

**A2 첫 cut 범위**:
- mode_manager 노드 신설 (FSM + service + 가드)
- 신규 srv/msg 2종 (SetMode/ModeState)
- launch spawn/kill 은 **stub 로그만** (실 launch 제어는 B 단계)
- dev_all.launch.py 통합
- 검증: ros2 service call + topic echo

**A2 가 안 다루는 것** (B 이후 트랙):
- 실 launch_ros API 또는 subprocess 로 stack 제어
- 자동 트리거 (POS, vision, 한산도 감지)
- 운영자 UI (A3)
- mode 별 phrase pool / 자체 발화 (A1 router 위에 얹음)

---

## 1. 작업 흐름 (Task 7~10)

### Task 7 — `SetMode.srv` + `ModeState.msg` 신규

**`SetMode.srv`** — 운영자/자동 트리거 → mode_manager 전환 요청:
```
string requested_mode    # "idle" | "npc" | "serving" | "follow"
string params            # JSON. serving={"waypoint":"table_5"}, follow={"target":"owner"}, etc.
---
bool success
string current_mode      # 응답 시점 실제 모드 (reject 시 미변경)
string reason            # "unknown_mode:..." | "invalid_json_params:..." | "battery_low:..." | "safety_alarm_active"
```

**`ModeState.msg`** — 1Hz publish, 운영자 UI/모니터링 입력:
```
std_msgs/Header header
string current_mode
builtin_interfaces/Time entered_at
string params                # 진입 시 JSON snapshot
bool battery_ok
bool safety_ok
string last_reject_reason    # 직전 reject 사유 (success 시 clear)
```

**디자인 의도**:
- params 를 **JSON string** 으로 두면 모드별 schema 변화에 msg 변경 불필요. parse 책임은 mode_manager 와 per-mode stack.
- last_reject_reason 은 운영자 UI 디버깅용 — 수락된 전환 시 clear.
- battery_ok / safety_ok 가드 상태를 publish 에 노출 → UI 가 별도 토픽 합치기 없이 모드+가드를 한 화면에 표시 가능.

빌드: `colcon build --packages-select dobi_npc_msgs` 6.45s.

### Task 8 — `mode_manager_node.py` 신설 (`dobi_npc_bringup`)

**패키지 선택**: 신규 `dobi_npc_orchestrator` 만들지 vs `dobi_npc_bringup` 통합 검토. 결정 = bringup 통합. 이유:
- 이미 `fake_customer_publisher.py` 같은 보조/오케스트레이션 노드 들어있음 (성격 동일)
- mode_manager 가 launch_ros API 와 가까운 곳에 있는 게 B 단계에서 자연스러움
- 신규 패키지는 의존성 그래프만 늘어남

**구현 핵심** (180줄):
- `VALID_MODES = ('idle', 'npc', 'serving', 'follow')` 4상태 dict
- `_lock = threading.Lock()` 으로 콜백 + 서비스 + timer 보호
- 입력: `/battery_state` (sensor_msgs/BatteryState), `/rapport/event` (RapportEvent abort_trigger 인지)
- 서비스: `/mode/request` (SetMode)
- 출력: `/mode/state` (ModeState, 1Hz timer)

**전이 규칙 (첫 cut)**: 모든 mode 간 전환 허용. 가드만 추가:
1. requested_mode 검증 (VALID_MODES 멤버십)
2. params JSON 형식 검증 (빈 문자열 OK)
3. **idle 외 전환은** battery_ok && safety_ok 조건 통과 필요. **idle 로의 전환은 항상 허용** (안전 측)

**가드 — battery 미수신 정책**:
```python
def _battery_ok(self) -> bool:
    if self._battery_pct < 0.0:    # 미수신
        return True                # 안전 측 OK 처리
    return self._battery_pct >= self.battery_min
```

라이브 환경에서 vic_pinky bringup 안 떠도 mode_manager 단독 운용 가능. 실 운영에선 토픽 수신 후 임계 비교가 가드. 미수신을 reject 로 처리하면 노트북 단독 검증/개발이 막혀 비현실적.

**가드 — safety alarm dwell**:
```python
def _on_rapport(self, msg):
    if msg.event_type == 'abort_trigger':
        self._safety_alarm_until_ns = now + dwell_sec * 1e9
        if self._current_mode != 'idle':
            self._set_mode_locked('idle', '', reject_reason='safety_alarm_forced_idle')
```

abort_trigger 1회 수신 시 dwell(기본 5초) 동안 idle 외 모드 거부 + 즉시 강제 idle 전이. dwell 끝나면 자동 회복.

**launch stub** — A2 첫 cut:
```python
if prev != new_mode:
    self.get_logger().info(
        f'[stub] kill {prev}_stack | spawn {new_mode}_stack (params=\'{params}\')')
```

B 단계에서 launch_ros API 또는 subprocess 로 실제 stack 제어. 현 cut 은 FSM/인터페이스/가드 검증에 집중.

**setup.py + package.xml**: entry_point 추가 + sensor_msgs 의존성 추가.

빌드: `colcon build --packages-select dobi_npc_bringup` 1.42s. Smoke 테스트 통과.

### Task 9 — `dev_all.launch.py` 통합

8번째 노드로 `mode_manager` 추가. `initial_mode` launch arg 추가 (기본 `idle`).

```python
initial_mode_arg = DeclareLaunchArgument(
    'initial_mode', default_value='idle',
    description='mode_manager 초기 모드 (idle|npc|serving|follow)')
...
Node(
    package='dobi_npc_bringup', executable='mode_manager',
    name='mode_manager', output='screen',
    parameters=[{'initial_mode': LaunchConfiguration('initial_mode')}],
),
```

기존 7 노드 무변경.

### Task 10 — 라이브 검증 (service call 시퀀스)

mode_manager 단독 background 시동 후 7 시나리오 검증.

**4 전이 시퀀스** (idle → npc → serving → follow → idle):
```
[INFO] mode_manager ready: initial=idle battery_min=0.2 pub_hz=1.0
[INFO] [stub] kill idle_stack | spawn npc_stack (params='')
[INFO] mode idle → npc params=''
[INFO] [stub] kill npc_stack | spawn serving_stack (params='{"waypoint": "table_5"}')
[INFO] mode npc → serving params='{"waypoint": "table_5"}'
[INFO] [stub] kill serving_stack | spawn follow_stack (params='{"target": "owner"}')
[INFO] mode serving → follow params='{"target": "owner"}'
```
4 전이 모두 success, stub 로그 정확.

**Reject 시나리오 2종**:
- `requested_mode='barista'` → `unknown_mode:barista`
- `requested_mode='serving' params='not_json'` → `invalid_json_params:Expecting value`

current_mode 미변경 (`follow` 그대로), last_reject_reason 정확 기록.

**가드 — safety alarm 강제 idle**:
```
Step 1: idle → npc 정상 전환
Step 2: ros2 topic pub /rapport/event {event_type: "abort_trigger", ...}
Step 3: ros2 service call ... requested_mode='npc'
        → SetMode_Response(success=False, current_mode='idle',
                           reason='safety_alarm_active')
/mode/state: current_mode=idle, safety_ok=false,
             last_reject_reason='safety_alarm_active'
```

abort_trigger 인지 즉시 강제 idle + dwell 동안 idle 외 모드 거부.

**`/mode/state` 1Hz publish 정상** — 검증 시작/종료 시점에 모두 정확한 상태 (initial idle, 가드 통과 false 반영).

---

## 2. 핵심 학습

### "stub 로그만" — 인터페이스 검증을 launch 구현과 분리

A2 가 stub 로 끊은 덕분에 검증 부담이 작음. FSM 로직 + service contract + 가드 정책을 launch_ros 의존성 없이 검증 — Python `transitions` 같은 라이브러리 없이도 dict + lock + service 만으로 충분히 정확.

B 단계에서 launch 제어를 추가할 때 mode_manager 의 외부 인터페이스(`/mode/request` srv + `/mode/state` topic)는 변경 없음. 운영자 UI(A3)는 인터페이스에만 의존하므로 B 와 병행 개발 가능.

**원칙**: 한 트랙에 한 가지 책임. A2 = "결정 로직 + 인터페이스", B = "결정 → 실행 연결". 한꺼번에 하면 검증이 launch 환경 의존성에 매몰됨.

### 미수신 입력의 "안전 측" 정의는 케이스마다 다름

`/battery_state` 미수신 → `battery_ok=True` 처리 (개발 편의 우선). 실 라이브 환경에선 항상 수신되므로 가드가 정상 작동.

`/rapport/event` abort_trigger → 명시 메시지가 와야만 alarm 발동 (수신 없음 = alarm 없음).

**원칙**: "안전 측"은 단일 정의가 없음. 입력별로 "운영 정상 시 빈도 + 미수신의 의미"를 보고 결정.
- 배터리: 정상 시 1Hz 지속 → 미수신은 "토픽 미연결"이지 "위험"이 아님. 라이브 환경에서 "미수신 → reject"는 너무 엄격 (개발 막힘).
- alarm: 정상 시 0Hz, 위험 시 발생 → 미수신이 정상.

이 비대칭이 코드의 두 갈래를 정당화함. 회고에 남겨둠 — 향후 같은 패턴 (위치/감정 등) 가드 추가 시 참조.

### params를 JSON string으로 두는 비용/이득

비용: msg schema 가 string 1개라 IDE/언어 자동완성 무용. parse 책임이 런타임으로 이동.

이득: 모드별 schema 변화에 msg/srv 안 건드림. 새 모드 추가도 인터페이스 변경 0. 운영자 UI 가 form 만들 때도 "JSON textarea + 모드별 placeholder hint" 한 가지 패턴.

A2 시점에서 이득 > 비용 — 첫 cut 에서는 schema 자체가 흔들림. 일정 안정화 후 (B 또는 C 단계) 모드별 typed msg 분리 검토. 운영자 UI 에서도 모드별 form schema 정의 시점에 자연스레 정리.

### last_reject_reason — success 시 clear 정책

`_set_mode_locked` 가 reject_reason 을 인자로 받음. success 호출 시 `reject_reason=''` 로 clear. UI 입장에서는:
- 직전 시도가 reject 였으면 그 사유 표시
- success 가 한 번이라도 들어가면 사라짐

운영자가 "왜 거절됐지?" 보다 "지금 상태가 정상이지?"에 더 관심 있다는 가정. 누적 reject 통계가 필요하면 별도 토픽/로그로 분리.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **FSM dict + lock 만으로 4상태 충분** — Python `transitions` 라이브러리 도입 없이 코드 ~180줄. 디버깅(어느 콜백에서 어느 전이가 일어났는지) 직관적.
- **idle 외 전환의 가드 + idle 으로의 전환 무조건 허용** 비대칭이 "안전 fall-back" 의미를 코드로 자연스럽게 표현.
- **`/mode/state` 가드 상태 노출** 한 토픽에 모드 + 가드 모두 → UI 가 단일 구독으로 전체 상태 파악.

### 위험 요소

- **launch stub 가 실제 stack 제어와 분리됨** — B 단계에서 stack spawn/kill 실패 시 mode_manager 의 `_current_mode` 와 실제 살아있는 stack 이 어긋날 가능성. B 에서 spawn/kill 결과를 confirm 하는 메커니즘 필요.
- **safety alarm dwell 5초 고정** — 실 운영에서 dwell 중 alarm 재발생 시 dwell 연장이 자동 (현 코드도 max 갱신). 그러나 dwell 끝나면 자동 회복하는 정책이 운영 시나리오에 적합한지 별도 검토.
- **battery 미수신 → ok 처리** — 라이브 검증 끝나고 실 운영 진입 시 "필수 수신" 모드로 전환할지 정책 결정 필요 (config flag 추가 검토).

### 갭

- **launch_ros API or subprocess 결정 미정** (B 단계). 후보:
  - launch.LaunchService + LaunchDescription in-process — 깨끗한 shutdown, 단 mode_manager 가 무거워짐
  - subprocess.Popen with `ros2 launch` — 격리, 단 cleanup 보장 약함
- **모드별 phrase pool / 자체 발화** — A1 router 가 다중 publisher 받으니 모드별 stack 자체가 `/dialog/router_in` 으로 publish 하면 됨. 그러나 어떤 모드에서 어떤 발화를 어느 시점에 할지 정책은 모드 stack 구현 시 결정.
- **자동 트리거 (POS/vision/한산도)** — A2 는 운영자 수동 트리거 first 정책. 자동 트리거는 같은 service call 사용해서 별도 노드(`hall_state_aggregator` 등)가 발사. 본 트랙 범위 외.
- **dev_all 풀 라이브 미검증** (mode_manager 단독만 검증). 다른 노드와의 토픽 충돌/이름 중복 없음을 확인하려면 풀 시동 + service call 한 차례 더 권장.

---

## 4. 다음 일정

### A3 (운영자 UI 모드 패널)

- [ ] `teleop_server.py` (`~/cabot/web/teleop_server.py`) 확장 — 모드 버튼 (NPC ON / 서빙 → 테이블 N 선택 / 팔로우 / 대기) + 현재 모드/가드 상태 표시
- [ ] `/mode/request` 서비스 호출 + `/dialog/router_in` 강제 발화 입력 폼 (priority/preempt 토글)
- [ ] `/mode/state` 1Hz 구독 → UI 자동 갱신

### B (실 launch spawn/kill)

- [ ] launch_ros API vs subprocess 선택
- [ ] mode_manager `_set_mode_locked` 의 stub 을 실 spawn/kill 로 교체
- [ ] spawn/kill 실패 시 `_current_mode` rollback + reject 응답
- [ ] dev_all 분리: 공통 always-on launch + 모드별 launch 4종 (idle 은 빈 stack)

### dev_all 풀 라이브 검증 (A2 보강)

- [ ] dev_all.launch.py 시동 + `/mode/request` service call → 토픽 충돌/이름 중복 없음 확인
- [ ] 실 vic_pinky bringup 연결 + battery_ok 가드 라이브 검증

### tts_node `/dialog/cancel` (A1 후속)

- [ ] safety alarm 을 router priority=0 + `/dialog/cancel` 경로로 통합 가능 (현재는 rapport abort_trigger 별도 경로)

---

## 5. 변경된 파일

```
src/dobi_npc/dobi_npc_msgs/srv/SetMode.srv         [신규]
src/dobi_npc/dobi_npc_msgs/msg/ModeState.msg       [신규]
src/dobi_npc/dobi_npc_msgs/CMakeLists.txt          ~ srv/msg 등록 2줄

src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py  [신규, ~180줄]
src/dobi_npc/dobi_npc_bringup/setup.py             ~ entry_point 1줄
src/dobi_npc/dobi_npc_bringup/package.xml          ~ sensor_msgs depend 1줄
src/dobi_npc/dobi_npc_bringup/launch/dev_all.launch.py
                                                   ~ initial_mode arg + Node 블록

docs/daily/2026-05-04_mode_manager_a2.md           (본 회고)
```

기존 파일 무변경: `dialog_router_node.py`, `persona_manager_node.py`, `tts_node.py`, `face_avatar_node.py`, `bt_executor`, `geva_node`, `rapport_tracker_node`. mode_manager 가 `/rapport/event` 만 read-only 구독, 나머지 시스템과 출력 토픽 충돌 없음.

---

*마지막 갱신: 2026-05-04 밤 (A2 mode_manager 라이브 검증 통과, 4상태 + 가드 + 2 reject 시나리오)*
*다음 갱신 예정: A3 운영자 UI 모드 패널 또는 B 실 launch 제어*
