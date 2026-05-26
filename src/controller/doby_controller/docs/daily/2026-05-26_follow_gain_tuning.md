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

## 2-1. 추가 수정 — min_group_size 2→1

**배경**: `min_group_size=2` 이면 혼자인 손님에게 접근 안 됨.
오늘 1인 테스트에서 접근이 됐던 건 YOLO 이중탐지 노이즈 덕분 (불안정).
스낵바 호객 시나리오에서는 1인 손님도 대상이므로 1로 변경.
여러 그룹이 있으면 여전히 인원 많은 쪽 우선.

```python
# dev_common.launch.py
'min_group_size': 1,   # 2→1 (2026-05-26)
```

---

## 2-2. 짜투리 세션 추가 수정 (노트북 전용)

### YOLO NMS IOU 명시 설정 — bbox 중복탐지 억제
**원인 분석**: 오늘 1인 테스트에서 비틀거림 잔존 원인이 YOLO 이중탐지로 추정.
- YOLO `iou=0.45`(기본값): 한 사람을 상체/전신 bbox 2개로 탐지하는 경우 발생
- DBSCAN `eps=450px`(넓음): 2개 bbox → 같은 그룹 → `count=2` → `min_group_size=2` 통과
- `_publish_customer_pose`: 매 프레임 "최대 area bbox" 선택 → 프레임마다 상체/전신 교체 → cx 진동 → 비틀거림

**수정**: `dev_common.launch.py`에 `yolo_iou: 0.65` 명시 추가

### angle_smoothing_alpha 누락 수정
- `mobility_controller.launch.py`: 0.4 → 0.6 (2026-05-26 튜닝 때 누락됐던 것)

### min_group_size 2→1
- 스낵바 시나리오: 1인 손님도 호객 대상
- 기존 2인 이상만 접근하던 로직 → 1인 포함 모두 접근, 여러 그룹이면 인원 많은 쪽 우선

### camera_pan_controller_node 뼈대 작성
- [scripts/camera_pan_controller_node.py](../../mobility_controller/scripts/camera_pan_controller_node.py)
- follow > approach 우선순위로 bbox 중심 x → 서보 P제어
- `_init_servo()` / `_set_servo_deg()` : TODO (내일 서보 타입/핀번호 확인 후 채울 것)
- `mobility_controller.launch.py` 에 주석 처리된 stub 추가

**내일 시작 전 확인 필요:**
- 서보 연결 방식 (RPi GPIO 직접 vs PCA9685 I2C 보드)
- PWM 핀 번호 / I2C 채널 번호
- 서보 스펙 (동작 각도, 펄스폭 min/max us)

---

## 3. 남은 과제

| 항목 | 상태 |
|---|---|
| GEVA 얼굴 인식 → target_selector → follow_controller 1:1 추종 | ⏳ 카메라 각도 조정 필요 |
| 카메라 Pan 모터 — 얼굴 추적 (서보 + camera_pan_controller_node) | 📋 다음 세션 |
| 그룹 vs 단독 실물 비교 테스트 (min_group_size=1 검증) | 📋 다음 테스트 |
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
a253bc4 feat(pan): camera_pan_controller_node 뼈대 + 파라미터 누락/버그 수정
a440f56 docs: min_group_size 2→1 변경 내용 docs/daily 반영
ff4d168 fix(approach): min_group_size 2→1 — 1인 손님 포함 모든 손님에게 접근 (스낵바 호객)
103bf35 docs: close_threshold 0.45 변경 내용 README + docs/daily 반영
8311439 tune(approach): close_threshold 0.999→0.45 (대화 거리 ~1.2m 정지)
ffb13f4 fix(follow): sync angular_gain 0.6, ema_alpha 0.5 to laptop source
3e8f43e docs: 2026-05-26 추종 게인 튜닝 작업기록 + README 갱신
95af629 tune(follow): approach controller gain tuning + stop-on-lost fix
aab3c88 feat(mobility): migrate driving controllers to RPi mobility_controller
```

---

## 6. 다음 세션 진입점 (2026-05-27 수요일)

1. **카메라 Pan 모터 완성** — 서보 타입/핀번호 확인 → `_init_servo()` 구현 → launch stub 활성화 → RPi 배포 테스트
2. **추종 시나리오 전체 테스트** (Pan 모터 붙인 상태)
   - 그룹탐지 → 접근 (YOLO iou=0.65 효과 확인)
   - GEVA 얼굴 인식 (카메라가 따라다니면 잘림 개선 기대)
   - target_selector → follow_controller 1:1 추종
3. **데모 촬영**
   - ① 사람 탐지/그룹 클러스터링 — 사진
   - ② 사람 접근 — 영상
   - ③ 1인 customer_id 고정 — 사진
   - ④ 거리/방향 유지 추종 — 영상
4. 목표: **금요일(2026-05-29)까지 4단계 데모 완성**

---

*다음 갱신: 카메라 Pan 모터 구현 후*
