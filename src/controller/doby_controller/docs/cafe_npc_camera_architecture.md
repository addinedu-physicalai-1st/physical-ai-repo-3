# 카페 NPC 비전 아키텍처 — 카메라 역할·토폴로지 명세서

> **목적**: 카메라 1·2·3의 용도가 시간이 지나도 혼동되지 않도록 명세를 잠근다.
> 이 문서가 모든 카메라 관련 의사결정의 단일 진실 원본(single source of truth).

**확정일**: 2026-05-01 (2026-05-05 카메라 3 추가, 2026-05-06 카메라 2/3 모델 스왑 확정)
**확정자**: 공국진 (Stephen)
**적용 범위**: Phase 1 ~ Phase 4 (천장 카메라 도입 평가는 Phase 4 이후)

---

## 0. 한 줄 원칙

> **카메라 1 = "마주한 손님 얼굴". 카메라 2 = "둘러본 환경". 카메라 3 = "마주한 손님 손".**
> 표정·시선은 1만, 위치·자세·사물은 2만, 손은 3만. **겹치지 않음.**

---

## 1. 시스템 토폴로지

모든 비전·컴퓨팅·디스플레이가 **vic_pinky 자체에 탑재**된다 — 외부 인프라 의존 0.

```
vic_pinky 본체 (192.168.0.138, 계정 vic, ROS_DOMAIN_ID=22)
│
├── 라즈베리파이 5 (센서/모션 허브)
│   ├── USB 2.0 포트 (Bus 4-1) ← [카메라 2] HCAM01N (Microdia, USB 외장)
│   ├── RPLiDAR (Nav2/AMCL 입력)
│   └── ZLAC 모터 드라이버
│   (※ vicpinky는 PinkyPro와 달리 LCD 없음 — 얼굴 표현은 노트북 풀스크린 전담)
│
└── 상단 거치 노트북 MSI Bravo 17 D7VF (AI 컴퓨팅 허브 + 디스플레이, ROS_DOMAIN_ID=22 동일)
    ├── [카메라 1] 내장 "HD Webcam" /dev/video0 (Bison 5986:211b, 1280×720 MJPEG @ 30fps)
    ├── [카메라 3] 외장 RPC-20F "RF20" /dev/video2 (Sunplus SNAP U2 1bcf:2281, autofocus + 1080p)
    ├── 풀스크린 얼굴 표현 (vicpinky_emotion/emotion/*.gif 8어휘 재활용)
    ├── 페르소나 아바타 + 미니게임 UI
    └── ROS2 노드: 감정 인식, 대화, BT 실행, face_avatar GUI, minigame_runner
```

→ 세 카메라는 **호스트가 분리**되어 있고 (카메라 1·3 노트북, 카메라 2 RPi), 같은 호스트 내 1·3 도 v4l2 디바이스가 별개 → 동시 점유 안전. ROS2 DDS가 토픽을 자동 분배.

---

## 2. 카메라 1 — 노트북 내장 웹캠 (MSI Bravo 17 D7VF "HD Webcam")

### 2.1 하드웨어
| 항목 | 값 |
|---|---|
| 노트북 | **MSI Bravo 17 D7VF** (Micro-Star International) |
| 카메라 | "HD Webcam" (`/dev/video0`, USB 내부 버스 `usb-0000:06:00.0-1`) |
| **칩셋/벤더** | **Bison Electronics, USB ID `5986:211b`** (MSI 노트북 표준 모듈, UVC 표준 동작) |
| 호스트 | vic_pinky 상단 거치 노트북 |
| 마운트 위치 | 손님 시선 높이 (~120cm 권장) |
| 향한 방향 | **interaction-facing** (정면, 손님을 마주봄) |
| 페이로드 | 노트북 ~2.6kg + 거치대 → vic_pinky 적재 한계 검증 필요 |
| 전력 | 풀로드 ~150W → 자체 배터리 1~2시간, 로봇 전원 분기 또는 외부 배터리 필요 |

