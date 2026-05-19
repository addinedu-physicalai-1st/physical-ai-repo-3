# MOCA Idle Mode 설계 문서

> **문서 ID**: `moca_idle_design.md`
> **버전**: v1.0 (2026-05-17)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2.2.2
> **관련 문서**:
> - `moca_5state_fsm_spec.md` §2.1 (S_idle)
> - `moca_serving_design.md` (idle → serving 전이)
> - `moca_patrol_design.md` (idle → patrol 자동 트리거)
> - `moca_guiding_design.md` (idle → guiding 전이)
> - `moca_engagement_design.md` (idle → engaging 전이)
> **구현 대상**:
> - `dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py` 의 `idle` 분기 (단순)
> - `dobi_npc_bringup/launch/dev_common.launch.py` (always-on 7 노드)
> - 모드 stack launch 파일 — **idle 은 launch 없음** (idle_no_stack 반환)

---

## 0. 본 문서의 범위

본 문서는 `idle` 모드 — 로봇이 운영자/POS 명령을 대기하면서 항상-활성 공통 layer (감정 인식 / 표정 / TTS / mode_manager) 만 유지하는 기본 상태 — 의 invariant 와 진입/유지/탈출 동작을 정의한다.

### 0.1 본 문서가 다루는 것

1. idle 모드의 정의 (mode stack 없음 = 활성 모드 launch 없음)
2. 항상-활성 공통 layer (dev_common.launch.py 7 노드)
3. invariant — idle 동안 항상 참이어야 할 조건
4. entry / during / exit action
5. 다른 모드로의 전이 트리거 (운영자, POS, 자동 patrol, safety alarm)
6. face_avatar idle 표정 정책
7. mode_manager 의 idle 분기 로직 (`idle_no_stack`)

### 0.2 본 문서가 다루지 않는 것

- 각 다른 모드의 entry/exit 세부 (별 문서: moca_serving_design.md, moca_patrol_design.md 등)
- 공통 layer 의 7 노드 각각 내부 알고리즘 (다음 트랙)
- dock plate / 충전 시스템 (현재 구현 미 — §10.4)

---

## 1. 모드 개요와 책임

### 1.1 idle 모드의 정의

> **idle = "활성 mode stack 없음"**

다른 4 모드 (serving / patrol / guiding / engaging) 는 각각 별 launch 파일 (`mode_serving.launch.py` 등) 을 spawn 해서 모드별 노드 stack 을 띄움. **idle 만 launch 파일 X** — mode_manager 가 `idle_no_stack` 반환하고 끝.

```python
# mode_manager_node.py 의 spawn 분기 (line 약 70)
def _spawn_mode_launch(self, mode: str, params_json: str):
    if mode == 'idle':
        return True, "idle_no_stack"   # ← idle 은 launch 안 함
    launch_file = f'mode_{mode}.launch.py'
    cmd = ['ros2', 'launch', 'dobi_npc_bringup', launch_file]
    ...
```

이유:
- idle 동안 추가 노드 필요 X — 공통 layer 가 다 처리 (감정 모니터링, mode 명령 수신, face_avatar idle 표정)
- 자원 절약 (Nav2 stack, BT executor, minigame_runner 등 idle 때 불필요)
- 빠른 진입 (launch spawn latency 5~10s 회피)

### 1.2 priority — 99 (최하)

`moca_5state_fsm_spec.md` 의 priority 매트릭스 기준, idle 은 **priority 99** (가장 낮음). 항상 다른 모드 요청에 선점됨.

### 1.3 기본 상태로서의 역할

| 상황 | idle 전이 |
|---|---|
| 시스템 부팅 직후 | `initial_mode=idle` (default, dev_common.launch.py) |
| 다른 모드 종료 (정상) | serving 큐 종료, patrol sweep 완료, guiding 도착, engaging funnel 완료 |
| safety alarm | 어느 모드에서든 idle 강제 (`/rapport/event` weight 큰 alarm) |
| operator emergency_stop | 어느 모드에서든 idle 강제 (`/operator/command`) |
| 모드 spawn 실패 | idle rollback (mode_manager 의 grace_spawn 감지) |

---

## 2. 공통 always-on Layer (dev_common.launch.py)

### 2.1 7 노드 구성

idle 모드는 추가 노드 X. 단, **dev_common.launch.py 의 7 노드** 가 살아있어야 함:

| 노드 | 패키지 | 책임 |
|---|---|---|
| `geva_node` | dobi_npc_emotion | 카메라 1 (노트북 내장) → 얼굴 표정 → `/emotion/state` (V·A) |
| `rapport_tracker_node` | dobi_npc_emotion | `/emotion/state` → `/rapport/event` (engagement_up/down, abort_trigger, neutral_continue) |
| `persona_manager` | dobi_npc_dialog | `/dialog/request` → `/dialog/router_in` (페르소나 phrase pool 선택) |
| `dialog_router` | dobi_npc_dialog | `/dialog/router_in` → `/dialog/utter` (priority 큐 — 안전 alarm > 운영자 > 서빙 > NPC) |
| `face_avatar_node` | dobi_npc_dialog | `/face_avatar/expression` → 풀스크린/윈도우 GIF 표시 (8 표정) |
| `tts_node` | dobi_npc_dialog | `/dialog/utter` → 음성 출력 (edge-tts) + `/dialog/utter_done` |
| `mode_manager` | dobi_npc_bringup | `/mode/request` 서비스 + `/mode/state` 발행 + mode stack spawn/kill |

### 2.2 launch arg

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `fullscreen` | bool | `false` | face_avatar 풀스크린 (검증엔 false) |
| `default_persona` | str | `casual_browser` | persona_manager 기본 페르소나 |
| `initial_mode` | str | `idle` | mode_manager 초기 모드 — 기본 idle |

`initial_mode=idle` — 부팅 시 idle 진입. legacy `npc` / `follow` 도 자동 변환 (M3 종료 2026-07-04 까지).

### 2.3 부팅 흐름

```bash
# 1. dev_common 가동 (PC 부팅 시 또는 세션 시작)
ros2 launch dobi_npc_bringup dev_common.launch.py

# 7 노드 spawn (geva → rapport_tracker → persona_manager → dialog_router → face_avatar → tts_node → mode_manager)
# mode_manager 가 idle 모드로 시작 (initial_mode=idle, idle_no_stack)
```

또는 통합 스크립트:
- `scripts/run_dashboard.sh` (dev_common + opserver)
- `scripts/run_real.sh` (dev_common + Nav2 + opserver, RPi 라이브)

### 2.4 dev_common 미가동 시 영향

dev_common 없으면:
- mode_manager 도 없음 → mode 전환 불가능
- face_avatar 없음 → 표정 출력 X
- TTS 없음 → 발화 X
- GEVA 없음 → 감정 모니터링 X

= **시스템 전체 작동 X**. idle 도 의미 없음 (mode 자체가 없음).

---

## 3. invariant — idle 동안 항상 참

### 3.1 모드 invariant

| 조건 | 검증 방법 |
|---|---|
| `mode_manager._mode is None` | 내부 상태 — `/mode/state.current_mode == 'idle'` |
| `mode_manager._proc is None` | spawn 한 mode 프로세스 없음 |
| `mode_<X>.launch.py` 어느 것도 가동 X | `pgrep -af "ros2 launch dobi_npc_bringup mode_"` empty |
| `bt_executor` 미가동 | `pgrep -af bt_executor` empty |
| `serving_dispatcher` 미가동 | 동상 |
| `patrol_scheduler` 미가동 | 동상 |
| `guiding_controller_node` 미가동 | 동상 |
| `follow_controller_node` 미가동 | 동상 (deprecated mode_follow) |
| `minigame_runner` 미가동 | 동상 |

### 3.2 공통 layer invariant

| 조건 | 검증 방법 |
|---|---|
| 7 노드 (dev_common) 가동 | `ros2 node list \| grep -E "geva\|rapport\|persona\|dialog\|face_avatar\|tts\|mode_manager"` 7건 |
| `/emotion/state` 발행 중 | `ros2 topic hz /emotion/state` (~10Hz) |
| `/face_avatar/expression` 수신 가능 | (idle 표정 발행) |
| `/dialog/utter` 수신 가능 | (조용한 상태) |
| `/mode/state` 1Hz 발행 | `ros2 topic hz /mode/state` |

### 3.3 robot 물리 invariant (선택)

| 조건 | 검증 방법 |
|---|---|
| cmd_vel = 0 (정지) | `ros2 topic echo /cmd_vel` zero |
| Nav2 stack 가동 (라이브 시) | active goal 없음 — `ros2 action list` |
| zlac_driver motor 정지 | `/joint_states` velocity 0 |

