# 로컬 추론 서버 구축 가이드

ROS 환경에서 모델 추론단(`model_worker.py`)과 로봇 실행단(`serving.py`)을 분리해 비동기 RTC(Real-Time Chunking) 추론 시스템을 구축하는 방법을 설명한다. SmolVLA 기반으로 구현된 현재 시스템을 기준으로, 다른 모델로 이식하는 방법과 sync 문제를 디버깅하는 방법을 다룬다.

---

## 1. 시스템 아키텍처

### 1.1 왜 이 구조인가

| 방식 | 문제점 |
|------|--------|
| 요청 시 모델 로딩 | 1~2분 소요 → 실시간 사용 불가 |
| TCP + pickle 전송 | 이미지(1.84MB) 직렬화 오버헤드 + 가변 지연 |
| **Shared Memory + Unix Socket** | **zero-copy 이미지 전달, 소켓은 신호만 → 일정한 저지연** |

### 1.2 전체 구조

```
ROS 프로세스 (serving.py)                  모델 워커 (model_worker.py)
┌─────────────────────────────┐            ┌────────────────────────────────┐
│ SingleArmControllerNode     │            │ 시작 시 모델 로딩 (1회)         │
│                             │            │                                │
│  ModelProcess               │            │                                │
│  ├─ shm_obs 에 관찰값 씀    │──── shm ──▶│ shm_obs 에서 관찰값 읽기        │
│  │                          │            │ GPU 추론                        │
│  ├─ Unix socket 'G' 신호   │──── sock ──▶│ shm_act 에 결과(청크) 씀        │
│  │                          │            │                                │
│  └─ shm_act 에서 결과 읽기  │◀─── shm ───│ Unix socket 'D' 신호            │
│                             │◀─── sock ──│                                │
│  _inference_loop (thread)   │            └────────────────────────────────┘
│  _AsyncCamera × 2 (thread)  │
│  제어 루프 (30Hz)            │
└─────────────────────────────┘

오버헤드 (실측):
  이미지 memcpy  : ~0.2ms
  소켓 신호      : ~0.01ms
  GPU 추론       : ~310ms (SmolVLA 기준)
```

### 1.3 RTC(Real-Time Chunking) 제어 흐름

```
제어 루프 (30Hz)          인퍼런스 스레드
    │                          │
    │  action_queue 소비       │  queue.size <= threshold(30)
    │  ─────────────────────   │  ──────────────────────────
    │  queue 40개 → 30개 소모  │  ← 추론 트리거
    │                          │  관찰값 읽기 → GPU 추론 (~310ms)
    │  queue 30개 → 22개 소모  │  → chunk 50개 생성
    │                          │  → delay=9 제거 → 41개 queue에 추가
    │  새 chunk 도착: 22→41    │
    │  ...                     │  (다시 queue 41→30 소모 후 재추론)
```

---

## 2. 핵심 파일

```
single_arm_controller/
├── serving.py          # ROS Action Server + 제어 루프 + ModelProcess
├── model_worker.py     # 모델 로딩/추론 워커 (별도 venv에서 실행)
└── build_inference_local_server.md  # 이 문서
```

---

## 3. 핵심 파라미터 (serving.py)

```python
_CONTROL_HZ             = 30.0   # 목표 제어 주파수 (실제: ~30Hz, async 카메라 후)
_RTC_EXECUTION_HORIZON  = 15     # prev_chunk_left_over 정규화 길이 (lerobot 동일)
_RTC_QUEUE_THRESHOLD    = 30     # 큐가 이 값 이하일 때 다음 추론 트리거
_CHUNK_SIZE             = 50     # 모델이 반환하는 action chunk 크기
_ACTION_DIM             = 6      # 관절 수
_STATE_DIM              = 6      # state 차원
_INTERPOLATION_MULT     = 3      # 보간 배수 (제어 루프 내 sub-step 수)
```

**파라미터 결정 근거:**

| 파라미터 | 값 | 결정 근거 |
|---------|-----|----------|
| `_CHUNK_SIZE` | 50 | 모델이 실제 반환하는 chunk 크기 (`[queue-merge] chunk_in=50` 로그로 확인) |
| `_RTC_QUEUE_THRESHOLD` | 30 | lerobot 기본값과 동일 (새 chunk 도착 후 10 step 소비 → 재추론) |
| `_RTC_EXECUTION_HORIZON` | 15 | lerobot 로그 `prev_normalized_len=15`에서 확인 |
| `_INTERPOLATION_MULT` | 3 | lerobot 로그 `sub=1/3, 3/3`에서 확인 |