### 2.2 영상 스펙 (v4l2-ctl 실측, 2026-05-01)
| 항목 | 값 |
|---|---|
| **최고 해상도** | **1280×720 @ 30fps (MJPEG)** |
| 보조 | 640×480, 640×360, 320×240 모두 30fps |
| YUYV 모드 | 720p에서 10fps만 (USB 2.0 대역폭 한계) → 처리용 부적합 |
| 1080p | **미지원** (Full HD 아님, HD only) |
| **포커스** | **고정초점 (No AF)** — `focus_*` 컨트롤 없음 확인. 거치 후 헌팅 0. 고정초점은 ~50cm 사전조정 가정 (GEVA 0.5~1.5m와 일치) |
| 자동 화이트밸런스 | ON (Phase 2 시 일관성 위해 LOCK 검토) |
| 자동 노출 (동적 fps) | ON → **30fps 일관성 위해 OFF 권장** (BT 루프 안정성) |
| 전원선 주파수 | 60Hz (한국 환경 정확) |
| Pan/Tilt/Zoom | 없음 (정적 고정 모듈) |
| 픽셀 포맷 권장 | **MJPEG** (대역폭 효율, ROS2 v4l2_camera_node 표준) |

### 2.3 인지 명세
| 항목 | 값 |
|---|---|
| 거리 범위 | **0.5 ~ 1.5m** |
| 대상 수 | **1명** (정밀 분석) |
| 추출 정보 | 얼굴 표정 7감정, 시선, Russell V·A 좌표 |
| 학술 채널 | **Salichs 2014 GEVA** (Gesture/Expression — Verbal/Arousal 근거리) |
| 활성 조건 | 손님 0.5~1.5m 검출 시. 그 외 idle (`confidence: 0.0`) |

### 2.4 GEVA 적합성 판정
- ✅ 합격: 1m 거리 얼굴 ~300×300px → MediaPipe Face Mesh / FER 안정 동작
- ✅ 30fps → 감정 인식 워크로드(10~15fps 사용) 충분
- ⚠ Phase 4 시연 단계에서 표정 정밀도 부족이 드러나면 외장 1080p 캠으로 교체 고려

### 2.5 ROS2 인터페이스
| 토픽/서비스 | 타입 | 방향 | 비고 |
|---|---|---|---|
| `/dev_cam/image_raw` | sensor_msgs/Image | publish | `v4l2_camera_node` (MJPEG 1280×720@30fps) |
| `/emotion/face` | dobi_npc_msgs/EmotionState | publish | V, A, 7감정, confidence, source="face" |
| `/face_landmarks` | (TBD) | publish | Phase 2에서 결정 |

### 2.6 BT 단계 담당
- IceBreak (인사 후 손님 초기 반응)
- Minigame (RPS 진행 중 손님 표정·시선 추적)
- Offer (메뉴 제안 시 호감도 측정)
- LeadIn (카운터 안내 직전 최종 만족도 평가)

---

## 3. 카메라 2 — HCAM01N (vic_pinky RPi USB 직결)

> **모델 변천**: 2026-05-04 초 HCAM01N → 2026-05-04 후 RPC-20F (autofocus 확인 트랙) → **2026-05-06 다시 HCAM01N 으로 원복** (RPC-20F 는 카메라 3 으로 재배치, §3.5 참조). 본 절은 2026-05-06 확정 상태 기준.

### 3.1 하드웨어
| 항목 | 값 |
|---|---|
| 모델 | **HCAM01N** (Sonix Technology / Microdia 보급형 USB 웹캠) |
| 인터페이스 | USB UVC → **RPi 5 USB 2.0 포트 (Bus 4-1)** 직결 |
| **칩셋 / USB ID** | **Microdia, `0c45:6367`** (실측 2026-05-04) |
| 호스트 | vic_pinky 라즈베리파이 5 |
| 마운트 위치 | 로봇 헤드 또는 본체 상부 (정면 고정) |
| 향한 방향 | **environment-facing** (주행 방향/주변 매장 전반) |
| 포커스 | **고정초점** (No AF). 1.5~8m 환경 관찰 거리에 충분 |
| 내장 마이크 | **사용 안 함** (별도 USB 어레이 마이크 사용 — CLAUDE.md §1.1) |
| 화각 | 보급형 웹캠 일반 화각 60~80° 추정 → GEFA 합격선(80~110°) **미달 가능성**. Phase 1~3은 그대로 사용, Phase 4 재평가 |

