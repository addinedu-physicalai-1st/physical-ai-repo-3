# Phase 2 W4 회고 — EmotionMonitor BT 통합 (rapport_tracker + alarm)

**작성일**: 2026-05-02
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `cafe_npc_implementation_plan.md` Phase 2 §4 Week 4
**선행 문서**: `2026-05-02_phase2_w4_geva.md` (① GEVA)
**상태**: 노트북 단독 트랙 ② EmotionMonitor BT 통합 본 작업 + 검증 완료. 다음은 ④ 노트북 풀스크린 face_avatar GUI.

---

## 0. 오늘의 목표 vs 실제 결과

| 계획 | 결과 |
|---|---|
| `rapport_tracker_node.py` (Python) — V·A → RapportEvent 분류 | ✅ 즉시 평가 룰 4종, /rapport/event 발행 |
| `emotion_monitor.hpp` (C++ BT 노드, ConditionNode) — alarm 패턴 | ✅ atomic 캐시, alarm 전이 시 1회 로그 |
| `cafe_funnel_v1.xml` — `Fallback → ReactiveFallback` + EmotionMonitor 자식 | ✅ |
| 빌드 + 정상/abort 시나리오 검증 | ✅ 둘 다 통과 |

---

## 1. 작업 흐름 (시간순)

### Step 1: rapport_tracker_node.py

CLAUDE.md §4.3 RapportEvent 명세 그대로:

| 조건 | event_type | weight | reason |
|---|---|---|---|
| `confidence == 0` 또는 `flags="no_face"` | `neutral_continue` | 0.0 | `no_signal` |
| `V<-0.5` ∧ `A>+0.4` (CLAUDE.md §2 학술 임계값) | **`abort_trigger`** | -1.0 | `negative_high_arousal` |
| `V>+0.3` | `engagement_up` | +0.5 | `positive_valence` |
| `V<-0.3` | `engagement_down` | -0.5 | `negative_valence` |
| 그 외 | `neutral_continue` | 0.0 | `within_neutral_band` |

- v1은 즉시 평가 (입력 1건 → 출력 1건). 윈도우/지속성 추적 없음.
- event_type **전이 시에만** INFO 로깅 (10Hz 스팸 방지).
- 견고한 main() 패턴 (CLAUDE.md §5.1).
- 파라미터: `input_topic`, `output_topic` (테스트 분리 가능).

### Step 2: emotion_monitor.hpp (C++ BT 노드)

**선택**: `BT::ConditionNode` (RUNNING 상태 없음, 단순 평가).

**상태 보관**: `std::atomic<bool> abort_active_` — ROS subscription 콜백과 BT tick이 같은 spin 루프에서 처리되지만, 추후 multi-threaded executor 도입 시 안전하도록 atomic 사용.

**alarm 전이 로깅**: `exchange()`로 직전 상태와 비교, 변화 시에만 1회 출력 — 5Hz로 abort_trigger가 들어와도 로그 1줄.

```cpp
BT::NodeStatus tick() override {
  return abort_active_.load()
    ? BT::NodeStatus::SUCCESS   // alarm 발동
    : BT::NodeStatus::FAILURE;  // 정상 → 다음 자식
}
```

시동 직후 어떤 메시지도 못 받았으면 FAILURE — 즉 정상으로 취급 (호객 진행).

### Step 3: bt_executor 등록

기존 IceBreak/Approach와 동일한 가변 인자 등록:

```cpp
factory.registerNodeType<dobi_npc_bt::EmotionMonitor>("EmotionMonitor", node);
```

`dobi_npc_msgs`는 이미 depend/find_package/ament_target_dependencies에 모두 들어있어 CMakeLists.txt 변경 0줄.

### Step 4: cafe_funnel_v1.xml — ReactiveFallback로 전환

```xml
<ReactiveFallback name="root_alarm_fallback">
  <SafetyCheck name="safety_alarm" battery_min="0.20"/>
  <EmotionMonitor name="emotion_alarm"/>
  <Sequence name="cafe_funnel">
    ... (6 stages)
  </Sequence>
</ReactiveFallback>
```