⚠ idle 이라고 robot 가 dock 에 정확히 있어야 한다 강제 X — 현재 위치 그대로 idle 가능. dock 복귀는 serving / patrol 의 home 복귀 정책으로 처리.

---

## 4. entry / during / exit action

### 4.1 entry — idle 진입 직후 (mode_manager 가 처리)

```python
# mode_manager_node.py 의 _spawn_mode_launch('idle', ...)
1. self._proc (이전 mode 프로세스) 가 있으면 SIGTERM + wait
2. self._proc = None
3. self._mode = None
4. return True, "idle_no_stack"

# 추가:
5. face_avatar idle 표정 publish — /face_avatar/expression "basic"
6. /mode/state 발행 (current_mode="idle")
```

### 4.2 during — idle 유지 동안 (1Hz tick)

```python
# mode_manager_node.py 의 _publish_state (1Hz)
1. /mode/state publish: {current_mode: "idle", uptime_sec: N, ...}

# rapport_tracker (10Hz)
2. /emotion/state 받음 → /rapport/event publish (engagement_up/down/abort_trigger/neutral)

# safety alarm 가드 (mode_manager 의 /rapport/event 구독)
3. event_type == "abort_trigger" + weight ≥ 임계 → idle 유지 (이미 idle, no-op)
```

⚠ 현재 mode_manager 가 idle 시 face_avatar 표정 자동 publish 안 함. 향후 후속 — idle 진입 시 "basic" 표정 자동 publish + N분 동안 표정 변동 (졸음 / 호기심).

### 4.3 exit — idle → 다른 모드 전이

```python
# 운영자 / POS / 자동 트리거 시
1. /mode/request 서비스 수신 (requested_mode in {serving, patrol, guiding, engaging})
2. mode_manager 가 _spawn_mode_launch(requested_mode, params_json)
3. subprocess.Popen("ros2 launch dobi_npc_bringup mode_<X>.launch.py params_json:=...")
4. grace_spawn (~3s) 동안 즉사 감지
5. 성공 시 self._mode = requested_mode, /mode/state.current_mode 갱신
6. 실패 시 idle rollback
```

---

## 5. 다른 모드로의 전이 트리거

### 5.1 운영자 수동 (dashboard)

```bash
# POST /api/v1/mode body
{"mode":"serving","params":{"waypoint":"T01"},"override_priority":true}
```

opserver 가 mode_manager `/mode/request` 서비스 호출 → mode_manager 가 spawn.

### 5.2 POS 자동 (S-C 후속)

POS 결제 완료 → opserver → `/mode/request serving` 자동.

### 5.3 자동 patrol 트리거

`moca_patrol_design.md` §2 의 정책 — 5분 주기 timer + 운영자가 patrol 비활성 안 한 경우 자동 진입.

### 5.4 자동 engaging 트리거 (S-D 검토)

opserver 의 한산 감지 알고리즘 — 5분 동안 customer 없으면 engaging spawn. 현재 미구현, M4 검토.

### 5.5 safety alarm 가드

idle 에선 safety alarm 받아도 이미 idle 상태라 no-op. 그러나 다른 모드 진행 중 safety alarm → mode_manager 가 즉시 idle 강제 전이.

```python
# mode_manager_node.py 의 /rapport/event 구독
def _on_rapport_event(self, msg):
    if msg.event_type == "abort_trigger" and msg.weight >= 임계:
        if self._mode != 'idle':
            self.get_logger().warn(f'safety abort — {self._mode} → idle')
            self._spawn_mode_launch('idle', '')
```

### 5.6 operator emergency_stop

```python
# mode_manager_node.py 의 /operator/command 구독
def _on_operator_command(self, msg):
    if msg.command == "stop_emergency":
        self._spawn_mode_launch('idle', '')
    elif msg.command == "resume":
        # 이전 모드 자동 복귀 X (사용자 명시 재선택 필요)
        pass
```

---

## 6. face_avatar idle 표정

### 6.1 idle 표정 정책

idle 동안 face_avatar 가 "기본" 표정 유지 — 8 표정 어휘 중 `basic` 또는 `interest` (호기심).

```bash
ros2 topic pub /face_avatar/expression std_msgs/String "data: basic"
```

