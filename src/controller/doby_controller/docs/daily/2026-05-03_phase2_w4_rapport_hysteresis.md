# Phase 2 W4 회고 — rapport_tracker hysteresis (false positive abort 방지)

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: 직전 회고 `2026-05-03_phase2_w4_face_abort_reset.md` §4 D 트랙
**상태**: rapport_tracker에 ON/OFF hysteresis 적용. 라이브 검증 (단발 합성 publish 10회) 모두 abort 발동 안 함 — false positive 차단 효과 입증.

---

## 0. 발견 → 해결

### 발견 (face_abort_reset 회고 §3 위험 요소)
- v1 rapport_tracker는 매 V·A 입력 즉시 평가 (즉시 평가 룰)
- GEVA가 10Hz로 V·A 발행. 한 프레임 잘못 분류된 angry → 즉시 abort_trigger
- false positive 위험: 일시적 표정 흔들림으로 호객 차단

### 해결
**ON/OFF 둘 다 연속 카운트 hysteresis 적용**.
- ON: raw abort 조건이 abort_on_count(기본 5) 프레임 연속 → abort_trigger 발행 시작
- OFF: raw 정상이 abort_off_count(기본 5) 프레임 연속 → abort 해제

10Hz GEVA 가정 시 5프레임 ≈ 0.5초. 짧은 outlier 흡수 + 빠른 반응 균형.

---

## 1. 작업 흐름

### Step 1: rapport_tracker_node.py 수정

**상태 머신**:
- `_abort_streak`: raw abort 조건 연속 카운트
- `_normal_streak`: raw 정상 연속 카운트
- `_currently_aborting`: 현재 abort 발행 중 여부

**처리 룰**:
```python
no_signal = (msg.confidence <= 0.0) or ("no_face" in msg.flags)
raw_abort = (not no_signal) and (v < -0.5) and (a > 0.4)

if no_signal:
    pass  # 카운트 변경 없음 — 사람 안 보이는 동안 abort 자동 해제 방지
elif raw_abort:
    self._abort_streak += 1; self._normal_streak = 0
else:
    self._normal_streak += 1; self._abort_streak = 0

# 상태 전이
if not currently_aborting and abort_streak >= 5:
    currently_aborting = True   # ENTER
elif currently_aborting and normal_streak >= 5:
    currently_aborting = False  # LEAVE

# event_type 결정
if no_signal:           event_type = "neutral_continue"  # reason=no_signal
elif currently_aborting: event_type = "abort_trigger"     # reason=negative_high_arousal_sustained
elif v > +0.3:          event_type = "engagement_up"
elif v < -0.3:          event_type = "engagement_down"   # raw abort 조건이지만 streak<5면 여기로
else:                   event_type = "neutral_continue"
```

핵심: **raw abort 조건이 한 프레임 충족돼도 streak<5면 abort_trigger 안 보냄**. 대신 약한 신호(engagement_down)로 분류 → BT는 정상 진행.

### Step 2: 자체 검증 (GEVA 없이 직접 publish)

| 시나리오 | streak 진행 | event_type | 결과 |
|---|---|---|---|
| **A. 단발 abort 조건** (1회) | abort=1 | engagement_down | ✓ abort_trigger 발동 안 함 |
| **B. 5회 연속** | abort=5 → ENTER | engagement_down → abort_trigger | ✓ 정확히 5번째에 발동 |
| **C. 정상 5회** | normal=5 → LEAVE | abort_trigger → neutral_continue | ✓ 정상 복귀 |

3 시나리오 모두 통과. 메커니즘 확실.

### Step 3: 사용자 라이브 검증 (dev_all.launch + 합성 publish)

사용자가 GEVA 켠 채로 단발 합성 abort_trigger publish를 **약 10번** 시도.

**로그 분석 결과** (`grep -E "ENTER|LEAVE|abort_streak" /tmp/dobi.log`):
```
T=508.34: event: ... -> engagement_down (V=-0.70, A=0.60, abort_streak=1, normal_streak=0)
T=521.55: event: ... -> engagement_down (V=-0.70, A=0.60, abort_streak=1, normal_streak=0)
T=524.02: event: ... -> engagement_down (V=-0.70, A=0.60, abort_streak=1, normal_streak=0)
... (총 10회)
```

**ENTER abort 라인이 한 번도 안 뜸**. 모든 단발 publish가 `abort_streak=1`만 만들고 다음 GEVA 카메라 프레임(V≈-0.2~-0.3, normal)이 즉시 streak reset.

즉 **단발 false positive 10/10 차단 성공** (이전 트랙이라면 매번 abort 발동했을 것).

### Step 4: 라이브 환경에서 abort 발동 시연 어려움 (메커니즘 검증의 함정)

라이브에서 ENTER를 직접 보려면 **GEVA(10Hz)보다 빠르게 abort 입력**해야 함:
- GEVA 노드를 끄고 합성 5회 연속 (가장 확실)
- 또는 `ros2 topic pub --rate 20 /emotion/state ...` (GEVA 인터리브 이김)

