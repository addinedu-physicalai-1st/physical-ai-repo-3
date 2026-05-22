# MOCA Mode FSM 사양서 (구 5-State, 현 6-State 확장)

> **문서 ID**: `moca_5state_fsm_spec.md` *(파일명은 v1.0 시점 5-state 기준 — 6-state 확장 후에도 cross-reference 보존 위해 그대로 유지)*
> **버전**: v1.1 (2026-05-19 — `follow` 6번째 상태 정식 승격, 후술 §0.2 참조)
> **이전 버전**: v1.0 (2026-05-16, 5-state)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2
> **구현 대상**: `dobi_npc_bringup/mode_manager_node.py`, `dobi_npc_msgs/srv/SetMode.srv`, `dobi_npc_msgs/msg/ModeState.msg`
> **워크스페이스**: `~/physical-ai-repo-3/src/controller/doby_controller` (ROS2 Jazzy, `ROS_DOMAIN_ID=22`) — *2026-05-19 이전 `~/moca`*

---

## 0. 본 문서의 범위

본 문서는 vic_pinky 서빙 로봇의 **운영 모드 FSM**(Finite State Machine)을 형식적으로 정의한다. 다음 4가지를 명확히 한다:

1. 각 상태의 **invariant**(상태 유지 동안 항상 참이어야 할 조건)
2. 각 상태의 **entry / during / exit action**(진입 시점/유지 동안/종료 시점에 수행하는 행위)
3. 전이의 **guard**(전이 허용 조건)와 **event**(전이를 일으키는 사건)
4. 동시성/경쟁 상황의 결정론적 처리 규칙

본 문서는 구현 코드와 1:1 대응되도록 작성되었으며, 기존 `mode_manager_node.py`의 확장 방향을 명세한다.

### 0.1 본 문서가 다루지 않는 것

- 각 모드 내부의 dispatcher/controller 로직 (별도 문서: `moca_patrol_design.md`, `moca_guiding_design.md`)
- 외부 트리거 발생 메커니즘 (별도 문서: `moca_opserver_api_spec.md`)
- 웹 UI에서의 모드 표시 (별도 문서: `moca_web_dashboard_spec.md`)

### 0.2 v1.1 변경 사항 — 6-state 확장 (2026-05-19)

**배경**: 2026-05-19 `moca_teammember` 18 commit 머지 (회고 `docs/daily/2026-05-19_teammember_merge.md`) 시 사용자 결정 — *"mode_follow + mode_guiding 분리 운용 (둘 다 살림) — VALID_MODES 6-state"*.

**v1.0 (5-state)**: `{idle, serving, patrol, guiding, engaging}` — 머지 직전 시점. `follow` 는 legacy alias 로 `guiding` 으로 자동 변환.

**v1.1 (6-state)**: `{idle, serving, patrol, guiding, engaging, follow}` — `follow` 가 정식 6번째 상태로 승격. `guiding` 과 알고리즘 정반대 (follow=reactive 추종, guiding=proactive 인솔) 라 별도 모드 유지가 옳다는 사용자 판단.

**spec-code 정합 상태**:
- ✅ `mode_manager_node.py` `VALID_MODES` — 6-state (2026-05-19 머지 직후 적용)
- ✅ `mode_follow.launch.py` — 별도 stack 운용 (deprecation wrapper 아님)
- ✅ `follow_controller_node.py` + `person_detector` — 추종 stack
- ✅ 본 문서 — 2026-05-19 v1.1 갱신으로 6-state 정합
- ✅ `dobi_npc_msgs/{msg/ModeState.msg, srv/SetMode.srv}` 코멘트 — 2026-05-19 v1.1 갱신으로 6-state 정합
- ⚠ **운영자 UI / 웹 대시보드는 5-state 기준 그대로 (`web/static/*.html` + `teleop_server.py` 의 모드 표시 / 모드 전환 버튼)** — `follow` 모드의 UI 통합은 별도 트랙 (사용자 확인 2026-05-19). 본 spec v1.1 이 SoT 로서 6-state 를 명세하지만, UI 구현은 향후 작업에서 추격 예정. UI 측 follow 미지원 기간 동안엔 ros2 service / CLI 로만 follow 모드 진입 가능.

**Legacy alias 정리**:
- v1.0: `LEGACY_MODE_ALIAS = {'npc': 'engaging', 'follow': 'guiding'}`
- v1.1: `LEGACY_MODE_ALIAS = {'npc': 'engaging'}` — `'follow': 'guiding'` 제거 (follow 가 정식 상태이므로 alias 불필요)

---

## 1. 형식적 정의

### 1.1 상태 집합 S

```
S = { S_idle, S_serving, S_patrol, S_guiding, S_engaging, S_follow }
```

상태 ID는 ROS 도메인에서 다음 문자열 리터럴로 표현된다:

```python
VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')
#                                                                   ^^^^^^ v1.1 추가 (2026-05-19)
```

**초기 상태**: `S_idle` (전원 ON 시 mode_manager가 `idle`로 부팅).

**종료 상태**: 없음 (FSM은 무한 동작; 전원 OFF는 외부 사건).

### 1.2 입력 사건 집합 E

전이를 일으킬 수 있는 사건은 7종이다:

| 사건 코드 | 의미 | 발생 출처 |
|---|---|---|
| `e_set_mode(m, p)` | SetMode 서비스 호출 (모드 m, params p) | opserver, 운영자 UI, 디버깅 |
| `e_complete` | 현재 모드의 임무 완료 | 각 모드 dispatcher (간접) |
| `e_battery_low` | `/battery_state.percentage < battery_min` | `/battery_state` 콜백 |
| `e_safety_alarm` | `/rapport/event.event_type == "abort_trigger"` | `/rapport/event` 콜백 |
| `e_emergency_stop` | 운영자 비상정지 | `OperatorCommand{command_type:"stop_emergency"}` |
| `e_battery_recovered` | 배터리 임계 초과 회복 | `/battery_state` 콜백 (5초 hysteresis) |
| `e_alarm_dwell_done` | safety alarm dwell 5초 경과 | mode_manager 내부 타이머 |

### 1.3 전이 함수 δ

전이는 다음 5-tuple로 정의한다:

```
transition = (S_from, e, guard, action, S_to)
```

- `S_from`: 현재 상태
- `e`: 입력 사건
- `guard`: 부울 함수 (참일 때만 전이 허용)
- `action`: 전이 시 수행할 부수 효과
- `S_to`: 목표 상태

전체 전이 목록은 §3에 정의.

### 1.4 가드 함수 G

```python
G_battery_ok      ≡ (battery_pct < 0.0)  ∨  (battery_pct >= battery_min)
                    # 미수신(-1)은 안전 측 OK (라이브 미연결 환경 호환)

G_safety_ok       ≡ (now_ns >= safety_alarm_until_ns)

G_not_busy        ≡ (busy_flag == False)

G_valid_mode(m)   ≡ (m ∈ VALID_MODES) ∨ (m ∈ LEGACY_MODE_ALIAS.keys())

G_valid_params(p) ≡ (p == "") ∨ (json.loads(p) is dict)

G_can_enter(m)    ≡ G_valid_mode(m) ∧ G_valid_params(p) ∧ G_not_busy ∧
                    (m == 'idle' ∨ (G_battery_ok ∧ G_safety_ok))
```

가드 미통과 시 SetMode는 `success=False`와 reason 문자열로 응답한다 (구체 코드 §6.1).

---

## 2. 상태 사양

각 상태는 다음 8개 속성으로 명세된다.

### 2.1 S_idle (대기)

| 속성 | 값 |
|---|---|
| ID | `'idle'` |
| 우선순위 | 99 (최저) |
| **Invariant** | • 활성 launch stack 없음 (`LaunchSupervisor._proc == None`)<br>• `/cmd_vel` 0 또는 미발행<br>• `/mode/state.current_mode == 'idle'` (1Hz) |
| **Entry action** | 1. 기존 stack kill (있으면)<br>2. `_current_mode = 'idle'`, `_params = ''`<br>3. `_entered_at = now()`<br>4. (선택) home_pose로 복귀 Nav2 goal (caller 모드의 cleanup 책임) |
| **During action** | • `_publish_state()` 1Hz<br>• `_on_battery`, `_on_rapport` 콜백 수신<br>• 5분 idle dwell 측정 (OpServer가 관찰; mode_manager 자체는 측정 안 함) |
| **Exit action** | (없음 — kill은 새 모드의 entry에서 수행) |
| **허용 진입 사건** | `e_set_mode('idle', _)`, `e_complete`, `e_battery_low`, `e_safety_alarm`, `e_emergency_stop` |
| **허용 진출 사건** | `e_set_mode(m, p)` where m ∈ {serving, patrol, guiding, engaging} ∧ G_can_enter(m) |
| **KPI 누적** | `idle_total_sec += (now - _entered_at)` (OpServer 집계) |

**비고**:
- idle은 "모드 없음"이 아니라 명시적 상태. 다른 모드의 cleanup이 끝나면 자동 진입.
- mode_manager 자체는 5분 카운트하지 않는다 (관심사 분리). idle 진입 시점은 `/mode/state.entered_at`로 외부에 노출되고, OpServer가 이를 보고 patrol을 트리거한다.

---

### 2.2 S_serving (서빙)

| 속성 | 값 |
|---|---|
| ID | `'serving'` |
| 우선순위 | 1 (최상위) |
| **Invariant** | • `mode_serving.launch.py` 자식 프로세스 alive<br>• `serving_dispatcher_node` running<br>• `/mode/state.current_mode == 'serving'`<br>• `/serving/state` 1Hz 발행 중 |
| **Entry action** | 1. `LaunchSupervisor.kill()` (기존 stack)<br>2. `LaunchSupervisor.spawn('serving', params_json)`<br>3. spawn grace 1.5초 통과 확인<br>4. 통과 시 `_current_mode='serving'`, `_params=params_json`<br>5. 실패 시 idle로 rollback + `_last_reject_reason='spawn_failed:...'` |
| **During action** | • `serving_dispatcher`가 큐 FIFO 처리: pickup_table(옵션) → target_table → dwell → home_pose<br>• `/serving/goto_table` 토픽 구독 (큐 append) |
| **Exit action** | • SIGTERM 송신 (LaunchSupervisor.kill)<br>• 3초 grace, 미응답 시 SIGKILL<br>• active Nav2 goal cancel (dispatcher cleanup) |
| **자동 종료 사건** | `e_complete` (큐 비고 + home 복귀 완료)<br>※ 본 사건은 mode_manager가 직접 감지하지 않음. OpServer가 `/serving/state`의 "idle" 상태를 일정 시간 관찰 후 `SetMode('idle')` 호출. |
| **params 스키마** | `{"waypoint": "<table_id>", "via_pickup": <bool>}`<br>예: `{"waypoint":"T03","via_pickup":true}` |
| **선점 정책** | • 다른 serving 요청: 거부 (큐 사용 안내) — 운영자 UI에서 `/serving/goto_table` append로 안내<br>• 다른 모드 요청: 거부 (`transition_in_progress` 아니면 `serving_busy`) |
| **KPI 누적** | `serving_total_count++`, `serving_avg_duration_sec`, `serving_per_table_count[target]` |

**비고**:
- "큐가 비어있으면 idle 복귀"는 dispatcher 내부 로직. dispatcher는 큐 소진 시 home_pose로 가서 `/serving/state="idle"` 발행. mode_manager는 모름. OpServer가 이를 보고 `SetMode('idle')` 호출 → mode_manager가 launch kill → S_idle 전이.
- 위 패턴은 모든 활동 모드에 공통 적용된다 (§2.3, §2.4, §2.5).

---

### 2.3 S_patrol (순회) — 신규

