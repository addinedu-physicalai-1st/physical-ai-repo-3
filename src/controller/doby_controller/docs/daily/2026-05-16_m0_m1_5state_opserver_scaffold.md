# 2026-05-16 — M0 + M1: 5-state FSM 확장 + moca_opserver scaffold + 단위 테스트

> 작업자: Stephen Kong (gjkong)
> 선행 문서: `docs/moca_mode_and_opserver_plan.md` v1.0,
>            `docs/moca_5state_fsm_spec.md` v1.0,
>            `docs/moca_opserver_api_spec.md` v1.0
> 다음 회고: M2 진입 전 `moca_patrol_design.md` + `moca_guiding_design.md` 수령 후

---

## 1. 오늘의 목표

기존 4상태 FSM (`idle/npc/serving/follow`) 을 5상태 (`idle/serving/patrol/guiding/engaging`) 로
확장하고, 외부(POS/OpenARM) ↔ ROS 게이트웨이 `moca_opserver` 패키지를 신설.
마스터 계획서 §13 액션 아이템 1~3 (msg/srv → mode_manager → opserver scaffold) 까지 완주.

## 2. M0 산출물 (메시지/서비스)

### 2.1 신규 5종 msg (`src/dobi_npc/dobi_npc_msgs/msg/`)

| 파일 | 발행자 (예정) | 용도 |
|---|---|---|
| `PatrolState.msg` | patrol_scheduler_node | 순회 진행 1Hz (scanning/moving/report/returning/done) |
| `TableReport.msg` | table_occupancy_detector_node | 테이블 점유 결과 (empty/occupied/finished/unknown + person_count + dishes_detected + sensor_msgs/CompressedImage snapshot) |
| `GuidingState.msg` | guiding_controller_node | 동행 안내 1Hz (lockon/moving/waiting_customer/arrived/lost) |
| `OpEvent.msg` | moca_opserver_node | 외부 이벤트를 ROS 도메인에 echo (디버깅/로깅) |
| `OperatorCommand.msg` | moca_opserver_node | 운영자 미세 제어 (utter/express/stop_emergency/resume/skip_table) |

### 2.2 신규 2종 srv

- `GetTableStatus.srv` — 테이블 점유 캐시 조회 (REST `/api/v1/tables` 의 ROS 백엔드)
- `SetPatrolSchedule.srv` — 순회 주기/활성화 동적 갱신

### 2.3 기존 파일 갱신

- `ModeState.msg` — 코멘트만 4-state → 5-state + legacy alias 명시
- `SetMode.srv` — 코멘트 5-state + reason 사전 + params 스키마 모드별 예시
- `CMakeLists.txt` — `sensor_msgs` 의존 추가 (`TableReport.snapshot` 때문), 7개 신규 등록
- `package.xml` — `sensor_msgs` depend 추가

빌드 통과: `colcon build --packages-select dobi_npc_msgs` (11.8s).
`ros2 interface package dobi_npc_msgs` 14종 모두 등록 확인.

## 3. M1 산출물

### 3.1 mode_manager_node.py (FSM 코어)

위치: `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py`

핵심 변경:
- `VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging')`
- `LEGACY_MODE_ALIAS = {'npc': 'engaging', 'follow': 'guiding'}` 자동 변환 + WARN 로그
- `_on_request` 진입부에 alias 변환 (FSM spec §6.3)
- `/operator/command` 토픽 구독 + `_on_operator_cmd` 콜백 (`stop_emergency` 강제 idle + alarm dwell, `resume` 즉시 해제) — FSM spec §3.4
- docstring 5-state + priority enforce 책임이 OpServer 라는 점 명시

핵심 보존: priority enforce 룰은 **mode_manager 에 추가 안 함** — FSM spec §5.2 책임 분리 원칙에 따라 OpServer 가 enforce. mode_manager 는 priority 무관 모든 전이 허용 (운영자 수동 트리거 우선).

스모크 테스트 결과:
- `unknown_mode:foobar` → `success=False` ✅
- `npc` → WARN + `engaging` 자동 변환 → `transition_started` ✅
- `patrol` 진입 → `patrol_stack_stub` 노드 spawn 확인 ✅

### 3.2 launch 5개 (`src/dobi_npc/dobi_npc_bringup/launch/`)

