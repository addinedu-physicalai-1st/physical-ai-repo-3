# A1 dialog_router — 멀티 모드 단일 출력 채널 게이트 (NPC 검증 통과)

**작성일**: 2026-05-04 (밤 트랙)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**선행 트랙**:
- 오전: `2026-05-04_rpi_first_contact.md` (RPi 1차 연결)
- 오후: `2026-05-04_approach_safety_patch.md` (cmd_vel watcher, allow_dummy_goal)
- 저녁: `2026-05-04_npc_first_live_test.md` (NPC ↔ RPi 통합 라이브, Approach 가드 34회)
**메모리 신규**: `project_mode_architecture.md` (vic_pinky 4상태 FSM — 대기/NPC/서빙/팔로우)
**상태**: A1 (dialog_router) 신설 + 라이브 검증 완료. NPC transparent 동작 + 운영자 강제 발화 우선순위/preempt 정확 발동.

---

## 0. 시작 컨텍스트

저녁 회고 직후 vic_pinky 운영 모드 디자인 논의:
- 사용자 시나리오: 카페 운영(주문 → 서빙 → 대기 → 한산하면 NPC 호객 → 고객 요청 → 데스크 → 서빙)에서 모드 전환이 분 단위 이벤트로 반복.
- 4상태(대기/NPC/서빙/팔로우) FSM 결정. 7개 핵심 결정사항(launch 분리 + on-demand spawn, 공통 always-on 층, dialog_router 단일 게이트, 현 발화 끝까지 cleanup 등)을 메모리(`project_mode_architecture.md`)에 저장.

**A1 = 오케스트레이션 백본의 첫 구성요소** — 멀티 모드가 face/TTS 같은 단일 출력 자원을 공유할 때 충돌 없이 직렬화하는 게이트. NPC 단독 환경에서도 transparent하게 동작해야 모드 추가 시 인터페이스 안정성이 보장됨.

---

## 1. 작업 흐름 (Task 1~6)

### Task 1 — `UtterRequest.msg` 필드 3개 추가

기존 `text/voice/rate/pitch/face_expression/persona_id/stage_id` 위에 라우팅 메타데이터 3종 추가:

```
string source       # "npc" | "serving" | "follow" | "operator" | "safety" | ""(legacy)
uint8 priority      # 0=safety alarm  10=operator  20=serving  30=npc  255=lowest
bool preempt        # true → 큐 head 배치 (현 cut: audio cut 미구현)
```

기존 publisher(persona_manager)는 default 값 유지 시 동일 동작. tts_node, BT, face_avatar 인터페이스 변경 없음.

빌드 통과: `colcon build --packages-select dobi_npc_msgs` 5.22s.

### Task 2 — `dialog_router_node.py` 신설

신규 노드, `dobi_npc_dialog` 패키지에 추가. 핵심 구조:
- 입력: `/dialog/router_in` (UtterRequest, 멀티 모드 publisher)
- 동기: `/dialog/utter_done` (Empty, tts_node 발행)
- 출력: `/dialog/utter` (UtterRequest, tts_node 입력)
- 내부: `heapq` 기반 우선순위 큐 + `_playing` 플래그 + `_lock` (스레드 보호)

큐 키: `(eff_prio, seq, msg)` — `seq`는 단조 증가로 타이브레이크 FIFO + msg 객체 비교 회피. `eff_prio = -1 if preempt else priority`.

dispatch 로직:
- `_on_request`: heap push → `_dispatch()` 시도
- `_on_done`: `_playing=False` → `_dispatch()` 시도
- `_dispatch`: `not _playing AND heap nonempty` 시 1건 pop+publish

**preempt 첫 cut 정책**: audio cut 미구현. preempt=true는 "큐 head 배치"만 수행 (eff_prio=-1), 현 발화는 utter_done까지 자연 대기. 진짜 audio cut은 tts_node에 `/dialog/cancel` 추가 시 확장 (TODO).

이유: tts_node 변경 없음 약속을 지키기 위함. 안전 alarm 즉시 중단은 기존 rapport `abort_trigger` 경로(`mixer.stop()`) 그대로 유지 — `_was_busy=False`로 utter_done도 발행 안 함.

### Task 3 — `persona_manager_node.py` 출력 토픽 변경