vicpinky_emotion 자산 (33MB, 8 GIF) 의 `basic.gif` 가 face_avatar 풀스크린에 표시.

### 6.2 표정 변동 (후속)

향후: idle N분 후 표정 변동 (졸음 / 호기심 / 따분 — bored). 운영자가 봤을 때 "로봇 살아있음" 신호.

현재 미구현 — 부팅 시 첫 표정만 발행, 이후 변동 X.

### 6.3 brightest 시작 정책 ([[feedback_face_avatar_brightest_start]])

face_avatar 가 표정 전환 시 GIF 의 brightest frame (예: hello 16/20, fun 6/20) 부터 시작 → 표정 즉시 visible. idle 진입 시도 동상 — basic GIF 의 brightest idx 부터.

---

## 7. mode_manager 의 idle 분기

### 7.1 코드 SoT 위치

`src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py` 의 `_spawn_mode_launch` 메서드.

### 7.2 핵심 로직

```python
def _spawn_mode_launch(self, mode: str, params_json: str):
    # 1. 이전 프로세스 종료
    if self._proc is not None:
        self._proc.terminate()
        self._proc.wait(timeout=5)
        self._proc = None
        self._mode = None

    # 2. idle 분기 — launch 없음
    if mode == 'idle':
        return True, "idle_no_stack"

    # 3. 다른 모드 — launch spawn
    launch_file = f'mode_{mode}.launch.py'
    cmd = ['ros2', 'launch', 'dobi_npc_bringup', launch_file]
    if params_json:
        cmd.append(f'params_json:={params_json}')

    self._proc = subprocess.Popen(cmd, start_new_session=True)
    # 4. grace_spawn 동안 즉사 감지
    time.sleep(grace_spawn)
    if self._proc.poll() is not None:
        return False, f'{mode} 즉사'

    self._mode = mode
    return True, f'{mode} spawn 성공'
```

### 7.3 idle rollback 패턴

다른 모드 spawn 실패 시 idle 로 자동 rollback:

```python
ok, msg = self._spawn_mode_launch(requested_mode, params_json)
if not ok:
    self.get_logger().error(f'{requested_mode} spawn 실패 — idle rollback')
    self._spawn_mode_launch('idle', '')   # 안전
    return False, msg
```

---

## 8. 단계별 구현

### 8.1 Phase M0 (완료, 2026-05-16)

✓ mode_manager skeleton + idle/serving/patrol/guiding/engaging 5 state
✓ /mode/state 1Hz 발행
✓ /mode/request 서비스
✓ dev_common.launch.py 7 노드

### 8.2 Phase M1 (완료, 2026-05-16)

✓ mode_orchestrator + VALID_MODES + LEGACY_MODE_ALIAS
✓ /operator/command (emergency_stop / resume)
✓ /rapport/event 가드 (safety alarm → idle 강제)

### 8.3 Phase M2 (완료, 2026-05-16)

✓ idle ↔ patrol 자동 트리거 (5분 timer)
✓ idle ↔ serving 운영자 수동
✓ idle ↔ guiding 운영자 수동

### 8.4 Phase M3 (완료, 2026-05-16)

✓ idle 상태 dashboard 표시 — Doby 헤더 "Doby Online" + 사이드바 mode_state
✓ /mode/state 3s timeout — robot online 판정 기준

### 8.5 Phase M4 후속 (진행 중)

- idle face_avatar 표정 자동 변동 (N분 후 졸음/호기심)
- idle 동안 GEVA 감지 시 engaging 자동 spawn (S-D)
- idle 동안 battery 충전 상태 표시 (vicpinky_bringup `/battery_state.power_supply_status`)
- idle 시 dock 자동 복귀 (현재 미 — serving / patrol 의 home 복귀에 위임)

---

## 9. 테스트 계획

### 9.1 단위 테스트

| 케이스 | 검증 |
|---|---|
| 부팅 시 initial_mode=idle | mode_manager._mode is None, _proc is None |
| idle → serving spawn 성공 | self._mode == 'serving', subprocess 실행 |
| idle → invalid mode (typo) | False, idle 유지 |
| serving → idle (운영자) | SIGTERM → _proc None, _mode None |
| serving 중 safety alarm | mode_manager 가 idle 강제 |
| serving spawn 실패 (launch 에러) | idle rollback |

### 9.2 sim 통합

