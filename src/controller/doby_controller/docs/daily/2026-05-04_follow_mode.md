# follow 모드 실 구현 — person_detector + follow_controller, mode_follow stub 교체

**작성일**: 2026-05-04 (robot_cam raw publisher 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 W4.5 GEFA 사전 / 사람 추종 / mode_follow stub 교체
**상태**: 4-state FSM 의 follow 모드가 stub 에서 실 noun 으로 전환. `/robot_cam/image_raw` 구독 → 사람 bbox 검출 → reactive cmd_vel. 라이브 검증 통과 (사람 검출 + 좌회전 + 안전 가드 + abort_trigger STOP 모두 동작).

---

## 0. 시작 컨텍스트

전 단계까지:
- ✅ `scripts/run_robot_cam.sh` (커밋 691e1da) — RPi v4l2_camera_node 자동 spawn → `/robot_cam/image_raw` (640x480 rgb8 28Hz)
- ❌ mode_follow.launch.py 는 mode_stack_stub (1Hz alive 로그만)
- ❌ person 검출 노드 없음

본 세션 목표: 노트북에서 `/robot_cam/image_raw` 구독 → 사람 bbox 검출 → reactive cmd_vel 까지의 풀스택을 mode_follow.launch.py 에 묶기.

---

## 1. 구현

### 1.1 person_detector (`dobi_npc_emotion/person_detector_node.py`, ~150 줄)

**입력**: `/robot_cam/image_raw` (sensor_msgs/Image, 640x480 rgb8 ~28Hz)
**출력**: `/robot_cam/persons` (vision_msgs/Detection2DArray)
**모델**: mediapipe `efficientdet_lite0.tflite` (~7.2MB, 80 클래스 → `category_allowlist=["person"]` 필터)

```python
options = mp_vision.ObjectDetectorOptions(
    base_options=mp_python.BaseOptions(model_asset_path=model_path),
    running_mode=mp_vision.RunningMode.IMAGE,
    score_threshold=0.4,
    max_results=5,
    category_allowlist=["person"],
)
```

추론 throttle: `detect_rate_hz=10.0` 기본. 영상은 28Hz로 들어오지만 추론은 10Hz로 cap → CPU 부하 ↓ + follow 반응성 충분.

cv_bridge `imgmsg_to_cv2(desired_encoding='rgb8')` → mediapipe `mp.Image(SRGB)` 직결. RGB 변환 추가 없음.

각 detection 을 `Detection2D` 로 매핑:
- `bbox.center.position.x/y` = pixel 중심 (origin + size/2)
- `bbox.size_x/y` = pixel w/h
- `results[0].hypothesis.class_id="person"`, `score=cat.score`
- header.frame_id 는 image header 그대로 forward (camera frame TF 일관)

### 1.2 follow_controller (`dobi_npc_bringup/follow_controller_node.py`, ~200 줄)

**입력**:
- `/robot_cam/persons` (Detection2DArray) — 검출된 bbox
- `/scan` (LaserScan) — 전방 안전 가드
- `/rapport/event` (RapportEvent) — abort_trigger 즉시 정지

**출력**: `/cmd_vel` (Twist) @ 20Hz

알고리즘 — 단순 P 제어 + 다중 안전 가드:

```
target = max(detections, key=area)        # 가장 큰 bbox = 가장 가까운 사람
err_angle = (image_w/2 - bbox_cx) / (image_w/2)     # +값 = 사람이 왼쪽
err_dist  = target_h_ratio - (bbox_h / image_h)     # +값 = 너무 멀다 (전진)
v = clamp(kp_linear * err_dist,  ±max_linear)
ω = clamp(kp_angular * err_angle, ±max_angular)
```

deadband: `|err_angle| < 0.05` 또는 `|err_dist| < 0.05` 이면 0 (헌팅 방지).

기본 게인:
```
target_height_ratio = 0.5 (bbox 높이가 frame 높이의 50%일 때 정거리)
kp_linear  = 0.6 m/s per unit error
kp_angular = 1.2 rad/s per unit error
max_linear = 0.30 m/s
max_angular = 0.80 rad/s
```

**안전 가드 4개 (OR — 어느 하나라도 발동 시 v 또는 v=ω=0)**:

1. `abort_dwell` (기본 2.0s): rapport `abort_trigger` 수신 시 `_dwell_until = now + 2.0s`. 그 동안 매 tick `Twist()` (모두 0) publish. tts/face_avatar dwell 패턴과 동일.
2. `detection_lost_sec` (1.0s): 마지막 person 검출 시각이 1초 이상 지나면 정지.
3. `scan_stop_dist` (0.8m, ±30° 전방 arc): `/scan` 의 전방 구간에 0.25~0.8m 사이 obstacle → v=0 (회전은 허용 — 사람 트래킹은 계속).
4. `scan_min_range` (0.25m): vicpinky 섀시 자기반사 마스킹. SafetyCheck/ROI 와 동일 값.

`destroy_node`: launch SIGINT 받을 때 마지막 `Twist()` 0 publish (브레이크 신호).

### 1.3 mode_follow.launch.py 교체

기존 `mode_stack_stub` (1 노드 stub) → person_detector + follow_controller (2 노드).

```python
return LaunchDescription([
    params_arg,
    Node(package='dobi_npc_emotion', executable='person_detector', ...),
    Node(package='dobi_npc_bringup', executable='follow_controller',
         parameters=[{'params_json': ParameterValue(LaunchConfig('params_json'), str)}]),
])
```

mode_manager 가 `SetMode("follow", {...})` → LaunchSupervisor 가 본 launch spawn. mode 전환 시 SIGINT → destroy_node 정지 cmd → SIGKILL.

`params_json` 은 mode_manager → launch → follow_controller 까지 reflect. 현 구현 미사용이지만 후속 (target face id 등) 확장 위한 통로.

### 1.4 자산/의존성

- 모델 다운로드: `scripts/download_models.sh` 에 efficientdet_lite0 추가 (1회 7.2MB).
- `dobi_npc_emotion/setup.py`: `models/*.tflite` glob 추가 → install/share 에 모델 자동 복사.
- `dobi_npc_emotion/package.xml`: `vision_msgs`, `cv_bridge` depend 추가.
- `dobi_npc_bringup/package.xml`: `vision_msgs` depend 추가.
- `dobi_npc_bringup/setup.py`: `follow_controller` entry point 추가.

---

## 2. 라이브 검증

전제: `bash scripts/run_robot_cam.sh` 로 RPi v4l2_camera 발행 중. `bash scripts/run_vic_bringup.sh` 로 vicpinky bringup 발행 중 (/scan 가용).

```bash
ros2 launch dobi_npc_bringup mode_follow.launch.py params_json:="{}"
```

검증 결과:

```
[follow_controller] follow_controller ready: persons=/robot_cam/persons scan=/scan
  cmd=/cmd_vel image=640x480 target_h=0.50 max_v=0.30 max_w=0.80
  abort_dwell=2.0s front_arc=±30° stop<0.80m

[person_detector] person_detector ready: in=/robot_cam/image_raw
  out=/robot_cam/persons model=efficientdet_lite0.tflite
  score>=0.4 max=5 detect_rate=10.0Hz
[person_detector] in=19.7Hz detected_frames=0/99 (0%) total_persons=0   # 카메라 빈 시야

[follow_controller] STOP: abort_trigger (live_test)                      # ← abort 수신 ✓

[person_detector] in=19.7Hz detected_frames=1/100 (1%) total_persons=1   # 사람 잠깐 등장
[follow_controller] cmd_rate=20.0Hz v=+0.00 w=+0.80
  err_angle=+0.93 err_dist=+0.38 bbox_h=58 scan_front=0.46m
```

해석:
- `/cmd_vel` 20Hz publish (timer 정확)
- 빈 시야 → person_detector 0% / follow_controller 정지 (모든 0)
- abort_trigger publish 직후 → "STOP: abort_trigger (live_test)" WARN 로그 ✓
- 사람 등장 → err_angle=+0.93 (사람이 화면 왼쪽 끝 근처) → ω=+0.80 (max 좌회전) ✓
- err_dist=+0.38 → 원칙적으로 v = 0.6 * 0.38 = 0.23 m/s 전진 — 그러나 scan_front=0.46m < stop_dist 0.8m **→ 전방 가드 발동, v=0** ✓ (회전은 그대로 허용)

→ 전 가드 동시 동작 확인. 4개 가드 OR 조합이 의도대로 작동.

---

## 3. 발견 / 함정

### 3.1 ros2 launch 인자 빈 문자열 금지

`params_json:=""` 는 "malformed launch argument" 로 거부. CLI 파서가 `<name>:=<value>` 비교 시 value 빈 문자열을 reject. 검증/디버깅 시 `params_json:="{}"` 처럼 placeholder 객체 명시.

mode_manager → LaunchSupervisor 호출 시도 항상 non-empty JSON 보내야 함. 본 launch 의 `default_value=''` 는 launch 자체 호출 (예: `ros2 launch ... .launch.py`) 시에만 의미. mode_manager 코드 확인 필요 — 별 트랙 점검사항.

### 3.2 follow_controller가 launch의 params_json을 declare 하지 않으면 launch 실패

ros2 launch의 Node parameters에 'params_json'을 넣었는데 노드가 declare 하지 않으면 첫 set_parameters 호출에서 거부. follow_controller에 `declare_parameter('params_json', '')` 추가로 해결. 현재는 사용 안 하지만 미래 확장 통로.

### 3.3 bbox_h 와 실측 거리 불일치

검증 시 `bbox_h=58 (px)` (frame 480 → ~12%) 인데 `scan_front=0.46m` — 사람이 실제로 가깝다. bbox 크기는 사람 자세, 카메라 마운트 높이, 사람이 frame 중앙에 있는지 등에 따라 변화. **target_height_ratio=0.5 는 카페 환경(사람 직립, 1.5~2m 거리, 카메라 시선 높이)에서 의미** — 실 라이브 시 carefully 캘리브레이션 필요.

short-term 우회: scan_stop_dist 가 hard 안전선 → bbox 기반 distance error 가 현실과 어긋나도 충돌 안 함. 다만 robot 이 "생각보다 너무 가까이 가려 한다" 거동은 여전히 발생 가능 — bbox 기반 추정의 본 약점.

후속 개선 옵션:
- 카메라 캘리브레이션 (focal length 측정) → 실 거리 추정 (`d = f * H_real / h_pixel`, H_real=1.7m 가정)
- 또는 mediapipe pose 의 segmask 면적 → 더 안정적 거리 proxy
- 또는 scan + camera fusion (사람 bbox 가 가리키는 방향의 scan 거리)

### 3.4 abort_trigger 의 dwell 정책 — 3 노드 일관

face_avatar (pygame ticks), tts_node (time.monotonic), follow_controller (time.monotonic) 모두 같은 `abort_dwell_sec=2.0` 기본값 + sustained abort 동안 timer reset 정책. 한 정책이 abort 시 시각/청각/모션 셋 다 동시에 정지.

### 3.5 scan_stop_dist 와 SafetyCheck `/scan` 가드 중복

SafetyCheck 노드(BT npc 모드)는 `/scan` 임계 1.0m → alarm SUCCESS. follow_controller(follow 모드)는 `/scan` 전방 0.8m → v=0. **둘이 동시에 활성화 안 됨 (mode 별 stack 분리)** — npc 모드에서는 BT 가, follow 모드에서는 follow_controller 가 각자 처리. 임계값 차이 (1.0 vs 0.8) 는:
- BT: alarm 발동 시 funnel 차단 (호객 시도 자체 중단)
- follow: 보행 안전 (멈추기 위한 min distance)
정책 다름이 OK. 추후 페르소나별/모드별 정책 정리 필요해지면 통합.

### 3.6 person_detector throttle vs follow_controller control_rate

- person_detector: 10Hz (CPU)
- follow_controller: 20Hz (제어 박자)

control 이 detect 보다 빠른 게 이상해 보일 수 있으나 — control 은 마지막 `_target_bbox` 캐시를 사용. 100ms 안 새 detection 안 와도 같은 bbox 로 cmd_vel 산출 → 부드러운 보간. detection_lost_sec=1.0s 이내라면 OK. 카메라 빈 시야로 1초 지나면 정지.

---

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/person_detector_node.py` | 신규 (~150 줄) |
| `src/dobi_npc/dobi_npc_emotion/setup.py` | tflite glob + person_detector entry point |
| `src/dobi_npc/dobi_npc_emotion/package.xml` | vision_msgs / cv_bridge depend |
| `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` | 신규 (~200 줄) |
| `src/dobi_npc/dobi_npc_bringup/setup.py` | follow_controller entry point |
| `src/dobi_npc/dobi_npc_bringup/package.xml` | vision_msgs depend |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py` | stub → 실 2 노드 launch |
| `scripts/download_models.sh` | efficientdet_lite0 추가 |

---

## 5. 다음 / TODO 갱신

### CLAUDE.md TODO 변경
- `[ ] W4.5 GEFA: RPi USB 캠 → 자세/접근/회피` → 부분 해결: person bbox 발행은 OK. **자세(skeleton) + body emotion 추정은 후속** (mediapipe pose 추가 필요).
- 신규 `[ ] follow 모드 실 구현 (2026-05-04, person_detector + follow_controller, abort/scan 가드 4종, target_h=0.5 캘리브 필요)` → 본 회고로 닫음.

### 후속 (관련성 가까움)
- [ ] **target_height_ratio 캘리브레이션**: 카메라 마운트 후 실측 거리 vs bbox_h 매핑. config/follow.yaml 분리.
- [ ] **카메라 캘리브레이션 → 실 거리**: focal length 측정 → 사람 키 가정 1.7m → distance 추정. bbox_h 대체.
- [ ] **사람 ID tracking**: 현재는 매 frame 가장 큰 bbox. 사람 여러 명 시 깜빡임. mediapipe ObjectDetector 가 ID 안 줘서 추가 tracker(IoU-based) 필요.
- [ ] **mode_manager 의 follow params_json**: target id / face descriptor 등 follow_controller 가 받아 처리.
- [ ] **GEFA body emotion**: mediapipe pose → 자세 분석 → `/emotion/state (source="body")`. follow 와 별개 트랙.

---

## 6. 한 줄 요약

> mode_follow stub 을 실 구현으로 교체. RPi 카메라 → mediapipe efficientdet_lite0 → vision_msgs/Detection2DArray → reactive cmd_vel. 안전 가드 4종(abort dwell / detection lost / scan front / scan_min_range) 모두 라이브 검증 통과.