| 파일 | 내용 |
|---|---|
| `mode_engaging.launch.py` (★ 신규) | 기존 `mode_npc.launch.py` 리네이밍 — bt_executor + minigame_runner. 내부 BT `cafe_funnel_v1.xml` 그대로 |
| `mode_guiding.launch.py` (★ 신규, M1 임시) | follow stack (person_detector + follow_controller) 재사용. M2 에서 진짜 `guiding_controller_node` 로 교체 예정 (Nav2 주도 + customer 추적 supervisor) |
| `mode_patrol.launch.py` (★ 신규, M1 stub) | `mode_stack_stub` placeholder. M2 에서 `patrol_scheduler_node` + `table_occupancy_detector_node` 추가 |
| `mode_npc.launch.py` | deprecation wrapper → `mode_engaging.launch.py` (LogInfo + IncludeLaunchDescription). M3 종료 2026-07-04 후 제거 |
| `mode_follow.launch.py` | deprecation wrapper → `mode_guiding.launch.py` |

통합 스모크: 3종 모드 (`patrol/engaging/guiding`) 모두 spawn → 노드 alive → idle 복귀 (kill=term + idle_no_stack) 정상.

### 3.3 moca_opserver 신규 패키지 (`src/moca_opserver/`)

ament_python 패키지. 핵심 모듈 5개:

| 파일 | 책임 |
|---|---|
| `opserver_node.py` | 메인 ROS 노드 + FastAPI uvicorn thread 임베드. ROS 구독 8 (mode/serving/patrol/table_report/guiding/battery/odom/rapport), 발행 4 (opserver/event, operator/command, serving/goto_table, utter/request). robot_online 판정 timer (3s threshold). /odom 20Hz→1Hz 다운샘플. OpServerConfig dataclass + dynamic update |
| `mode_orchestrator.py` | priority 5-state gating + 사전 가드 (battery/safety/robot_online) + SetMode async 호출 (2s timeout, future poll). `override_priority=True` 운영자 의도 우선 |
| `rest_api.py` | FastAPI 라우터 — `/health`, `/status`, `/tables`, `/order`, `/pickup` (★ priority 분기), `/guide`, `/mode`, `/command`, `/emergency_stop`, `/config` GET+POST. WS `/ws/dashboard` 핸들러 + client→server dispatch (set_mode/emergency_stop/utter/skip_table/set_config/ack_alarm) |
| `ws_hub.py` | WebSocket broadcast 허브. `broadcast_threadsafe(loop, type, data)` 로 ROS 콜백(별 thread) → asyncio loop 안전 진입. welcome / fan-out / dead client cleanup |
| `schemas.py` | pydantic 모델 — Order/Pickup/Guide/Mode/Command/Config REST 요청 + WS 6종 클라이언트 메시지 |

부속:
- `launch/opserver.launch.py` — config_file 인자 지원
- `config/opserver_config.yaml` — host/port + patrol 정책 + 가드 임계 + completion_dwell
- `package.xml` — `python3-fastapi/uvicorn/pydantic/websockets/yaml` exec_depend

통합 스모크 (mode_manager + opserver 동시 기동) 결과:
- `GET /health` → JSON OK
- `GET /status` → mode/battery/queue/tables/config snapshot
- `POST /pickup` (idle→serving) → `preempted=true, current_mode_before=...` priority 1<X 선점 동작 ✅
- `POST /pickup` 중복 event_id → **HTTP 409 DUPLICATE_EVENT** ✅
- `POST /mode override_priority=true` → idle 강제 복귀 ✅
- `POST /emergency_stop` → `OperatorCommand{stop_emergency}` 발행, mode_manager 측 강제 idle 진입 ✅

### 3.4 단위 테스트 (`src/moca_opserver/test/test_orchestrator.py`)

41 tests / 0 failures (pytest 0.22s, colcon test 통과).

커버리지:
- priority gating 5×4=**20 매트릭스** (idle/serving/patrol/guiding/engaging × 4 target, self-loop 제외)
- override_priority=True 4 케이스 (운영자 강제 lower-priority 허용)
- 가드 6: battery_low(rejects active / allows idle / unknown ok) + safety_alarm(rejects / allows idle)
- 입력 검증 2: invalid_mode 거부 + legacy alias (npc/follow) 는 mode_manager 책임이라 orchestrator 가 INVALID_MODE 처리
- 로봇 오프라인 2: rejects active / allows idle
- SetMode 응답 3: failure_propagated / service_unavailable / 0.1s timeout
- preempted flag 3: correctness / idle_origin / to_idle
- PRIORITY 상수 sanity 1
- self-loop 거부 1

