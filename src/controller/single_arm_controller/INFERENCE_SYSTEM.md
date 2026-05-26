# 로봇 추론 시스템 설계 가이드

SmolVLA 기반으로 구축된 추론 시스템의 설계 원리와, 다른 모델에 동일한 구조를 적용하는 방법을 설명한다.

---

## 1. 왜 이 구조인가

### 문제
- ROS action server에 request가 오면 그 때 모델을 로딩하면 1~2분이 걸려 사용 불가
- 별도 서버 프로세스를 만들어 미리 로딩해두면 → 네트워크 통신 지연 발생
- TCP + pickle로 이미지(1.84MB)를 주고받으면 직렬화/역직렬화 오버헤드 + 가변 지연

### 해결: Shared Memory + Unix Socket 시그널링
```
ROS 프로세스 (serving.py)         모델 워커 프로세스 (model_worker.py)
┌──────────────────────────┐      ┌──────────────────────────────────┐
│                          │      │ 노드 시작 시 모델 로딩 (1회)      │
│ ModelProcess             │      │                                  │
│  shm_obs에 이미지 씀     │─shm─▶│ shm_obs에서 이미지 읽기          │
│                          │      │ GPU 추론                         │
│  Unix socket 'GO' 신호  │─sock▶│ shm_act에 결과 씀                │
│                          │      │                                  │
│  shm_act에서 결과 읽기  │◀─shm─│ Unix socket 'DONE' 신호          │
└──────────────────────────┘◀sock─└──────────────────────────────────┘

오버헤드:
  이미지 memcpy  : ~0.2ms (일정)
  소켓 시그널    : ~0.01ms
  GPU 추론       : ~330ms (모델에 따라 다름)
  합계           : TCP+pickle 대비 ~10-25배 빠름
```

---

## 2. 핵심 파일 구조

```
single_arm_controller/
├── serving.py          # ROS Action Server + ModelProcess 클래스
├── model_worker.py     # 모델 워커 (lerobot venv에서 실행)
├── smolvla_server.py   # (구버전) TCP 기반 서버 - 참고용
└── smolvla_client.py   # (구버전) TCP 기반 클라이언트 - 참고용
```

---

## 3. 구현 구조 상세

### 3.1 Shared Memory 레이아웃

```
shm_obs (관찰값 버퍼):
┌────────────────┬────────────────┬──────────────┐
│  top_image     │  wrist_image   │    state     │
│  480×640×3     │  480×640×3     │  6×float32   │
│  uint8         │  uint8         │              │
│  921,600 bytes │  921,600 bytes │  24 bytes    │
└────────────────┴────────────────┴──────────────┘
offset: 0        921600           1843200

shm_act (액션 버퍼):
┌────────────────────────────────┐
│  action_chunk                  │
│  50 × 6 × float32              │
│  1,200 bytes                   │
└────────────────────────────────┘
```

### 3.2 통신 프로토콜 (Unix Domain Socket)

```
serving.py → worker:
  b'G' + 4바이트(task 길이, big-endian) + task 문자열
  (이미지/관절은 이미 shared memory에 있음)

  b'Q'  → 워커 종료

worker → serving.py:
  b'R'  → 모델 로딩 완료 (Ready)
  b'D'  → 추론 완료 (Done)
```

### 3.3 제어 루프의 추론 지연 보정 (delay_skip)

추론(~330ms) 동안 로봇이 이미 10스텝 움직였으므로, 다음 청크를 실행할 때
이미 지나간 스텝을 skip해 역방향 진동을 방지한다.

```python
# 추론 시간 측정
infer_total_s = time.time() - t_infer_start
delay_skip = round(infer_total_s / period)  # period = 1/30Hz = 33ms

# 다음 청크에서 skip 적용
exec_slice = chunk[delay_skip : delay_skip + EXECUTION_HORIZON]
```

---

## 4. 다른 모델 적용 방법

### 4.1 체크리스트