```python
# Before
self.pub_ = self.create_publisher(UtterRequest, '/dialog/utter', 10)
# After
self.pub_ = self.create_publisher(UtterRequest, '/dialog/router_in', 10)

# UtterRequest 채울 때 라우팅 메타데이터 추가
utter.source = 'npc'
utter.priority = 30
utter.preempt = False
```

기존 NPC 흐름 동일 + 라우팅 라벨만 추가. `/dialog/utter` 토픽은 router 출력으로 이관.

### Task 4 — `dev_all.launch.py`에 router 추가

7번째 노드로 `dialog_router` 추가 (persona_manager와 face_avatar 사이). 기존 노드 변경 없음.

```python
Node(
    package='dobi_npc_dialog', executable='dialog_router',
    name='dialog_router', output='screen',
),
```

빌드 통과: `colcon build --packages-select dobi_npc_msgs dobi_npc_dialog dobi_npc_bringup` 2.42s. Smoke 테스트로 `dialog_router ready: in=/dialog/router_in out=/dialog/utter done=/dialog/utter_done` 확인.

### Task 5 — NPC 단독 라이브 검증 (transparent)

dev_all.launch.py 시동 후 약 25초 동안 NPC funnel 동작 캡처.

**`/dialog/router_in` 메타데이터** (persona_manager 출력):
```
text: 잠깐 시간 되시면 게임 한 판 하실래요?
source: npc
priority: 30
preempt: false
```

**dialog_router 로그** (`grep dialog_router /tmp/dobi.log`):
```
enqueue [npc/p=30/ ] '잠깐 시간 되시면 게임 한 판 하실래요?' eff_prio=30 qsize=1 playing=False
dispatch [npc/p=30/ ] '잠깐 시간 되시면 게임 한 판 하실래요?' eff_prio=30 seq=12
utter_done → playing=False qsize=0
enqueue [npc/p=30/ ] '오늘은 시그니처 라떼가 잘 나가요. 하나 어떠세요?' eff_prio=30 qsize=1 playing=False
dispatch [npc/p=30/ ] ... seq=13
utter_done → playing=False qsize=0
... (반복)
```

매 cycle `enqueue → dispatch → utter_done` 일관 순환, **큐 누적 0**. NPC 단독에선 router가 transparent — 기존 동작 동일.

### Task 6 — 운영자 강제 발화 검증 (priority/preempt)

#### Test 1: preempt=true (operator p=10)

```bash
ros2 topic pub --once /dialog/router_in dobi_npc_msgs/msg/UtterRequest \
  '{text: "운영자 강제 발화 테스트입니다", source: "operator",
    priority: 10, preempt: true, ...}'
```

router 로그 시퀀스:
```
... NPC seq=26 dispatch (playing=True) ...
enqueue [operator/p=10/P] '운영자 강제 발화 테스트입니다' eff_prio=-1 qsize=1 playing=True
                                                       ▲
                                                  preempt 마크 'P' + eff_prio=-1
... (840ms 대기 — 현 NPC 발화 utter_done까지) ...
utter_done → playing=False qsize=1
dispatch [operator/p=10/P] '운영자 강제 발화 테스트입니다' eff_prio=-1 seq=27
enqueue [npc/p=30/ ] '잠깐 시간 되시면 게임 한 판 하실래요?' eff_prio=30 qsize=1 playing=True
```

**결과**: preempt=true → 큐 head(eff_prio=-1) → 현 발화 끝까지 대기(약 840ms) → operator 즉시 dispatch → 이후 NPC 요청은 큐 후미. 정책대로.

#### Test 2: preempt=false priority=10 (operator 일반 우선)

```
... NPC seq=33 dispatch (playing=True) ...
enqueue [npc/p=30/ ] '안녕하세요! ...' eff_prio=30 qsize=1 playing=True
enqueue [operator/p=10/ ] '운영자 일반 우선 발화입니다' eff_prio=10 qsize=2 playing=True
                                                  ▲
                                              preempt 마크 없음 ' '
utter_done → playing=False qsize=2
dispatch [operator/p=10/ ] '운영자 일반 우선 발화입니다' eff_prio=10 seq=35
                                            ▲
                       NPC seq=34 (eff_prio=30) 보다 먼저 pop
```