**왜 Reactive 필수**:
- plain `Fallback`은 자식이 RUNNING 또는 FAILURE를 한 번 평가한 뒤 그 상태를 latch
- → cafe_funnel이 RUNNING 중이면 SafetyCheck/EmotionMonitor를 다시 안 봄 → abort 무력화
- `ReactiveFallback`은 매 tick마다 모든 자식을 왼쪽부터 다시 평가 → abort가 즉시 작동

### Step 5: 검증 시나리오 2종

**시나리오 1 (정상)**: geva_node + rapport_tracker 동시 실행
- 평범 표정 → V=-0.20, A=0.30 (abort 임계 미달)
- rapport_tracker 출력: `event_type=neutral_continue, reason=within_neutral_band`
- 전이 로그 1회: `event: None -> neutral_continue`

**시나리오 2 (abort)**: bt_executor + 수동 abort_trigger
- `ros2 topic pub --rate 5 /rapport/event ... event_type=abort_trigger ...`
- 결과 (BT 로그 핵심):
  - `[EmotionMonitor] abort_trigger ON  (reason=latched_test, V=-0.70, A=0.60)` — 콜백 수신
  - `emotion_alarm IDLE -> SUCCESS` — alarm 발동
  - `root_alarm_fallback ... -> SUCCESS` — funnel 차단
  - `[tick N] BT status: RUNNING -> SUCCESS` — bt_executor 메인 루프 인식

검증 통과. abort_trigger publish 중단 후 상태 OFF 전이도 로그에서 확인.

---

## 2. 핵심 학습 (개념 정리)

### Reactive vs plain Fallback

BT 4.x의 `Fallback`은 자식의 RUNNING 상태를 한 번만 봄 (memory). 즉 SafetyCheck가 RUNNING이면 다음 tick에서 SafetyCheck부터 다시 시작하지만, 우리 funnel은 SafetyCheck가 즉시 SUCCESS/FAILURE이고 cafe_funnel(Sequence)이 RUNNING이 됨. 이 상태에선 cafe_funnel만 평가됨 → SafetyCheck/EmotionMonitor가 다시 안 불림.

`ReactiveFallback`은 매 tick에서 왼쪽부터 모든 자식을 재평가. 비용이 더 들지만 alarm 패턴엔 필수. SafetyCheck/EmotionMonitor가 가벼운 ConditionNode(평가만)이므로 비용 무시 가능.

### atomic vs mutex for ROS topic cache

ROS 콜백과 BT tick이 같은 spin 루프(SingleThreadedExecutor)에서 처리되면 race condition 없음. 그러나 **MultiThreadedExecutor 도입 시** 콜백 스레드와 tick 스레드가 분리되어 race 발생 가능.

3가지 옵션:
1. `std::atomic<bool>` — 단일 boolean 플래그면 가장 가볍고 안전
2. `std::mutex` + `std::string event_type_` — 추후 reason/weight도 캐시할 때 적합
3. lockfree queue — 모든 이벤트를 BT가 처리해야 한다면

v1은 (1). Phase 후속에서 rapport_delta(weight)를 BT 출력 포트로 노출할 때 (2)로 승격.

### QoS 미스매치 함정 (시나리오 2 부수 발견)

검증 시 `ros2 topic pub --qos-durability transient_local`로 latched publish를 시도했는데 다음 경고 출력:
```
Some, but not all, publishers are offering QoSDurabilityPolicy.TRANSIENT_LOCAL.
Falling back to QoSDurabilityPolicy.VOLATILE
```

원인: 우리 EmotionMonitor 구독자가 default QoS(`reliable + volatile + depth=10`). publisher가 transient_local이면 sub도 transient_local로 맞춰야 latch 메시지를 받는다.

**v1 결정**: rapport_tracker는 stream 발행 (volatile, depth=10). EmotionMonitor sub도 default. 정상 시나리오에선 충분. 검증용 latch publish가 필요하면 둘 다 transient_local로 맞추거나 단순히 `--rate N`으로 지속 발행.