### 3.2 영상 스펙 (v4l2 실측, 2026-05-04)
| 항목 | 값 |
|---|---|
| 지원 포맷 | MJPG 1280×720 @ 30fps / YUYV 640×480 @ 30fps |
| 1280×720 YUYV | USB 2.0 대역폭 한계로 5fps 만 → 미사용 |
| **운용 포맷** | **YUYV 640×480 @ 28~30Hz** (`scripts/run_robot_cam.sh` 검증) |
| MJPG 활용 | `ros-jazzy-v4l2-camera 0.7.1` 가 MJPG → rgb8 변환에서 cv_bridge 빈 encoding 예외로 종료 → YUYV 우회 |
| USB auto-suspend | **매 시동 시 해제 필요** (`/sys/bus/usb/devices/4-1/power/control = on`). 안 하면 streaming Protocol error 71 |

### 3.3 인지 명세
| 항목 | 값 |
|---|---|
| 거리 범위 | **1.5 ~ 8m** |
| 대상 수 | **다수** (군중 + 사물 + 장애물) |
| 추출 정보 | 사람 bbox/위치/자세, 사물 라벨, 군중 밀도 |
| 학술 채널 | **Salichs 2014 GEFA** (Gesture/Expression — Facial/Action 원거리) |
| 활성 조건 | **항상** (주행 중 지속 발행) |

### 3.4 ROS2 인터페이스
| 토픽 | 타입 | 발행자 | 비고 |
|---|---|---|---|
| `/robot_cam/image_raw` | sensor_msgs/Image | RPi `v4l2_camera_node` (`scripts/run_robot_cam.sh`) | YUYV 640×480 → rgb8 |
| `/robot_cam/persons` | vision_msgs/Detection2DArray | 노트북 mediapipe efficientdet_lite0 | 사람 bbox |
| `/robot_cam/scene` | (TBD) | 노트북 | 사물·장애물 라벨 |
| `/emotion/body_gesture` | dobi_npc_msgs/EmotionState | 노트북 | source="body", GEFA 신호 (decision_rule 후속) |

### 3.5 BT 단계 담당
- IdleScan (매장 정찰, 호객 후보 발굴)
- Approach (접근 중 사람 자세·거리 추적)
- mode_follow (person_detector + follow_controller — 사람 추종)
- 주행 중 사물·장애물 인식 (Nav2 보조)

### 3.6 Phase 4 화각 재평가 시 후보 (HCAM01N 광각 부족 확인 후 교체 검토용)
| 항목 | 합격선 (재평가 시) |
|---|---|
| UVC 표준 | ✓ 필수 (`v4l2-ctl` 인식) |
| 화각 (HFOV) | 80 ~ 110° |
| 해상도/프레임 | 1080p30 또는 720p60 이상 |
| 포커스 | AF 또는 고정초점 |
| 무게 | ~150g 이하 |
| RPi 5 USB 호환 | 전류 ~500mA 이내 |

**후보** (필요시):
- Logitech C920 / C922 Pro — 78° HFOV (광각 부족)
- Anker PowerConf C300 — 115° HFOV, AI 자동프레이밍 OFF 가능
- Arducam IMX477 HQ + M12 2.8mm — 광각 자유, 셋업 번거로움

---

## 3.5a. 카메라 3 — RPC-20F "RF20" (게임 손 인식 전용, 노트북 USB 외장)

