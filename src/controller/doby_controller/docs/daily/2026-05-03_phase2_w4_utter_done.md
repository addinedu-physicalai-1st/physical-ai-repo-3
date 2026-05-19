# Phase 2 W4 회고 — utter_done 동기화 + abort TTS 중단 + dev launch

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `cafe_npc_implementation_plan.md` Phase 2 §4 W4 (잔여 — TTS 발화 완료 신호)
**선행 문서**: `2026-05-03_phase2_w4_tts.md` (③ TTS 회고 §3 위험 요소가 라이브 검증에서 현실화)
**상태**: 라이브 통합 검증 + utter_done 동기화 완료. cafe_funnel 박자 자연스러워짐.

---

## 0. 라이브 검증 발견 → 해결 흐름

### 발견 (사용자 보고)
> "너무 빨리 빨리 진행이되, 이전 표정과 음성이 끝나기 전에 다음 표정과 음성으로 전환이 되는 현상이 반복 발생해."

### 원인
TTS 회고 §3에서 미리 예측한 위험이 정확히 현실화:
- BT 노드 `IceBreak/Offer/LeadIn`이 `SyncActionNode` — `stage_id` publish 즉시 SUCCESS
- BT 100ms tick 한 번에 cafe_funnel Sequence의 6 stage가 모두 SUCCESS
- → persona_manager가 3개 stage_id를 0.4ms 안에 받아 utter/face 3건 발행
- → tts_node의 interrupt 정책으로 진행 중 발화 끊고 마지막것만 들림

### 해결 (B 트랙)
TTS 발화 완료 신호 + BT 동기화. 동시에 abort 시 TTS 즉시 중단도 추가 (같은 동기화 문제의 다른 면).

---

## 1. 작업 흐름

### Step 1: tts_node 확장

추가 기능:
- `/dialog/utter_done` (`std_msgs/Empty`) 발행 — 100ms ROS Timer로 `pygame.mixer.music.get_busy()` 폴링. busy → not busy 전이 시 발행
- `/rapport/event` 구독 — `event_type == "abort_trigger"` 수신 시:
  - `pygame.mixer.music.stop()` 즉시 중단
  - `_gen += 1` (진행 중 합성도 stale 처리)
  - `_was_busy = False` (가짜 utter_done 발행 안 하게)
- 새 utter 진입 시 `_was_busy = False`로 리셋 (직전 발화의 done 발행 안 보내기)

핵심 동기 변수:
- `_gen` (atomic via lock): 새 utter마다 증가, stale 합성 폐기
- `_was_busy` (GIL atomic bool): mixer 재생 추적. play 직후 True, get_busy 변화 또는 abort/새 utter 시 False

### Step 2: BT 노드 StatefulActionNode 변환

세 노드 공통 구조 → `UtterActionBase` 헤더 추출 (DRY):
```cpp
class UtterActionBase : public BT::StatefulActionNode {
  // 공통: stage_id publish, utter_done 구독, timeout, halt
  onStart()   → publish stage_id, RUNNING
  onRunning() → done_received? SUCCESS : timeout_check
  onHalted()  → cleanup (abort 또는 외부 halt)
};

class IceBreak : public UtterActionBase { ...stage_id="icebreak"... };
class Offer    : public UtterActionBase { ...stage_id="offer"... };
class LeadIn   : public UtterActionBase { ...stage_id="leadin"... };
```

각 derived는 자기 고유 InputPort만 추가 (예: `phrase_pool_id`, `menu_category`).

**timeout 정책 — SUCCESS로 강제 진행** (FAILURE 아님):
- 호객 funnel은 끝까지 가는 게 자연스러움
- TTS 합성 실패/네트워크 장애 시 침묵 후에라도 다음 stage로
- 기본 10초, `timeout_sec` 입력 포트로 조정 가능
- 발생 시 `WARN` 로그

**`std::atomic<bool> done_received_`**: 콜백과 BT tick이 같은 thread(SingleThreadedExecutor)지만 추후 multi-thread 대비 atomic.

### Step 3: dev_all.launch.py 신설

라이브 검증의 첫 friction이 **6 노드를 하나씩 띄우는 번거로움**이었음. `dobi_npc_bringup/launch/dev_all.launch.py` 신설:
- 6 노드(geva, rapport_tracker, bt_executor, persona_manager, face_avatar, tts_node)를 한 launch에서
- 인자: `fullscreen` (기본 false — 검증엔 windowed가 다른 작업과 동시 보기 편함), `default_persona` (기본 casual_browser)
- Ctrl+C 한 번으로 모든 자식 정리 (launch_ros가 SIGINT 전파)

### Step 4: 자체 검증 (합성 메시지)

| 시나리오 | 결과 |
|---|---|
| 단일 발화 → utter_done | `speak '안녕하세요'` (T=0) → `utter_done` (T+2.3s) → 토픽에 `{}` 캡처 ✓ |
| 발화 중 abort | 긴 발화 시작 → 1.5s 후 abort_trigger publish → `mixer.stop()` 즉시 ✓ |
| abort 후 utter_done 미발행 | stop된 발화로 인한 가짜 done 안 보냄 (BT halt와 일관) ✓ |

