# Phase 2 W4 회고 — face_avatar abort dwell time

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `2026-05-03_phase2_w4_face_anim_v2.md` §3 위험 요소 (abort 후 BT 다음 사이클이 즉시 face publish 덮어씀)
**상태**: face_avatar에 abort_dwell_sec(기본 2.0초) 도입. 자체 검증 ignore 메커니즘 확인 + 라이브 dwell timer 시작 확인.

---

## 0. 발견 → 해결

### 발견 (face_anim_v2 회고 §3)
- abort_trigger 발동 → face_avatar가 basic reset
- 그러나 BT 다음 사이클의 IceBreak가 ~0.2초 만에 새 face(예: hello) publish
- → basic이 깜빡 보이고 즉시 다른 표정으로 덮임 → "호객 차단" 시각 신호 약함

### 해결
**face_avatar에 self-contained dwell timer**: abort_trigger 후 일정 시간 동안 새 expression publish ignore.
- 파라미터 `abort_dwell_sec` (기본 2.0초)
- _on_rapport에서 `_dwell_until_ms = now + dwell_sec` 설정
- _on_expression에서 `now < _dwell_until_ms`이고 새 expression이 abort_expression이 아니면 ignore

---

## 1. 작업 흐름

### Step 1: face_avatar_node.py 수정

추가:
- `abort_dwell_sec` 파라미터 (기본 2.0)
- `_dwell_until_ms` 상태 변수
- `_on_rapport`: abort_trigger 시 `_dwell_until_ms = pygame.time.get_ticks() + int(dwell * 1000)`. 매 abort_trigger 메시지마다 갱신 (sustained abort 동안 dwell 유지).
- `_on_expression`: dwell 중이면 `abort_expression(basic)` 자체는 허용 + 다른 expression은 ignore + remaining 시간 로그.

핵심 로직:
```python
def _on_rapport(self, msg):
    if msg.event_type != "abort_trigger":
        return
    if self.abort_dwell_sec > 0:
        self._dwell_until_ms = pygame.time.get_ticks() + int(
            self.abort_dwell_sec * 1000)
    ...
    if self.current != self.abort_expression:
        self.get_logger().info(
            f"abort_trigger ({msg.reason}) → face: ... -> "
            f"{self.abort_expression} (dwell {self.abort_dwell_sec:.1f}s)")
        self._switch_to(self.abort_expression)

def _on_expression(self, msg):
    name = msg.data.strip().lower()
    ...
    now_ms = pygame.time.get_ticks()
    if (now_ms < self._dwell_until_ms and
            name != self.abort_expression):
        remaining = (self._dwell_until_ms - now_ms) / 1000.0
        self.get_logger().info(
            f"abort dwell {remaining:.1f}s remaining → ignore '{name}'")
        return
    if name != self.current:
        self._switch_to(name)
```

`abort_expression(basic)` 자체는 허용한 이유: sustained abort 동안 누군가 (예: 다른 노드) basic publish해도 무시할 필요 없음 + dwell 중 추가 abort_trigger로 dwell 갱신될 때 일관성.

### Step 2: 자체 검증 (face_avatar 단독 + 합성 publish 시퀀스)

| 시간 | 이벤트 | 결과 |
|---|---|---|
| T=0 | hello publish | `face: basic -> hello` ✓ 적용 |
| T+0.5 | abort_trigger | `abort_trigger (test) → face: hello -> basic (dwell 2.0s)` ✓ |
| T+1.8 | fun publish | **`abort dwell 0.2s remaining → ignore 'fun'`** ✓ 차단 |
| T+4 | happy publish | `face: basic -> happy` ✓ dwell 끝남, 적용 |
| T+5.5 | angry publish | `face: happy -> angry` ✓ |

핵심: dwell 윈도우 안의 expression이 정확히 ignore됨.

### Step 3: 라이브 검증 (dev_all.launch + abort_trigger 직접 publish)

라이브 환경에서 첫 시도 (`ros2 topic pub --rate 20 /emotion/state`)로 hysteresis 우회 안 됨 — GEVA의 카메라 normal 입력이 abort_streak 깸 (이전 hysteresis 트랙에서 발견한 패턴 재현).

해결: **rapport_tracker 우회하고 `/rapport/event`에 abort_trigger 직접 publish** — face_avatar / EmotionMonitor / tts_node 모두 같은 토픽 구독이라 직접 신호 도달.

```bash
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: abort_trigger, weight: -1.0, reason: manual_dwell_test, ...}"
```