테스트 전략: ROS 노드 없이 ModeOrchestrator + FakeNode + MagicMock SetMode client.
`cli_set_mode.wait_for_service` / `call_async` / `future.result` 패치.
실 SetMode 통신은 통합 스모크에서 검증.

## 4. 발견 / 결정

### 4.1 priority enforce 책임 분리 명문화

FSM spec §5.2 + API spec §5.1 모두 "priority enforce 는 OpServer 에서" 결정.
mode_manager 는 priority 무관 모든 전이 허용 (운영자 수동 명령이 직접 호출해도 동작).
이렇게 분리하면 비즈니스 룰(주기/영업시간/우선순위 변경) 이 mode_manager 재기동 없이 가능.
단위 테스트도 ModeOrchestrator 만 검증 (mode_manager 코어는 별개).

### 4.2 M1 임시 모드 stack 처리

`patrol` / `guiding` 의 진짜 노드 (patrol_scheduler / table_occupancy_detector / guiding_controller) 는
M2 작업. M1 단계에서는:
- **patrol**: `mode_stack_stub` 1개 (1Hz "patrol stack alive" 로그만). spawn/kill cycle 검증용
- **guiding**: 기존 follow stack 그대로 재사용. 알고리즘은 follow=주인 추적, guiding=로봇 앞장+추적
  → M2 에서 신규 작성 필요 (FSM spec §2.4 50% 신규)

mode_manager 의 spawn/kill 파이프라인 자체는 두 모드 모두 정상 동작 확인.

### 4.3 FastAPI / uvicorn / pydantic 의존

Ubuntu 24.04 시스템 apt 에 `python3-fastapi 0.135` / `python3-uvicorn 0.44` / `python3-pydantic 2.13`
이미 설치되어 있음 (별도 pip 불필요). `package.xml` 에 `exec_depend` 로 명시.

CLAUDE.md §7 외부 의존성 정책 (mediapipe/edge-tts 만 user pip) 준수.

### 4.4 [[feedback_dont_touch_working_code]] 준수

- `mode_npc.launch.py` / `mode_follow.launch.py` 내부 노드 구성 그대로 새 파일 (`mode_engaging` / `mode_guiding`) 에 복제. 기존 파일은 deprecation wrapper 로 변환 (legacy SetMode 호출 경로가 끊기지 않도록)
- `mode_manager_node.py` 수정 범위: VALID_MODES 1줄, LEGACY_MODE_ALIAS dict 1개, `_on_request` 진입부 4줄, `_on_operator_cmd` 콜백 1개, 구독 1줄. 기존 `_do_transition` / `LaunchSupervisor` / `_publish_state` 무수정
- `tables.yaml` / `serving_dispatcher_node.py` / `cafe_funnel_v1.xml` 무수정

### 4.5 LEGACY_ALIAS는 mode_manager 만, orchestrator는 거부

orchestrator 는 VALID_MODES (5종) 만 허용. `npc`/`follow` 를 던지면 `INVALID_MODE` 반환.
mode_manager 가 SetMode 호출 직전에 alias 변환하므로, REST 클라이언트는 새 이름만 사용.
이는 책임 분리 원칙 + 외부 인터페이스의 "단일 진실" 보장.

### 4.6 sensor_msgs 의존 추가의 파급

`TableReport.msg` 의 `sensor_msgs/CompressedImage snapshot` 필드 때문에 CMakeLists.txt 에
`find_package(sensor_msgs REQUIRED)` + `DEPENDENCIES sensor_msgs` 추가. 다른 메시지 (Patrol/Guiding/OpEvent/OperatorCommand) 는 std_msgs/builtin_interfaces 만 사용.

M2 단계 카메라 통합 시 snapshot 채우기. M2 까지는 빈 메시지로 발행해도 OK.

## 5. 빌드 / 테스트 명령

