# Phase 2 W4 회고 — abort 시 face reset

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: 직전 회고 `2026-05-03_phase2_w4_face_utter_sync.md` §3 위험 요소 1번 해결
**상태**: face_avatar가 abort_trigger 수신 시 basic으로 reset — 사용자 라이브 검증(합성 publish) 통과.

---

## 0. 발견 → 해결

### 발견 (face/utter sync 회고 §3 위험 요소 1번)
- abort 발생 시 funnel halt → 다음 stage 안 옴 → face_avatar에 새 face 발행 없음
- → 마지막 표정(예: "fun" 활기찬)이 그대로 남아 호객 차단 상황과 부조화

### 해결
**face_avatar가 직접 `/rapport/event` 구독 → abort_trigger 수신 시 self.current = abort_expression(기본 basic) + dirty=True**.
self-contained 변경 — emotion_monitor / tts_node 변경 0건. 결합도 가장 낮음.

---

## 1. 작업 흐름

### Step 1: face_avatar_node.py 수정

추가:
- `from dobi_npc_msgs.msg import RapportEvent`
- 파라미터 `abort_expression` (기본 `basic`), `rapport_topic` (기본 `/rapport/event`)
- `self.rapport_sub = create_subscription(RapportEvent, rapport_topic, self._on_rapport, 10)`
- `_on_rapport(msg)` 콜백:
  - `event_type != "abort_trigger"` → 무시
  - `abort_expression`이 빈 값 → 무시 (reset 안 함 옵션)
  - GIF 미로드 → warn
  - 현재가 abort_expression과 다르면 → set + dirty + log

빈 값 시맨틱: `abort_expression=""`로 파라미터 설정하면 abort 시 reset 안 함 (기존 표정 유지). 운영 정책별 토글 가능.

### Step 2: 자체 검증

```bash
ros2 run dobi_npc_dialog face_avatar -p fullscreen:=false &
ros2 topic pub --once /face_avatar/expression std_msgs/String "{data: fun}"
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', ...}"
```

로그: `abort_trigger (test_abort) → face: fun -> basic` ✓

`neutral_continue` 발행 시 reset 안 됨 (조건절에서 abort_trigger만 처리) ✓

### Step 3: 사용자 라이브 검증

#### 첫 시도 — 잘못된 시나리오
사용자가 face_avatar의 키보드 8번(angry)으로 검증 시도. 그러나 키보드는 face_avatar 내부 디버그 매핑일 뿐 abort_trigger 발생 안 함. 이번 트랙과 무관.

또 카메라에 angry 표정 시도. V=-0.32, A=0.29로 abort 임계(V<-0.5 ∧ A>+0.4) 미달 → `engagement_down`만 발행 → emotion_monitor도 face_avatar도 reset 안 됨.

#### 학습한 검증 도구화

운영 환경에서 사람 표정으로 V≤-0.5 + A≥+0.4 둘 다 넘기는 어려움 — **합성 publish가 더 통제 가능**.

또 `safety_alarm`/`emotion_alarm`의 `IDLE → FAILURE → IDLE` 100ms toggle 로그 폭발(ReactiveFallback의 ConditionNode 매 tick 재평가 정상 동작)이 검증 시 노이즈. **로그 파일 + grep 패턴**이 필수:

```bash
# 콘솔 + 파일 동시
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log

# 별도 터미널에서 abort 강제
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'manual',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"

# abort 사슬만 추출
grep -E "abort|EmotionMonitor|emotion_alarm.*SUCCESS|face: .* -> basic" /tmp/dobi.log

# 또는 toggle 노이즈 제거하고 보기
grep -vE "safety_alarm.*(IDLE|FAILURE)|emotion_alarm.*(IDLE -> FAILURE|FAILURE -> IDLE)" /tmp/dobi.log
```

#### 검증 결과 (사용자 합성 publish 2회)

| 컴포넌트 | 1차 publish (T~544.7) | 2차 publish (T~555.7) |
|---|---|---|
| **face_avatar** (이번 트랙) | `→ face: happy -> basic` ✓ | `→ face: happy -> basic` ✓ |
| EmotionMonitor (BT) | `abort_trigger ON` ✓ | `abort_trigger ON` ✓ |
| tts_node | (발화 중 아니었음) | `→ mixer.stop()` ✓ |