`scripts/run_sim.sh` 가동 후:
1. dashboard 접속 → 부팅 직후 mode "idle" 표시
2. 5 모드 각각 진입 + 종료 → idle 복귀 확인
3. safety alarm 시뮬 (배터리 19% mock) → idle 강제 확인

### 9.3 라이브 (RPi)

`cafe_npc_rpi_live_amcl_checklist.md` §6.5 의 "emergency_stop 5s" 시나리오 직후 idle 복귀 확인.

### 9.4 invariant 검증 (`scripts/check_idle_invariants.sh` — 신규 필요)

```bash
#!/bin/bash
# idle 상태에서 모드 stack 노드 모두 죽어있는지 검증
for n in bt_executor serving_dispatcher patrol_scheduler guiding_controller_node \
         follow_controller_node minigame_runner; do
    if pgrep -af "$n" | grep -v claude; then
        echo "FAIL: $n 가동 중 (idle invariant 위반)"
        exit 1
    fi
done
echo "OK: 모드 stack 노드 모두 종료"
```

---

## 10. 미해결 / 후속

### 10.1 idle face_avatar 표정 자동 변동

현재 idle 진입 시 표정 자동 publish X. mode_manager 또는 별 idle_expression_scheduler 노드 추가 검토 — N분 마다 basic ↔ interest ↔ bored 변동.

### 10.2 idle 동안 자동 engaging 트리거 (S-D)

opserver 가 한산 감지 (5분 + customer 없음) → mode_manager 에 engaging 자동 요청. 운영자가 수동 비활성 가능. M4 검토.

### 10.3 dock plate 자동 복귀

현재 idle 가 robot 가 어디에 있든 상관 X. 향후:
- 5분 이상 idle + dock 가 멀면 자동 home 복귀 (idle_dock_return 정책)
- vicpinky_home 좌표 (-36.903, 2.693) 로 Nav2 단발
- 충돌: serving / patrol 종료 시 이미 home 복귀하므로 중복 trigger 회피 필요

### 10.4 idle dock 정렬 + 충전 (Phase 미정)

dock plate 모델 신규 (`src/moca_gazebo/models/dock_plate/`) + 실 충전소 정렬 알고리즘 (AprilTag 또는 reflective marker). 충전 연결 + battery_state 의 power_supply_status 변화 감지.

### 10.5 idle 상태에서의 GEVA 자원 사용

idle 동안 GEVA (카메라 1 + mediapipe) 가동 — 약간의 CPU/메모리 부담. 향후 idle N분 후 GEVA suspend 옵션 검토 (자원 절약). 그러나 호객 자동 trigger 와 충돌 (GEVA 가 한산 감지 못 함).

### 10.6 mode_manager 의 idle 진입 표정 자동 publish

현재 idle 진입 시 face_avatar 에 자동 표정 publish X. mode_manager 의 `_spawn_mode_launch('idle', ...)` 에 추가:
```python
if mode == 'idle':
    self._face_pub.publish(String(data='basic'))
    return True, "idle_no_stack"
```

`/face_avatar/expression` 발행자 추가 필요.

---

## 11. 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1.0 | 2026-05-17 | 초안 — mode_manager + dev_common 실 구현 기반 |

---

## 12. 부록 — 코드 SoT 매핑

| 섹션 | 코드 위치 | 라인 |
|---|---|---|
| §1.1 idle_no_stack 분기 | `mode_manager_node.py` `_spawn_mode_launch` | 약 70-75 |
| §1.2 priority 99 | `mode_manager_node.py` 모드 priority 표 | 헤더 docstring |
| §2 공통 layer | `dev_common.launch.py` | 전체 (87 줄) |
| §2.2 launch arg | `dev_common.launch.py` | 36-50 |
| §3 invariant | (검증 스크립트 미작성 — §9.4 ToDo) | — |
| §4.1 entry | `mode_manager_node.py` `_spawn_mode_launch` | 약 60-75 |
| §4.3 exit | `mode_manager_node.py` `_on_mode_request` | (서비스 콜백) |
| §5.5 safety alarm 가드 | `mode_manager_node.py` `_on_rapport_event` | (구독 콜백) |
| §5.6 operator command | `mode_manager_node.py` `_on_operator_command` | (구독 콜백) |
| §6.3 brightest start | `face_avatar_node.py` `start_at_brightest=true` | (별 노드) |
| §7 mode_manager idle 분기 | `mode_manager_node.py` | 약 60-90 |