기록 위치: 본 회고. CLAUDE.md에 일반 정책으로 올릴지는 Phase 4 통합 시점에 결정.

### 노드 분리의 가치 재확인

```
geva_node ──/emotion/state──▶ rapport_tracker ──/rapport/event──▶ EmotionMonitor (BT)
```

- `/emotion/state`는 raw V·A (검증/그래프/기록용으로 가치 있음)
- `/rapport/event`는 가공된 의사결정 신호 (BT가 직접 사용)
- 둘을 분리하면:
  - 분류 룰 변경 시 BT 재컴파일 불필요
  - GEFA/fused 입력 추가 시 rapport_tracker만 확장
  - 학습 기반 분류기로 교체할 때 rapport_tracker만 교체
  - 디버깅/시각화 노드는 raw `/emotion/state` 봄

### BT 사이클 너무 빠른 문제

검증 중 발견: cafe_funnel의 모든 stage가 stub(즉시 SUCCESS)이라 한 사이클이 0.4ms 안에 끝남. abort_trigger가 끼어들 시간이 거의 없어 검증이 까다로움.

해결책 (시도): abort_trigger를 **tick보다 빠른 5Hz**로 지속 발행 → 한 사이클 시작 직전에 캐시된 abort_active_가 true → 첫 tick에서 emotion_alarm SUCCESS로 종료.

**근본 해결**: Phase 2 후속에서 IdleScan/Approach가 실 Nav2와 통합되면 자연스럽게 RUNNING 상태가 길어져 abort 검증이 쉬워짐.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **abort 트리거가 전체 funnel 사이클을 차단함** (의도된 동작): root_fallback이 SUCCESS 전이되면 BT 메인 루프는 이를 한 사이클의 종료로 봄. 다음 tick에서 다시 IDLE → RUNNING으로 새 사이클 시작. 즉 abort는 "지금 이 손님 호객 중단"의 단발 의미. 다음 손님(다음 사이클)부터 다시 정상 진행. 이게 cafe NPC 시나리오와 잘 맞음.
- **bt_executor 메인 루프의 status 전이 출력**: `RUNNING -> SUCCESS` 한 줄로 사이클 종료를 알 수 있어 디버깅 용이.
- **ReactiveFallback 비용**: stage당 stub은 마이크로초 단위. 매 100ms tick마다 SafetyCheck/EmotionMonitor를 추가로 평가해도 부담 없음.

### 위험 요소

- **abort_trigger 단발성 vs 지속성**: rapport_tracker v1은 매 입력마다 즉시 평가. 한 프레임만 angry로 잘못 분류돼도 즉시 abort. 실 환경에선 false positive 위험. **Phase 2 후속에 hysteresis 추가** (예: 최근 1초 평균 V·A를 봐서 임계 초과 시 abort).
- **GEVA confidence 임계 미사용**: 현재 confidence는 raw로 통과. confidence < 0.3이면 emotion 신호로 신뢰 안 함 등의 게이트가 없음. Phase 후속.
- **engagement_up/down 미사용**: 발행은 하지만 BT가 안 씀. Phase 3 Minigame이 `rapport_delta` 포트로 받을 예정 (현재 `{rapport_delta}` 블랙보드 키만 비어있음).
- **얼굴 부재 시 동작**: GEVA가 `flags=["no_face"]`를 채울 때 rapport_tracker가 `neutral_continue`로 분류 → BT 정상 진행. 이건 의도된 동작이지만, 실제론 손님 얼굴 안 보이면 호객도 멈춰야 자연스러울 수 있음 (IdleScan에서 처리하는 게 맞음).
- **QoS 미스매치 사일런트 함정**: latch publisher와 default sub 조합 시 메시지 누락. ROS 노드 간 일관된 QoS 정책을 Phase 4 통합 시점에 정의 필요.

### 갭

- 계획서 W4 명세의 **Salichs 2014 Decision Rule** (다중 모달 fusion + 의사결정 트리) 미구현 — GEVA 단독 입력만 다루므로 fusion 트리 불필요. GEFA 도입(W4.5/W2.5) 시점에 추가.
- 계획서의 `decision_rule_node` 별도 신설 미수행 — v1에선 rapport_tracker가 그 역할 흡수. fusion 도입 시 분리 검토.

