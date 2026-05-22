# 로봇 행동 문제 디버깅 기록

## 목표
`ros2 run single_arm_controller serving`으로 실행했을 때 `lerobot-rollout`과 동일한 수준의 로봇 행동 달성.

## 비교 기준: lerobot-rollout 명령어

```bash
cd /home/jr/ws/lerobot
lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/300000/pretrained_model \
  --inference.type=rtc \
  --inference.rtc.execution_horizon=11 \
  --interpolation_multiplier=5 \
  --action_ema_alpha=0.43 \
  --compile_warmup_inferences=3 \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.cameras='{"top":{"type":"intelrealsense","serial_number_or_name":"943222071539","width":640,"height":480,"fps":30},"wrist":{"type":"opencv","index_or_path":"/dev/video6","width":640,"height":480,"fps":30}}' \
  --task="pick up cup and place at target zone" \
  --duration=9000
```

lerobot-rollout은 정상 동작 확인됨.

---

## 시스템 아키텍처

```
SingleArmControllerNode (serving.py)
  └── ModelProcess (serving.py 내부)
        ├── SharedMemory(shm_obs): top_img + wrist_img + state
        ├── SharedMemory(shm_act): action_chunk
        └── Unix Socket: 시그널(GO/DONE)만 전달
              ↕
        model_worker.py (lerobot venv에서 실행)
              └── SmolVLAPolicy.from_pretrained()
```

**파일 위치**: `single_arm_controller/src/single_arm_controller/single_arm_controller/`
- `serving.py`: ROS Action Server + 제어 루프
- `model_worker.py`: 모델 로딩 및 추론 워커

---

## 모델 정보

- 경로: `/home/jr/ws/lerobot/outputs/300000/pretrained_model`
- 타입: SmolVLA (VLM 기반 정책)
- **`rtc_config: None`** ← 중요: RTC 모드로 학습되지 않음
  - `inference_delay`, `prev_chunk_left_over` 파라미터를 모델이 **무시**함
  - lerobot-rollout의 RTC 효과를 내려면 외부에서 처리해야 함

---

## 발견된 문제들과 시도한 해결책

### 문제 1: 이전 행동 반복 (역방향 진동)

**증상**: 로봇이 앞으로 갔다가 이전 위치로 돌아가는 진동 반복.

**원인 분석 과정**:
- 로그로 확인: `chunk_size=50 skip=40 exec=[40:50]` → 이전에는 청크 전체를 실행해서 청크 후반부(복귀 모션)가 포함됨
- `delay_skip=35` 같은 큰 값이 나오면 큐 교체 시 청크 뒷부분을 실행

**시도 1: delay_skip 제거 (chunk[0]부터 실행)**
- 결과: 이전보다 개선됐으나 여전히 느린 진행 + 일부 진동
- 이유: chunk[0]은 265ms 전 관찰 위치 기준 → 로봇이 이미 8~9스텝 앞에 있음

**시도 2: execution_horizon=11로 청크 앞부분만 사용**
- `chunk[skip : skip+11]`만 실행 → 청크 후반 복귀 모션 회피
- 결과: 후반 복귀 모션 제거됨

**시도 3: lerobot RTC 구조 재현**
- 인퍼런스 스레드 / 제어 루프 분리 (현재 구조)
- 큐 threshold 기반 재추론
- P95 latency tracker
- `prev_chunk_left_over` + `inference_delay` → 모델이 무시함(rtc_config=None)

---

### 문제 2: queue EMPTY로 인한 로봇 정지 (leap/끊김)

**증상**: 주기적으로 로봇이 멈췄다가 갑자기 움직이는 현상.

**원인**: `_INFER_QUEUE_THRESHOLD=3`에서 추론 시간(265ms=9스텝) > 큐 잔여(3스텝) → 큐 고갈.

**해결**: threshold를 인퍼런스 시간보다 크게 설정.

```
horizon=15, threshold=10:
- Queue=15 → 5스텝 후 queue=10 → 추론 시작
- 추론 9스텝 → queue=1 → 새 청크 도착
- 큐 고갈 없음
```

---

