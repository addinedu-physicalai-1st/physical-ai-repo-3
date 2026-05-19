# Phase 2 W4 회고 — face/utter 시작 동기화

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: 직전 회고 `2026-05-03_phase2_w4_utter_done.md` §3 위험 요소 1번 해결
**상태**: face가 tts_node에서 mixer.play 직전 발행되어 음성과 거의 동시 시작 — 사용자 라이브 검증 통과.

---

## 0. 발견 → 해결

### 발견 (utter_done 회고 §3 위험 요소)
- persona_manager가 `/dialog/request` 받는 즉시 face/utter 동시 publish
- face_avatar는 즉시 face 변경 (~ms)
- tts_node는 mp3 합성 후 재생 → ~200~500ms 후 발화 시작
- → face가 음성보다 200~500ms 먼저 변함

### 해결
**UtterRequest에 face_expression 필드 추가 → tts_node가 play 직전에 face 발행**.
한 노드(tts_node)가 face와 음성을 같은 시점에 시작 → race 없음.

---

## 1. 작업 흐름

### Step 1: UtterRequest.msg 확장
`string face_expression` 필드 추가. 빈 문자열이면 face 변경 없음 (이전 표정 유지).

### Step 2: persona_manager 변경
- `face_pub_` 제거 — 더 이상 직접 face 발행 안 함
- `_handle_request`에서 face_expression을 UtterRequest에 packing
- 코드 단순화: phrase + voice + face가 한 메시지로 캡슐

```python
utter.text = phrase
utter.voice = voice.get('name', 'ko-KR-SunHiNeural')
utter.rate = voice.get('rate', '+0%')
utter.pitch = voice.get('pitch', '+0Hz')
utter.face_expression = face if face is not None else ''
```

### Step 3: tts_node 변경
- 새 `face_pub` 추가 (`/face_avatar/expression`)
- `_synth` 안에서 `pygame.mixer.music.play()` **직전**에 face 발행
- 빈 문자열이면 publish skip (이전 face 유지)
- `_on_utter` → `_synth_and_play` → `_synth` 시그니처에 `face` 파라미터 추가

핵심 로직:
```python
async def _synth(self, text, voice, rate, pitch, face, my_gen):
    await comm.save(self._mp3_path)         # 합성 (~200-500ms)
    if my_gen != self._gen:
        return                               # stale 폐기
    if face:
        self.face_pub.publish(String(data=face))  # face 발행
    pygame.mixer.music.load(self._mp3_path)
    pygame.mixer.music.play()                 # 음성 시작
    self._was_busy = True
```

face publish와 play는 같은 thread에서 연달아 호출 — ROS DDS latency(~ms) 외엔 사실상 동시.

### Step 4: 검증
**자체** (합성 메시지 1회):
- persona_manager 로그: `[casual_browser/icebreak/.../face=hello] 더운데 시원한 거 한 잔 어떠세요?`
- tts_node 로그: `speak [.../face=hello] '...'` → ~3초 후 `utter_done`
- `/face_avatar/expression` 토픽: `data: hello` (1회만, 이전엔 persona_manager가 즉시 + tts 늦게의 시간차 있었음)

**라이브** (사용자):
> "face와 음성이 동기화가 잘 되었어."

---

## 2. 핵심 학습

### 시청각 동기화는 "발행 시점"이 아니라 "수신 측 작용 시점"

이전엔 persona_manager가 face와 utter를 같은 callback에서 publish — **발행 시점은 동시**. 그러나 face_avatar는 즉시 표시, tts_node는 합성 latency 후 발화. 즉 **수신 측 작용까지의 latency가 모달리티마다 다름**.

해결의 본질: **latency가 큰 모달리티(음성)의 시작 시점에 다른 모달리티(face)도 시작**. tts_node가 play 직전에 face 발행하면 두 작용이 거의 동시.

일반화: 멀티모달 액추에이터에서 latency가 비대칭이면 가장 느린 액추에이터의 시작 신호에 다른 모든 액추에이터를 동기화. 또는 모든 액추에이터에 "예약 실행" 시간을 명시.

### 메시지 packing의 가치

UtterRequest 한 메시지에 text/voice/rate/pitch/face/persona_id/stage_id 모두 포함. 장점:
- BT/persona_manager가 한 번 발행 → tts_node가 한 번 처리
- 통합 로깅 (한 줄에 모든 메타 — 디버깅 용이)
- 동기화가 한 노드 안에서 — race condition 없음
- 인터페이스 안정성 (메시지/토픽 변경 없이 새 모달리티 추가 가능 — 예: `body_pose`, `arm_gesture` 필드)

단점: face_avatar가 utter 메시지에 의존 안 하지만, 발행자(tts_node)는 face의 의미를 알아야 함. 책임 분산.

