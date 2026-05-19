# A3 운영자 UI 모드 패널 — 모드 전환 + 강제 발화 라이브 검증

**작성일**: 2026-05-04 (밤 트랙, A2 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**선행 트랙**:
- `2026-05-04_dialog_router_a1.md` (멀티 모드 단일 출력 채널 게이트)
- `2026-05-04_mode_manager_a2.md` (4상태 FSM 골격)
**상태**: A3 (운영자 UI 모드 패널) 신설 + 라이브 검증 완료. 모드 전환 4 시나리오 + reject + 강제 발화(operator preempt) 모두 정확 동작.

---

## 0. 시작 컨텍스트

A2 직후. mode_manager 가 service/topic 인터페이스를 갖췄으니, 운영자가 직접 모드를 전환하고 강제 발화를 보낼 수 있는 UI 가 필요. 메모리(`project_mode_architecture.md`) §4 결정사항 — "1차는 운영자 UI 수동 트리거" — 의 구현.

**A3 첫 cut 범위**:
- 기존 `moca/web/teleop_server.py` (FastAPI) 확장 — 새 노드 추가 안 하고 같은 노드에 메서드/라우트 추가
- 모드 버튼 4개 + 현재 상태 표시 + 강제 발화 폼이 있는 단일 페이지 `/operator`
- moca 전용 venv (`~/moca/.venv`, `--system-site-packages`로 system rclpy 사용) 신규
- `run_operator_ui.sh` 신규 — moca venv + moca install + ROS env 일괄 source 후 서버 시동

**위치 정정 follow-up**: 1차 작업에서 `~/cabot/web/teleop_server.py`에 변경했으나 cabot/web은 별도 프로젝트(텔레옵 전용)임이 확인되어 **moca/web으로 이전**. cabot/web은 사용자 4월 30일 base 그대로 원상복구. run_teleop_ui.sh의 moca install source 블록(이전 commit에서 추가)도 되돌림.

**A3 가 안 다루는 것**:
- 자동 트리거 (POS / vision / 한산도 감지)
- 모드 stack 실 launch 제어 (B 단계)
- 운영자 인증/권한 (단일 운영자 가정)
- 모바일 최적화 디테일 (단일 dark 테마, 720px 컨테이너로 폰/태블릿도 충분히 보임 정도)

---

## 1. 작업 흐름 (Task 11~14)

### Task 11 — `teleop_server.py` 백엔드 확장

기존 `TeleopBridge(Node)` 단일 노드에 멤버 추가 (별 노드 분리 안 함, spin 구조 유지):

```python
# import (try/except 로 moca install 미source 환경에서도 server 자체는 시동)
try:
    from dobi_npc_msgs.msg import UtterRequest, ModeState
    from dobi_npc_msgs.srv import SetMode
    _DOBI_NPC_MSGS_OK = True
except ImportError:
    _DOBI_NPC_MSGS_OK = False

# TeleopBridge.__init__ 끝부분
self._mode_state_lock = threading.Lock()
self._latest_mode_state = None
if _DOBI_NPC_MSGS_OK:
    self.sub_mode_state = self.create_subscription(
        ModeState, '/mode/state', self._on_mode_state, 10)
    self.pub_router_in = self.create_publisher(
        UtterRequest, '/dialog/router_in', 10)
    self.cli_mode_request = self.create_client(SetMode, '/mode/request')
```

3 메서드 추가:
- `_on_mode_state(msg)` — ModeState 콜백, dict 캐시 (lock 보호)
- `mode_state_snapshot() -> dict | None`
- `request_mode(requested_mode, params, timeout=5.0) -> dict` — 서비스 client + Future + Event 패턴 (별 thread spin 환경에서 sync wait)
- `publish_utter(*, text, source, priority, preempt, voice, rate, pitch, face_expression) -> bool`

3 라우트 추가:
- `GET /operator` — operator.html serve
- `GET /api/mode/state` — 캐시된 ModeState JSON
- `POST /api/mode/request` — SetMode 서비스 호출 (try/except 로 exception 메시지 응답에 포함)
- `POST /api/dialog/utter` — UtterRequest publish

### Task 12 — `static/operator.html` 신규

단일 페이지, vanilla JS + CSS (의존성 0). 다크 테마, 720px max-width 중앙 정렬.

구성:
1. **현재 상태 패널** — current_mode (큰 글씨), battery_ok / safety_ok 배지, params, 진입 후 elapsed, last_reject. 1Hz 폴링으로 자동 갱신.
2. **모드 전환 패널** — 4 버튼 (대기/NPC/서빙/팔로우). 서빙은 `serving-waypoint` input, 팔로우는 `follow-target` input 으로 params 받음.
3. **강제 발화 폼** — text textarea + priority dropdown(0/10/20/30) + face dropdown(8 어휘 + 변경 없음) + preempt checkbox + 전송 버튼.
4. **로그 패널** — 시각 + 행동 라인, 최근 30건 표시.

라우트 호출은 모두 `fetch` + JSON. 결과는 로그 + 1Hz 상태 갱신으로 즉시 반영.

### Task 13 — moca 전용 venv + `run_operator_ui.sh` 신규

cabot venv 와 분리. moca 운영자 패널 띄울 때 fastapi/uvicorn 만 있으면 충분.

```bash
python3 -m venv --system-site-packages ~/moca/.venv
~/moca/.venv/bin/pip install fastapi uvicorn
```

`--system-site-packages` 로 system rclpy + dobi_npc_msgs (moca install) 모두 import 가능. cabot venv 와 의존성 충돌 없음.

신규 스크립트 `~/moca/scripts/run_operator_ui.sh`:
- moca venv activate
- ROS Jazzy + moca install/setup.bash source
- ROS_DOMAIN_ID=22 + fastrtps
- `python3 ~/moca/web/teleop_server.py` 포그라운드 시동

cabot 의 `run_teleop_ui.sh` 와 책임 분리 — 본 스크립트는 RPi bringup / USB 캠 자동 기동 안 함 (이미 dev_all.launch.py 로 mode_manager 떠있는 환경 가정).

### Task 14 — 라이브 검증 (curl 자동 + 브라우저 시각)

**curl 자동 검증**:
| Test | 결과 |
|---|---|
| GET /api/mode/state (초기) | current_mode=idle, battery_ok=true, safety_ok=true |
| POST /api/mode/request idle→npc | success=true, current_mode=npc |
| POST /api/mode/request npc→serving (waypoint=table_5 JSON) | success=true, current_mode=serving |
| POST /api/mode/request 'barista' | success=false, reason=unknown_mode:barista, current_mode=serving (미변경) |
| POST /api/dialog/utter (operator preempt) | publish OK, dialog_router 로그 enqueue [operator/p=10/P] eff_prio=-1 |
| POST /api/mode/request serving→idle | success=true, current_mode=idle |

**브라우저 시각 검증** (사용자 확인): 강제 발화 폼 → 음성 출력 + face 변화 + 로그 OK 모두 정상 동작.

mode_manager 로그 시퀀스 (전이 + reject 모두 포함):
```
[mode_manager] mode_manager ready: initial=idle battery_min=0.2 pub_hz=1.0
[mode_manager] [stub] kill idle_stack | spawn npc_stack (params='')
[mode_manager] mode idle → npc params=''
[mode_manager] [stub] kill npc_stack | spawn serving_stack (params='{"waypoint":"table_5"}')
[mode_manager] mode npc → serving params='{"waypoint":"table_5"}'
[mode_manager] reject [barista] → unknown_mode:barista
[mode_manager] [stub] kill serving_stack | spawn idle_stack (params='')
[mode_manager] mode serving → idle params=''
```

dialog_router 로그 (operator preempt enqueue):
```
[dialog_router] enqueue [operator/p=10/P] '운영자 패널에서 보낸 발화입니다' eff_prio=-1 qsize=1 playing=True
```

A1 + A2 + A3 가 라이브 환경에서 통합 동작 확인.

---

## 2. 핵심 학습

### 디버깅 — "프로세스 etime 먼저 확인"

A3 검증 1차 시도 시 POST /api/mode/request 가 HTTP 500 + 빈 body. 원인 찾는 데 두 라운드 디버깅:

**라운드 1**: try/except 로 exception 을 응답에 포함시키는 패치 추가. 그런데 패치 후 재요청해도 같은 500. 의심.

**라운드 2**: `ps -eo pid,etime,cmd` 로 teleop_server 프로세스 시작 시각 확인 → **etime=08:07** (8시간 7분 전). 패치는 파일에 있지만 **재시동 안 됨**. 사용자가 패치 적용한 줄 모르고 동일 명령 진행.

**원칙**: "패치 했는데 동일 결과" 시 가장 먼저 확인할 것 — **프로세스가 새 코드를 들고 있는가**. uvicorn 같은 사용자 셸 직접 실행 (no `--reload`) 환경에선 명시적 재시동 필요. `ps -eo etime` 로 즉시 확인.

향후 같은 패턴 (FastAPI + ROS 통합 서버) 재시동 forget 자주 발생할 듯 — 패치 알림 메시지에 "재시동 필요" 명시 + etime 확인 명령을 디버깅 첫 step 으로.

### rclpy `wait_for_service` API — `timeout_sec` (`timeout` 아님)

라운드 2 후 새 exception 잡힘:
```
TypeError: Client.wait_for_service() got an unexpected keyword argument 'timeout'
```

rclpy Jazzy 의 시그니처: `wait_for_service(timeout_sec: float = -1.0) -> bool`. 다른 ROS 라이브러리(rospy 등)는 `timeout`인데 rclpy 는 `timeout_sec`. 흔한 함정.

**원칙**: rclpy API 호출 시 키워드 인자 이름은 코드 자체로 확인 (rclpy/client.py 같은 source 또는 `help(Client.wait_for_service)`). 추정 금지 — 다른 ROS 버전과 다른 경우가 많음.

본 트랙에선 try/except 로 exception 을 응답에 포함시킨 덕에 한 라운드에 정확한 원인 파악. **API 함정 디버깅에서 raw exception 메시지 노출이 시간 단축의 핵심**.

### 단일 노드에 메서드 추가 vs 별 노드

A3 백엔드 디자인 결정. 옵션:
- **A**: TeleopBridge 단일 노드에 mode/dialog 메서드 추가 (현 cut)
- **B**: 새 OperatorBridge 노드 신설, MultiThreadedExecutor 또는 add_node 로 같은 spin 에 추가

A 선택 이유:
- 기존 spin 구조 무변경 (이미 `_ros_thread` 에서 `rclpy.spin(node)` 단일 노드 패턴)
- TeleopBridge 클래스 줄 수가 늘어나지만 (~80줄 추가), 새 노드 추가 시 spin 패턴 변경 + executor 학습 곡선이 더 비쌈
- A3 가 첫 cut — 기능 검증 우선, 책임 분리는 코드가 커지면 그때 리팩

**원칙**: 단일 책임 원칙은 좋지만 "지금 분리 비용 vs 분리 안 하는 미래 비용" 저울. 기능 한 두 개 추가는 단일 노드 OK. 노드 책임이 4-5 영역 넘어가기 시작하면 분리 검토.

### 패치 import 안전성 — try/except 로 server 시동 보장

```python
try:
    from dobi_npc_msgs.msg import UtterRequest, ModeState
    from dobi_npc_msgs.srv import SetMode
    _DOBI_NPC_MSGS_OK = True
except ImportError:
    _DOBI_NPC_MSGS_OK = False
```

teleop_server.py 는 cabot 워크스페이스라 moca 빌드 미수행 환경에서도 띄워야 함. import 실패해도 시동 자체는 OK (운영자 패널만 비활성). 라우트는 `_DOBI_NPC_MSGS_OK` 플래그 + node 객체 점검으로 graceful degrade.

cross-workspace 통합에서 권장 패턴 — 한 쪽 워크스페이스가 빠져 있어도 부분 기능은 살아남게.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **A1 + A2 + A3 통합 라이브 동작** — 세 트랙이 인터페이스 안정성 덕에 추가 충돌 없음. UI 클릭 → mode_manager 전이 → ModeState publish → UI 1Hz 갱신 순환 정상.
- **Future + Event 패턴 — sync wait OK** — `add_done_callback(lambda _f: done.set())` + `done.wait(timeout)` 패턴이 별 thread spin 환경에서 안정. timeout 처리도 명시적.
- **단일 페이지 vanilla JS — 의존성 0 으로 충분** — Vue/React 없이 fetch + DOM 직접 조작. 720px 컨테이너 다크 테마. 운영자 한 명 시나리오에 적합.

### 위험 요소

- **dobi_npc_msgs import 환경 의존** — moca venv가 `--system-site-packages` 아니거나 `moca install/setup.bash` source 안 됐으면 import 실패. graceful degrade 했지만 운영자 입장에선 "왜 패널 비활성?" 진단 필요. WARN 메시지로 안내 추가했지만 종종 놓칠 듯.
- **cabot/web 과 위치 혼동** — 1차 작업에서 `~/cabot/web` 에 변경 (run_teleop_ui.sh 가 cabot 가리켜서). cabot/web 은 텔레옵 전용 별도 프로젝트로 격리. moca/web 으로 이전 + cabot/web 원상복구. 향후 두 워크스페이스 web 위치 동시 존재 시 어디가 정식인지 README 명시 필요.
- **rclpy API 시그니처 미일치 위험** — `wait_for_service(timeout=...)` vs `timeout_sec=...` 같은 함정이 다른 메서드에도 잠재. 본 트랙에서 직접 노출만 두 가지 (timeout, future.result 결과 type 등). 향후 rclpy 메서드 호출 시 source 확인 습관.
- **uvicorn 재시동 명시성 부재** — `--reload` 안 쓰는 환경에서 사용자가 패치 후 재시동 잊는 빈도 높음. CI/dev 환경에선 `uvicorn --reload` 검토 가치 있음 (단 production 시 끔).
- **운영자 강제 발화 — 권한/제한 없음** — 누구나 8765 포트 접근 시 임의 발화 publish 가능. 카페 운영 시점에 망상이지만 디자인 단계에서 인지.

### 갭

- **모드 stack 실 launch 제어 미구현** (B 단계) — 현재 mode 전환 시 stub 로그만. UI 가 정상 동작해도 실제 stack 시동/종료는 다음 트랙.
- **/mode/state UI 갱신 1Hz** — 빠른 전이(예: 1초 이내 두 번 클릭) 시 중간 상태 못 봄. WebSocket 으로 push 받는 게 더 반응적이지만 polling 도 충분.
- **강제 발화 audio cut preempt 미구현** (A1 후속) — preempt=true 여도 현 발화 utter_done 까지 대기. 진짜 즉시 중단은 tts_node `/dialog/cancel` 추가 트랙에서.
- **모바일/태블릿 미검증** — 720px 컨테이너로 모바일에서도 보일 것이지만 실 폰 / 운영자 태블릿에서 클릭/입력 UX 검증 안 됨.

---

## 4. 다음 일정

### B (실 launch spawn/kill) — 가장 자연스러운 다음 단계

A1+A2+A3 으로 인터페이스/UI 모두 검증됐으니 이제 "실제로 모드 전환 시 stack 이 시동/종료" 구현. 현 mode_manager 의 `_set_mode_locked` 안 stub 로그를 launch_ros API 또는 subprocess 로 교체.

- [ ] launch_ros API vs subprocess.Popen 결정
- [ ] dev_all 분리: 공통 always-on launch + 모드별 launch 4종 (idle = 빈 stack)
- [ ] spawn/kill 실패 시 `_current_mode` rollback + reject 응답
- [ ] launch 인자 (params JSON) 모드별 처리

### tts_node `/dialog/cancel` (A1 후속)

- [ ] tts_node 에 /dialog/cancel (Empty) 구독 추가 → mixer.stop() + utter_done 안 발행
- [ ] dialog_router preempt=true 처리 시 cancel 발행
- [ ] safety alarm 을 router priority=0 + cancel 경로로 통합 가능

### 운영자 UI 보강

- [ ] WebSocket 으로 ModeState push (1Hz polling 대체)
- [ ] 강제 발화에 음성/속도 dropdown (현재 fixed)
- [ ] 모바일/태블릿 실 디바이스 UX 검증
- [ ] 모드별 강제 발화 phrase 프리셋 (예: 서빙 모드 시 "주문 도착했습니다" 버튼)

### 자동 트리거 (먼 미래)

- [ ] POS 시스템 통합 — 주문 들어오면 자동 SetMode(serving)
- [ ] vision 한산도 감지 → 자동 SetMode(npc)
- [ ] hall_state_aggregator 노드 신설 (운영자 UI 와 같은 /mode/request 사용)

---

## 5. 변경된 파일

```
[moca 워크스페이스 — git tracked]
scripts/run_teleop_ui.sh                  ~ 이전 commit의 moca install source 블록 되돌림
                                            (cabot/web 은 dobi_npc_msgs 안 씀)
scripts/run_operator_ui.sh                [신규, moca venv + ROS env + teleop_server 시동]
docs/daily/2026-05-04_operator_panel_a3.md  (본 회고)

[moca/web — .gitignore 'web/' 라 untracked, 사용자 personal 영역]
web/teleop_server.py                      ~ import + TeleopBridge 80줄 추가 + 라우트 4개
web/static/operator.html                  [신규, 단일 페이지 ~280줄]

[moca venv — git untracked]
~/moca/.venv                              [신규] python3 -m venv --system-site-packages
                                                  + pip install fastapi uvicorn

[cabot 워크스페이스 — 별도 프로젝트, 본 트랙에서 무변경]
~/cabot/web/teleop_server.py              4월 30일 base 그대로 (1차 작업한 변경은 원상복구)
~/cabot/web/static/operator.html          (잘못 만들었던 파일 삭제)
```

**cross-workspace 정리 노트**:
- 본 트랙 1차 작업 시 cabot/web 에 변경했으나 cabot/web 은 텔레옵 전용 별도 프로젝트임이 확인되어 moca/web 으로 이전.
- run_teleop_ui.sh 의 moca install source 블록(이전 commit `3b22e10`)도 cabot/web 가리키는 한 무용지물이라 되돌림.
- moca/web/* 은 .gitignore `web/` 패턴에 잡혀 git 안 들어감 — 사용자 personal 운영 영역.

---

*마지막 갱신: 2026-05-04 밤 (A1 + A2 + A3 통합 라이브 검증 통과, 운영자 UI /operator 동작)*
*다음 갱신 예정: B 단계 (실 launch spawn/kill) 또는 tts_node /dialog/cancel*