새 모델을 적용할 때 수정해야 하는 항목:

**model_worker.py 수정:**
- [ ] 모델 import 경로
- [ ] 모델 로딩 코드 (`SmolVLAPolicy.from_pretrained` 부분)
- [ ] `preprocess`, `postprocess` (없으면 제거)
- [ ] `predict_action_chunk` 호출부 (모델마다 API 다름)
- [ ] `CHUNK_SIZE`, `ACTION_DIM` 상수

**serving.py 수정:**
- [ ] `_LEROBOT_PY` → 해당 모델의 venv python 경로
- [ ] `_WORKER_SCRIPT` → 새 worker 스크립트 경로
- [ ] `_CHUNK_SIZE`, `_ACTION_DIM`, `_STATE_DIM` 상수
- [ ] `_TOP_SHAPE`, `_WRIST_SHAPE` (카메라 해상도)
- [ ] shared memory 크기 재계산 (`_OBS_BYTES`, `_ACT_BYTES`)

### 4.2 GR00T 모델 적용 예시

GR00T는 lerobot이 아닌 Isaac-GR00T 패키지를 사용한다.

**gr00t_worker.py (새로 작성):**
```python
# 모델 로딩 부분만 교체
from gr00t.policy.gr00t_policy import Gr00tPolicy
from gr00t.data.embodiment_tags import EmbodimentTag

policy = Gr00tPolicy(
    embodiment_tag=EmbodimentTag.resolve('new_embodiment'),
    model_path=args.model_path,
    device=args.device,
    strict=False,
)

# 추론 부분: GR00T는 observation dict를 직접 받음
obs = {
    'video': {'top': top, 'wrist': wrist},
    'state': {'single_arm': state[:5], 'gripper': state[5:6]},
    'language': {'annotation.human.task_description': task},
}
# GR00T는 action chunk가 아닌 단일 action 반환
action_chunk, _ = policy.get_action(add_batch_time(obs))
```

**shared memory 레이아웃은 동일하게 유지** — 관찰값(이미지+관절)과 결과(액션 청크) 형태가 같으면 serving.py를 거의 수정하지 않아도 된다.

**serving.py에서 변경:**
```python
_LEROBOT_PY    = '/home/jr/ws/Isaac-GR00T/.venv/bin/python'
_WORKER_SCRIPT = str(Path(__file__).parent / 'gr00t_worker.py')
_CHUNK_SIZE    = 1   # GR00T는 단일 action 반환
_ACTION_DIM    = 6
```

### 4.3 lerobot ACT/π0 등 다른 정책 적용 예시

lerobot 기반 모델들은 model_worker.py에서 모델 로딩 부분만 교체하면 된다.

```python
# SmolVLA → ACT 교체 예시
# 변경 전
from lerobot.policies.smolvla import SmolVLAPolicy
model = SmolVLAPolicy.from_pretrained(model_path)

# 변경 후
from lerobot.policies.act import ACTPolicy
model = ACTPolicy.from_pretrained(model_path)

# predict_action_chunk API는 동일
chunk = model.predict_action_chunk(obs)
```

### 4.4 관찰값 형태가 다른 경우

카메라 수, 해상도, 관절 수가 다르면 shared memory 레이아웃을 바꿔야 한다.

**예: 카메라 1개 + 관절 7개 모델**

```python
# model_worker.py와 serving.py 모두 동일하게 수정

TOP_SHAPE   = (480, 640, 3)
# WRIST_SHAPE 제거
STATE_DIM   = 7

TOP_BYTES   = int(np.prod(TOP_SHAPE))   # 921,600
STATE_BYTES = STATE_DIM * 4             # 28
OBS_BYTES   = TOP_BYTES + STATE_BYTES   # 921,628

# shm_obs 레이아웃
top_buf   = np.ndarray(TOP_SHAPE, dtype=np.uint8,   buffer=shm_obs.buf, offset=0)
state_buf = np.ndarray(STATE_DIM, dtype=np.float32, buffer=shm_obs.buf, offset=TOP_BYTES)
# wrist 없음
```