대안 (안 채택): face_avatar가 별도 sync 신호 대기. 더 느슨한 결합이지만 latency 보정 어려움.

### face 빈 값 = "변경 없음"의 시맨틱

UtterRequest의 face_expression이 비면 publish skip → face_avatar는 이전 표정 유지. 이로써:
- face_expression이 정의 안 된 stage(예: approach, abort)도 메시지 통합 가능
- "현재 표정 유지" 명시 옵션 제공
- face와 utter의 라이프사이클 분리 (utter는 발화 단위, face는 stage 전이 단위 — 한 utter 동안 face 안 바뀌어도 됨)

### persona_manager의 책임 슬림화

이전: persona_manager가 utter + face 두 토픽 발행. 두 발행 사이 race 없지만 **두 채널 의존**.
지금: persona_manager가 utter 한 토픽만 발행. face 발행은 tts_node로 위임. **단일 발행 책임**.

이로써 persona_manager 코드 짧아지고 (about 5줄 감소), 향후 voice/face 발행 정책 변경 시 수정 위치 1곳.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **합성 latency가 안정적**: edge-tts 후속 호출 ~100~200ms로 일정. 첫 호출만 300~500ms (네트워크 setup). 라이브에서 사용자 체감 동기화 양호.
- **mp3 load + play도 ~ms latency**: pygame.mixer는 빠름. face publish 직후 play 호출이 거의 동시 작용으로 느껴짐.
- **빈 face 처리**: 현재 페르소나 4종은 모든 stage(icebreak/offer/leadin)에 face 정의됨. 빈 케이스는 ROS 메시지 default empty string 처리로 안전.

### 위험 요소

- **abort 시 face는 마지막 표정 유지**: face_avatar가 abort 신호 안 받음. funnel 차단 후 표정이 "fun" 같은 활기찬 상태로 멈춰있는 부조화. **Phase 후속에서 emotion_monitor 또는 tts_node가 abort 시 face_avatar에 "basic" 발행** 검토.
- **첫 utter의 latency**: edge-tts 첫 호출이 300~500ms로 긴 편. 호객 시작 시 face/utter 모두 약간 지연. 워밍업 utter 또는 edge-tts 연결 유지 검토.
- **interrupt 시 face도 리셋?**: 현재 새 utter 들어오면 face는 새 face로 즉시 전환. 이전 utter의 face는 표시되지 않을 수 있음. 의도된 동작이지만 빠른 stage 전환 시 face도 빨리 변함.
- **timeout 시 face 처리**: utter timeout(10초) 발생해도 face는 이미 발행됨. utter 없이 face만 변한 케이스. 자연스러움 — face는 의도된 표정.

### 갭

- **face_avatar가 abort 신호 미수신**: 위 위험 1번. 후속 트랙으로 분리.
- **메시지 다중 채널 일반화**: UtterRequest가 face까지 packing — 향후 body_pose/arm_gesture 등 추가 시 패턴 확장. v1엔 v1엔 face만.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **abort 시 face reset** (위험 §3 1번): emotion_monitor 또는 별도 노드가 abort 시 face_avatar에 "basic" 발행
- **rapport_tracker hysteresis** (D 트랙): false positive abort 방지
- **face_avatar 애니메이션 v2** (C 트랙): Pillow 모든 프레임 + 30fps
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase 검증

### Phase 후속

- W2.5 (RPi 확보 시): vic_pinky RPi 5 셋업, GEFA, decision_rule fusion
- Phase 3: RPS 미니게임 + Polite phrase

---

## 5. 산출물 위치

### 수정 파일
- `src/dobi_npc/dobi_npc_msgs/msg/UtterRequest.msg` (face_expression 필드 추가)
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/persona_manager_node.py` (face_pub_ 제거 + face packing)
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/tts_node.py` (face_pub 추가 + play 직전 발행)

### 신규 파일
- `docs/daily/2026-05-03_phase2_w4_face_utter_sync.md` (본 회고)

### 변경 없음
- face_avatar_node.py — 이미 /face_avatar/expression 구독 중, 변경 0건
- BT 노드 — 변경 없음

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_msgs dobi_npc_dialog --symlink-install
'
```

### 자체 검증 (face publish 1회만)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_dialog tts_node &
ros2 run dobi_npc_dialog persona_manager &
sleep 2

ros2 topic echo /face_avatar/expression &
ros2 topic pub --once /dialog/request std_msgs/String "{data: 'icebreak'}"
# 기대: face 토픽에 'data: hello' 1번 (persona_manager 직접 발행 0번)
```

### 라이브 통합 검증
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py
```

---

**상태**: face/utter 동기화 완료. 다음은 abort 시 face reset 또는 rapport hysteresis 또는 휴식.