자체 검증(Step 2)에선 GEVA 없이 직접 publish해서 5연속이 즉시 충족 → ENTER 통과. 메커니즘은 확실하지만, **라이브에서 합성 단발 publish로 ENTER를 보려면 GEVA를 잠시 멈춰야** 함.

이건 약점이라기보다 **hysteresis가 의도대로 작동하는 증거** — 실시간 GEVA가 outlier를 즉시 흡수하는 효과를 직접 관찰.

---

## 2. 핵심 학습

### Hysteresis의 ON/OFF 비대칭 가능성

이번 v1은 ON/OFF 둘 다 5프레임으로 대칭. 그러나 운영 상황에 따라 비대칭이 자연:
- 보수적 시나리오: ON 빠르게(예: 3프레임), OFF 느리게(10프레임). abort 빨리 들어가고 천천히 빠짐.
- 적극적 시나리오: ON 느리게(8프레임), OFF 빠르게(3프레임). abort 진입 까다로움.

기본은 대칭 + `abort_on_count`/`abort_off_count` 파라미터로 운영 시점에 조정.

### Streak vs 윈도우 평균 vs 시간 기반 지속

3가지 hysteresis 패턴 비교:
- **Streak (선택)**: 단순, 디버깅 용이 (streak 카운트 로그)
- 윈도우 평균: 부드러움, outlier 분산 흡수, 그러나 윈도우 크기 + 평균/중앙값 정책 결정 필요
- 시간 기반: 프레임 rate 무관, 더 일반적, 그러나 monotonic clock 관리 추가

v1은 streak이 충분 (GEVA가 publish_rate_hz 파라미터로 일정 rate). Phase 후속에서 GEFA 도입 시 publish rate가 다른 source 섞이면 시간 기반으로 승격 검토.

### `no_signal` 처리 정책

GEVA가 `confidence==0` 또는 `flags=["no_face"]` 발행 시:
- (a) **카운트 변경 없음** (선택) — 사람 안 보이는 동안 abort 상태 유지
- (b) normal_streak++ — 사람 안 보이면 정상 취급 → abort 자동 해제
- (c) abort_streak/normal_streak 둘 다 reset — 중립 취급

(a) 채택 이유: abort 중 카메라 가렸다 다시 보이면 손님 화 안 풀렸을 가능성. 안전 측 (호객 안 재개).

(b)는 손님 떠난 케이스에 자연스러우나 abort 도중 일시적 occlusion에 abort 풀려 위험.

(c)는 가장 단순하나 abort 안정성 약함.

운영 시점에 정책 검토 가능. 현재는 (a) 고정.

### 라이브 검증의 약점 — 실시간 입력이 outlier를 흡수

이번 검증에서 사용자가 단발 합성 publish를 했지만 GEVA의 10Hz 실시간 입력이 즉시 streak 깸 → ENTER 안 뜸. **메커니즘이 잘 작동한다는 증거**이지만 동시에 라이브에서 hysteresis ON 시연이 어려움.

해결 (검증 도구화):
- 자체 검증 (Step 2): GEVA 없이 직접 publish — 메커니즘 검증
- 라이브 검증 (Step 3): GEVA 켠 채로 — outlier 흡수 검증
- 두 방식이 보완적

라이브에서 ENTER 보려면 GEVA 일시 정지 또는 abort publish rate를 GEVA보다 빠르게.

### `currently_aborting` 동안 매 입력마다 abort_trigger 발행

ENTER 후엔 매 V·A 입력마다 `event_type=abort_trigger` 발행. 이전 v1은 raw 조건 충족 시에만 abort_trigger. 차이:
- v1 (이전): abort 조건 충족 시점만 abort_trigger 1건 → 그 사이 정상 1건 들어오면 즉시 abort 풀림
- 이번 (hysteresis): ENTER 후 OFF 임계 충족까지 매 입력마다 abort_trigger → 안정적 신호

EmotionMonitor BT 노드는 `abort_active_` atomic flag — 한 번 set되면 다음 메시지로만 unset. 이번 변경으로 abort_trigger 메시지 흐름이 안정되어 BT alarm 상태도 더 안정.

### `confidence > 0` 가드 — raw abort 조건에 추가

기존 분류 룰엔 `confidence` 체크 없음 (no_face flag만). 새 룰에선 `raw_abort` 계산 시 `not no_signal` 가드 추가. 즉 conf=0이면 raw_abort=False. 이는 GEVA가 잠깐 얼굴 못 잡은 프레임에 V·A 우연히 abort 임계 넘어도 streak 안 쌓이도록 방지.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **단발 outlier 차단 효과 명확**: 라이브에서 단발 합성 publish 10회 모두 ENTER 안 뜸. 의도대로 작동.
- **streak 카운트 로그가 디버깅에 유용**: 매 event 전이 로그에 `abort_streak=N, normal_streak=M` 포함 — 상태 머신 시각화.
- **GEVA의 normal_streak이 100~300까지 누적**: 사용자가 카메라 앞에서 평범하게 있는 동안. 안정적인 normal 입력 흐름 확인.