세 컴포넌트가 같은 `/rapport/event` 토픽을 각자 구독 → 각자 자기 책임 동작 → race 없음. 분산 책임의 가치 확인.

ON/OFF 빠른 반복: rapport_tracker가 abort_trigger 1건 발행 직후 GEVA의 다음 V·A 입력에 따라 즉시 다른 event_type(neutral_continue 등) 발행 → emotion_monitor가 한 tick에 OFF. 정상 동작.

---

## 2. 핵심 학습

### self-contained vs 중앙 orchestrator

abort 시 face reset을 처리할 수 있는 위치 4가지:
- (A) emotion_monitor (BT 노드, C++) — face publish 추가
- (B) tts_node — 이미 abort 구독 중, face_pub 추가
- (C) 별도 face_orchestrator 노드
- (D) **face_avatar 자기 자신** — abort 직접 구독

(D) 채택 이유: face_avatar가 자기 동작에만 집중. 다른 노드 변경 0건. 새 노드 추가 안 함. 결합도 가장 낮음.

일반 원칙: 어떤 노드의 출력이 정해진 룰로 변경되어야 한다면, **그 노드 자신이 룰의 입력을 구독**하는 게 깔끔. 외부 노드가 강제 publish하면 결합도 증가.

### 같은 토픽을 여러 노드가 각자 구독하는 패턴

`/rapport/event`를 3 노드(emotion_monitor, tts_node, face_avatar)가 각자 구독. ROS DDS는 자연스럽게 fan-out — 한 publish가 모든 sub에 전달. 각 노드가 자기 책임만 수행:
- emotion_monitor: BT alarm SUCCESS
- tts_node: mixer.stop()
- face_avatar: face reset

**race condition 없음** — 각 노드의 callback이 독립적으로 실행, 공유 상태 없음. 이게 ROS pub/sub 패턴의 핵심 가치.

### ReactiveFallback의 ConditionNode 로그 폭발

`ReactiveFallback`은 매 100ms tick마다 SafetyCheck/EmotionMonitor를 재평가 → BT::StdCoutLogger가 IDLE/FAILURE 전이를 매번 출력 → 로그 폭발 (한 stage 발화 3초 동안 60+ 라인의 toggle 로그).

**검증 어려움**: 핵심 라인(abort, utter_done 등)이 노이즈에 묻힘. grep 필수.

해결 옵션 (Phase 후속):
- BT::StdCoutLogger 대신 verbose 낮은 logger 또는 자체 logger 작성
- 또는 ConditionNode의 IDLE 전이 로그만 필터링하는 wrapper

### 합성 publish vs 라이브 검증

라이브 검증(카메라 표정)은 **자연스러움 확인**에 강함. 그러나 임계값 명확히 넘기기 어려움 (V≤-0.5 + A≥+0.4 둘 다).

합성 publish(`ros2 topic pub --once`)는 **신호 사슬 정확성 검증**에 강함. 통제된 입력 → 명확한 출력 확인.

두 방법은 보완적. 라이브로 사용자 체감 확인 + 합성으로 사슬 검증.

### `--once` publisher의 latched 문제

`ros2 topic pub --once`는 한 번 publish 후 즉시 종료 — sub가 아직 discovery 안 끝났으면 메시지 누락. 우리 검증에선 launch가 이미 띄워진 상태(sub 다 ready)라 OK였으나, 일반화 시 `--rate 1` 같은 지속 publish 또는 `--qos-durability transient_local` latch 고려.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **abort 처리 분산이 자연스러운 ROS 패턴**: 한 토픽 → 여러 sub → 각자 책임. 통합 orchestrator보다 단순.
- **face_avatar 변경 약 25줄**: 가장 짧은 트랙. self-contained 패턴의 가치.
- **abort_expression 파라미터 + 빈 값 시맨틱**: 운영 환경에서 reset 끄고 싶으면 `abort_expression:=""` — 정책 토글 가능.