| 속성 | 값 |
|---|---|
| ID | `'patrol'` |
| 우선순위 | 3 |
| **Invariant** | • `mode_patrol.launch.py` 자식 alive<br>• `patrol_scheduler_node`, `table_occupancy_detector_node` running<br>• `/patrol/state` 1Hz 발행 중<br>• `/patrol/table_report` 테이블 방문 시마다 발행 |
| **Entry action** | LaunchSupervisor.spawn('patrol', params_json)<br>params 기본: `{"sweep_mode":"all","report_to_opserver":true}` |
| **During action** | • `patrol_scheduler`가 sweep_order 순회: T01 → T02 → T03 → T04 → T05<br>• 각 도착 시 dwell 2초 + occupancy_detector 호출 + report 발행<br>• 모든 테이블 방문 종료 → home 복귀 |
| **Exit action** | • SIGTERM<br>• active Nav2 goal cancel<br>• 마지막 `/patrol/state="done"` 발행 후 dispatcher self-terminate |
| **자동 종료 사건** | `e_complete` (5테이블 방문 + home 복귀 완료) — OpServer가 `/patrol/state="done"` 관찰 후 `SetMode('idle')` |
| **params 스키마** | `{"sweep_mode": "all"\|"priority_only", "report_to_opserver": <bool>}`<br>• `all`: T01~T05 전부<br>• `priority_only`: 직전 사이클에서 occupied였던 테이블만 |
| **선점 정책** | • serving/guiding 요청 수신 시: **선점 허용** (우선순위 1, 2 < 3)<br>• engaging 요청: 거부 (`patrol_busy`)<br>• 또 다른 patrol 요청: 거부 (`patrol_busy`) |
| **KPI 누적** | `patrol_total_count++`, `patrol_avg_duration_sec`, `patrol_occupied_detected += sum(...)`, `patrol_finished_detected += sum(...)` |

---

### 2.4 S_guiding (동행 안내) — 기존 follow 리네이밍 + 재설계

| 속성 | 값 |
|---|---|
| ID | `'guiding'` |
| 우선순위 | 2 |
| **Invariant** | • `mode_guiding.launch.py` 자식 alive<br>• `guiding_controller_node` running (+ person_detector)<br>• `/mode/state.current_mode == 'guiding'`<br>• `/guiding/state` 1Hz 발행 중 |
| **Entry action** | LaunchSupervisor.spawn('guiding', params_json)<br>params 필수: `{"target_table":"<id>","customer_id":"<id>"}` |
| **During action** | 1. 카운터에서 customer lock-on (person_detector + 최근접 bbox)<br>2. Nav2 NavigateToPose(target_table) 시작<br>3. 이동 중 customer 카메라 추적; lag > 1.5m 시 정지+발화<br>4. 도착 → "여기서 편하게 즐기세요" 발화 → 대기 5초 → done |
| **Exit action** | • SIGTERM<br>• active Nav2 goal cancel<br>• `/cmd_vel` 0 강제 (자식 종료 직전 마지막 stop msg) |
| **자동 종료 사건** | `e_complete` (도착 + customer confirm) — OpServer가 `/guiding/state="arrived"` 5초 dwell 관찰 후 `SetMode('idle')` |
| **params 스키마** | `{"target_table":"<id>","customer_id":"<id>"}`<br>예: `{"target_table":"T02","customer_id":"C-2026-05-16-0017"}` |
| **선점 정책** | • serving 요청 수신: **선점 허용** (우선순위 1 < 2)<br>• guiding/patrol/engaging 요청: 거부 (`guiding_busy`) |
| **KPI 누적** | `guiding_total_count++`, `guiding_avg_duration_sec`, `guiding_lost_customer_count` (lag > timeout 미복구) |

**중요**: `follow_controller_node.py`(기존)와 `guiding_controller_node.py`(신규)는 알고리즘이 정반대다.
- follow: 사람의 움직임을 따라가는 reactive controller
- guiding: 로봇이 앞장서고 사람이 따라오는지 확인하는 supervisor

→ 코드 재사용 < 30%. 신규 노드로 작성하는 것이 맞다. 자세한 설계는 `moca_guiding_design.md` 참조.

---

### 2.5 S_engaging (모객) — 기존 npc 리네이밍

| 속성 | 값 |
|---|---|
| ID | `'engaging'` |
| 우선순위 | 5 |
| **Invariant** | • `mode_engaging.launch.py` 자식 alive<br>• `bt_executor_node` + `cafe_funnel_v1.xml` BT 실행 중<br>• `dialog/emotion/minigame` 스택 가동<br>• `/mode/state.current_mode == 'engaging'` |
| **Entry action** | LaunchSupervisor.spawn('engaging', params_json)<br>params 옵션: `{"persona":"casual_browser"\|"friendly_child"\|"professional_adult"}` |
| **During action** | • cafe_funnel_v1.xml의 6단계 funnel 실행:<br>  IdleScan → Approach → IceBreak → Minigame → Offer → LeadIn<br>• SafetyCheck + EmotionMonitor가 root Fallback에서 매 tick 평가 |
| **Exit action** | • SIGTERM<br>• BT tick 중단<br>• dialog/emotion/minigame 노드 cleanup |
| **자동 종료 사건** | `e_complete` (funnel 6단계 완주 OR BT root SUCCESS OR Emotion abort) — bt_executor가 `/bt/result` 발행 후 self-terminate; OpServer가 이를 보고 `SetMode('idle')` |
| **params 스키마** | `{"persona":"<id>"}` (선택). 미지정 시 `casual_browser` 기본 |
| **선점 정책** | • serving/guiding/patrol/follow 요청 수신: **선점 허용** (모두 우선순위 < 5)<br>• 또 다른 engaging 요청: 거부 |
| **KPI 누적** | `engaging_total_count++`, `engaging_conversion_count` (LeadIn 성공), `engaging_abort_count` |

---

### 2.6 S_follow (1인 추종) — v1.1 신설 (2026-05-19 머지)

