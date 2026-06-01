# single_arm_controller 설치 가이드

## 1. Python 의존성 설치

### 1-1. ROS2 노드용 패키지 (`requirements.txt`)

ROS2 환경에서 실행되는 노드(`serving`, `waiter` 등)에 필요한 패키지입니다.

```bash
pip install -r requirements.txt
```

### 1-2. palm_direction_publisher 전용 가상환경 (`requirements-palm.txt`)

`palm_direction_publisher` 노드는 MediaPipe와 TTS 라이브러리를 별도 venv에서 사용합니다.

```bash
# 가상환경 생성 (처음 한 번만)
python3 -m venv ~/ws/physical-ai-repo-3/.venv

# 가상환경 활성화
source ~/ws/physical-ai-repo-3/.venv/bin/activate

# 의존성 설치
pip install -r requirements-palm.txt

# 가상환경 비활성화
deactivate
```

---

## 2. MediaPipe HandLandmarker 모델 다운로드

`palm_direction_publisher.py`는 MediaPipe의 **HandLandmarker** Task API를 사용합니다.  
모델 파일(`hand_landmarker.task`)을 아래 경로에 다운로드해야 합니다.

**저장 경로:** `~/ws/physical-ai-repo-3/models/hand_landmarker.task`

### 방법 A — wget

```bash
mkdir -p ~/ws/physical-ai-repo-3/models
wget -O ~/ws/physical-ai-repo-3/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

### 방법 B — curl

```bash
mkdir -p ~/ws/physical-ai-repo-3/models
curl -L -o ~/ws/physical-ai-repo-3/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

다운로드 후 파일이 존재하는지 확인합니다.

```bash
ls -lh ~/ws/physical-ai-repo-3/models/hand_landmarker.task
```

> **참고:** 모델 경로는 `config/smolvla_serving_config.yaml` 또는 `config/act_serving_config.yaml`의  
> `env.mediapipe_model_path` 항목에서 변경할 수 있습니다.

---

## 3. 시스템 의존성 (선택)

TTS 폴백으로 `espeak-ng`를 사용하고, 음성 재생에 `ffplay`가 필요합니다.

```bash
sudo apt install espeak-ng ffmpeg
```