---

## 4. Shared Memory 레이아웃

`model_worker.py`와 `serving.py`의 상수가 **반드시 일치**해야 한다.

### shm_obs (관찰값 버퍼)

```
offset=0          offset=921600     offset=1843200
┌─────────────────┬─────────────────┬──────────────┐
│  top_image      │  wrist_image    │    state     │
│  480×640×3 u8   │  480×640×3 u8   │  6×float32   │
│  921,600 bytes  │  921,600 bytes  │  24 bytes    │
└─────────────────┴─────────────────┴──────────────┘
총 1,843,224 bytes
```

### shm_act (액션 버퍼)

```
┌────────────────────────────────────────────────────┐
│  plane 0: original actions  (50×6 float32)  raw    │  ← RTC prefix 계산용
│  plane 1: processed actions (50×6 float32)  denorm │  ← 로봇 실행용
└────────────────────────────────────────────────────┘
총 2×50×6×4 = 2,400 bytes
```

---

## 5. Unix Socket 프로토콜

### serving → worker (GO 명령)

```
b'G'
+ uint32 big-endian: task 문자열 길이
+ bytes:             task 문자열
+ uint32 big-endian: inference_delay (steps)
+ bool (1 byte):     has_prev_chunk
[ + uint32: prev_bytes 길이
  + bytes:  prev_chunk_left_over (float32 배열) ]
```

### worker → serving

| 바이트 | 의미 |
|--------|------|
| `b'R'` | 모델 로딩 완료 (Ready) |
| `b'D'` | 추론 완료 (Done) |
| `b'Q'` | 종료 요청 |

---

## 6. 비동기 카메라 (blocking 제거)

기존 `cap.read()` (blocking, ~33ms/카메라) → `_AsyncCamera.read_latest()` (non-blocking, ~0.01ms)

```python
class _AsyncCamera:
    def __init__(self, path, name):
        # 백그라운드 스레드가 cap.read() 루프 실행
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while not self._stop.is_set():
            ret, frame = self.cap.read()   # blocking은 여기서만
            if ret:
                with self._lock:
                    self._frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def read_latest(self, max_age_ms=1000.0):
        with self._lock:
            return self._frame.copy()      # 항상 즉시 반환
```

**효과:** 제어 루프 실제 주기 39ms(25Hz) → 33ms(30Hz) 근접

---

## 7. 실행 명령어

```bash
# 빌드
cd /home/jr/ws/physical-ai-repo-3/device/single_arm_controller
colcon build --packages-select single_arm_controller_interfaces single_arm_controller
source install/setup.bash

# 실행 (모델 워커 자동 시작)
ros2 run single_arm_controller serving 2>&1 | tee /tmp/serving_log.txt

# 다른 터미널: serve 요청
source /home/jr/ws/physical-ai-repo-3/device/single_arm_controller/install/setup.bash
ros2 action send_goal /serve single_arm_controller_interfaces/action/Serve \
  "{has_drink: true}" --feedback

# 취소
ros2 service call /serve/_action/cancel_goal action_msgs/srv/CancelGoal "{}"
```

### lerobot-rollout 비교 실행 (기준선)

```bash
cd /home/jr/ws/lerobot
lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/300000/pretrained_model \
  --inference.type=rtc \
  --inference.rtc.execution_horizon=15 \
  --interpolation_multiplier=3 \
  --action_ema_alpha=0.43 \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.cameras='{"top":{"type":"opencv","index_or_path":"/dev/video4","width":640,"height":480,"fps":30},"wrist":{"type":"opencv","index_or_path":"/dev/video2","width":640,"height":480,"fps":30}}' \
  --task="pick up cup and place at target zone" \
  --duration=9000 2>&1 | tee /tmp/rollout_log.txt
```

---

## 8. Sync 디버그 로그 시스템

serving.py와 lerobot-rollout 모두 동일한 `[태그]` 포맷으로 로그를 출력해 나란히 비교할 수 있다.