**결과** (3 컴포넌트 동시 abort 처리):
```
T=558.03 [bt_executor]: [EmotionMonitor] abort_trigger ON (reason=manual_dwell_test)
T=558.03 [tts_node]:    abort_trigger → mixer.stop()
T=558.05 [face_avatar]: abort_trigger (manual_dwell_test) → face: interest -> basic (dwell 2.0s)
```

dwell 2.0s 메시지 정상. 그러나 **`abort dwell N.Ns remaining → ignore 'X'` 라인은 라이브에서 보기 어려움** — BT가 abort 후 새 사이클을 시작해도 utter 합성 latency(~3초)가 dwell(2초)보다 길어서 다음 face publish가 dwell 윈도우 밖에서 옴.

**검증 정리**:
- ✅ dwell timer 작동 (자체 검증 ignore 라인 확인)
- ✅ 라이브에서 dwell 시작 + 3 컴포넌트 동시 abort 처리 확인
- 라이브 ignore 라인 보기엔 BT 사이클 timing이 까다로움 — 메커니즘은 이전 자체 검증에서 입증됨

---

## 2. 핵심 학습

### Self-contained 패턴의 일관성 가치

이번 트랙도 face_avatar 자체에서 처리. emotion_monitor / tts_node 변경 0건.
- 같은 토픽(`/rapport/event`)을 3 노드가 각자 구독
- 각자 자기 책임만 처리
  - emotion_monitor: BT alarm SUCCESS
  - tts_node: mixer.stop()
  - face_avatar: face reset + dwell timer

이 패턴이 **face_abort_reset → rapport_hysteresis → face_dwell**까지 일관 유지. ROS pub/sub fan-out의 자연스러운 활용.

### Dwell 매 abort_trigger마다 갱신

abort 1건만 받고 dwell 시작하는 게 아니라 **매 abort_trigger 메시지마다 _dwell_until_ms 갱신**. 즉 sustained abort(rate 5Hz로 abort_trigger 매번 들어옴)이면 dwell이 계속 연장. abort 끝나면 마지막 메시지 후 2초 더 유지.

이게 자연 — sustained abort 중엔 face가 계속 basic이고, abort 해제 후 2초 buffer로 다음 funnel 사이클 시작해도 첫 face가 잠시 ignore되어 부드러운 전환.

### Dwell 우회 케이스 — abort_expression 자체

`name != self.abort_expression` 체크로 **abort_expression(basic) publish는 dwell 무시하고 통과**. 이로써:
- 다른 노드가 abort 중 basic publish → 통과 (어차피 같은 표정)
- dwell 갱신 로직과 분리 — dwell은 _on_rapport에서만 조정

만약 통과 안 시키면: dwell 중 들어온 basic도 ignore → 디버깅 시 혼란. 통과시키는 게 단순.

### 라이브 검증 한계 — BT 사이클 timing

**자체 검증** (face_avatar 단독): 합성 publish 시퀀스로 ignore 라인까지 정확히 확인. 메커니즘 입증.

**라이브 검증** (dev_all.launch): BT가 abort 후 새 사이클 → 첫 utter 합성 ~3초 → 다음 face publish가 dwell(2초) 밖에서 옴 → ignore 라인 자연스럽게 안 보임.

해결책 (필요 시):
- dwell을 utter 시간(~3초)보다 길게 (예: 5초)
- 또는 BT 사이클을 인위적으로 빠르게 만들어서 dwell 안에 face publish가 오도록

라이브에서 ignore 라인 자체는 못 봐도, **dwell 시작 메시지 + 시각적 basic 머무는 시간 증가**로 효과 체감 가능.

### `abort_dwell_sec=0`로 비활성 옵션

운영 정책에 따라 dwell 끄고 싶으면 `abort_dwell_sec:=0.0` 파라미터. 이전 동작(즉시 덮임)으로 복귀. v1 동작으로 fallback 가능.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **Self-contained 일관성**: face_avatar 변경만으로 해결. 1개 파일 ~25줄 추가.
- **dwell 시작 메시지에 시간 포함**: `(dwell 2.0s)` 표시로 운영 시 정책 인지 쉬움.
- **3 컴포넌트 동시 abort 처리** (라이브 검증): ROS pub/sub fan-out으로 emotion_monitor/tts_node/face_avatar가 동시에 자기 책임 수행.

### 위험 요소