| 속성 | 값 |
|---|---|
| ID | `'follow'` |
| 우선순위 | 4 (mode_manager_node 헤더 docstring 명시) |
| **Invariant** | • `mode_follow.launch.py` 자식 alive<br>• `person_detector` (dobi_npc_emotion) + `follow_controller` (dobi_npc_bringup) running<br>• `/mode/state.current_mode == 'follow'`<br>• `/robot_cam/image_raw` (또는 `/image_raw` — 카메라 통합 시점 의존) 입력 수신 중<br>• `/scan` (LiDAR) 입력 수신 중 (안전 가드용) |
| **Entry action** | LaunchSupervisor.spawn('follow', params_json)<br>params 옵션: `{"target":"<id>"}` (현 구현 미사용 — 가장 큰 person bbox 자동 추종) |
| **During action** | 1. `person_detector` 가 `/robot_cam/image_raw` 처리 → `/robot_cam/persons` (Detection2DArray) 발행<br>2. `follow_controller` 가 최대 bbox 선택 → P 제어:<br>   • `err_angle = (image_cx - bbox_cx) / (image_w / 2)` → ω 명령<br>   • `err_dist = target_height_ratio - (bbox_h / image_h)` → v 명령<br>3. 안전 가드 4종 (모두 발동 시 cmd_vel=0 강제):<br>   ① `/rapport/event abort_trigger` → 즉시 v=ω=0 + abort_dwell 동안 송신 중단<br>   ② `/scan` 전방 ±front_arc_deg(기본 30°) 구간 `< scan_stop_dist`(기본 0.8m) → v=0 (회전 허용)<br>   ③ `detection_lost_sec`(기본 1.0s) 동안 person 미검출 → v=ω=0<br>   ④ image_size 미수신 → 0 (첫 sample 대기) |
| **Exit action** | • SIGTERM (LaunchSupervisor.kill())<br>• `follow_controller.destroy_node()` 직전 마지막 stop msg (`/cmd_vel` v=ω=0) 발행 후 종료 |
| **자동 종료 사건** | 없음 — **operator-triggered diagnostic/manual 모드**. 자동 완료 신호 없음. OpServer 또는 운영자 UI 가 명시적으로 `SetMode('idle')` 호출 시 종료. (`e_complete` 미정의) |
| **params 스키마** | `{"target":"<id>"}` 또는 `""` (현 구현은 target 식별자 미사용 — face id 등 확장 시 follow_controller 파라미터로 매핑, 후속). |
| **선점 정책** | • serving/guiding/patrol 요청 수신: **선점 허용** (모두 우선순위 < 4)<br>• engaging 요청 수신: 거부 (`follow_busy` — 5 > 4)<br>• 또 다른 follow 요청: 거부 |
| **KPI 누적** | `follow_total_count++`, `follow_total_duration_sec`, `follow_abort_count` (rapport 또는 scan 가드로 강제 종료) |
| **⚠ UI 통합 상태** | **2026-05-19 v1.1 spec 갱신 시점 기준 운영자 UI / 웹 대시보드는 5-state UI 구현 그대로**. `follow` 모드 표시 / 진입 버튼 / KPI 카드 등은 향후 별도 트랙 (`web/static/*.html` + `teleop_server.py`). 그 사이엔 ros2 service / CLI 로만 follow 진입 가능. SoT: `docs/moca_web_dashboard_spec.md` 와 동기화 필요. |

**의도된 사용 시나리오** (v1.1 신설 시점):
- 운영자가 로봇을 사람 옆에 대기시키거나 짧은 거리 추종이 필요한 디버깅/캘리브 상황
- 신규 person_tracking_pkg (YOLOv8 + DBSCAN + BoT-SORT) 검증
- 카페 영업 외 시간 + 점주 동행 시 사용 가정. **영업 중 customer-facing 사용은 미권장** (engaging 우선)

**guiding 과의 차이 (재확인)**:
- `follow`: **사람의 움직임을 따라가는 reactive controller** — 사람이 앞, 로봇이 뒤따름
- `guiding`: **로봇이 앞장서고 사람이 따라오는지 확인하는 supervisor** — 로봇이 앞, 사람이 뒤
- 알고리즘 정반대, 코드 재사용 < 30%. 별도 `follow_controller_node.py` / `guiding_controller_node.py` 분리 유지.

---

## 3. 전이표 (Transition Table)

### 3.1 전이 매트릭스 (행: S_from, 열: S_to)

| from \ to | idle | serving | patrol | guiding | engaging | follow |
|---|---|---|---|---|---|---|
| **idle** | (self-loop, no-op) | T-IS | T-IP | T-IG | T-IE | T-IF |
| **serving** | T-SI | (큐 append) | ✗ T-busy | ✗ T-busy | ✗ T-busy | ✗ T-busy |
| **patrol** | T-PI | T-PS (preempt) | (self, no-op) | T-PG (preempt) | ✗ T-busy | ✗ T-busy |
| **guiding** | T-GI | T-GS (preempt) | ✗ T-busy | (큐 append) | ✗ T-busy | ✗ T-busy |
| **engaging** | T-EI | T-ES (preempt) | T-EP (preempt) | T-EG (preempt) | (self, no-op) | T-EF (preempt) |
| **follow** | T-FI | T-FS (preempt) | T-FP (preempt) | T-FG (preempt) | ✗ T-busy | (self, no-op) |

**우선순위 정렬 (낮을수록 高 priority)**: serving(1) < guiding(2) < patrol(3) < follow(4) < engaging(5) < idle(99).

### 3.2 전이 상세 명세

#### T-IS: idle → serving

```
Event:    e_set_mode('serving', {"waypoint":"T<x>","via_pickup":bool})
Guard:    G_can_enter('serving')
          = G_valid_params ∧ G_not_busy ∧ G_battery_ok ∧ G_safety_ok
Action:   1. busy_flag = True
          2. spawn_thread(_do_transition(prev='idle', new='serving', params))
          3. return SetMode response: success=True, reason='transition_started'
Postcondition: 비동기 thread에서 LaunchSupervisor.spawn('serving', params)
               성공 시 _current_mode='serving', _entered_at=now()
               실패 시 _current_mode='idle' (rollback), _last_reject_reason='spawn_failed:...'
```

#### T-IP: idle → patrol

```
Event:    e_set_mode('patrol', {"sweep_mode":"all","report_to_opserver":true})
Guard:    G_can_enter('patrol')
Action:   spawn_thread(...) — T-IS와 동일 패턴
```

#### T-IG: idle → guiding

```
Event:    e_set_mode('guiding', {"target_table":"T<x>","customer_id":"C-..."})
Guard:    G_can_enter('guiding')
          + (require params with non-empty target_table)
Action:   spawn_thread(...)
```

#### T-IE: idle → engaging

