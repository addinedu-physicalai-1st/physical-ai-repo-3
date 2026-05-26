# 2026-05-26 — 추종 게인 튜닝 + 소실 대응 개선

> 작성: 2026-05-26 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: 실물 추종 테스트 + 비틀거림 해결 + 사람 소실 시 당황 방지

---

## 0. 배경

mobility_controller RPi 이관(오전) 완료 후, 실물 추종 테스트 진행.
run_follower.sh 한 번으로 전체 스택 시동 → 실물 테스트.

---

## 1. 발견한 문제 및 해결

### 1-1. 비틀거림 (Zigzag)

**원인**: `angular_gain=1.8` 이 너무 높아 방향 보정 과잉 → 좌우 진동

**수정**:

| 파라미터 | 변경 전 | 변경 후 |
|---|---|---|
| `angular_gain` | 1.8 | **0.6** |
| `derivative_gain` | 0.3 | **0.5** (댐핑 강화) |
| `ema_alpha` | 0.3 | **0.5** (목표 위치 스무딩) |
| `kp_angular` (follow) | 0.5 | **0.3** |
| `angle_smoothing_alpha` (follow) | 0.4 | **0.6** |

결과: 실물에서 "훨씬 좋아졌어" 확인 ✅

---

### 1-2. 사람 소실 시 갑작스러운 방향 전환 ("당황")

**원인**: `pose_timeout=1.0`초 동안 마지막으로 본 위치(프레임 가장자리) 향해 계속 회전

**수정**:
- `pose_timeout`: 1.0 → **0.3초**
- `detection_lost_sec` (follow): 1.0 → **0.3초**
- approach_controller에 **Twist(0,0) 명시 발행** 추가 — 소실 시 즉시 정지

**코드 변경** (`approach_controller_node.py`):
```python
# 변경 전
self._prev_err_x = 0.0
return  # 아무것도 발행 안 함 → twist_mux 타임아웃까지 계속 이전 cmd_vel 유지

# 변경 후
self._pub.publish(Twist())  # 즉시 정지
return
```

---

### 1-3. 중복 노드 누적 문제

**원인**: RPi에서 nohup 실행된 프로세스가 SIGTERM에 안 죽어서 세션마다 누적 (최대 7세트까지 쌓임)

**해결**:
- `stop_follower.sh` 신규 작성 — `pkill -f` 후 `sleep 2` + `pkill -9 -f` 이중 kill
- `run_follower.sh` 전면 개편:
  - doby_controller install 경로 추가 소스 (dobi_npc_identity 인식)
  - face_landmarker.task 모델 복사 (설치경로 fix)
  - mode_follow.launch.py 자동 실행
  - follow 모드 자동 전환 포함

---

### 1-4. face_landmarker.task 모델 누락

**원인**: 노트북 상위 install 경로에 모델 없음 (doby_controller 하위 install에만 있었음)

**해결**: `cp` 로 상위 install 경로에 복사

```
install/dobi_npc_emotion/share/dobi_npc_emotion/models/face_landmarker.task ✅
install/dobi_npc_emotion/share/dobi_npc_emotion/models/efficientdet_lite0.tflite ✅
```

---

## 2. 현재 파라미터 (확정값)

### approach_controller (RPi)
```python
angular_gain    = 0.6   # Kp
derivative_gain = 0.5   # Kd
ema_alpha       = 0.5   # 목표 위치 EMA 스무딩
pose_timeout    = 0.3   # 소실 후 정지까지 (초)
linear_speed    = 0.15
dead_zone       = 0.05
close_threshold = 0.45  # bbox 높이 비율 임계값 — 대화 거리 ~1.2m에서 전진 정지 (0.999→0.45)
```

**close_threshold 변경 배경**: 기존 0.999는 사실상 멈추지 않는 값 → 코앞까지 접근.
0.45 로 줄여 대화가 자연스러운 거리(약 1.2m)에서 전진 정지.
bbox 높이 비율은 카메라 각도·거리에 따라 달라지므로 실물 캘리브 기준값임 (2026-05-26 확정).

### follow_controller (RPi)
```python
kp_angular              = 0.3
angle_smoothing_alpha   = 0.6
detection_lost_sec      = 0.3
target_height_ratio     = 0.33
scan_stop_dist          = 0.30
kp_linear               = 0.8
```

---

## 3. 남은 과제

| 항목 | 상태 |
|---|---|
| GEVA 얼굴 인식 → target_selector → follow_controller 1:1 추종 | ⏳ 카메라 각도 조정 필요 |
| 카메라 Pan 모터 — 얼굴 추적 (서보 + camera_pan_controller_node) | 📋 다음 세션 |
| 사람 사라진 후 방향 유지 추적 (마지막 방향으로 천천히 탐색) | 📋 추후 |

---

## 4. 스크립트 사용법 (정착된 워크플로우)

```bash
# 시작 (한 번만)
bash src/controller/doby_controller/scripts/run_follower.sh

# 종료
bash src/controller/doby_controller/scripts/stop_follower.sh
```

---

## 5. 커밋

```
8311439 tune(approach): close_threshold 0.999→0.45 (대화 거리 ~1.2m 정지)
ffb13f4 fix(follow): sync angular_gain 0.6, ema_alpha 0.5 to laptop source
3e8f43e docs: 2026-05-26 추종 게인 튜닝 작업기록 + README 갱신
95af629 tune(follow): approach controller gain tuning + stop-on-lost fix
aab3c88 feat(mobility): migrate driving controllers to RPi mobility_controller
```

---

## 6. 다음 세션 진입점

1. **카메라 Pan 모터 ROS2 노드 작성** (`camera_pan_controller_node`)
   - 서보 타입/PWM 핀 번호 확인 필요
   - `/person_tracking/tracks` bbox 중심 → 서보 각도 P제어
2. **GEVA 얼굴 인식 안정화** — 카메라 마운트 위치/각도 검토
3. **1:1 추종 full flow 테스트** — GEVA → target_selector → follow_controller

---

*다음 갱신: 카메라 Pan 모터 구현 후*