### 8.1 로그 태그 목록

| 태그 | 출력처 | 의미 |
|------|--------|------|
| `[infer-trigger #N]` | serving / lerobot rtc.py | 추론 시작 조건 판단 |
| `[infer-start #N]` | serving / lerobot rtc.py | 추론 직전 파라미터 |
| `[infer-done #N]` | serving / lerobot rtc.py | 추론 완료 + 큐 상태 |
| `[queue-merge]` | lerobot action_queue.py | 큐 교체 상세 |
| `[queue-delay-resolve]` | lerobot action_queue.py | delay 선택 로직 결과 |
| `[ctrl-step NNNN]` | serving / lerobot base.py | 30Hz 정책 action |
| `[ctrl-interp step=N sub=I/3]` | serving / lerobot | 보간 sub-step |
| `[ema]` | lerobot action_interpolator.py | EMA 적용 (lerobot만) |

### 8.2 추론 사이클 로그 읽는 법

```
[infer-trigger #3] qsize=30 threshold=30 p95=310ms delay_hint=9 prev_raw_len=30 prev_normalized_len=15
                   ^^^^^^^^                           ^^^^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                   큐가 30 이하로              이전 추론의       prev_chunk 길이
                   떨어져 트리거              P95 기반 delay 예측  (raw=30, 15로 정규화)

[infer-done #3] infer=308ms p95=310ms real_delay=9 consumed=9 delay_src=consumed actual_delay=9
                             ^^^^^^^^^^^^ ^^^^^^^^^^^ ^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^^
                             P95 업데이트   timing 기반   실제 소비    실제 소비값 사용
                             prev_raw_len=30 prev_normalized_len=15
                             q_before=22→q_after=41
                             chunk_first=[-2.61,-56.17,47.70,...,grip=48.56]
                             chunk_last=[0.98,-54.89,47.22,...,grip=47.51]
                             grip_minmax=46.9/48.0
                             grip_head=[47.1,46.9,...] grip_tail=[47.9,48.0,...]
```

**핵심 확인 항목:**

```bash
# 1. 추론 트리거 타이밍 비교 (threshold, qsize)
grep "\[infer-trigger" /tmp/serving_log.txt | head -5
grep "\[infer-trigger" /tmp/rollout_log.txt | head -5

# 2. 실제 delay 계산 (consumed vs latency)
grep "\[infer-done" /tmp/serving_log.txt | grep -o "delay_src=[^ ]* actual_delay=[^ ]*" | head -10

# 3. 제어 루프 실제 주기 측정
grep "ctrl-step" /tmp/serving_log.txt | head -20 | python3 -c "
import sys, re
times = []
for line in sys.stdin:
    m = re.search(r'\[(\d+)\.(\d+)\].*ctrl-step', line)
    if m:
        times.append(float(m.group(1)) + float(m.group(2))/1e9)
for i in range(1, len(times)):
    print(f'dt={( times[i]-times[i-1])*1000:.1f}ms')
"

# 4. chunk 경계에서 shoulder_lift 이동량 (멈춤 chunk 탐지)
grep "infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'infer-done #(\d+).*chunk_first=\[[^,]+,([^,]+).*chunk_last=\[[^,]+,([^,]+)', line)
    if m:
        f1, l1 = float(m.group(2)), float(m.group(3))
        diff = abs(l1-f1)
        flag = ' ← HOLD' if diff < 3 else ''
        print(f'chunk#{m.group(1)} diff={diff:.2f}{flag}')
"

# 5. 큐 소비 패턴 (새 chunk 도착 후 trigger까지 step 수)
grep "infer-trigger\|infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
prev_after = None
for line in sys.stdin:
    d = re.search(r'infer-done.*q_after=(\d+)', line)
    if d: prev_after = int(d.group(1))
    t = re.search(r'infer-trigger.*qsize=(\d+)', line)
    if t and prev_after:
        consumed = prev_after - int(t.group(1))
        print(f'chunk arrived q={prev_after} → trigger q={t.group(1)}: {consumed} steps consumed')
        prev_after = None
" | head -10

# 6. grip 패턴 분석 (oscillation 탐지)
grep "infer-done" /tmp/serving_log.txt | grep -o "grip_tail=\[[^]]*\]" | head -10
```