---

## 4. 다음 일정

### 노트북 단독 트랙

- ✅ ① GEVA — `2026-05-02_phase2_w4_geva.md`
- ✅ ② EmotionMonitor BT 통합 — 본 회고
- 🔜 **④ 노트북 풀스크린 face_avatar GUI** — `/face_avatar/expression` 구독 → 8 어휘 GIF 표시. 프레임워크(pygame/Qt/웹) 결정 필요.
- ⏳ ③ TTS 노드 — `/dialog/utter` 구독 → 음성 출력 (espeak-ng/piper).

### Phase 2 W4 본 작업 잔여 (소규모)

- [ ] **표정 변화 동적 검증**: 사용자가 직접 카메라 앞에서 happy/sad/angry/fear 짓고 V·A + RapportEvent 변동 관찰. 특히 angry/fear에서 abort_trigger가 발동하는지 (현재까지 모두 합성 메시지로만 검증).
- [ ] **rapport_tracker hysteresis** (선택): 최근 1초 V·A 평균 임계 초과 시 abort. false positive 방지.

### RPi 확보 시 (별도 트랙)

- W2.5: vic_pinky RPi 5 셋업, 카메라 2 (RPC-20F) raw publisher
- W4.5: GEFA (자세/접근/회피) → `/emotion/state` (source="body")
- decision_rule_node: GEVA + GEFA fusion → `/emotion/state` (source="fused")

---

## 5. 산출물 위치

### 신규 파일
- `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py` (110줄)
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/emotion_monitor.hpp` (95줄)

### 수정 파일
- `src/dobi_npc/dobi_npc_emotion/setup.py` (entry_point `rapport_tracker` 추가)
- `src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp` (`EmotionMonitor` include + register)
- `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` (Fallback → ReactiveFallback, EmotionMonitor 자식 추가, 주석 갱신)

### 변경 없음 (확인만)
- `src/dobi_npc/dobi_npc_bt/CMakeLists.txt` — dobi_npc_msgs 이미 들어있음
- `src/dobi_npc/dobi_npc_bt/package.xml` — dobi_npc_msgs 이미 들어있음
- `src/dobi_npc/dobi_npc_emotion/package.xml` — dobi_npc_msgs 이미 들어있음

### 다음 커밋
- W4 EmotionMonitor 산출물 + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_emotion dobi_npc_bt --symlink-install
'
```

### 시나리오 1 (정상): geva → tracker
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_emotion geva_node &
ros2 run dobi_npc_emotion rapport_tracker &
ros2 topic echo /rapport/event
# 기대: event_type=neutral_continue (평범 표정), reason=within_neutral_band
```

### 시나리오 2 (abort): 합성 메시지 → BT
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
# abort_trigger를 5Hz로 지속 발행
ros2 topic pub --rate 5 /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: abort_trigger, weight: -1.0, reason: manual,
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: face, flags: []}}" &
# bt_executor 시작 — 첫 tick부터 emotion_alarm SUCCESS, root_fallback SUCCESS
ros2 launch dobi_npc_bt bt_executor.launch.py
# 기대 로그:
#   [EmotionMonitor] abort_trigger ON (reason=manual, V=-0.70, A=0.60)
#   emotion_alarm IDLE -> SUCCESS
#   root_alarm_fallback RUNNING -> SUCCESS
#   [tick N] BT status: RUNNING -> SUCCESS
```

### 토폴로지 확인
```bash
ros2 topic list | grep -E "emotion|rapport"
# /emotion/state    (geva_node 발행)
# /rapport/event    (rapport_tracker 발행 / EmotionMonitor 구독)

ros2 topic info /rapport/event --verbose
# Pub: rapport_tracker_node (volatile, depth=10)
# Sub: bt_executor (volatile, depth=10)
```

---

**상태**: ② EmotionMonitor 완료. cafe_funnel BT가 감정 인식 abort에 반응. 다음은 ④ face_avatar GUI.
