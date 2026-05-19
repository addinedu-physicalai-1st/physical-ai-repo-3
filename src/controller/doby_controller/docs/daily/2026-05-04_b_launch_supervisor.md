# B 단계 — LaunchSupervisor + 모드별 launch 분리 (실 spawn/kill 검증 통과)

**작성일**: 2026-05-04 (밤 트랙, A3 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**선행 트랙**:
- `2026-05-04_dialog_router_a1.md` (멀티 모드 단일 출력 채널 게이트)
- `2026-05-04_mode_manager_a2.md` (4상태 FSM 골격, launch 는 stub)
- `2026-05-04_operator_panel_a3.md` (운영자 UI /operator)
**상태**: B 단계 (실 launch spawn/kill) 구현 + 4 모드 전이 라이브 검증 통과. mode_manager 의 stub 로그가 진짜 subprocess 제어로 교체됨.

---

## 0. 시작 컨텍스트

A1+A2+A3 으로 인터페이스/UI 모두 동작. 그러나 mode_manager 의 모드 전환은 stub 로그뿐 — 실제로 stack 시동/종료가 일어나지 않음.

B 단계 = "운영자가 모드 버튼을 누르면 실제로 그 모드의 launch 가 시동되고, 다른 모드 전환 시 깨끗히 종료된다" 까지 만드는 것.

**B 첫 cut 범위**:
- `dev_all.launch.py` 8 노드 묶음 → 공통 always-on(7) + 모드별 stack(3+1) 분리
- mode_manager 의 `_set_mode_locked` stub 을 `LaunchSupervisor.kill/spawn` 으로 교체
- subprocess + setsid + killpg 패턴
- spawn 후 grace(1.5초)로 즉사 감지 → spawn 실패 시 idle rollback
- 비동기 service 응답 (즉시 transition_started, /mode/state 1Hz 가 결과 반영)

---

## 1. 작업 흐름 (Task 15~17)

### Task 15 — launch 파일 분리

기존 `dev_all.launch.py` 8 노드 → 다음으로 분리:

```
dev_common.launch.py    공통 always-on 7 노드 (mode_manager 포함)
                          geva_node, rapport_tracker, persona_manager,
                          dialog_router, tts_node, face_avatar, mode_manager
mode_npc.launch.py      bt_executor 만 (cafe_funnel BT)
mode_serving.launch.py  mode_stack_stub (params_json 받음, alive 1Hz log)
mode_follow.launch.py   mode_stack_stub (params_json 받음, alive 1Hz log)
dev_all.launch.py       backward-compat — dev_common 을 IncludeLaunchDescription
```

신규 노드 `mode_stack_stub` (dobi_npc_bringup):
- 파라미터 `mode_label` + `params_json` 받음
- 1Hz INFO log (`{label} stack alive: {params_json}`)
- 자리표시 — Nav2 waypoint follower / person tracker 실 구현은 별 트랙

**`dev_all.launch.py` 처리** — 기존 호출자 호환을 위해 dev_common 을 IncludeLaunchDescription. mode_manager 가 모드 전이 시 자동 spawn 하므로 NPC 노드를 dev_all 에 직접 넣을 필요 없음. 검증 시 NPC 즉시 띄우고 싶으면 `initial_mode:=npc` launch 인자.

### Task 16 — `LaunchSupervisor` 클래스 신설

mode_manager 안에 helper 클래스로 추가 (~120줄). 핵심 인터페이스:

```python
class LaunchSupervisor:
    GRACE_SPAWN_SEC = 1.5     # spawn 후 즉사 감지
    GRACE_TERM_SEC = 3.0      # SIGTERM 후 SIGKILL 까지 대기

    def kill(self) -> tuple[bool, str]:
        """현 stack 종료. 항상 ok=True (외부적으로 실패 없음)."""
    def spawn(self, mode, params_json) -> tuple[bool, str]:
        """모드별 launch spawn. (ok, reason) 반환."""
    def shutdown(self):
        """노드 종료 시 잔존 stack 정리."""
```

**프로세스 격리 패턴**:
```python
proc = subprocess.Popen(
    ['ros2', 'launch', 'dobi_npc_bringup', f'mode_{mode}.launch.py',
     f'params_json:={params_json}'],
    start_new_session=True,         # setsid → process group leader
    stdout=subprocess.DEVNULL,
    stderr=subprocess.STDOUT,
)
# kill: os.killpg(proc.pid, SIGTERM) → 3초 wait → 안 죽으면 SIGKILL
```

`start_new_session=True` 가 핵심 — `os.setsid()` 효과로 자식이 새 process group leader. `killpg(pgid=pid, ...)` 로 ros2 launch 가 띄운 자식 노드까지 한 번에 정리.

**즉사 감지** — spawn 후 `proc.wait(timeout=GRACE_SPAWN_SEC)` 가 timeout 안에 반환되면 자식이 즉시 종료된 것 → spawn 실패. timeout 발생하면 정상 시동.

**비동기 응답 패턴** — service callback 에서:
```python
def _on_request(self, request, response):
    with self._lock:
        # validate (mode, params, 가드)
        # busy 플래그 set
    # 백그라운드 thread 띄움
    threading.Thread(target=self._do_transition, ...).start()
    # 즉시 응답
    response.success = True
    response.reason = 'transition_started'
```

`_do_transition` 이 lock 외부에서 supervisor.kill() + spawn() 진행 (~3-5초 block). 끝나면 lock 안에 결과 반영. /mode/state 1Hz publish 가 자동으로 새 상태(또는 spawn 실패 시 idle rollback + last_reject_reason) 노출.

### Task 17 — 라이브 검증 (4 모드 전이 + node list)

**T0 → T1 → T2 → T3 → T4** 각 시점에 `ros2 node list | grep -E "bt_executor|serving_stack|follow_stack"`:

| 시점 | service 응답 | mode_manager 로그 | 보이는 노드 |
|---|---|---|---|
| T0 idle | — | — | (없음) |
| T1 idle → npc | transition_started | spawn OK pgid=22446, transition_done | /bt_executor |
| T2 npc → serving | transition_started | kill SIGTERM rc=-15, spawn OK pgid=22490, transition_done | /serving_stack |
| T3 serving → follow | transition_started | kill SIGTERM rc=-15, spawn OK pgid=22531, transition_done | /follow_stack |
| T4 follow → idle | transition_started | kill SIGTERM rc=-15, transition_done (spawn=idle_no_stack) | (없음) |

전 전이 정확 동작. mode_manager 로그에서 `pgid` 변화 추적 가능. 각 kill 의 rc=-15 가 SIGTERM 정상 처리 의미.

mode_stack_stub 의 alive log 는 `dev_common.log` 에 안 잡힘 (subprocess stdout 을 DEVNULL 로 보냈기 때문) — 검증은 `ros2 node list` 로 충분.

---

## 2. 디버깅 (1차 시도 함정 두 가지)

### 함정 A: `params_json:={"waypoint":"table_5"}` ros2 launch 가 dict 자동 파싱

1차 시도에서 serving/follow spawn 실패 (rc=1). mode_serving.launch.py 를 직접 실행하니 명확한 에러:

```
[ERROR] [launch]: Caught exception in launch (see debug for traceback):
  Allowed value types are bytes, bool, int, float, str, ...
  Got dict for "params_json".
  If the parameter is meant to be a string, try wrapping it in
  launch_ros.parameter_descriptions.ParameterValue(value, value_type=str)
```

ros2 launch 가 인자 값에 `{...}` 보면 dict 로 자동 파싱 시도 → string param 거부.

**수정**:
```python
from launch_ros.parameter_descriptions import ParameterValue
parameters=[{
    'mode_label': 'serving',
    'params_json': ParameterValue(
        LaunchConfiguration('params_json'), value_type=str),
}]
```

`value_type=str` 강제 → JSON 문자열 그대로 노드 파라미터 전달. 에러 메시지가 정확한 해법까지 안내해서 한 번 만에 수정.

**원칙 재확인**: ros2 launch 의 자동 형 변환은 편리하지만 string 의도가 깨지는 함정. params 같은 raw string 에는 항상 ParameterValue 강제.

### 함정 B: `/bt_executor` 좀비 — 이전 dev_all 잔재

1차 검증 T0 시점에 `/bt_executor` 가 이미 떠있음 (dev_common 에는 안 넣었는데). 다른 세션의 dev_all 종료 시 깔끔히 안 죽은 것.

**진단**: `pgrep -af bt_executor` → PID 19378 (1시간 전 etime).

**복구**: `pkill -KILL -f "..."` 로 모든 dobi_npc 노드 정리 후 dev_common 재시동.

**시사**: 향후 검증 전 `pgrep -af "geva_node|...|mode_stack_stub"` 로 잔재 점검 습관. CLAUDE.md `좀비 잔존 시 pkill` hint 가 dev_all docstring 에 이미 있음 — 검증 자동화 스크립트에 prelude 로 통합 검토.

---

## 3. 핵심 학습

### subprocess + setsid + killpg 가 ros2 launch 정리에 정답

ros2 launch 는 자체가 자식 노드들을 spawn 하는 supervisor. 단순 `proc.terminate()` 로는 부모만 죽고 자식 노드들이 좀비로 남을 수 있음.

`start_new_session=True` 로 자식을 새 process group leader 로 띄우면 `os.killpg(pgid, SIGTERM)` 으로 그룹 전체에 시그널 전파. 본 트랙 검증에서 매 kill 후 ros2 node list 가 깨끗히 비어있음을 확인 — 자식 노드 leak 없음.

**다른 옵션과 비교**:
- `proc.terminate()` + `proc.wait()`: 부모만 종료, 자식 leak 위험
- launch_ros API in-process: mode_manager 가 LaunchService 객체 보유 → 코드 복잡도 큼
- subprocess + setsid + killpg: 단순 + 격리 + ros2 launch CLI 동작과 동일

처음에 launch_ros API vs subprocess 고민했는데 검증 결과 subprocess 가 충분 + 단순. 향후 더 복잡한 시나리오(여러 모드 동시 활성 등) 시 launch_ros 검토.

### 비동기 패턴이 service block 회피에 필수

service callback 안에서 supervisor.kill()/spawn() 직접 호출하면 callback 이 3-5초 block. 그동안 ROS spin thread 가 다른 콜백(timer, subscription) 못 처리 → /mode/state publish 멈춤, /battery_state 누락 등.

해결: callback 에서 thread 띄우고 즉시 응답. 응답은 `transition_started` (success=True 지만 spawn 결과는 미정). 운영자 UI 는 /mode/state 1Hz 로 spawn 결과 확인.

이 패턴의 함정 — 응답 success 가 "transition 시작 OK" 의미이지 "transition 완료 OK" 가 아님. 운영자 UI 가 last_reject_reason 으로 spawn 실패 표시 필수 (이미 ModeState 에 있음).

### `_busy` 플래그로 동시 전이 reject

비동기 thread 가 spawn/kill 진행 중일 때 새 SetMode 요청 들어오면 충돌 위험. `_busy=True` 동안 새 요청 reject `transition_in_progress`. 운영자 UI 입장에선 5초 정도 버튼 막힘 — 카페 페이스에 무난.

safety alarm 콜백도 같은 _busy 검사. 강제 idle 전이가 다른 진행 중 전이를 끊지 않게 — 진행 중 전이가 spawn 실패하면 자동 idle rollback 되니 결과 동일.

### 에러 메시지가 해법까지 안내 — ParameterValue 사례

ros2 launch 의 에러 메시지가 친절했음:
> Got dict for "params_json". If the parameter is meant to be a string, try wrapping it in launch_ros.parameter_descriptions.ParameterValue(value, value_type=str)

해결 방법까지 명시해서 한 번 만에 수정. 본 프로젝트의 에러/로그 메시지도 같은 원칙 — 운영자가 막혔을 때 다음 액션을 가능한 만큼 포함 (allow_dummy_goal 의 raw value 노출, SKIP_CAM hint 등).

---

## 4. 발견 / 위험 요소 / 갭

### 발견

- **subprocess.Popen + setsid + killpg + grace timeout 패턴이 ros2 launch 그룹 제어에 정확히 작동** — 4 모드 전이 모두 깔끔, 노드 leak 0.
- **ParameterValue value_type=str 로 ros2 launch 의 자동 형 변환 우회 가능** — JSON 문자열 같은 raw string 인자 보낼 때 표준 패턴.
- **비동기 service 응답** 으로 callback block 회피 + ModeState 1Hz 가 결과 reflect — 운영자 UI 부드러움.

### 위험 요소

- **kill 의 GRACE_TERM_SEC=3초 고정** — Nav2 같은 무거운 stack 은 SIGTERM 후 정리 시간이 더 필요할 수 있음. 향후 모드별 timeout 차등 검토.
- **spawn 실패 시 자동 idle rollback** — kill 한 옛 stack 은 이미 죽은 상태. 운영자가 의도한 모드와 무관하게 idle 됨. last_reject_reason 으로 알리지만 운영자가 놓치면 혼란. UI 에 명시적 알람 띄우기 검토.
- **mode_stack_stub 은 stub 일 뿐** — serving/follow 의 실 동작(Nav2/person tracker)은 아직 없음. spawn/kill 흐름은 검증됐지만 실 모드 동작 검증은 별 트랙.
- **subprocess stdout DEVNULL** — 자식 노드 stderr/stdout 보려면 별도 `tee` 또는 ros log 디렉토리 추적 필요. 현재 `~/.ros/log/<timestamp>/` 에 자동 저장.
- **start_new_session 에 의존** — Linux 한정 (Windows X). 본 프로젝트는 ROS Jazzy + Ubuntu 24.04 라 무관.

### 갭

- **mode 전이 retry 정책 없음** — spawn 실패 시 즉시 idle rollback. 일시적 실패(예: ROS DDS discovery 지연) 시 자동 retry 하면 운영 안정성 향상.
- **mode 별 health check 없음** — spawn 후 1.5초 후 살아있다 = 정상 으로 판단. 그러나 노드가 살아있는데 기능이 죽어있을 수도 (예: Nav2 의 controller 만 죽음). spawn 후 N초 안 mode_stack 의 health 토픽 발행 검증 같은 단계 필요.
- **dev_all.launch.py 사용처 정리 미완** — 운영 스크립트들이 dev_all 가리키는지 dev_common 가리키는지 일관성 점검 필요. 현재는 alias 로 호환 유지.
- **stub 노드 → 실 stack 교체 시점** — serving 은 Nav2 NavigateThroughPoses 통합 + waypoint config, follow 는 person tracker + reactive controller 가 별 트랙으로 진행 예정.

---

## 5. 다음 일정

### 단기

- [ ] **운영자 UI A3 통합 라이브 재검증** — A3 검증은 stub 환경에서 했음. B 단계 라이브에서 운영자 UI 클릭으로 모드 전환 시 실 spawn/kill 동작 확인 (curl 검증은 통과했지만 브라우저 UX 확인).
- [ ] **dev_common run 스크립트** — `bash ~/moca/scripts/run_dev_common.sh` 같은 검증 편의 스크립트 (좀비 prelude + dev_common launch + log tee).

### Phase 후속 (실 모드 stack)

- [ ] **serving 실 구현** — Nav2 NavigateThroughPoses client + waypoint YAML config (`config/serving_waypoints.yaml`).
- [ ] **follow 실 구현** — RPi USB 캠 person detection + reactive cmd_vel controller.
- [ ] **mode 별 health check** — spawn 후 mode_stack 이 `/mode/<mode>/ready` 발행 → mode_manager 가 N초 대기.
- [ ] **mode 전이 retry** — spawn 실패 시 1회 retry (DDS discovery 지연 대응).

### 인프라

- [ ] **tts_node `/dialog/cancel`** (A1 후속) — audio cut preempt 지원, safety alarm 을 router 경로로 통합.
- [ ] **자동 트리거** — POS / vision 한산도 감지 → `/mode/request` 자동 호출 (운영자 UI 와 같은 인터페이스 사용).

---

## 6. 변경된 파일

```
src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py        [신규]
src/dobi_npc/dobi_npc_bringup/launch/mode_npc.launch.py          [신규]
src/dobi_npc/dobi_npc_bringup/launch/mode_serving.launch.py      [신규, ParameterValue value_type=str]
src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py       [신규, ParameterValue value_type=str]
src/dobi_npc/dobi_npc_bringup/launch/dev_all.launch.py           ~ alias (dev_common include)
src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_stack_stub.py  [신규, alive 1Hz logger]
src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
                                                                 ~ LaunchSupervisor 클래스 추가 (~120줄)
                                                                 ~ _set_mode_locked stub → _do_transition 비동기 thread
                                                                 ~ _busy 플래그 + transition_in_progress reject
                                                                 ~ destroy_node 에 supervisor.shutdown()
src/dobi_npc/dobi_npc_bringup/setup.py                           ~ mode_stack_stub entry_point 추가

docs/daily/2026-05-04_b_launch_supervisor.md                     (본 회고)
```

mode_manager_node.py 가 ~180줄 → ~330줄로 늘어남 (+150줄). LaunchSupervisor 가 분리된 helper 라 책임 분리는 명확.

---

*마지막 갱신: 2026-05-04 밤 (B 단계 LaunchSupervisor 라이브 검증 통과, 4 모드 전이 노드 leak 0)*
*다음 갱신 예정: 운영자 UI A3 + B 통합 라이브 재검증 또는 serving/follow 실 구현 트랙*