**결과**: preempt=false → 큐 후미(qsize=2)지만 priority=10 < NPC priority=30이라 다음 dispatch 시점에 priority 정렬로 먼저 pop. 정책대로.

---

## 2. 핵심 학습

### Transparent layer 도입 — "기존 인터페이스 보존"이 가장 큰 효과

router를 persona_manager와 tts_node 사이에 끼우는 단순 디자인. 기존 토픽 4종(`/dialog/request`, `/dialog/utter`, `/dialog/utter_done`, `/face_avatar/expression`) 모두 변경 없음. 변경 범위:
- 신규: `dialog_router_node.py` 1개
- 수정: `UtterRequest.msg` (필드 3개 추가, default 0/empty/false라 기존 publisher 호환), `persona_manager_node.py` (출력 토픽 1줄 + 라우팅 메타데이터 3줄), `setup.py` (entry_point 1줄), `dev_all.launch.py` (Node 블록 1개)

**총 5파일, 약 150줄 신규 + 10줄 미만 수정**. tts_node, BT (`utter_action_base.hpp`), face_avatar는 단 한 줄도 안 건드림. 이 작은 침습성 덕분에 검증 부담도 적었음 — Task 5에서 NPC 동일 동작 확인 + Task 6에서 신규 경로만 검증.

향후 모드 추가(서빙/팔로우/운영자 UI) 시에도 같은 인터페이스 사용 — `UtterRequest.msg`에 source/priority/preempt 채워서 `/dialog/router_in`에 publish하면 됨.

### preempt 첫 cut — "약속을 지키기 위한 정책 단순화"

아키텍처 결정에서 "현 발화 끝까지(`utter_done` 활용), 안전 alarm은 즉시"였음. preempt=true의 의미를 두 갈래로 해석할 수 있음:
- (A) 큐 head 배치만 (현 발화 끝까지 대기) — 본 cut
- (B) 진짜 audio cut + 즉시 재생 — 미구현

(B)는 tts_node에 `/dialog/cancel` 추가 필요 → "tts_node 무변경" 약속 깨짐. 그래서 (A)로 첫 cut 진행. 안전 alarm의 진짜 즉시 중단은 기존 rapport `abort_trigger` 경로 그대로 사용.

**시사**: 정책 단순화는 약속(인터페이스 안정성)을 지키기 위한 도구. (B)가 필요하면 tts_node에 명시적 cancel API 추가하는 별도 트랙으로 분리. 한 번에 다 안 함.

### 큐 키 설계 — `(priority, seq, msg)` heapq 함정 회피

`heapq.heappush`는 튜플 비교로 정렬. `(priority, msg)`만 쓰면 priority 동일 시 msg 객체 비교 → `__lt__` 미정의 에러. 흔한 함정.

**해결**: 단조 증가 `seq`를 중간에 끼움. `(priority, seq, msg)` — seq는 항상 unique이라 msg 비교에 도달하지 않음. 동시에 동일 priority 내 FIFO 보장 (`seq`가 작을수록 먼저 pop).

본 노드에선 lock 안에서 `self._seq += 1` → push로 atomic. 멀티스레드 안전.

### 라이브 검증 — 로그 라벨이 검증 속도를 결정

router 로그 라벨 형식: `[source/p=priority/preempt_mark] 'text_short'`. 예: `[operator/p=10/P] '운영자 강제...'`.

이 한 줄로 검증 가능한 사실:
- source 식별 (어떤 모드가 publish했는지)
- priority 명시 값
- preempt 여부 (P vs ' ')
- 발화 본문 식별

별도 grep/diff 없이 시퀀스 흐름만 봐도 enqueue/dispatch 인과 추적 가능. Phase 2 W4 hysteresis 트랙 + 본 트랙에서 일관 적용된 원칙 — **로그에 의사결정 근거(raw 값)를 명시 노출**.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **router transparent 검증 통과** — NPC 단독에서 기존 funnel 동일 동작. 큐 누적 0, dispatch latency 무시 가능 수준 (enqueue → dispatch 동일 ms).
- **preempt 첫 cut 정책 정확** — 현 발화 utter_done까지 약 840ms 대기 후 즉시 operator dispatch. 카페 시나리오에 충분.
- **priority 정렬 동작** — NPC(30) vs operator(10) 큐 정렬 정확.

