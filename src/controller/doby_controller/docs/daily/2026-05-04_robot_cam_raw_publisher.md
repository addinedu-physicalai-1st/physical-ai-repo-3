# RPi 카메라 2 raw publisher — run_robot_cam.sh + 실측 빠짐 해결

**작성일**: 2026-05-04 (face_avatar v2.1 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "카메라 2 (RPC-20F) raw publisher: RPi USB 캠 직결 (W4.5 GEFA 사전 작업)"
**상태**: RPi v4l2_camera 기반 `/robot_cam/image_raw` 토픽 발행 + 노트북 수신 검증. 자동화 스크립트 2종(run/stop) 작성. 단 실 카메라가 RPC-20F가 아닌 **HCAM01N (Microdia)** — 아키텍처 SoT 정정 필요.

---

## 0. 시작 컨텍스트

GEVA(노트북 웹캠) 검증 완료. 카메라 2(RPi USB)는 docs SoT에 명시되어 있으나 **raw publisher 미구현** 상태. 사람 추종 / GEFA 본 채널 / Approach 시 obstacle 보강 등 후속 트랙의 사전 작업.

---

## 1. 실 하드웨어 vs 아키텍처 문서 차이

`docs/cafe_npc_camera_architecture.md` §3은 카메라 2를 **로이체 RPC-20F**로 명시. 실제 RPi USB에 연결된 카메라는 **HCAM01N (Sonix Technology / Microdia, USB ID `0c45:6367`)**.

```
$ lsusb | grep HCAM
Bus 004 Device 002: ID 0c45:6367 Microdia HCAM01N
```

지원 포맷 (`v4l2-ctl --list-formats-ext`):
- MJPG: 1280x720 / 800x600 / 640x480 / 352x288 / 320x240 / 176x144 / 160x120 — 모두 30fps 가능
- YUYV: 640x480 30fps, 800x600 10fps, 1280x720 5fps

차이가 있는데 **실 카메라가 우선**. SoT 문서를 HCAM01N으로 수정해야 함 (별 트랙). 본 작업은 실 하드웨어 기준 진행.

---

## 2. 구현 — `scripts/run_robot_cam.sh` + `stop_robot_cam.sh`

`run_vic_bringup.sh` 패턴 그대로. SSH 키 없이 `sshpass`로 vic@192.168.0.138 원격 ros2 run 인라인.

### 2.1 흐름

```
1) 로컬 ROS2 환경 (domain=22, fastrtps)
2) ping + sshpass 점검
3) /dev/video0 v4l2 인식 + USB auto-suspend 해제
4) v4l2_camera_node spawn (없을 때만)
5) /robot_cam/image_raw 토픽 발견 + ros2 topic hz 측정
```

### 2.2 핵심 파라미터 (env 변수 override 가능)

```bash
VIDEO_DEVICE=/dev/video0
IMAGE_WIDTH=640
IMAGE_HEIGHT=480
PIXEL_FORMAT=YUYV          # 기본값. MJPG는 §3.2 함정 참조
CAMERA_NS=/robot_cam
CAMERA_FRAME=robot_cam_link
USB_DEVPATH=/sys/bus/usb/devices/4-1/power/control
```

### 2.3 RPi 측 ros2 run 인라인

워크스페이스 install 불필요 — apt 패키지(`ros-jazzy-v4l2-camera`)만으로 충분.

```bash
ros2 run v4l2_camera v4l2_camera_node --ros-args \
  -r __ns:=/robot_cam \
  -p video_device:=/dev/video0 \
  -p pixel_format:=YUYV \
  -p output_encoding:=rgb8 \
  -p image_size:=[640,480] \
  -p time_per_frame:=[1,30] \
  -p camera_frame_id:=robot_cam_link
```

`setsid nohup ... </dev/null >~/logs/robot_cam.log 2>&1 &` 패턴으로 SSH 종료에도 살아남음. 스크립트 종료 후 RPi 백그라운드 동작.

---

## 3. 라이브 검증 + 발견

### 3.1 RPi 측 v4l2_camera 패키지 미설치 (해결)

`apt install ros-jazzy-v4l2-camera` 1회 — 0.7.1-1noble 버전 설치. RPi에 다른 ROS 카메라 패키지 없었음.

### 3.2 v4l2_camera_node가 MJPG → rgb8 변환 실패

```
[WARN] Current pixel format is not supported yet: MJPG 1196444237
[WARN] Image encoding not the same as requested output, performing possibly slow conversion: => rgb8
terminate called after throwing 'cv_bridge::Exception': Unrecognized image encoding []
```

— 빌드의 cv_bridge가 빈 encoding 문자열을 못 받음. MJPG → rgb8 디코드 경로가 깨졌음.

**해결책**: PIXEL_FORMAT을 YUYV로 전환. YUYV → rgb8은 정상 동작 (간단 색공간 변환). 640x480 30fps OK, 1280x720은 5fps 한계.

대역폭 비교 (USB 2.0 480Mbps):
- MJPG 1280x720 30fps: ~30 Mbps (압축, 안전)
- YUYV 640x480 30fps: 147 Mbps (raw, USB2 안전선)
- YUYV 1280x720 30fps: 442 Mbps (USB2 한계 근접 → 5fps 제약)

→ **사람 검출 용도 640x480 YUYV @ 30Hz가 충분**. Phase 4 시연/HD 필요 시 MJPG 경로 정정 (별도 트랙).

### 3.3 USB auto-suspend (Protocol error 71)

첫 시동 시 streaming 시작에서 `VIDIOC_STREAMON returned -1 (Protocol error)`. 원인 추적:

```
$ cat /sys/bus/usb/devices/4-1/power/runtime_status
suspended
```

— 카메라가 USB auto-suspend 상태. dmesg에 `Failed to set UVC probe control : -71` 누적.

**해결책**: 스트림 시작 전 `echo on > /sys/bus/usb/devices/4-1/power/control` (sudo 필요). 스크립트 Step 3에 통합. 매 시동 시 자동 해제.

영구 해제는 udev rule로 가능하나, 본 단계는 매 시동 자동화로 충분.

### 3.4 v4l2-ctl 행걸림

streaming 실패 시 `v4l2-ctl --stream-mmap` 프로세스가 종료되지 않고 행걸림. 별 트랙에서 `pkill v4l2-ctl` 정리 필요. RPi의 v4l2_camera_node 자체는 영향 없음.

### 3.5 UVC quirk 경고 — 무시

dmesg `cannot get freq at ep 0x84` — UVC 1.0 device의 isochronous endpoint freq 컨트롤 미지원 경고. 모든 동작에 영향 없음.

---

## 4. 검증 결과 (라이브)

### RPi 측 노드 로그 (`~/logs/robot_cam.log`)
```
[INFO] Driver: uvcvideo
[INFO] Device: HCAM01N: HCAM01N
[INFO] Requesting format: 640x480 YUYV
[INFO] Success
[INFO] Starting camera
```

### 노트북 측 토픽 검증
```
$ ros2 topic hz /robot_cam/image_raw
average rate: 28.669 (window 30)
average rate: 27.829 (window 57)
average rate: 27.751 (window 85)

$ ros2 topic echo /robot_cam/image_raw --once --no-arr
header.frame_id: robot_cam_link
height: 480
width: 640
encoding: rgb8
step: 1920
data: <sequence type: uint8, length: 921600>
```

— ✅ 28Hz publish, RGB8 변환된 raw 이미지, frame_id 일관, 921600 bytes (=640×480×3) 정상.

### 토폴로지 (`ros2 topic info -v`)
```
Type: sensor_msgs/msg/Image
Publisher count: 1 (RPi v4l2_camera)
QoS: RELIABLE / VOLATILE
```

---

## 5. 파일 변경

| 파일 | 변경 |
|---|---|
| `scripts/run_robot_cam.sh` | 신규 — RPi v4l2_camera_node 자동 spawn + 토픽 검증 (~140 줄) |
| `scripts/stop_robot_cam.sh` | 신규 — 원격 종료 + 로컬 daemon 정리 (~50 줄) |
| RPi `apt install ros-jazzy-v4l2-camera` | RPi 측 1회 설치 (코드 변경 아님) |

---

## 6. 다음 / TODO 갱신

### CLAUDE.md TODO 변경
- `[ ] 카메라 2 (RPC-20F) raw publisher` → **`[x] 카메라 2 raw publisher (2026-05-04, HCAM01N YUYV 640x480@30 동작, MJPG는 v4l2_camera_node 빌드 제약으로 보류)`**

### 추가 발견 항목 (TODO 신규)
- [ ] **카메라 아키텍처 SoT 정정**: `docs/cafe_npc_camera_architecture.md` §3 RPC-20F → HCAM01N (Microdia 0c45:6367) 으로 수정. 화각/해상도 실측 갱신.
- [ ] **MJPG 경로 복구**: cv_bridge 빈 encoding 함정 추적. v4l2_camera 0.7.1 빌드 또는 image_transport plugin 보강. 1280x720@30 시연용.
- [ ] **USB auto-suspend udev 영구 해제**: 시동 스크립트 의존 → udev rule (`/etc/udev/rules.d/99-disable-cam-suspend.rules`) 1회 설정으로 갈음.

### Phase 후속
- [ ] **person detector 노드** (W4.5 GEFA): 노트북에서 `/robot_cam/image_raw` 구독 → mediapipe pose / YOLO → `/robot_cam/persons` (vision_msgs/Detection2DArray) 발행
- [ ] **사람 추종**: person detector 결과 → cmd_vel reactive 또는 Nav2 dynamic goal. mode_follow.launch.py 의 stub 교체.

---

## 7. 한 줄 요약

> RPi USB 카메라(HCAM01N) raw publisher 동작. `scripts/run_robot_cam.sh` 자동화 + USB auto-suspend 해제 + v4l2_camera_node spawn. `/robot_cam/image_raw` 640x480 rgb8 28Hz 검증 통과. MJPG 경로는 v4l2_camera 빌드 제약으로 YUYV 우회.