> **결정**: 2026-05-05 추가, 2026-05-06 모델 확정 + 코드 patch 적용.

### 3.5a.1 추가 배경

Phase 3 미니게임 통합 (RPS / 스피드 카운터 / 카페 닌자) 진행 중,
**카메라 1 (GEVA 표정) 과 게임 (손 인식) 이 같은 노트북 웹캠 단일 점유 시도 → v4l2 충돌**.

해결책으로 minigame_runner 가 게임 시작 시 GEVA suspend (cv2.VideoCapture release)
정책 도입했으나, 이는 **Salichs 2014 학술 정합 위반**:
funnel 모든 stage 에서 매 tick V/A 평가 + abort_trigger 발동 (ReactiveFallback) 의도였는데
게임 ~30~50초 동안 GEVA 정지 → abort_trigger 발동 불가.

→ **카메라 1대 추가**로 학술 정합 회복 + SoT "겹치지 않음" 원칙 강화.

### 3.5a.2 하드웨어 (2026-05-06 확정)

| 항목 | 값 |
|---|---|
| 모델 | **로이체 FULL HD 마이크 내장 웹캠 RPC-20F** ("RF20", 별칭 "SNAP U2") |
| 호스트 | vic_pinky 상단 노트북 (USB 외장) |
| 인터페이스 | USB UVC → 노트북 USB 포트 |
| **칩셋 / USB ID** | **Sunplus Innovation Technology (SPCA2281), `1bcf:2281`** (실측 2026-05-06) |
| **`/dev/videoN`** | **`/dev/video2`** (노트북 lsusb 0c:00.3-1, 카메라 1 = video0 과 분리) |
| 마운트 | 노트북 키보드 위 / 화면 하단 — 카메라 1 (얼굴 정면) 과 화각 분리 |
| 향한 방향 | **interaction-facing (손)** — 손님이 노트북 화면 보면서 손동작 |
| 거리 범위 | 0.3 ~ 0.8m (손 인식 거리) |
| **포커스** | **autofocus continuous** — 거리 변화에 자동 추적 (close-range 손 인식 이점) |
| 해상도 능력 | MJPG 1920×1080 @ 30fps / YUYV 다양. cv2.VideoCapture default 640×480 운용 |
| 내장 마이크 | **사용 안 함** |

### 3.5a.3 인지 명세

| 항목 | 값 |
|---|---|
| 거리 범위 | 0.3 ~ 0.8m |
| 대상 수 | 1명 (손) |
| 추출 정보 | 손가락 / 검지 / 양손 합산 |
| 추출 라이브러리 | mediapipe Hands (게임 subprocess 가 자체 cv2.VideoCapture 로 직접 점유) |
| 학술 채널 | **없음** — 호객 funnel 미니게임 전용 (Phase 3) |
| BT 담당 | Minigame phase 의 게임 subprocess 입력 |
| 활성 조건 | 게임 진행 중에만 (idle 시 자원 0) |

### 3.5a.4 활성화 매트릭스

| 운영 환경 | 카메라 1 (GEVA) | 카메라 2 (RPi GEFA) | 카메라 3 (게임 손) |
|---|---|---|---|
| 노트북 단독 시연 | ✓ | — (RPi off) | 게임 중만 |
| vic_pinky 동행 (Phase 4 실 카페) | ✓ | ✓ | 게임 중만 |

**핵심 효과**: 게임 중에도 카메라 1 GEVA 가동 → EmotionMonitor 매 tick V/A 평가 + abort_trigger 정상 작동 → **Salichs 2014 학술 정합 회복**.

### 3.5a.5 코드 영향 (2026-05-06 적용 완료)