### 위험 요소

- **audio cut preempt 미구현** — 안전 alarm을 router 경로로 보내려면 tts_node `/dialog/cancel` 추가 필요. 현재는 별도 rapport `abort_trigger` 경로 사용. 모드 디자인 통합 시 고려 (`project_mode_architecture.md` 우선순위 0 = safety alarm 부분 재검토).
- **큐 backpressure 정책 부재** — `queue_warn_size=10` 초과 시 WARN만, 자동 drop 없음. 멀티 모드 환경에서 폭주 시 큐 무한 증가 가능. 운영 중 모니터링 + 필요 시 max_queue_size 추가.
- **router 자체 죽으면 발화 채널 마비** — 현재 watchdog/restart 없음. 모드 전환 같은 무거운 트리거 후 router 안정성 모니터링 필요.

### 갭

- **mode 표시** — 모드 전환 시 face/voice/persona 자동 전환 정책 미정. mode_manager(A2)에서 결정.
- **dialog_router → mode_manager 인지** — 현재 router는 모드 무관. 모드 전환 시 진행 중 발화 처리 정책(현 모드 발화 마저 / 즉시 큐 비우기) mode_manager 입장에서 결정.
- **priority 동적 조정** — 한산도/긴급도에 따라 NPC priority 일시적 상향(예: 신규 손님 입장 시 NPC 호객 우선) 미구현. 모드 디자인 후속.

---

## 4. 다음 일정

### A2 (mode_manager FSM 골격)

- [ ] FSM 구조: 4상태(대기/NPC/서빙/팔로우) + 운영자 트리거 + 가드(배터리/안전)
- [ ] 인터페이스: `/mode/request` (서비스), `/mode/state` (토픽 publish, 1Hz)
- [ ] 첫 cut: launch spawn/kill stub (로그만), 진짜 launch 제어는 B 단계
- [ ] Python `transitions` 라이브러리 vs 단순 dict FSM 비교

### A3 (운영자 UI 모드 패널)

- [ ] `teleop_server.py` 확장 — 모드 버튼(NPC/서빙→테이블 N/팔로우/대기) + 현재 모드 표시
- [ ] `/mode/request` 서비스 호출 + `/dialog/router_in` 강제 발화 입력 폼

### tts_node `/dialog/cancel` (audio cut preempt 보강)

- [ ] tts_node에 `/dialog/cancel` (Empty) 구독 추가 → mixer.stop() + utter_done 안 발행
- [ ] dialog_router preempt=true 처리 시 cancel 발행
- [ ] safety alarm을 router 경로로 통합 가능

---

## 5. 변경된 파일

```
src/dobi_npc/dobi_npc_msgs/msg/UtterRequest.msg
  + source / priority / preempt 필드 3개 (라우팅 메타데이터)

src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/dialog_router_node.py  [신규]
  + 우선순위 큐 + utter_done 동기화 + preempt 큐 head 배치

src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/persona_manager_node.py
  ~ 출력 토픽 /dialog/utter → /dialog/router_in (1줄)
  + UtterRequest 채울 때 source="npc"/priority=30/preempt=false (3줄)

src/dobi_npc/dobi_npc_dialog/setup.py
  + dialog_router entry_point 1줄

src/dobi_npc/dobi_npc_bringup/launch/dev_all.launch.py
  + dialog_router Node 블록 (persona_manager와 face_avatar 사이)
  ~ docstring "6 노드" → "7 노드" 갱신

docs/daily/2026-05-04_dialog_router_a1.md  (본 회고)
~/.claude/projects/-home-gjkong-moca/memory/project_mode_architecture.md  (메모리, 사전 저장)
```

기존 5파일 + 신규 1파일 + 회고 1파일 + 메모리 1파일. tts_node, face_avatar, BT(`utter_action_base.hpp`), 기존 utter 동기화 인프라 모두 무변경.

---

*마지막 갱신: 2026-05-04 밤 (A1 dialog_router 라이브 검증 통과, NPC transparent + 운영자 preempt/priority 정확)*
*다음 갱신 예정: A2 mode_manager FSM 골격*