```
Event:    e_set_mode('engaging', {"persona":"<id>"})
Guard:    G_can_enter('engaging')
Action:   spawn_thread(...)
```

#### T-IF: idle → follow (v1.1 추가)

```
Event:    e_set_mode('follow', {"target":"<id>"})   # target 옵션 (현 구현 미사용)
Guard:    G_can_enter('follow')
Action:   spawn_thread(_do_transition(prev='idle', new='follow', params))
Postcondition: 비동기 spawn → mode_follow stack alive (person_detector + follow_controller)
```

#### T-SI, T-PI, T-GI, T-EI, T-FI: <any-active> → idle

```
Event:    e_set_mode('idle', '')
Guard:    G_not_busy
Action:   spawn_thread(_do_transition(prev=current, new='idle', params=''))
Postcondition: LaunchSupervisor.kill() → 기존 stack SIGTERM
               _current_mode = 'idle', _params = ''
```

**중요**: 활동 모드의 자동 종료(`e_complete`)는 별도 사건이 아니라 *OpServer가 `SetMode('idle')`을 외부에서 호출*한 결과로 이 전이가 발생한다. mode_manager 자체는 `e_complete`를 모른다. `follow` 는 자동 완료 사건 자체가 없으므로(`§2.6`) 운영자/OpServer 가 명시적으로 idle 호출해야 종료.

#### T-PS, T-GS, T-ES, T-FS: <patrol|guiding|engaging|follow> → serving (선점)

```
Event:    e_set_mode('serving', params)
Guard:    G_can_enter('serving')
          ∧ priority('serving') < priority(current)
Action:   spawn_thread(_do_transition(prev=current, new='serving', params))
          — kill() → spawn() 순으로 자동 처리 (LaunchSupervisor가 책임)
Postcondition: 이전 모드 stack SIGTERM 후 serving stack spawn
               이전 모드는 자기 상태 cleanup 책임 (active goal cancel 등)
```

#### T-EP: engaging → patrol (선점)

```
Event:    e_set_mode('patrol', params)
Guard:    G_can_enter('patrol') ∧ priority('patrol') < priority('engaging')
                                     # 3 < 5 = True
Action:   spawn_thread(...)
```

#### T-PG: patrol → guiding (선점)

```
Event:    e_set_mode('guiding', params)
Guard:    G_can_enter('guiding') ∧ priority('guiding') < priority('patrol')
                                     # 2 < 3 = True
Action:   spawn_thread(...)
```

#### T-EG: engaging → guiding (선점)

```
Event:    e_set_mode('guiding', params)
Guard:    G_can_enter('guiding') ∧ priority('guiding') < priority('engaging')
                                     # 2 < 5 = True
Action:   spawn_thread(...)
```

#### T-EF: engaging → follow (선점, v1.1 추가)

```
Event:    e_set_mode('follow', params)
Guard:    G_can_enter('follow') ∧ priority('follow') < priority('engaging')
                                   # 4 < 5 = True
Action:   spawn_thread(...)
Note:     영업 중 customer-facing engaging 도중 follow 진입은 운영자 명시 트리거가 필요.
          OpServer 자동 로직에서는 거의 발생 안 함 — 디버깅/캘리브 상황 가정.
```

#### T-FP, T-FG: follow → patrol|guiding (선점, v1.1 추가)

```
T-FP:
  Event:    e_set_mode('patrol', params)
  Guard:    G_can_enter('patrol') ∧ priority('patrol') < priority('follow')
                                     # 3 < 4 = True
  Action:   spawn_thread(...)

T-FG:
  Event:    e_set_mode('guiding', params)
  Guard:    G_can_enter('guiding') ∧ priority('guiding') < priority('follow')
                                     # 2 < 4 = True
  Action:   spawn_thread(...)
```

### 3.3 거부되는 요청 (T-busy)

다음 케이스는 SetMode가 즉시 `success=False`로 응답하며 상태 변경 없음:

| 현재 | 요청 | reason |
|---|---|---|
| serving | patrol | `lower_priority_during_serving` (3 > 1) |
| serving | guiding | `lower_priority_during_serving` (2 > 1) |
| serving | engaging | `lower_priority_during_serving` (5 > 1) |
| serving | follow | `lower_priority_during_serving` (4 > 1) |
| guiding | patrol | `lower_priority_during_guiding` (3 > 2) |
| guiding | engaging | `lower_priority_during_guiding` (5 > 2) |
| guiding | follow | `lower_priority_during_guiding` (4 > 2) |
| patrol | engaging | `lower_priority_during_patrol` (5 > 3) |
| patrol | follow | `lower_priority_during_patrol` (4 > 3) |
| follow | engaging | `lower_priority_during_follow` (5 > 4) |

**비고**: 위 규칙은 **mode_manager가 아니라 OpServer가 enforce**하는 것이 권장 패턴이다. mode_manager는 priority 무관하게 모든 전이를 허용하고(기존 코드 그대로), OpServer가 우선순위 규칙을 적용한 후 적절한 시점에만 SetMode를 호출한다. 이는 책임 분리 원칙(§5.1)에 따른다.

다만 **수동 운영자 명령**(웹 UI에서 직접 SetMode)은 priority 무시하고 무조건 진행한다 — 운영자 의도 우선.

### 3.4 안전 가드 전이 (강제 idle)

```
T-FORCE_IDLE:
  Event:    e_safety_alarm  OR  e_emergency_stop  OR  e_battery_low (during active)
  Guard:    G_not_busy ∧ (_current_mode != 'idle')
  Action:   1. _last_reject_reason = '<alarm_type>_forced_idle'
            2. spawn_thread(_do_transition(prev=current, new='idle', '',
                                            reject_reason=...))
            3. (alarm dwell): _safety_alarm_until_ns = now + 5e9
                              (5초간 신규 모드 진입 차단)
Postcondition: idle 진입 + 5초간 G_safety_ok = False
```

5초 dwell이 지나면 `e_alarm_dwell_done` 사건으로 G_safety_ok 자동 복구. 운영자가 다시 SetMode 호출 가능.

---

## 4. 동시성 처리

### 4.1 mode_manager의 락 모델

`mode_manager_node`는 단일 `threading.Lock`(`self._lock`)으로 다음 상태를 보호한다:

```python
보호 대상:
  - _current_mode (str)
  - _params (str)
  - _entered_at (Time)
  - _last_reject_reason (str)
  - _busy (bool)

읽기 작업:
  - _publish_state() — 1Hz timer 콜백
  - _on_request() — SetMode 서비스 콜백 (가드 평가용)

쓰기 작업:
  - _on_request() — busy flag set
  - _do_transition() — 전이 결과 commit
  - _on_rapport() — alarm forced idle 시작
```

**락 보유 시간 최소화 원칙**: spawn/kill 같은 blocking 작업은 락 외부에서 수행. 락은 상태 변수 read/write 순간에만 잡는다.

### 4.2 비동기 전이 패턴

```python
def _on_request(self, request, response):
    with self._lock:
        # 1. 검증 (전부 lock 안에서)
        if self._busy: return reject("transition_in_progress")
        if not valid(...): return reject(...)
        # 2. busy flag set + 응답 즉시 반환
        prev_mode = self._current_mode
        self._busy = True

    # 3. 락 밖에서 별 thread 시작
    threading.Thread(
        target=self._do_transition,
        args=(prev_mode, req_mode, req_params),
        daemon=True,
    ).start()

    # 4. 서비스 응답 즉시
    response.success = True
    response.reason = 'transition_started'
    return response


def _do_transition(self, prev, new, params, reject_reason=''):
    # 락 외부: 무거운 작업 (kill + spawn, 각 최대 4.5초 가능)
    kill_ok, kill_reason = self.supervisor.kill()
    spawn_ok, spawn_reason = self.supervisor.spawn(new, params)

    with self._lock:
        # 락 안: 결과 commit
        self._busy = False
        if spawn_ok:
            self._current_mode = new
            self._params = params
            self._entered_at = now()
        else:
            self._current_mode = 'idle'  # rollback
            self._last_reject_reason = f'spawn_failed:{spawn_reason}'
```

### 4.3 동시 요청 직렬화

`busy_flag` 패턴으로 시간 직렬화한다:

```
시점 t0:  SetMode('patrol') 도착
시점 t1:  → busy=True, thread1 시작, 응답 반환
시점 t2:  SetMode('serving') 도착 (선점 의도)
시점 t3:  → busy 체크 → True → reject("transition_in_progress")
시점 t4:  thread1 완료 → busy=False
시점 t5:  client(OpServer) 재시도 → SetMode('serving') 성공
```

**문제**: 진정한 선점 시 첫 SetMode 응답 후 즉시 두 번째 요청이 도착하면 거부됨. OpServer가 클라이언트 측에서 1초 retry 로직을 둔다 (지수 백오프 포함, 최대 3회). 자세한 로직은 `moca_opserver_api_spec.md` §3.4 참조.

### 4.4 race condition 회피

**고려된 race**:

1. **rapport abort_trigger 도착 + SetMode 동시**:
   - `_on_rapport`가 busy=True이고 다른 모드 전이 진행 중이면 강제 idle 안 함 (기존 코드)
   - 진행 중 전이가 끝난 후 alarm dwell이 여전히 살아있으면 다음 SetMode가 거부됨 (safety_ok=False)
   - → 결과적으로 안전 측 동작

2. **launch supervisor의 spawn 후 즉사**:
   - `GRACE_SPAWN_SEC = 1.5`초 wait → returncode 확인
   - 즉사 감지 시 spawn_ok=False → idle rollback

3. **외부에서 kill -9로 자식 강제 종료**:
   - 다음 1Hz publish 시 `supervisor.is_running()` False 감지 → `_current_mode`와 불일치
   - 보호: M1에서 `_publish_state`에 supervisor 상태 검증 추가. 불일치 시 강제 idle 전이 트리거 (옵션 — M1 stretch goal).

---

## 5. 책임 분리 (Separation of Concerns)

### 5.1 mode_manager가 책임지는 것

- VALID_MODES 검증
- params JSON 검증
- 가드 평가 (battery_ok, safety_ok)
- LaunchSupervisor 운용 (spawn/kill/grace/rollback)
- `/mode/state` 1Hz 발행
- `/rapport/event` abort_trigger 강제 idle

### 5.2 mode_manager가 책임지지 않는 것

- **모드 우선순위 규칙**: OpServer가 enforce (수동 운영자 명령은 priority 무시)
- **e_complete 사건 감지**: OpServer가 `/serving/state`, `/patrol/state`, `/guiding/state` 관찰 후 SetMode('idle') 호출
- **5분 patrol 타이머**: OpServer 책임
- **영업시간/배터리 정책**: OpServer 책임
- **이벤트 큐 관리**: OpServer 책임

### 5.3 책임 분리의 효과

| 관심사 | 변경 빈도 | 변경 시 영향 |
|---|---|---|
| mode_manager (FSM 코어) | 낮음 (1~2회/분기) | 로봇 재기동 필요 |
| OpServer (비즈니스 룰) | 높음 (주 단위 튜닝) | 노드만 재시작, 로봇 무영향 |

비즈니스 룰을 OpServer에 두면, 점주가 "순회 주기 5분 → 10분", "영업 종료 30분 전 모객 차단" 같은 정책을 자주 바꿔도 mode_manager는 건드릴 필요가 없다.

---

## 6. SetMode 응답 코드 사전

### 6.1 success 케이스

| reason | 의미 | 후속 행동 |
|---|---|---|
| `'transition_started'` | 검증 통과, 비동기 전이 시작됨 | 클라이언트는 `/mode/state` 관찰로 결과 확인 |

### 6.2 거부 케이스

| reason | 조건 | 클라이언트 권장 처리 |
|---|---|---|
| `'unknown_mode:<m>'` | `m ∉ VALID_MODES ∧ m ∉ LEGACY_ALIAS` | UI 에러 표시, 입력 검증 |
| `'invalid_json_params:<msg>'` | params 파싱 실패 | UI 에러 표시 |
| `'transition_in_progress'` | busy_flag True | 1초 후 1회 재시도 (지수 백오프) |
| `'battery_low:<pct><<min>'` | `battery < battery_min` | UI 경고 + 충전 안내 |
| `'safety_alarm_active'` | alarm dwell 내 | 5초 후 자동 해제, UI 노란 배너 |
| `'spawn_failed:<reason>'` | launch 즉사 | 이벤트 로그, 디버그 패널 |
| `'rollback_to_idle:<reason>'` | 비동기 spawn 실패 후 rollback 완료 | (`/mode/state` 갱신으로 통보) |

