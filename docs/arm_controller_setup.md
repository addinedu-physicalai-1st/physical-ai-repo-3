# Single Arm Controller 설정 가이드

`act_serving.launch.py`로 실행되는 3개 노드의 환경 설정 방법을 설명합니다.

---

## 1. 가상환경(venv) 설치

`palm_direction_publisher` 노드는 MediaPipe와 edge-tts를 사용하기 위해 별도 가상환경이 필요합니다.

```bash
# 가상환경 생성
python3 -m venv ~/ws/physical-ai-repo-3/.venv

# 활성화
source ~/ws/physical-ai-repo-3/.venv/bin/activate

# 패키지 설치
pip install -r ~/ws/physical-ai-repo-3/requirements.txt

# 비활성화
deactivate
```

> **주의**: 가상환경은 ROS2 환경과 별개입니다. `colcon build` 및 `ros2 launch`는 가상환경 없이 시스템 Python으로 실행합니다.

---

## 2. MediaPipe 손 감지 모델 다운로드

`palm_direction_publisher`는 MediaPipe의 `HandLandmarker` 모델 파일(`.task`)이 필요합니다.

### 다운로드

```bash
# models 디렉토리 생성 (없는 경우)
mkdir -p ~/ws/physical-ai-repo-3/models

# 모델 다운로드
wget -O ~/ws/physical-ai-repo-3/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

또는 브라우저에서 직접 다운로드 후 `~/ws/physical-ai-repo-3/models/` 에 배치합니다.

### 다운로드 확인

```bash
ls -lh ~/ws/physical-ai-repo-3/models/hand_landmarker.task
# 예상 크기: ~29 MB
```

---

## 3. 경로 설정 (`act_serving_config.yaml`)

모든 경로는 `act_serving_config.yaml` 한 곳에서 관리합니다.

**파일 위치:**
```
src/controller/single_arm_controller/single_arm_controller/config/act_serving_config.yaml
```

### `env` 섹션

```yaml
env:
  venv_path:            /home/jr/ws/physical-ai-repo-3/.venv
  mediapipe_model_path: /home/jr/ws/physical-ai-repo-3/models/hand_landmarker.task
```

| 항목 | 설명 |
|------|------|
| `venv_path` | 위 1단계에서 생성한 가상환경 경로. `palm_direction_publisher`가 mediapipe/edge-tts 임포트 시 사용 |
| `mediapipe_model_path` | 위 2단계에서 다운로드한 `.task` 모델 파일 경로 |

### 카메라 설정

```yaml
cameras:
  top_path:   /dev/video2   # ACT 추론용 top 카메라
  wrist_path: /dev/video0   # ACT 추론용 wrist 카메라
  palm_index: 4             # 손 감지용 카메라 (OpenCV index)
```

> `palm_index`는 장치 인덱스(`int`)입니다. `ls /dev/video*` 로 확인 후 변경하세요.

---

## 4. 빌드 및 실행

```bash
cd ~/ws/physical-ai-repo-3/src/controller/single_arm_controller

# 빌드
colcon build --packages-select single_arm_controller_interfaces single_arm_controller

# 환경 소싱
source install/setup.bash

# 실행
ros2 launch single_arm_controller act_serving.launch.py
```

### 실행 확인

정상 실행 시 다음 로그가 출력됩니다:

```
[act_policy_server-1]       ... ACT policy server ready: /act_policy/infer
[act_serving_controller-2]  ... ACT serving action server ready (Pickup + Serve)
[palm_direction_publisher-3] ... 대기 중 | camera=4 dwell=1.5s trigger=/palm_detect_trigger → /palm_direction
[palm_direction_publisher-3] ... TTS 사전 합성 시작...
[palm_direction_publisher-3] ... TTS 사전 합성 완료 — 트리거 시 즉시 재생 가능
```

---

## 5. 테스트

```bash
# Pickup 실행
python3 src/controller/single_arm_controller/single_arm_controller/test/send_arm_goal.py pickup

# Serve (음료 없음 — 파란 마커)
python3 src/controller/single_arm_controller/single_arm_controller/test/send_arm_goal.py serve --no-drink

# Serve (음료 있음 — 손 방향 감지 대기)
python3 src/controller/single_arm_controller/single_arm_controller/test/send_arm_goal.py serve --has-drink
# → 별도 터미널에서 방향 수동 지정 (테스트용):
ros2 topic pub --once /palm_direction std_msgs/msg/String "data: 'right'"
```