### Step 5: 사용자 라이브 검증

`ros2 launch dobi_npc_bringup dev_all.launch.py`로 6 노드 실행 → 사용자 확인:
- BT 사이클 박자 자연스러움 — 한 발화 끝나야 다음 stage 진행
- face/utter 동시성 (같은 callback) 유지
- abort 시 funnel 차단 + 발화 즉시 끊김
- 종료 시 좀비 없음

사용자 보고: "잘 동작해."

---

## 2. 핵심 학습

### StatefulActionNode + ROS subscription 콜백 패턴

BT::StatefulActionNode는 RUNNING 상태를 유지하면서 외부 이벤트를 기다릴 수 있는 표준 패턴. ROS 토픽 콜백과 결합:
- `onStart`: 시작 동작(publish 등) + 플래그 리셋
- `onRunning`: 매 tick에서 플래그 체크 → SUCCESS or RUNNING
- 별도 토픽 콜백: 플래그 set
- `onHalted`: 외부 halt(예: ReactiveFallback의 alarm) 시 cleanup

플래그는 `std::atomic<bool>`로 thread-safe. timeout으로 무한 대기 방지.

### Base class로 BT 노드 DRY 패턴

세 stage가 stage_id만 다른 동일 구조 → 단일 base. derived는 stage_id 생성자 인자 + 고유 InputPort만 추가. `static commonPorts()`를 베이스에 두고 derived의 `providedPorts()`에서 머지:
```cpp
auto ports = UtterActionBase::commonPorts();
ports.insert(BT::InputPort<std::string>("phrase_pool_id", ...));
return ports;
```

향후 stage 추가(예: 비상 안내, 사과 등) 시 boilerplate 거의 없이 가능.

### utter_done 폴링 vs 이벤트

선택지:
- (a) **ROS Timer 100ms 폴링** (선택) — `pygame.mixer.music.get_busy()` 체크
- (b) pygame `END_MUSIC_EVENT` — display thread에서만 처리, 백엔드 노드(headless)에선 부적절
- (c) 합성 thread에서 sleep loop으로 polling — async와 thread mix 복잡

(a)가 ROS-friendly + 단순. 100ms 지연은 1~3초 발화 대비 무시 가능.

### `was_busy` 전이 detection의 함정

play 직후 `_was_busy = True` 설정해야 polling이 다음 tick에서 detect 가능. 그러나 play 자체가 비동기 — `play()` 호출 직후 `get_busy()`가 아직 False일 수 있음. polling이 was_busy=True && busy=False를 잡아 **가짜 utter_done** 발행 위험.

해결:
- 새 utter 진입 시 `_was_busy = False`로 강제 리셋 (직전 was_busy 클리어)
- play 직후 `_was_busy = True` 설정 (다음 polling은 100ms 후 — play가 시작될 시간 충분)
- abort 시 `_was_busy = False` 강제 (mixer.stop이 busy=False 만들지만 가짜 done 발행 방지)

이 3 transition만 일관되게 관리하면 race 없음.

### timeout SUCCESS의 의미

호객 funnel은 **끝까지 진행이 자연스러운 동작 모델** — 손님이 뭔가 어색하게 잠깐 침묵해도 다음 stage(offer, leadin)로 넘어가는 게 자연. TTS 실패가 funnel 멈춤을 야기하면 손님 이탈. 따라서 timeout은 SUCCESS + WARN. 이 정책은 SafetyCheck/EmotionMonitor의 alarm과 별개 — 알람은 **실 위험만** 차단.

이 원칙은 다른 BT 노드에도 적용 가능 (Approach가 Nav2 timeout 시 SUCCESS+WARN 등).

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **base class 추출의 가치**: 세 노드 코드 양 약 50% 감소 (50줄 → 25줄/노드). 향후 stage 추가 시 boilerplate 최소화.
- **launch 파일이 검증 friction을 크게 줄임**: 이전엔 `pkill ...` + 6번 `ros2 run ...`을 매번 반복. 이제 한 명령. 또 검증 후 Ctrl+C 한 번으로 정리. 좀비 발생률 크게 감소.
- **utter_done이 BT 박자 + 동기화 두 가지를 한 번에 해결**: 발화 시간 동안 RUNNING 유지 → 자연 박자. face/utter는 같은 callback에서 publish이라 추가 동기화 불필요.

### 위험 요소