- `games/{06_rps_evolution, 07_speed_counter, 01_cafe_ninja}/src/game.py`: `cv2.VideoCapture(0)` hardcoded → `self.camera_index` 멤버 + `--camera-index N` argparse (default 0)
- `dobi_npc_minigame/.../minigame_runner_node.py`: `game_camera_index` ROS 파라미터 (default 2) → subprocess 에 `--camera-index <N>` 전달
- `dobi_npc_bringup/launch/mode_npc.launch.py`: `game_camera_index` launch arg (default 2) + `ParameterValue(value_type=int)` wrap 으로 노출
- `dobi_npc_minigame`: `/geva/suspend` + `/geva/resume` publisher **폐기**. `/face_avatar/suspend|resume` 는 디스플레이 충돌 회피 위해 유지
- `dobi_npc_emotion/.../geva_node.py`: `/geva/suspend|resume` subscriber + `_on_suspend`/`_on_resume` 메서드 + `_suspended` 플래그 + `from std_msgs.msg import Empty` 일괄 제거. 단일 카메라로 회귀할 일 있을 시 git history (~2026-05-05) 복원

라이브 검증 (2026-05-06): `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ros2 launch dobi_npc_bringup sim_funnel_demo.launch.py` → IceBreak 발화 → minigame_runner suspend face → 게임 진입 → resume → cycle 진행 확인. 사용자 "잘 동작해" 보고.

---

## 4. 4축 분리표 (혼동 방지)

| 축 | 카메라 1 | 카메라 2 | 카메라 3 |
|---|---|---|---|
| **거리** | 근거리 ≤1.5m | 원거리 1.5~8m | 손 거리 0.3~0.8m |
| **대상 수** | 1명 (정밀) | 다수 (개관) | 1명 (손) |
| **추출 정보** | 얼굴 (표정·시선) | 몸 (위치·자세) + 환경 | 손가락 / 검지 / 양손 합산 |
| **방향** | interaction-facing (얼굴) | environment-facing | interaction-facing (손) |
| **호스트** | 노트북 내장 | RPi USB 직결 | 노트북 USB 외장 |
| **모델** | Bison `5986:211b` (MSI 내장) | HCAM01N `0c45:6367` (Microdia) | RPC-20F `1bcf:2281` (Sunplus SNAP U2) |
| **포커스** | 고정 (~50cm) | 고정 | **autofocus continuous** |
| **`/dev/videoN`** | 0 | 0 (RPi 측) | 2 (노트북 측) |

→ 셋 다 vic_pinky 위에서 함께 이동하지만 **방향과 추출 대상**이 다르다.

---

## 5. 학술 채널 매핑 (Salichs 2014)

| Salichs 채널 | 의미 | 본 시스템 담당 |
|---|---|---|
| **GEVA** (Verbal/Arousal — 근거리 표정·시선) | 얼굴 픽셀이 충분한 거리에서만 의미 있는 신호 | **카메라 1** |
| **GEFA** (Facial/Action — 원거리 자세·접근) | 멀리서도 보이는 거시 신체 신호 | **카메라 2** |

→ Phase 2 EmotionMonitor가 `/emotion/face` + `/emotion/body_gesture` 두 토픽을 동시 구독하여 Decision Rule로 fusion.

---

## 6. 컴퓨팅 분담 (Phase 1 W2 시작점)

| 처리 단계 | 호스트 | 이유 |
|---|---|---|
| 카메라 2 raw 영상 publish | **RPi 5** (`v4l2_camera_node`) | USB 직결된 곳에서 발행 |
| 카메라 2 사람 검출 (YOLO/MediaPipe) | **노트북** (raw 구독 후 처리) | RPi5 부담 ↓, 노트북 GPU 활용 |
| 카메라 1 raw + 표정 인식 | **노트북** (자체 처리) | 같은 머신 내 처리, 지연 0 |
| BT 실행 | **노트북 또는 RPi** | 토픽 구독만 하면 어디서든 |
| Nav2 / AMCL | **RPi** | 기존 자산 그대로 |

→ **노트북 = AI 허브 / RPi = 센서·모션 허브** 역할 분리.

---

## 7. Phase별 활성화 매트릭스

