# 2026-05-27 (오후) — BoT-SORT new_track_thresh 버그 수정 + 카메라 아키텍처 확정

> 세션 목표: 탐지 안 되는 버그 원인 파악 → 수정 + 카메라 구조 정리

---

## 1. 버그 수정 — BoT-SORT new_track_thresh

### 원인
```
yolo_conf        = 0.50  (YOLO 탐지 최소 신뢰도)
new_track_thresh = 0.60  (BoT-SORT 신규 트랙 생성 최소 신뢰도)
```
YOLO가 사람을 0.50~0.59 신뢰도로 탐지해도 BoT-SORT가 트랙을 만들지 않음.
→ viz에 사람이 안 뜨는 현상 발생.

### 수정 (`person_tracking_node.py`)
```python
# 변경 전
track_high_thresh=0.5,
new_track_thresh=0.6,

# 변경 후
track_high_thresh=0.4,   # yolo_conf=0.50 기준으로 낮춤
new_track_thresh=0.45,   # yolo_conf(0.50)보다 낮게 → 트랙 생성 보장
```

### 결과
- tracks 토픽 10Hz 발행 확인 ✅
- new_track_thresh=0.45 로그 확인 ✅

---

## 2. 카메라 아키텍처 확정 — 노트북 직결

### 배경
- 팀원이 RPi(빅핑키)를 주행모드로 사용 중 → 카메라 공유 불가
- 로봇카메라(SNAP U2)를 노트북에 직접 연결하여 테스트

### 확정된 구조
```
[기존] 카메라 → RPi → WiFi(DDS) → 노트북 person_tracking
[확정] 카메라 → 노트북 직결 → person_tracking (레이턴시 0)
```

노트북이 빅핑키에 탑재되므로 카메라를 노트북에 직결하는 것이 최종 구조.
`run_robot_cam.sh` (RPi SSH 카메라) 불필요해짐.

### 테스트 실행 방법 (usb_cam)
```bash
# 터미널 1 — 카메라
source /opt/ros/jazzy/setup.bash && export ROS_DOMAIN_ID=22
ros2 run usb_cam usb_cam_node_exe --ros-args \
  -r __ns:=/robot_cam \
  -p video_device:=/dev/video2 \
  -p image_width:=640 -p image_height:=360 \
  -p framerate:=30.0 -p pixel_format:=yuyv2rgb \
  -p camera_frame_id:=robot_cam_link

# 터미널 2 — 탐지
ros2 launch dobi_npc_bringup dev_common.launch.py

# 터미널 3 — 시각화
python3 src/controller/doby_controller/scripts/viz_tracking.py
```

---

## 3. 논의 — GEVA 카메라 구조

### 현재 구조 (05-26 변경 후)
- 로봇 카메라 → person_tracking(track_id) + GEVA(per-bbox 감정) 통합
- 목적: track_id 기반으로 감정 좋은 사람 → customer_id 지정 → 1인 추종

### 얼굴 잘림 문제 해결 방향
- 원인: 카메라 각도가 전신을 향해 얼굴이 잘림
- 해결: **카메라 Pan 모터** — 얼굴 방향으로 카메라 회전 → 자동 해결
- `camera_pan_controller_node` 서보 출력 구현이 핵심 (현재 TODO)

---

## 4. 미완료 — 내일 진입점 (빅핑키 필요)

### 빅핑키 있어야 가능
1. **카메라 Pan 모터 구현** — 서보 핀번호/타입 확인 → `_init_servo()` 구현
2. **GEVA + 1:1 추종 full flow 확인** — Pan 모터로 얼굴 잘림 해결 후
3. **데모 촬영** — ① 그룹탐지 사진 ② 접근 영상 ③ customer_id 사진 ④ 추종 영상
4. **추종 연동 테스트** — approach → follow 전체 흐름

### 빅핑키 없어도 가능 (팀원만 있으면)
- 그룹 클러스터링 확인 — 2~3명 카메라 앞에서 group_id 제대로 묶이는지

---

*다음 세션: 빅핑키 탑재 → Pan 모터 서보 구현 → GEVA full flow 확인 → 데모 촬영*