---

## 9. 발견된 Sync 문제와 해결책

이 시스템을 구축하면서 lerobot-rollout과 비교해 발견한 문제들과 해결책을 기록한다.

### 9.1 카메라 경로 불일치 → 행동이 완전히 다름

**증상:** serving.py 행동이 lerobot과 완전히 다름 (shoulder_pan 방향부터 다름)  
**원인:** top 카메라를 다른 `/dev/video*` 경로로 열고 있었음  
**진단:**
```bash
grep "Camera\|video\|top_cam" /tmp/serving_log.txt | head -5
grep "Camera\|video"          /tmp/rollout_log.txt | head -5
```
**해결:** `_TOP_CAM_PATH`, `_WRIST_CAM_PATH`를 lerobot 로그의 실제 경로와 일치시킴

---

### 9.2 p95 latency warmup 오염 → delay_hint 과대 계산

**증상:**
```
serving  [infer-done #2] p95=925ms delay_hint=28   ← 1회 warmup(925ms)이 고정됨
lerobot  [infer-done #2] p95=419ms delay_hint=13
```
**원인:** 첫 추론(warmup, ~900ms)이 `_latency_history`에 포함되어 p95가 영구적으로 925ms로 고정  
**해결:** 첫 추론 결과를 history에서 제외
```python
if infer_count[0] > 0:   # 두 번째 추론부터 기록
    _latency_history.append(infer_s)
```

---

### 9.3 CHUNK_SIZE 불일치 → 청크 잘림

**증상:**
```
serving  q_after=29  (chunk_stored=40)
lerobot  q_after=39  (chunk_in=50)
```
**원인:** `CHUNK_SIZE=40`으로 설정했지만 모델은 50개 반환 → 마지막 10개 유실  
**진단:** `q_after + actual_delay = chunk_stored` 확인
```bash
grep "infer-done" /tmp/serving_log.txt | awk '{match($0,/actual_delay=([0-9]+)/,a); match($0,/q_after=([0-9]+)/,b); print "chunk_stored="a[1]+b[1]}' | sort | uniq -c
```
**해결:** `CHUNK_SIZE = 50` (serving.py + model_worker.py 동시 수정)

---

### 9.4 prev_chunk_left_over 미정규화

**증상:**
```
serving  prev_normalized_len=NOT_NORMALIZED
lerobot  prev_normalized_len=15 (execution_horizon으로 정규화)
```
**원인:** lerobot은 `_normalize_prev_actions_length(prev, target=execution_horizon)` 적용  
**해결:**
```python
target = _RTC_EXECUTION_HORIZON   # 15
if n >= target:
    prev_left_over_norm = prev_left_over[:target].copy()
else:
    pad = np.zeros((target - n, _ACTION_DIM), dtype=np.float32)
    prev_left_over_norm = np.concatenate([prev_left_over, pad], axis=0)
```

---

### 9.5 그리퍼 오므렸다폈다 (place 후 oscillation)

**증상:** 물체를 놓은 뒤 그리퍼가 3~4회 열렸다닫혔다 반복  
**원인:**
```
chunk#13 grip tail: [51.0, 53.4, 55.3, 56.8]  ← 청크 끝에서 grip이 상승 (재파지 패턴)
chunk#14 head: [57.1, 58.6, 60.1, ...]         ← 모델이 "이전 계획=56이니 계속 닫자" → full close
chunk#15-25:   oscillation 3~4사이클
```
**원인 분석:**
```bash
grep "infer-done" /tmp/serving_log.txt | grep -o "grip_tail=\[[^]]*\]" | head -20
```
**해결:** prev_chunk의 grip 차원(index 5)만 EMA smoothing → rising tail 억제
```python
_grip_ema = float(prev_left_over_norm[0, 5])
for i in range(len(prev_left_over_norm)):
    _grip_ema = 0.43 * float(prev_left_over_norm[i, 5]) + 0.57 * _grip_ema
    prev_left_over_norm[i, 5] = _grip_ema
```

---

### 9.6 주기적 stop-start (이동 중 멈춤)

