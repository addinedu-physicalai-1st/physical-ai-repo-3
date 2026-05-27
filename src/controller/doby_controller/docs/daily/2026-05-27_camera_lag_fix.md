# 2026-05-27 — 카메라 렉 해결 + viz_tracking 개선 + run_follower 정리

> 작성: 2026-05-27 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: 카메라 렉 해결 → 데모 촬영 준비

---

## 0. 배경

2026-05-26 이어서. 팀원 Vic Pinky 공유 환경.
렉 있는 상태에서 데모 촬영 불가 → 렉 해결 우선.

---

## 1. 카메라 해상도 변경 — 렉 원인 해결

### 원인
- 기존 640x480 @ 17fps(compressed) → YOLO 처리 + 전송 병목
- 640x360 @ 30fps(compressed) 가능 (SNAP U2 지원)

### 수정
- `run_follower.sh`: `IMAGE_HEIGHT=360` 추가 (run_robot_cam.sh ENV 전달)
- `dev_common.launch.py`: `image_height: 360` 명시

### 결과
- 카메라 17fps → **30fps** ✅
- "훨씬 더 부드러워졌어" 확인

---

## 2. frame_skip 최적화

### 실험 결과

| frame_skip | 실제 tracks Hz | 비고 |
|---|---|---|
| 1 | ~1.5Hz | GPU 큐 과부하 (최악) |
| 2 | ~3Hz | 큐 약간 쌓임 |
| 5 | ~5-6Hz | GPU 여유, 안정적 |
| **3** | 미확인 | **현재 설정** (딜레이 개선 목적) |

- frame_skip=1 이 오히려 느린 이유: GPU가 30fps YOLO를 못 따라가서 큐 쌓임
- frame_skip=5 가 GPU 최적 (6회/초)
- 탐지 딜레이 개선 목적으로 frame_skip=3 으로 변경 (테스트 미완료)

### 확정값
```python
# dev_common.launch.py
'frame_skip': 3,     # YOLO 10회/초 — 탐지 딜레이 개선 (테스트 필요)
'image_height': 360, # 30fps
```

---

## 3. viz_tracking.py 개선

### 변경 내용
1. **텍스트 아웃라인** — `_put_text()` helper 추가 (검정 테두리 → 어떤 배경에서도 선명)
2. **HUD 색상 변경**
   - People/Groups: 흰색 → **밝은 초록** `(0, 230, 80)`
   - Target none: 회색 → **주황** `(0, 165, 255)`
   - Target 있을 때: 기존 노랑 유지
3. **대기 화면 추가** — 카메라/YOLO 준비 전 "Waiting for camera..." 메시지 표시

---

## 4. run_follower.sh 개선 — 터미널 5개 → 2개

### 변경 내용
| 컴포넌트 | 변경 전 | 변경 후 |
|---|---|---|
| RPi bringup | gnome-terminal | 백그라운드 (`/tmp/log_rpi_bringup.log`) |
| RPi mobility_controller | gnome-terminal | 백그라운드 (`/tmp/log_mobility_ctrl.log`) |
| Camera | gnome-terminal | **gnome-terminal 유지** (SSH 안정성) |
| dev_common | gnome-terminal | 백그라운드 (`/tmp/log_dev_common.log`) |
| mode_follow | gnome-terminal | 백그라운드 (`/tmp/log_mode_follow.log`) |
| viz_tracking.py | 없음 | **gnome-terminal 자동 시동** |

결과: 창 5개 → **Camera + Tracking Viz 2개만** 표시

### 발견한 문제
- 카메라를 백그라운드로 돌리면 토픽 데이터 미수신 (SSH 세션 이슈)
- → 카메라만 gnome-terminal 유지로 해결

### 팀원 작업 중단 원인
- run_robot_cam.sh 실행 시 기존 v4l2_camera_node 강제 종료 후 재기동
- run_follower.sh 재시작할 때마다 팀원 카메라 토픽 끊김
- → **카메라 이미 켜져 있으면 재시작 건너뜀** 로직 추가 필요 (다음 세션)

---

## 5. 미완료 — 다음 세션 진입점

### 🥇 즉시 할 것
1. **카메라 재시작 방지** — run_follower.sh에서 `/robot_cam/image_raw/compressed` 토픽 이미 수신 중이면 [3/4] 스킵
2. **frame_skip=3 실물 테스트** — tracks Hz 측정 + 탐지 딜레이 체감 확인
3. **2인 탐지 확인** — yolo_conf=0.50에서 2명 bbox 제대로 뜨는지

### 🥈 데모 촬영 (준비되면)
- ① 사람 탐지/그룹 클러스터링 사진 (viz_tracking.py 화면)
- ② 접근 영상
- ③ customer_id 고정 사진
- ④ 추종 영상

### 🥉 GEVA + 1:1 추종
- 카메라 마운트 조정 (얼굴 잘림)
- target_selector → follow_controller 연동

---

## 6. 커밋 목록

```
fix(viz): 텍스트 아웃라인 + HUD 색상 + 대기화면
fix(launch): frame_skip 5→3, image_height 360 확정
fix(script): run_follower 백그라운드화 + viz 자동시동
```

---

*다음 세션: 카메라 재시작 방지 로직 → frame_skip=3 테스트 → 데모 촬영*