### 문제 3: 추론 폭주 (threshold=10 → 큐 2중 교체)

**증상**: 인퍼런스 #7, #8이 연달아 완료되어 큐가 두 번 교체됨 → 심한 진동.

**원인**: `threshold=_EXECUTION_HORIZON-1=10`으로 설정하면 새 청크 도착 후 1스텝만에 다음 추론 시작 → 연속 추론.

**현재 해결**: `threshold=horizon=15` (새 청크 도착 즉시 추론 시작, 자연스러운 1 inference/cycle 유지).

---

### 문제 4: delay_skip이 역방향 유발

**증상**: delay_skip=9로 chunk[9]부터 실행하면 청크 전환 시 `diff=[-18, ...]` 같은 큰 역방향 점프.

**원인**: `chunk[9]`는 "chunk[0]부터 자연스럽게 9스텝 후" 위치를 예측. 하지만 로봇은 이전 청크를 따라 9스텝 움직였음 → 두 경로가 일치하지 않으면 점프.

**lerobot에서는 왜 작동하는가**:
- `rtc_config`가 있는 모델은 `inference_delay`를 받아 내부적으로 "9스텝 후" 위치를 조정한 청크 생성
- `rtc_config=None`인 우리 모델은 이를 무시 → delay_skip이 부정확

**현재 상태**: `threshold=horizon=15`로 설정하면 관찰 지연 = 추론 시간만(265ms), delay_skip이 더 정확해짐.

---

### 문제 5: 모델에 task를 잘못 전달 (발견된 버그)

**증상**: 컵 앞에 도달해도 그냥 지나쳐 계속 전진.

**원인**: `model_worker.py`에서 task를 문자열로 전달.

```python
# 잘못된 방식 (model_worker.py 이전 코드)
obs = prepare_observation_for_inference(obs_dict, device, task, robot_type)
# task가 문자열로 설정됨

# lerobot RTCInferenceEngine 실제 코드
obs_batch["task"] = [self._task]  # ← 리스트로 오버라이드
```

**수정**: model_worker.py에 `obs['task'] = [task]` 추가.

---

### 문제 6: 느린 진행 + 이전 행동 반복 (관찰 타이밍 지연)

**증상**: 컵 방향으로 매우 조금씩 전진하며 새로운 행동이 너무 적게 실행됨.

**원인 분석** (사용자 진단이 정확):
```
threshold=10, horizon=15:
- 새 청크 도착 → 5스텝(165ms) 실행 → queue=10 → 추론 시작
- 추론 9스텝(265ms) 실행 → 총 관찰→실행 지연 = 430ms
- chunk[0]은 430ms 전 위치용 → 로봇이 뒤로 가야 하는 악순환
```

**현재 적용된 수정**:
```
threshold=15 (=horizon):
- 새 청크 도착(queue=15) → 즉시 추론 시작 (0ms 추가 지연)
- 추론 시간 265ms 동안 queue: 15→6
- 관찰→실행 지연 = 265ms만
- delay_skip = round(265/33) = 8 → chunk[8]이 실제 로봇 위치에 일치
```

---

## 현재 코드 상태 (미해결)

### serving.py 핵심 파라미터

```python
_EXECUTION_HORIZON_CTRL = 15   # lerobot execution_horizon과 유사
_INFER_QUEUE_THRESHOLD  = 15   # = horizon: 새 청크 즉시 추론
_INTERPOLATION_MULT     = 5    # lerobot --interpolation_multiplier=5
_SUB_PERIOD             = period / 5  # 6.67ms (150Hz 보간)

# delay_skip: round(infer_time / period) ≈ 8
actual_delay = round(infer_s / period)
sliced = chunk[actual_delay : actual_delay + _EXECUTION_HORIZON_CTRL]
```

### model_worker.py 핵심 수정

```python
obs = prepare_observation_for_inference(obs_dict, device, task, robot_type)
obs['task'] = [task]  # ← 리스트로 오버라이드 (lerobot과 동일)
obs = preprocess(obs)
chunk = model.predict_action_chunk(
    obs,
    inference_delay=inference_delay,    # 모델이 무시 (rtc_config=None)
    prev_chunk_left_over=prev_chunk_left_over,  # 모델이 무시
)
```