### 위험 요소

- **abort_on_count=5의 적합성**: 0.5초 지연이 카페 환경에서 적절한지 운영 시 검증 필요. 너무 짧으면 false positive 잔존, 너무 길면 진짜 위험 반응 늦음.
- **GEFA 도입 시 publish rate 차이**: GEVA 10Hz, GEFA는 RPi USB 캠 rate에 따라 다름. fusion 시 streak 카운트가 source별 비대칭. 시간 기반으로 승격 검토 (W4.5 시점).
- **윈도우 평균 미적용**: outlier 1건은 흡수하지만 outlier 분포(예: 2~3건이 산발적으로) 케이스는 streak 0/1로 토글되며 noise가 통과 가능. Phase 후속에서 short window mean 검토.
- **conf 임계 미적용**: `confidence==0`만 차단. conf>0이지만 낮은 값(예: 0.1)도 신뢰 안 할 수 있음. `min_confidence` 임계 추가 검토.

### 갭

- **face_abort_reset의 dwell time 미연계**: hysteresis로 abort_trigger가 안정적으로 흐르므로 face가 basic으로 reset되어도 매 입력마다 새 abort_trigger 들어옴. 그러나 BT가 funnel halt 후 다시 사이클 시작하면 새 face publish가 basic을 즉시 덮음. dwell time(예: abort 후 2초간 face publish 무시) 별도 트랙 필요.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **ReactiveFallback 로그 노이즈 정리**: 100ms마다 IDLE/FAILURE toggle 로그 폭발. 자체 logger 또는 toggle 필터.
- **face_avatar 애니메이션 v2**: 정적 1프레임 → Pillow 모든 프레임 + 30fps.
- **abort dwell time**: abort 후 일정 시간 face publish 무시.
- **min_confidence 임계**: 위 위험 §4.
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase.

### Phase 후속

- W2.5 (RPi): GEFA, decision_rule fusion. 이때 streak → 시간 기반 승격 검토.
- Phase 3: RPS 미니게임.

---

## 5. 산출물 위치

### 수정 파일
- `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/rapport_tracker_node.py` (hysteresis 상태 머신 + 파라미터 + 로그 강화)

### 신규 파일
- `docs/daily/2026-05-03_phase2_w4_rapport_hysteresis.md` (본 회고)

### 변경 없음
- emotion_monitor / tts_node / face_avatar — 모두 그대로. 메시지 인터페이스 동일.

### 다음 커밋
- W4 hysteresis + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_emotion --symlink-install
'
```

### 자체 검증 (GEVA 없이, 메커니즘 확인)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_emotion rapport_tracker > /tmp/rt.log 2>&1 &
sleep 2

# A. 단발 abort 조건 — abort 발동 안 됨
ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
  "{valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}"

# B. 5회 연속 — ENTER abort
for i in 1 2 3 4 5; do
  ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
    "{valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}"
  sleep 0.05
done

# C. 정상 5회 — LEAVE abort
for i in 1 2 3 4 5; do
  ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
    "{valence: 0.0, arousal: 0.0, confidence: 0.5, source: 'face', flags: []}"
  sleep 0.05
done

grep -E "event:|ENTER|LEAVE" /tmp/rt.log
```

### 라이브 통합 검증 (GEVA 켠 채로, 단발 outlier 흡수 확인)
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log

# 별도 터미널에서 단발 abort 시도 (GEVA가 흡수 → ENTER 안 됨)
ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
  "{valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}"

# 라이브에서 ENTER 보려면 GEVA 인터리브 이기는 rate
ros2 topic pub --rate 20 /emotion/state dobi_npc_msgs/msg/EmotionState \
  "{valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}"
# Ctrl+C로 중단 후 GEVA 정상 입력으로 LEAVE 관찰

grep -E "ENTER|LEAVE|abort_streak" /tmp/dobi.log
```

### 운영 시 hysteresis 임계 조정
```bash
# 빠른 반응 (불안정 환경)
ros2 launch dobi_npc_bringup dev_all.launch.py \
  -p rapport_tracker_node.abort_on_count:=3 \
  -p rapport_tracker_node.abort_off_count:=10

# 보수적 (false positive 최소화)
ros2 launch dobi_npc_bringup dev_all.launch.py \
  -p rapport_tracker_node.abort_on_count:=10 \
  -p rapport_tracker_node.abort_off_count:=5
```

---

**상태**: hysteresis 적용 완료. 단발 outlier 차단 입증. 다음은 ReactiveFallback 로그 노이즈 정리 / 애니메이션 v2 / dwell time / 자투리 또는 휴식.