**증상:** pick→place 이동 중 ~660ms 주기로 멈춤-이동 반복  
**원인:**
```
chunk#13: shoulder_lift first=-10.54, last=-8.68, diff=1.86  ← HOLD chunk (40step 동안 1.86도!)
```
모든 관절에 EMA(α=0.43) 적용 시 chunk 경계마다 ramp-up 지연:
```
새 chunk 도착 → action jump
→ EMA(α=0.43) 댐핑: 새 값의 43%만 반영
→ 2~5 step(80~200ms): arm 거의 정지 = "멈춤"
→ EMA 수렴 후 정상 속도 = "이동"
→ 다음 chunk 경계(~660ms)에서 반복
```
**진단:**
```bash
# HOLD chunk 탐지
grep "infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'infer-done #(\d+).*chunk_first=\[[^,]+,([^,]+).*chunk_last=\[[^,]+,([^,]+)', line)
    if m:
        diff = abs(float(m.group(3)) - float(m.group(2)))
        if diff < 3.0:
            print(f'HOLD chunk#{m.group(1)} shoulder_lift diff={diff:.2f}')
"
```
**해결:** arm 관절(0-4)은 EMA 제거, grip(5)만 EMA 유지
```python
# 실행 EMA: gripper만
if ema_state is None:
    ema_state = action.copy()
else:
    ema_state[5] = _EMA_ALPHA * action[5] + (1.0 - _EMA_ALPHA) * ema_state[5]
action[5] = ema_state[5]

# prev_chunk EMA: gripper만
_grip_ema = float(prev_left_over_norm[0, 5])
for i in range(len(prev_left_over_norm)):
    _grip_ema = 0.43 * float(prev_left_over_norm[i, 5]) + 0.57 * _grip_ema
    prev_left_over_norm[i, 5] = _grip_ema
```

---

### 9.7 제어 루프 실제 주기 저하 (blocking camera)

**증상:**
```
목표: 33ms (30Hz)
실측: 39ms (25Hz)  ← blocking camera read 2개 × ~33ms = +66ms 오버헤드
```
**진단:**
```bash
grep "ctrl-step" /tmp/serving_log.txt | head -20 | python3 -c "
import sys, re
times = []
for line in sys.stdin:
    m = re.search(r'\[(\d+)\.(\d+)\].*ctrl-step', line)
    if m:
        times.append(float(m.group(1)) + float(m.group(2))/1e9)
for i in range(1, len(times)):
    print(f'dt={(times[i]-times[i-1])*1000:.1f}ms')
"
```
**해결:** `_AsyncCamera` — 백그라운드 스레드가 blocking read, control loop는 `read_latest()` 호출
```python
# 수정 전: ~33ms blocking
top_img = top_cam.read()       # cap.read() — blocks until next frame

# 수정 후: ~0.01ms
top_img = top_cam.read_latest()   # cached frame — instant
```

---

### 9.8 추론 트리거 주기 비교

| | lerobot | serving.py |
|--|---------|-----------|
| 새 chunk q | ~39 | ~41 |
| trigger q | 30 | 30 |
| trigger까지 소비 | 9 steps × 33ms = **297ms** | 10 steps × 33ms = **330ms** |

두 시스템 모두 새 chunk 도착 후 약 300~330ms 후 다음 추론을 시작한다.

---

## 10. 다른 모델로 이식하기

### 10.1 이식 체크리스트

**model_worker.py 교체/수정:**

- [ ] 모델 로딩 (`SmolVLAPolicy.from_pretrained` 교체)
- [ ] `preprocess`, `postprocess` 파이프라인 (없으면 제거)
- [ ] `predict_action_chunk` 호출부 (모델마다 API 다름)
- [ ] `CHUNK_SIZE`, `ACTION_DIM` 상수 — 모델 실제 출력에 맞게
- [ ] `obs_dict` 키 이름 — 모델이 기대하는 키로

**serving.py 수정:**

- [ ] `_LEROBOT_PY` → 해당 모델의 venv python 경로
- [ ] `_WORKER_SCRIPT` → 새 worker 스크립트 경로
- [ ] `_CHUNK_SIZE`, `_ACTION_DIM`, `_STATE_DIM`
- [ ] `_TOP_SHAPE`, `_WRIST_SHAPE` (카메라 해상도)
- [ ] `_RTC_EXECUTION_HORIZON` — 모델 학습 설정 확인
- [ ] `_RTC_QUEUE_THRESHOLD` — 기본값 30, 추론 속도에 맞게 조정
- [ ] `_INTERPOLATION_MULT` — 보간 배수