### 6.3 후방 호환

```python
# v1.1 (2026-05-19 ~)
LEGACY_MODE_ALIAS = {
    'npc': 'engaging',
}
# 'follow' -> 'guiding' alias 는 v1.1 에서 제거됨 — follow 가 정식 6번째 상태로 승격.
```

- 요청이 legacy 이름이면 `WARN` 로그 + 신규 이름으로 자동 변환 + 처리.
- M3 종료(2026-07-04) 후 alias 제거 예정 (현재 잔여: `npc -> engaging` 만).

**v1.0 → v1.1 마이그레이션 주의**: v1.0 시점 코드가 `'follow'` 를 `'guiding'` 으로 자동 변환했다면, v1.1 코드는 `'follow'` 를 그대로 follow 모드 진입으로 해석한다. v1.0 시점 자동 변환에 의존하던 호출자 (예: 옛 운영자 UI 의 follow 버튼이 실제로 guiding 을 띄우길 기대) 가 있으면 의도 재확인 필요.

---

## 7. 시각적 다이어그램

### 7.1 상태 다이어그램 (v1.1 — 6-state)

```
                                  ┌──────────────┐
                                  │ (Power ON)   │
                                  └──────┬───────┘
                                         │ initial
                                         ▼
            ┌────────────────────────────────────────────────────┐
            │                                                     │
            │                S_idle (priority 99)                 │◀───────┐
            │                                                     │        │
            │  Invariant: stack=None, /cmd_vel≈0, mode='idle'     │        │
            └─┬────┬────┬────┬────┬────┬───────────────────────┘        │
              │    │    │    │    │    │                                  │
       T-IS   │T-IP│T-IG│T-IE│T-IF│                                       │
       SetM   │SetM│SetM│SetM│SetM│  (v1.1)                                │
      (s,p)   │(p,p│(g,p│(e,p│(f,p│                                       │
              ▼    ▼    ▼    ▼    ▼                                       │
        ┌─────────┐┌────────┐┌────────┐┌─────────┐┌──────────┐            │
        │S_serving││S_patrol││S_guiding││S_engagi.││ S_follow │            │
        │ (prio 1)││(prio 3)││(prio 2)││ (prio 5)││ (prio 4) │            │
        └────┬────┘└───┬────┘└───┬────┘└────┬────┘└────┬─────┘            │
             │         │         │          │          │                   │
             │         ▼ T-PS   ▼ T-GS    ▼ T-ES    ▼ T-FS                │
             │      (preempt → (preempt → (preempt → (preempt →            │
             │       serving)  serving)  serving)   serving)               │
             │         │                                                   │
             │         ▼ T-PG  ▼ T-EP    ▼ T-EG    ▼ T-FG                 │
             │      (preempt → (preempt → (preempt → (preempt →            │
             │       guiding) patrol)    guiding)   guiding)               │
             │                                       ▼ T-FP                │
             │                            ▼ T-EF (preempt →                │
             │                          (preempt →  patrol)                │
             │                           follow)                            │
             │ T-SI  T-PI  T-GI  T-EI   T-FI                               │
             └─────┴─────┴─────┴────────┴──────────────────────────────────┘
                          (e_set_mode('idle') OR e_complete via OpServer)
                          ※ S_follow 는 e_complete 없음 — 운영자 명시 idle 전이만


  ╔═══════════════════════════════════════════════════════════════════════╗
  ║              ALARM 전이 (모든 활성 상태에서 발동 가능)                  ║
  ║                                                                       ║
  ║   e_safety_alarm  /  e_emergency_stop  /  e_battery_low               ║
  ║       ├──────────────────────────────────────────────────┐            ║
  ║       │ T-FORCE_IDLE: kill + idle + alarm_dwell(5s)      │            ║
  ║       └──────────────────────────────────────────────────┘            ║
  ║                                                                       ║
  ║       dwell 동안 G_safety_ok=False → 신규 모드 진입 모두 거부          ║
  ║       5초 후 e_alarm_dwell_done → G_safety_ok 자동 복구                ║
  ╚═══════════════════════════════════════════════════════════════════════╝
```

### 7.2 시퀀스: idle → serving → idle (정상 경로)

```
OpServer       mode_manager   LaunchSup    serving_dispatcher   /mode/state
   │               │              │                │                │
   │ SetMode       │              │                │                │
   │ ('serving',   │              │                │                │
   │  {"wp":"T3"}) │              │                │                │
   ├──────────────▶│              │                │                │
   │               │ lock         │                │                │
   │               │ busy=True    │                │                │
   │               │ unlock       │                │                │
   │               │              │                │                │
   │   ok,         │              │                │                │
   │  'transition_ │              │                │                │
   │   started'    │              │                │                │
   │◀──────────────┤              │                │                │
   │               │ thread:      │                │                │
   │               │   kill()     │                │                │
   │               ├─────────────▶│                │                │
   │               │   ok         │                │                │
   │               │◀─────────────┤                │                │
   │               │   spawn      │                │                │
   │               │  ('serving') │                │                │
   │               ├─────────────▶│                │                │
   │               │              │  Popen + grace │                │
   │               │              ├───────────────▶│                │
   │               │   ok,        │                │                │
   │               │  'spawned'   │                │                │
   │               │◀─────────────┤                │                │
   │               │ lock         │                │                │
   │               │ mode=serving │                │                │
   │               │ entered=now  │                │                │
   │               │ busy=False   │                │                │
   │               │ unlock       │                │                │
   │               │              │                │                │
   │ /mode/state   │              │                │  current_mode= │
   │ ('serving')   │              │                │  'serving'     │
   │◀──────────────┼──────────────┼────────────────┼────────────────┤
   │               │              │                │                │
   │ (10초 후)     │              │                │ Nav2 진행…     │
   │               │              │                │ T3 도착,        │
   │               │              │                │ dwell, home 복귀│
   │               │              │                │                │
   │ /serving/     │              │                │ "idle"          │
   │  state        │              │                │ (큐 비어있음)   │
   │◀──────────────┼──────────────┼────────────────┤                │
   │               │              │                │                │
   │ (3초 관찰)    │              │                │                │
   │ SetMode       │              │                │                │
   │ ('idle')      │              │                │                │
   ├──────────────▶│ kill +       │                │                │
   │               │ idle 전이    │ SIGTERM        │                │
   │               ├─────────────▶├───────────────▶│ cleanup        │
   │               │              │   exit         │                │
   │               │◀─────────────┤◀───────────────┤                │
   │               │ mode=idle    │                │                │
```