### 위험 요소

- **basic 표정의 적합성**: abort는 손님이 화났거나 두려워한 상황 — basic(평온) 표정이 자연스러우나, "sad" (사과)나 "bored" (회피) 표정도 후보. 페르소나별/상황별 다른 abort_expression 필요할 수 있음. v1엔 단일 default.
- **ReactiveFallback 로그 노이즈**: 위 §2 학습 참조. 검증/디버깅 부담. Phase 후속에서 logger 개선 필요.
- **abort 후 다음 utter의 face가 즉시 덮어씀**: BT가 새 사이클 시작하면 다음 stage_id의 face가 발행됨. basic 잠깐만 보임. 이게 의도된 동작이지만 사용자 체감엔 reset 효과가 약할 수 있음. abort 후 일정 시간 dwell 정책(예: 2초간 basic 유지) 검토.
- **합성 publish 검증의 라이브 환경 race**: 합성 publish 시점에 BT가 마침 다음 stage 진입 직전이면 face publish가 같은 ms에 도착해 어느 게 먼저 처리될지 timing 의존. 라이브 검증에서 1차 시도 시 mixer.stop이 안 보였던 것도 비슷 (발화 중이 아니었음).

### 갭

- **abort_expression 페르소나별 override 미구현**: persona YAML에 `abort_expression` 필드 추가 가능. v1엔 face_avatar 글로벌 파라미터만. 페르소나별 abort 표정 차별화는 후속.
- **dwell time 정책 부재**: 위 위험 §3번. 후속 트랙.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **rapport_tracker hysteresis** (D 트랙): 한 프레임 잘못된 angry로 abort 발동 방지. 최근 1초 V·A 평균 임계.
- **face_avatar 애니메이션 v2** (C 트랙): 정적 1프레임 → Pillow 모든 프레임 + 30fps.
- **abort dwell time** (위 위험 §3): abort 후 일정 시간 face publish 무시.
- **ReactiveFallback 로그 노이즈 정리** (위 §2): 자체 logger 또는 toggle 필터.
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase 검증.

### Phase 후속

- W2.5 (RPi): GEFA, decision_rule fusion
- Phase 3 (W7-9): RPS 미니게임 + Polite phrase

---

## 5. 산출물 위치

### 수정 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` (RapportEvent import + 파라미터 + sub + _on_rapport 콜백, 약 25줄 추가)

### 신규 파일
- `docs/daily/2026-05-03_phase2_w4_face_abort_reset.md` (본 회고)

### 변경 없음
- emotion_monitor.hpp, tts_node.py, BT XML, persona_manager — 모두 그대로

### 다음 커밋
- W4 face abort reset + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_dialog --symlink-install
'
```

### 자체 검증 (window mode + 합성 신호 한 사슬)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash

ros2 run dobi_npc_dialog face_avatar \
  --ros-args -p fullscreen:=false -p window_width:=400 -p window_height:=300 &
sleep 2
ros2 topic pub --once /face_avatar/expression std_msgs/String "{data: 'fun'}"
sleep 1
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'test',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"
# 기대 로그: face_avatar에 'abort_trigger (test) → face: fun -> basic'
```

### 라이브 통합 검증 (로그 캡처 + grep)
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log

# 별도 터미널:
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'manual',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"

# launch 종료 후 abort 사슬만 추출:
grep -E "abort|EmotionMonitor|emotion_alarm.*SUCCESS|face: .* -> basic" /tmp/dobi.log
```

### 옵션: abort reset 끄기
```bash
ros2 launch dobi_npc_bringup dev_all.launch.py \
  -p face_avatar.abort_expression:=""
# 또는 노드 단독:
ros2 run dobi_npc_dialog face_avatar --ros-args -p abort_expression:=""
```

---

**상태**: face abort reset 완료. abort 사슬 3 컴포넌트(emotion_monitor + tts_node + face_avatar) 모두 작동. 다음은 rapport hysteresis / 애니메이션 v2 / 로그 노이즈 정리 / 자투리 또는 휴식.