**확인 절차:**

```bash
# 1. CHUNK_SIZE 실측 — 모델 실제 출력 크기 확인
grep "infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'actual_delay=(\d+).*q_after=(\d+)', line)
    if m:
        print('chunk_stored=', int(m.group(1)) + int(m.group(2)))
        break
"

# 2. 실제 추론 시간 측정 → threshold 조정
grep "infer-done" /tmp/serving_log.txt | grep -o "infer=[0-9]*ms" | head -20

# 3. 실제 제어 주기 측정 → period 확인
# (9.7 절 스크립트 참고)
```

### 10.2 GR00T 적용 예시

```python
# gr00t_worker.py
from gr00t.policy.gr00t_policy import Gr00tPolicy
from gr00t.data.embodiment_tags import EmbodimentTag

CHUNK_SIZE = 16   # GR00T 출력 크기 확인 후 설정
ACTION_DIM = 6

policy = Gr00tPolicy(
    embodiment_tag=EmbodimentTag.resolve('new_embodiment'),
    model_path=args.model_path,
    device=args.device,
)

# 추론
obs = {
    'video': {'top': top[None], 'wrist': wrist[None]},
    'state': {'joint_pos': state},
    'language': {'task_description': task},
}
result = policy.get_action(obs)
chunk = result['joint_pos']   # (1, CHUNK_SIZE, ACTION_DIM)
```

```python
# serving.py 수정
_LEROBOT_PY    = '/home/jr/ws/Isaac-GR00T/.venv/bin/python'
_WORKER_SCRIPT = str(Path(__file__).parent / 'gr00t_worker.py')
_CHUNK_SIZE    = 16
_RTC_EXECUTION_HORIZON = 8  # GR00T 설정 확인
```

### 10.3 카메라 1개 + 관절 7개 모델

```python
# model_worker.py + serving.py 모두 동일하게 수정
TOP_SHAPE  = (480, 640, 3)
# WRIST 없음
STATE_DIM  = 7

TOP_BYTES   = int(np.prod(TOP_SHAPE))   # 921,600
STATE_BYTES = STATE_DIM * 4             # 28
OBS_BYTES   = TOP_BYTES + STATE_BYTES   # 921,628

# shm_obs 레이아웃
top_buf   = np.ndarray(TOP_SHAPE, dtype=np.uint8,   buffer=shm_obs.buf, offset=0)
state_buf = np.ndarray(STATE_DIM, dtype=np.float32, buffer=shm_obs.buf, offset=TOP_BYTES)
# wrist_buf 없음

# obs_dict 키도 wrist 제거
obs_dict = {
    'observation.images.top': top,
    'observation.state':      state,
}
```

### 10.4 RTC 미지원 모델 (단순 동기 추론)

청크 크기가 1이거나 RTC를 지원하지 않는 모델은 `prev_chunk_left_over`와 `inference_delay`를 넘기지 않는다.

```python
# model_worker.py 수정
with torch.no_grad():
    chunk = model.predict_action(obs)  # RTC API 없는 모델

# chunk를 (1, CHUNK_SIZE, ACTION_DIM)으로 맞추기
if chunk.dim() == 2:
    chunk = chunk.unsqueeze(0)
```

```python
# serving.py: inference_delay, prev_chunk_left_over 파라미터 제거
original_chunk, processed_chunk = self._model.get_action_chunk(
    top_image=obs['top'],
    wrist_image=obs['wrist'],
    state=obs['state'],
    task=task,
    robot_type=_ROBOT_TYPE,
    inference_delay=0,          # 항상 0
    prev_chunk_left_over=None,  # 항상 None
)
```

---

## 11. 관절 정규화 방식

모델을 학습한 프레임워크의 정규화 방식과 반드시 일치시켜야 한다.

| 모터 | lerobot 모드 | 범위 | 공식 (raw→norm) |
|------|-------------|------|----------------|
| shoulder_pan ~ wrist_roll (ID 11~15) | `RANGE_M100_100` | [-100, 100] | `(raw/4095)×200 - 100` |
| gripper (ID 16) | `RANGE_0_100` | [0, 100] | `(raw/4095)×100` |