| Phase | 카메라 1 | 카메라 2 | 비고 |
|---|---|---|---|
| **1 (W1~W3)** | 시뮬레이션 입력만 | (W2부터) 실측 또는 시뮬레이션 | BT 골격 + Nav2 통합 |
| **2 (W4~W6)** | GEVA 본 채널 활성 | GEFA 본 채널 활성 | EmotionMonitor 양방향 fusion |
| **3 (W7~W9)** | 미니게임 중 손님 반응 | 매장 환경·다른 손님 인식 | 둘 다 풀가동 |
| **4 (W10~W12)** | 파일럿 시연 운영 | 파일럿 시연 운영 | 천장캠 도입 평가 시점 |

---

## 8. 오버랩 우려 사전 해소 규칙

| 시나리오 | 의문 | 규칙 |
|---|---|---|
| 카메라 2가 손님과 가까워지면 얼굴이 보임 | 카메라 2도 표정 추출? | **금지**. 카메라 2는 body keypoints만. 표정은 카메라 1 전담 |
| 카운터 손님이 1.5m 이상 떨어져 있음 | 카메라 1이 일하나? | **idle 발행** (`confidence: 0.0`). 카메라 2 GEFA로 BT 진행 |
| 두 카메라가 같은 손님을 동시에 봄 | 신호 충돌? | 충돌 아님 — **다른 정보 종류**. Decision Rule이 합산 |

---

## 9. 제외된 옵션 (의사결정 이력)

| 옵션 | 제외 사유 | 결정 시점 |
|---|---|---|
| **천장 카메라 (고객 감지용)** | 사용자 원래 의도는 로봇 위치 redundancy였고, 매장 GEFA는 카메라 2로 충분 | 2026-05-01 |
| **천장 카메라 (로봇 위치용)** | Nav2 + LiDAR로 충분, **Phase 3까지 고려 없음** | 2026-05-01 |
| **dalimi_gazebo_teleop pose_server** | dalimi 데모 환경과 moca 카페가 물리적으로 별개 공간, 좌표계 불일치 | 2026-05-01 |
| **분산 광각 카메라 다대 (벽/구석)** | 인프라 비용 과다, 자족형 구성으로 갈음 | 2026-05-01 |
| **GoPro Hero 5** | UVC 미지원 (HDMI 캡처카드 또는 WiFi RTSP 필요), ROS2 통합 비용 과다 | 2026-05-01 |

---

## 10. 결정 이력

- **2026-05-01**: 카메라 2채널 + 자족형 토폴로지 확정 (사용자 명시)
- **2026-05-01**: 노트북을 vic_pinky 상단에 탑재하여 카메라 1 호스트로 사용 결정
- **2026-05-01**: 카메라 2를 RPi 5 USB 포트에 직결하기로 결정
- **2026-05-01**: 천장 카메라는 Phase 3까지 고려 없음
- **2026-05-04**: 카메라 2 실 하드웨어가 RPC-20F 가 아닌 HCAM01N (Microdia `0c45:6367`) 으로 실측 확인. SoT 정정 트랙으로 이관. 같은 날 RPC-20F (Sunplus SNAP U2 `1bcf:2281`) 로 카메라 2 교체 시도 (autofocus + 1080p 능력 검토)
- **2026-05-05**: **카메라 3 추가 결정** — Phase 3 미니게임이 카메라 1 단독 점유와 충돌 (게임 중 GEVA 정지 → Salichs 2014 학술 정합 위반). 노트북 USB 외장 1대 추가로 게임 손 인식 전용. 모델/마운트는 사용자 선택
- **2026-05-06**: **카메라 2/3 모델 스왑 확정** — RPC-20F (autofocus + 1080p) 가 close-range 손 인식에 더 적합 → 카메라 3 으로 재배치. 카메라 2 (RPi) 는 검증된 HCAM01N 으로 원복 (`run_robot_cam.sh` 그대로). 같은 날 카메라 3 코드 patch 적용 (game.py 3종 `--camera-index` + minigame_runner `game_camera_index` + `/geva/suspend|resume` 폐기) + 라이브 cycle 검증 통과