```bash
# 전체 빌드 (검증)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  colcon build --packages-select dobi_npc_msgs dobi_npc_bringup moca_opserver --symlink-install
'

# 단위 테스트
source install/setup.bash
python3 -m pytest src/moca_opserver/test/test_orchestrator.py -v
# 또는 colcon test --packages-select moca_opserver

# 통합 스모크 (mode_manager + opserver 동시)
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 run dobi_npc_bringup mode_manager &
ros2 run moca_opserver opserver_node &
sleep 5
curl http://localhost:8800/api/v1/health
curl -X POST http://localhost:8800/api/v1/pickup \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"t1","drink_id":"D-t1","target_table":"T03","via_pickup":true,"ready_at":"2026-05-16T13:00:00Z"}'
ros2 topic echo /mode/state --once
```

## 6. 미해결 / 다음 단계

### 6.1 M1 미완 (FSM/API spec §9 미해결 이슈 — M1 결정 보류)

| # | 이슈 | 결정 시점 |
|---|---|---|
| F1 | `_publish_state` 의 supervisor.is_running() 불일치 자동 복구 | M2 본격 진입 후 라이브 시뮬에서 결정 |
| F2 | spawn_failed 자동 재시도 | 현 즉시 idle rollback 유지 (테스트 통과) |
| F3 | 운영자 수동 명령의 `manual_override` 표시 — ModeState 필드 추가? | M3 web dashboard 작업 시 |
| F4 | engaging abort 시 idle vs 직전 모드 복원 | 사용자 결정 필요 (현 always idle) |
| F5 | guiding customer lost 시 정지 대기 vs idle | M2 guiding 설계 시 |
| O1 | FastAPI ↔ rclpy executor 통합 — 현 별 thread, asyncio task 검토 | 안정 후 |
| O2 | SetMode timeout — 현 2s 후 INTERNAL_ERROR | 라이브에서 튜닝 |
| O3 | KPI 영속화 — 현 in-memory deque(500) | M3 sqlite |
| O4 | WS 권한 차등 (operator vs viewer) | M3 인증 도입 시 |
| O5 | event_log 영속화 | M3 |
| O6 | priority gating 위치 (현 orchestrator 단일) | 변경 안 함 (책임 분리 원칙) |

### 6.2 M2 진입 전 필요 산출물

- `docs/moca_patrol_design.md` (사용자 제공)
- `docs/moca_guiding_design.md` (사용자 제공)

이 두 문서 받은 후 M2 본격 시작:
- `patrol_scheduler_node.py` 신규 (sweep T01-T05, dwell 2s, /patrol/state + /patrol/table_report 발행)
- `table_occupancy_detector_node.py` 신규 (YOLOv8 person, M3 식기 detection)
- `guiding_controller_node.py` 신규 (Nav2 주도 + customer 카메라 추적, lockon→moving→waiting→arrived 상태머신)
- opserver `CompletionWatcher` — 각 활동 모드 `/X/state` dwell 후 자동 `SetMode('idle')` 호출 (API spec §5.4)
- opserver `PatrolScheduler` — 5분 idle dwell + 영업시간 체크 후 patrol 자동 트리거 (API spec §5.2)

### 6.3 M3 진입 전 필요 산출물

- `docs/moca_web_dashboard_spec.md` (사용자 제공)

### 6.4 즉시 후속 (선택)

- 커밋 — Conventional Commits 형식 권장 (`feat(msgs):` / `feat(bringup):` / `feat(opserver):` / `test(opserver):`)
- 일일 백업 (작업 종료) — `~/backup/moca_daily_20260516_HHMM/` 추가 본 (`38f6662` HEAD 는 변하지 않음, working tree 변경분만 patch)

## 7. 메모리 갱신 사항

본 작업으로 새로 박힐 만한 메모리 후보:
- (없음 — 본 작업은 모두 spec 문서대로 진행. 새로운 함정/회피책 없음)

기존 메모리와의 정합 확인:
- `[[feedback_dont_touch_working_code]]` — mode_manager 수정 범위 최소화 + 기존 launch 보존 ✅
- `[[feedback_terminology_mogaek]]` — 본 회고는 "모객" 사용 ✅
- `[[project_navigation_code_separation]]` — opserver 가 `/cmd_vel*` 발행 안 함, mode_serving 의 cmd_vel publisher 추가 없음 ✅
- `[[feedback_freeze_gazebo_world_20260515]]` — Gazebo 자산 무수정 ✅

---

*다음 갱신: M2 design 문서 수령 + patrol/guiding 본격 구현 후 별도 회고*