```python
# serving.py 정규화 함수
def _raw_to_norm(raw):       return (raw / 4095) * 200.0 - 100.0
def _norm_to_raw(norm):      return int(((clamp(norm, -100, 100) + 100) / 200) * 4095)
def _raw_to_gripper_norm(r): return (r / 4095) * 100.0
def _gripper_norm_to_raw(n): return int((clamp(n, 0, 100) / 100) * 4095)
```

---

## 12. 전체 디버그 워크플로우

```bash
# Step 1: 두 시스템 동시 실행 + 로그 저장
ros2 run single_arm_controller serving 2>&1 | tee /tmp/serving_log.txt
lerobot-rollout ... 2>&1 | tee /tmp/rollout_log.txt

# Step 2: 핵심 지표 비교
for f in serving rollout; do
  echo "=== $f ==="
  grep "\[infer-done" /tmp/${f}_log.txt | \
    grep -o "infer=[^ ]* p95=[^ ]* actual_delay=[^ ]* q_before=[^ ]*→q_after=[^ ]*" | \
    head -5
done

# Step 3: chunk_stored 확인 (CHUNK_SIZE 문제)
grep "infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'actual_delay=(\d+).*q_after=(\d+)', line)
    if m: print('chunk_stored =', int(m.group(1))+int(m.group(2)))
" | sort | uniq -c

# Step 4: HOLD chunk 탐지 (stop-start 원인)
grep "infer-done" /tmp/serving_log.txt | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'#(\d+).*chunk_first=\[[^,]+,([^,]+).*chunk_last=\[[^,]+,([^,]+)', line)
    if m:
        diff = abs(float(m.group(3)) - float(m.group(2)))
        flag = ' ← HOLD' if diff < 3 else ''
        print(f'chunk#{m.group(1):>3} shoulder_diff={diff:>6.2f}{flag}')
"

# Step 5: grip oscillation 탐지 (chunk tail 분석)
grep "infer-done" /tmp/serving_log.txt | grep -o "grip_tail=\[[^]]*\]" | \
  python3 -c "
import sys, re
for line in sys.stdin:
    vals = list(map(float, re.findall(r'[\d.]+', line)))
    if vals and max(vals) - min(vals) > 3:
        print('RISING TAIL:', vals)
"

# Step 6: 제어 루프 주기 측정
grep "ctrl-step" /tmp/serving_log.txt | python3 -c "
import sys, re
times = []
for line in sys.stdin:
    m = re.search(r'\[(\d+)\.(\d+)\].*ctrl-step', line)
    if m:
        times.append(float(m.group(1)) + float(m.group(2))/1e9)
if len(times) > 10:
    dts = [(times[i]-times[i-1])*1000 for i in range(1,min(20,len(times)))]
    print(f'avg dt={sum(dts)/len(dts):.1f}ms  ({1000/sum(dts)*len(dts):.1f}Hz)')
"
```

---

## 13. 시스템 구성 요약

```
ros2 run single_arm_controller serving
│
├── SingleArmControllerNode.__init__()
│     └── ModelProcess()
│           ├── SharedMemory 생성 (shm_obs, shm_act)
│           ├── Unix socket 서버 열기
│           └── subprocess.Popen(python, model_worker.py)
│                 └── 모델 로딩 완료 → b'R' 전송
│
└── /serve action request 수신 → _do_serve()
      ├── _AsyncCamera × 2 시작 (백그라운드 캡처 스레드)
      ├── _OMXRobot 연결
      ├── _inference_loop 스레드 시작
      │     └── 루프:
      │           queue.size ≤ threshold(30)
      │           → prev_chunk 정규화 + grip EMA
      │           → shm_obs에 최신 obs 복사
      │           → Unix socket 'G' 전송 → 추론 대기 → 'D' 수신
      │           → actual_delay 계산 → 큐 교체
      └── 제어 루프 (30Hz):
            ├── top/wrist_cam.read_latest() [non-blocking]
            ├── robot.get_positions()
            ├── obs 업데이트 (inference thread 공유)
            ├── queue.popleft() → grip EMA → 3-step 보간 전송
            ├── 홈 포지션 감지 → VLM task 완료 판단
            └── cancel 시 초기 위치 복귀
```