- **persona_manager가 stage_id 받는 즉시 face_avatar에도 publish**: utter는 합성 latency(200~500ms) 후 시작인데 face는 즉시. **face가 먼저 변하고 음성이 약간 늦게 나옴**. 사용자 라이브 검증에선 자연스럽게 느껴졌으나, 큰 latency 환경(느린 인터넷)에선 부조화 가능. Phase 후속에서 face 발행을 utter 시작 시점으로 동기화 검토 (tts_node가 `/face_avatar/expression`도 발행 또는 `/face_avatar/expression`도 utter_done 같은 시작 신호 받음).
- **timeout 10초가 너무 길 수도**: 짧은 phrase는 1~2초 발화. timeout이 10초면 합성 실패 시 너무 오래 대기. 페르소나/stage별 적정 timeout 검토. 하지만 v1엔 보수적으로 10초 OK.
- **abort 후 BT가 새 사이클 시작 시 timing**: ReactiveFallback이 abort SUCCESS → IDLE → 다음 tick에 RUNNING으로 새 사이클. tts_node는 abort 직후 mixer.stop + _gen 무효화. 새 사이클의 utter는 정상 처리. 짧게 검증된 흐름.
- **utter_done의 다중 BT 노드 ambiguity**: 모든 IceBreak/Offer/LeadIn 인스턴스가 같은 토픽 구독. 동시 RUNNING 시 누구의 done인지 모름. 현재 cafe_funnel은 Sequence라 동시 RUNNING 없음. 미래 Parallel 도입 시 utter_done에 stage_id 포함 검토.
- **dev_all.launch.py 자식 lifecycle**: ros2 launch가 SIGINT 전파하나 가끔 자식 살아남는 경우 보고됨 (face_avatar 회고 §6.3). 매 검증 후 `pkill` 백업 명령 권장.

### 갭

- 계획서에 없던 utter_done 매커니즘을 추가 — 명시되지 않았으나 라이브 검증으로 필수성 확인됨.
- BT halt 시점의 cleanup이 onHalted에 로그만 — 실제 cleanup(예: 진행 중 publisher 작업 취소) 필요 시 향후 추가.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **face/utter 시작 동기화** (위험 §3 1번): 현재 face가 utter보다 빠름. tts_node가 utter 시작 시점에 `/face_avatar/expression` 발행 또는 face_avatar가 tts 시작 신호 대기.
- **rapport_tracker hysteresis** (D 트랙): 한 프레임 잘못된 angry로 abort 발동 방지. 최근 1초 V·A 평균 임계.
- **face_avatar 애니메이션 v2** (C 트랙): 정적 1프레임 → Pillow 모든 프레임 + 30fps.
- **자투리**: YAML 스키마 검증 (jsonschema), BT 단위 테스트, 영어 phrase 검증.

### RPi 확보 시 (별도 트랙)

- W2.5: vic_pinky RPi 5 셋업, 카메라 2 raw publisher
- W4.5: GEFA (자세) → decision_rule_node fusion

### Phase 후속

- Phase 3 (W7-9): RPS 미니게임 + Polite phrase + OMX 가위바위보
- Phase 4 (W10-12): 통합 + N=5 파일럿 테스트

---

## 5. 산출물 위치

### 신규 파일
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/utter_action_base.hpp` (StatefulActionNode 공통 base)
- `src/dobi_npc/dobi_npc_bringup/launch/dev_all.launch.py` (6 노드 통합 launch)
- `docs/daily/2026-05-03_phase2_w4_utter_done.md` (본 회고)

### 수정 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/tts_node.py` (utter_done 발행 + abort 구독)
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/ice_break.hpp` (UtterActionBase 상속)
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/offer.hpp` (UtterActionBase 상속)
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/lead_in.hpp` (UtterActionBase 상속)

### 변경 없음
- BT XML cafe_funnel_v1.xml — Stateful 변환은 코드 수준, BT 구조는 그대로
- bt_executor_node.cpp — registerNodeType 그대로 (가변 인자 동일)
- dobi_npc_msgs — Empty는 std_msgs라 새 메시지 불필요

### 다음 커밋
- W4 utter_done 산출물 + dev launch + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_dialog dobi_npc_bt dobi_npc_bringup --symlink-install
'
```

### 자체 검증 (합성 메시지)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_dialog tts_node &
sleep 2

# A. utter_done 캡처
ros2 topic echo /dialog/utter_done &
ros2 topic pub --once /dialog/utter dobi_npc_msgs/msg/UtterRequest \
  "{text: '안녕하세요', voice: 'ko-KR-SunHiNeural', rate: '+0%', pitch: '+0Hz', persona_id: 'test', stage_id: 'icebreak'}"

# B. abort 중단
ros2 topic pub --once /dialog/utter dobi_npc_msgs/msg/UtterRequest \
  "{text: '디카페인도 준비되어 있고 시그니처 라떼도 있습니다', voice: 'ko-KR-SunHiNeural', rate: '+0%', pitch: '+0Hz', persona_id: 'test', stage_id: 'offer'}"
sleep 1
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'test', emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"
```

### 라이브 통합 검증
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py
# 또는 풀스크린:
# ros2 launch dobi_npc_bringup dev_all.launch.py fullscreen:=true
# 또는 다른 페르소나로 시작:
# ros2 launch dobi_npc_bringup dev_all.launch.py default_persona:=friendly_child
```

### 좀비 정리
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
```

---

**상태**: utter_done 동기화 완료. cafe_funnel 박자 자연스러움 확인. 다음은 face/utter 시작 동기화 또는 rapport_tracker hysteresis 또는 휴식.