---

## 11. 미결정 사항 (TODO)

- [x] ~~카메라 1 (노트북 내장) 스펙 확인~~ → **완료 2026-05-01**: MSI Bravo 17 D7VF, "HD Webcam", 720p30 MJPEG (§2.2 참조)
- [x] ~~카메라 1 AF 여부 확인~~ → **완료 2026-05-01**: 고정초점 (No AF), 헌팅 0
- [x] ~~카메라 1 칩셋/벤더 ID~~ → **완료 2026-05-01**: Bison Electronics `5986:211b` (MSI 표준 UVC 모듈)
- [ ] Phase 1 W2 진입 전 v4l2 controls 튜닝: `exposure_dynamic_framerate=0`, WB 락 검토
- [ ] 노트북 마운트 거치대 설계 (각도, 높이, 진동 흡수)
- [ ] 기존 7인치 터치 LCD 운명 (CLAUDE.md §1.1) — 노트북으로 대체 vs 보조 잔존
- [ ] vic_pinky 페이로드 검증 (**MSI Bravo 17 D7VF ~2.6kg** + RPC-20F + 거치대)
- [ ] 노트북 전원 — 자체 배터리(1~2시간) vs 로봇 전원 분기 vs 외부 보조배터리
- [x] ~~**카메라 3 모델/마운트 결정**~~ → **완료 2026-05-06**: RPC-20F (Sunplus SNAP U2 `1bcf:2281`) 노트북 USB 외장 `/dev/video2` 확정 (§3.5a)
- [x] ~~**카메라 3 적용 후 minigame_runner `/geva/suspend|resume` publish 폐기** + game.py 3종 `--camera-index` 추가~~ → **완료 2026-05-06** (§3.5a.5)
- [ ] **follow_controller 재튜닝** (HCAM01N 화각 vs RPC-20F 화각 차이) — `2026-05-04_follow_tune_smoothing.md` 의 게인/EMA/align_gate 라이브 재검증
- [ ] 카메라 2 (HCAM01N) base_link → camera_link 정적 TF 캘리브 (Phase 1 W2 진입 전)
- [ ] **Phase 4 카메라 2 광각 재평가** — HCAM01N 60~80° 화각이 매장 GEFA에 충분한지 시연 데이터로 판정
- [ ] **MJPG 1080p 경로 복구** — `ros-jazzy-v4l2-camera 0.7.1` cv_bridge 빈 encoding 예외 우회 (별 빌드 또는 image_transport)
- [ ] 카메라 3 마운트 거치대 설계 (노트북 화면 하단 고정, 손 거리 0.3~0.8m 유지)

---

## 12. 본 문서와의 연관 문서

- `CLAUDE.md` §1.1, §8 — 카메라 표기 정정 필요 (천장 카메라 → "P3 이후 평가", GEFA용 → 카메라 2)
- `cafe_npc_paper_master.md` — Salichs 2014 GEFA/GEVA 학술 근거
- `cafe_npc_implementation_plan.md` §1.1, §3.3 W2 — "천장 카메라 pose_server" 표기 정정 필요
- `cafe_npc_engagement_funnel.md` — 5-stage funnel ↔ 카메라 활성화 단계 정합
- `docs/daily/2026-05-04_robot_cam_raw_publisher.md` — 카메라 2 실 하드웨어 HCAM01N 실측 회고
- `docs/daily/2026-05-04_follow_tune_smoothing.md` — RPC-20F 1차 교체 시점의 follow 튜닝 (HCAM01N 원복 후 재검증 필요)
- `docs/daily/2026-05-06_camera3_swap_and_patch.md` — 카메라 2/3 모델 스왑 + 코드 patch 회고

---

*본 문서는 카메라 관련 의사결정의 단일 진실 원본이다. 향후 카메라 구조 변경 시 본 문서를 먼저 갱신하고, 다른 문서에 전파한다.*