- **dwell 중 새 utter가 시작 안 됨**: abort 후 BT 다음 사이클의 첫 utter는 발화되지만 face는 ignore → 음성과 표정 불일치 (예: 발화는 "안녕하세요!"인데 표정은 basic). 운영 시 약간 부조화 가능. dwell 짧게(예: 1초) 또는 음성도 dwell하는 정책 검토.
- **dwell 적정값**: 2초가 너무 짧을 수도(BT 사이클 평균 ~10초이라 첫 face publish가 dwell 밖에서) 또는 너무 길 수도(다음 손님 호객 지연). 운영 측정 필요.
- **dwell timer가 pygame.time 기반**: ROS time과 분리. ROS time과 동기화하려면 `self.get_clock().now()` 사용 권장. 단순한 dwell엔 차이 무시.
- **GEVA 입력이 hysteresis를 깬다**: 라이브 검증에서 합성 abort_trigger가 abort_streak 5 충족 못 함. 사용자 표정으로만 abort 발동시키려면 강하고 지속적인 angry/fear 표정 필요. 운영 시 카페 손님이 진짜 화내는 케이스에서만 발동될 확률 높음 — 의도된 동작이지만 시연 어려움.

### 갭

- **음성/표정 dwell 통합**: 위 위험 §1. tts_node도 dwell 도입 검토 (음성도 일정 시간 멈추기).
- **persona별 dwell 정책 미구현**: 현재 글로벌 파라미터. 페르소나별 다른 dwell이 자연스러울 수 있음 (예: friendly_child는 짧게 1초, professional_adult는 길게 3초).
- **dwell 중 시각 신호 추가**: basic만 표시하는 것 외에 "차단됨" 표시(예: 화면 가장자리 빨간 테두리 0.5초)도 검토. 운영 시 사용자/손님이 alarm 발동 인지 도움.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **min_confidence 임계**: rapport_tracker에 conf 게이팅 (낮은 conf 입력 무시)
- **brightest 시작 옵션**: face_avatar 첫 프레임이 fade-in 검정 회피
- **dwell 음성 통합**: tts_node도 abort dwell
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase

### Phase 후속

- W2.5 (RPi): GEFA, decision_rule fusion
- Phase 3: RPS 미니게임

---

## 5. 산출물 위치

### 수정 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` (abort_dwell_sec 파라미터 + _dwell_until_ms 상태 + 콜백 dwell 처리, ~25줄 추가)

### 신규 파일
- `docs/daily/2026-05-03_phase2_w4_face_dwell.md` (본 회고)

### 변경 없음
- 다른 노드, 메시지, BT, persona YAML — 모두 그대로

### 다음 커밋
- W4 face dwell + 본 회고 단일 커밋

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

### 자체 검증 (face_avatar 단독 + 합성 시퀀스)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_dialog face_avatar \
  --ros-args -p fullscreen:=false -p window_width:=400 -p window_height:=300 \
  -p max_frames_per_gif:=20 -p abort_dwell_sec:=2.0 &
sleep 4
ros2 topic pub --once /face_avatar/expression std_msgs/String "{data: 'hello'}"
sleep 0.5
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'test',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"
sleep 1
ros2 topic pub --once /face_avatar/expression std_msgs/String "{data: 'fun'}"
# 기대 로그: 'abort dwell 1.0s remaining → ignore fun'
sleep 3
ros2 topic pub --once /face_avatar/expression std_msgs/String "{data: 'angry'}"
# 기대 로그: 'face: basic -> angry' (dwell 끝남)
pkill -INT -f face_avatar
```

### 라이브 통합 검증 (dev_all.launch + 직접 abort)
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log

# 별도 터미널 — hysteresis 우회 위해 /rapport/event 직접 publish
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'manual',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"

# 기대 라인 (3 컴포넌트 동시):
#   [EmotionMonitor] abort_trigger ON
#   [tts_node] abort_trigger → mixer.stop()
#   [face_avatar] abort_trigger → face: <X> -> basic (dwell 2.0s)
```

### 운영 시 dwell 조정
```bash
# dwell 비활성 (이전 동작)
ros2 launch dobi_npc_bringup dev_all.launch.py face_avatar.abort_dwell_sec:=0.0

# 더 긴 dwell (시각 신호 명확히)
ros2 launch dobi_npc_bringup dev_all.launch.py face_avatar.abort_dwell_sec:=5.0

# 짧은 dwell (다음 호객 빠르게)
ros2 launch dobi_npc_bringup dev_all.launch.py face_avatar.abort_dwell_sec:=1.0
```

---

**상태**: face dwell 완료. 자체 검증 ignore 라인 확인 + 라이브 dwell timer 시작 확인. 다음은 min_confidence / brightest 시작 / 음성 dwell 통합 / 자투리 또는 휴식.