### 제어 루프 구조

```
[인퍼런스 스레드] (연속 실행)
  queue <= threshold(15) → 즉시 추론
  새 observation 읽기 → 추론(265ms) → chunk[delay:delay+15] → 큐 교체

[제어 루프 30Hz]
  observation 업데이트 → queue에서 pop → 150Hz 보간 전송
```

---

## 남은 문제

1. **여전히 진동이 있음**: lerobot-rollout과 비교했을 때 행동이 덜 부드럽고 일부 역방향 운동이 관찰됨.

2. **근본 원인 (미해결)**:
   - `rtc_config=None` 모델이 `prev_chunk_left_over`를 무시 → 청크 간 연속성 없음
   - 각 청크가 독립적으로 생성되어 연속성이 없음

3. **lerobot-rollout에서 작동하는 이유**:
   - `--action_ema_alpha=0.43`: 액션에 EMA 적용 → 급격한 변화 흡수
   - `--interpolation_multiplier=5`: 이미 구현됨 ✓
   - `rtc_config`가 있는 모델이라면 `prev_chunk_left_over`로 부드러운 연속 청크 생성

---

## 다음 세션에서 시도해볼 것

### 우선순위 높음

**A. action EMA 적용** (`--action_ema_alpha=0.43`)
```python
# serving.py 제어 루프에 추가
_ACTION_EMA_ALPHA = 0.43
ema_action = None

if action is not None:
    if ema_action is None:
        ema_action = action.copy()
    else:
        ema_action = _ACTION_EMA_ALPHA * action + (1 - _ACTION_EMA_ALPHA) * ema_action
    # robot.set_positions(ema_action)로 변경
```
- 이전에 구현했다가 사용자가 "일단 빼달라"고 요청하여 제거됨
- lerobot-rollout에서 필수 파라미터 → 다시 시도 필요

**B. RTC 모델로 재학습 또는 교체**
- `rtc_config`가 있는 모델이면 `prev_chunk_left_over`와 `inference_delay`가 실제 효과를 냄
- lerobot 학습 시 `--inference.type=rtc` 옵션 사용

### 우선순위 중간

**C. threshold/horizon 추가 튜닝**
- threshold=15가 너무 공격적일 수 있음 (연속 추론으로 CPU 과부하 가능)
- threshold=12~14 범위 실험

**D. 관찰 업데이트를 인퍼런스 직전에 수행**
- 현재: 제어 루프에서 33ms마다 obs 업데이트 → 인퍼런스 스레드가 사용
- 개선안: 인퍼런스 스레드에서 직접 카메라/로봇 읽기 (더 fresh한 obs)
- 단점: 카메라 접근이 멀티스레드로 복잡해짐

### 우선순위 낮음

**E. torch.compile 사용 (추론 속도 향상)**
- `--use_torch_compile=True`와 유사하게 model_worker.py에서 `torch.compile(model)` 적용
- 추론 265ms → ~150ms로 단축 시 delay_skip도 줄어들어 정확도 향상

---

## 디버깅 팁

```bash
# 로그에서 확인할 내용
# 1. 큐 고갈 여부
grep "queue EMPTY" 로그

# 2. 추론 속도
grep "\[infer" 로그 | head -20

# 3. 청크 경계에서의 점프
grep "\[ctrl\]" 로그 | awk -F'diff=' '{print $2}' | head -30

# 4. 관찰→실행 지연 (이전 버전의 로그 형식)
grep "obs→exec_delay" 로그
```

---

## 관련 파일

- `serving.py`: `/home/jr/ws/physical-ai-repo-3/device/single_arm_controller/src/single_arm_controller/single_arm_controller/serving.py`
- `model_worker.py`: `같은 디렉토리/model_worker.py`
- `INFERENCE_SYSTEM.md`: 전체 아키텍처 설명 (시스템 이해 문서)
- 데이터셋: `/home/jr/ws/lerobot/datasets/serving_b` (총 160 에피소드)
- lerobot 모델: `/home/jr/ws/lerobot/outputs/300000/pretrained_model`