---

## 5. 관절 정규화 방식 (OMX 기준)

모델을 학습한 프레임워크의 정규화 방식을 반드시 맞춰야 한다.

| 모터 | lerobot 모드 | 범위 | 공식 (raw→norm) |
|------|-------------|------|----------------|
| shoulder_pan ~ wrist_roll (ID 11~15) | `RANGE_M100_100` | [-100, 100] | `(raw/4095)*200 - 100` |
| gripper (ID 16) | `RANGE_0_100` | [0, 100] | `(raw/4095)*100` |

GR00T 등 다른 프레임워크를 쓴다면 해당 프레임워크의 정규화 방식을 확인할 것.

---

## 6. 실행 명령어

```bash
# 1. 빌드
cd /home/jr/ws/physical-ai-repo-3/device/single_arm_controller
colcon build --packages-select single_arm_controller_interfaces single_arm_controller
source install/setup.bash

# 2. ROS 노드 실행 (모델 워커 자동 시작 + 로딩)
ros2 run single_arm_controller serving

# 3. serve 요청 (다른 터미널)
source install/setup.bash
ros2 action send_goal /serve single_arm_controller_interfaces/action/Serve {} --feedback

# 카메라/task 지정
ros2 action send_goal /serve single_arm_controller_interfaces/action/Serve \
  "{wrist_cam_path: '/dev/video4', task: 'pick up the red cup'}" --feedback

# 취소
ros2 service call /serve/_action/cancel_goal action_msgs/srv/CancelGoal "{}"
```

---

## 7. 디버깅 / 문제 해결

### 모델 워커가 시작 안 될 때
```bash
# 워커 스크립트를 직접 실행해서 에러 확인
/home/jr/ws/lerobot/.venv/bin/python \
  src/single_arm_controller/single_arm_controller/model_worker.py \
  --model-path /home/jr/ws/lerobot/outputs/300000/pretrained_model \
  --socket-path /tmp/test.sock \
  --shm-obs-name test_obs \
  --shm-act-name test_act
```

### 로봇이 역방향으로 진동할 때
`delay_skip` 로그를 확인한다:
```
infer=334ms → next_skip=10   ← 정상: 추론시간/제어주기 = 10스텝 skip
infer=600ms → next_skip=18   ← 추론이 느려짐, skip이 커서 청크 끝에 가까워짐
```
`_EXECUTION_HORIZON`을 늘리거나 청크 크기(`CHUNK_SIZE`)를 늘린다.

### 그리퍼가 항상 열려있을 때
lerobot OMX follower의 그리퍼는 `RANGE_0_100` ([0,100]) 모드다.
나머지 관절의 `RANGE_M100_100` ([-100,100])과 혼동하지 말 것.
`serving.py`의 `_gripper_norm_to_raw` / `_raw_to_gripper_norm` 함수가 올바른지 확인.

---

## 8. 시스템 구성 요약

```
ros2 run single_arm_controller serving
│
├── SingleArmControllerNode.__init__()
│     └── ModelProcess()
│           ├── SharedMemory 생성 (shm_obs, shm_act)
│           ├── Unix socket 서버 열기
│           └── subprocess.Popen(lerobot_python, model_worker.py)
│                 └── 모델 로딩 완료 → 'R' 신호 전송
│
└── /serve action request 수신
      └── _do_serve()
            ├── 카메라 + 로봇 연결
            ├── 첫 청크 추론 요청
            └── 제어 루프 (30Hz)
                  ├── 관찰값 → shared memory 쓰기
                  ├── 'G' + task → Unix socket 전송
                  ├── 이전 청크 실행 (delay_skip 적용)
                  ├── 'D' 수신 → 다음 청크 읽기
                  └── cancel 시 초기 위치 복귀 (3초, 선형 보간)
```