### 7.3 시퀀스: patrol 중 selving 선점

```
OpServer        mode_manager     LaunchSup
   │                │                │
   │ (현재 patrol 진행 중)            │
   │                │                │
   │ POS pickup_ready 이벤트 도착    │
   │                │                │
   │ orchestrator   │                │
   │  priority      │                │
   │  체크:         │                │
   │  serving(1) <  │                │
   │  patrol(3)     │                │
   │  → 선점        │                │
   │                │                │
   │ SetMode        │                │
   │ ('serving',    │                │
   │  {"wp":"T4"})  │                │
   ├───────────────▶│                │
   │                │ lock           │
   │                │ busy체크: false│
   │                │ 가드 통과       │
   │                │ busy=True      │
   │                │ unlock         │
   │   ok,started   │                │
   │◀───────────────┤                │
   │                │ thread:        │
   │                │  kill(patrol)  │
   │                ├───────────────▶│ SIGTERM patrol stack
   │                │                │  ↓ 3초 grace
   │                │                │  완료
   │                │  ok            │
   │                │◀───────────────┤
   │                │ spawn(serving) │
   │                ├───────────────▶│
   │                │                │ Popen + 1.5초 grace
   │                │  ok,spawned    │
   │                │◀───────────────┤
   │                │ mode=serving   │
   │                │ busy=False     │
```

---

## 8. 구현 체크리스트

> v1.0 → v1.1 시점 체크 상태를 반영. v1.0 항목 중 이미 완료된 건 [x], v1.1 신규 추가 건은 별도 표기.

### 8.1 mode_manager_node.py 변경

- [x] `VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')` — v1.1 6-state
- [x] `LEGACY_MODE_ALIAS = {'npc': 'engaging'}` — v1.1 에서 `'follow': 'guiding'` 제거
- [x] `_on_request` 진입부에 legacy alias 자동 변환 + WARN 로그
- [x] `launch_file = f'mode_{mode}.launch.py'` (mode_follow.launch.py 포함 6 파일 모두 정상 spawn)
- [ ] `_publish_state`에 supervisor.is_running() 불일치 감지 (M1 stretch)
- [x] `_on_operator_cmd` 콜백 (`OperatorCommand{command_type:"stop_emergency"}` 처리)

### 8.2 신규 launch 파일

- [x] `dobi_npc_bringup/launch/mode_engaging.launch.py` (mode_npc 리네이밍 + 내부 BT 그대로)
- [x] `dobi_npc_bringup/launch/mode_guiding.launch.py`
- [x] `dobi_npc_bringup/launch/mode_patrol.launch.py`
- [x] `dobi_npc_bringup/launch/mode_npc.launch.py` — LEGACY_MODE_ALIAS 가 mode_engaging.launch.py 를 spawn 하도록 redirect (자체 deprecation wrapper 형태)
- [x] `dobi_npc_bringup/launch/mode_follow.launch.py` — **v1.1: deprecation wrapper 아닌 정식 stack** (person_detector + follow_controller + LiDAR 가드)
- [ ] (v1.2 후보) `mode_follow.launch.py` 의 face id 기반 target 식별자 활용 — 현재는 가장 큰 bbox 추종

### 8.3 단위 테스트

- [ ] `test_mode_manager_6state.py` (v1.1 — 옛 `test_mode_manager_5state.py` 갱신/리네이밍):
  - VALID_MODES 6종 진입/이탈
  - LEGACY_MODE_ALIAS 자동 변환 (`npc` 만 잔여 — `follow` alias 제거 후 직접 진입 검증)
  - 가드 (battery_low, safety_alarm) 거부
  - busy_flag 동시 요청 거부
  - spawn 실패 시 idle rollback
  - **follow 모드 신규 시나리오**: idle→follow→idle, engaging→follow→engaging 복구, follow 중 scan 가드 발동
- [ ] `test_setmode_responses.py`: 응답 코드 사전(§6) 전부 발생 시나리오 커버

### 8.4 통합 테스트

- [ ] §10.1의 자동 시나리오 A1~A4 통과 (마스터 계획서 참조)
- [ ] alarm dwell 5초 후 자동 해제 확인
- [ ] **6종 모드 전부 spawn/kill cycle 100회 누수 없음** (v1.1 — 5→6 갱신)
- [ ] (v1.2 후보) UI 측 6-state 통합 검증 — `web/static/*.html` + `teleop_server.py` follow 모드 카드/버튼 추가 후 e2e 시나리오

---

## 9. 미해결 이슈 (M1 단계 결정)

| # | 이슈 | 후보 |
|---|---|---|
| F1 | `_publish_state`의 supervisor 불일치 자동 복구 | (a) 강제 idle 전이 (b) WARN 로그만 |
| F2 | spawn_failed 시 자동 재시도 횟수 | (a) 0회 즉시 idle (b) 1회 재시도 후 idle |
| F3 | 운영자 수동 명령의 priority 무시 표시 | (a) ModeState에 `manual_override` 필드 추가 (b) reason 문자열만 |
| F4 | engaging 도중 사용자 abort 신호 (rapport) → idle vs 직전 모드 | (a) 항상 idle (현 동작) (b) 직전 모드 복원 |
| F5 | guiding 도중 customer lost → 어떻게 처리 | (a) /cmd_vel 0 + 대기 (b) idle 복귀 |

각 이슈는 M1 OpServer 골격 작업 시 같이 결정. 본 사양서 v1.1에서 확정.

---

**End of Document**
