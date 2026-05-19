# follow_controller 튜닝 — RPC-20F 교체 + 좌우 jitter 평탄화 + 1m target + v 부호 + compressed transport

**작성일**: 2026-05-04 (target_height_ratio 캘리브 직후 ~ 라이브 튜닝 끝)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**상태**: HCAM01N → RPC-20F (SNAP U2 / Sunplus) USB 카메라 교체. follow_controller 게인 하향 + EMA 저역통과 + align_gate + 1m target + v 부호 반전 + person_detector compressed transport. 라이브 반복 튜닝.

---

## 0. 시작 컨텍스트

전 세션에 follow 모드 실 구현 + target_height_ratio=0.97 캘리브 완료. 사용자가:
1. 카메라를 **RPC-20F (살짝 위 향함)** 로 물리 교체
2. follow 동작 시 **좌우(angular) 회전이 너무 빠르고 jitter** 관찰

본 세션: 카메라 교체 검증 + 회전 게인/필터 튜닝.

---

## 1. RPC-20F 교체 (Sunplus 1bcf:2281, "SNAP U2")

```
$ lsusb
Bus 004 Device 004: ID 1bcf:2281 Sunplus Innovation Technology Inc. SPCA2281 Web Camera

$ v4l2-ctl --list-devices
SNAP U2: SNAP U2 (usb-xhci-hcd.1-1):
    /dev/video0
    /dev/video1
```

이전 HCAM01N과 비교:
| 항목 | HCAM01N | RPC-20F (SNAP U2) |
|---|---|---|
| USB ID | 0c45:6367 (Microdia) | 1bcf:2281 (Sunplus) |
| 최고 MJPG | 1280x720@30 | **1920x1080@30** |
| 최고 YUYV | 1280x720@5 | 1280x720@10 |
| 포커스 | 고정초점 | **autofocus continuous 지원** |
| Bus 위치 | 4-1 | 4-1 (동일 포트) |

→ run_robot_cam.sh 의 `USB_DEVPATH=/sys/bus/usb/devices/4-1/...` 수정 불필요. PIXEL_FORMAT=YUYV 640x480 동작 확인 (28Hz).

**MJPG 변환 버그 동일**: v4l2_camera_node 0.7.1 의 `MJPG → rgb8` 변환 cv_bridge 빈 encoding 예외. 카메라 무관 (빌드 자체 제약). RPC-20F는 1080p MJPG 지원하나 v4l2_camera_node 빌드 한계로 활용 불가 — YUYV 640x480 계속 사용.

---

## 2. 좌우 jitter 분석

### 2.1 원인

이전 follow_controller 게인:
```
kp_angular = 1.2     # err_angle 0.7 도달 시 ω 0.84 → max 0.8 saturated
max_angular = 0.8 rad/s ≈ 46°/s
angle_deadband = 0.05 (≈ ±5%)
EMA 필터 없음
```

증상:
- err_angle 작은 변동에도 ω 큰 변화 (kp 높음)
- bbox center cx의 frame-to-frame jitter가 그대로 cmd_vel에 통과 (저역통과 없음)
- 빠른 ω → frame center 사람 오버슈트 → 반대 방향 → ringing

### 2.2 튜닝 (반복 라이브 조정)

3 차례 반복 (사용자 피드백 → 조정):

| 파라미터 | 노드 default | 1차 (회전 보수) | 2차 (대폭 보수) | 3차 (현 운영값, 회전 살짝 회복) |
|---|---|---|---|---|
| `kp_angular` | 1.2 | 0.6 | 0.4 | **0.35** |
| `max_angular` | 0.8 rad/s (46°/s) | 0.4 (23°/s) | 0.25 → 0.12 | **0.20** (~11°/s) |
| `kp_linear` | 0.6 | 0.6 | 0.4 | **−0.4** (부호 반전) |
| `max_linear` | 0.30 | 0.30 | **0.20** | 0.20 |
| `angle_deadband` | 0.05 | **0.10** | 0.10 | 0.10 |
| `angle_smoothing_alpha` | (없음) | **0.3** | 0.2 | 0.2 |
| `align_gate` | (없음) | (없음) | 0.2 | **0.10** (= deadband) |
| `target_height_ratio` | 0.5 | 0.97 (close game) | 0.97 | **0.5** (1m 일반 follow) |
| `scan_stop_dist` | 0.8 | 0.8 | 0.45 | 0.45 |

EMA 저역통과:
```python
self._err_angle_filt = a * err_angle_raw + (1 - a) * self._err_angle_filt
```

a=0.3 → 신값 30% + 이전 70%. 응답 시상수 ~ 3 tick (~150ms @ 20Hz). 빠른 jitter 흡수, 느린 사람 움직임 추종은 보존.

`detection_lost` 시 `_err_angle_filt = 0` reset → 사람 재발견 시 부드럽게 가속 (이전 값에서 점프 방지).

### 2.3 align_gate (지그재그 차단)

회전 + 전진 동시에 → trajectory 카브 → 사람이 frame center 오버슈트 → 반대 방향 → 지그재그.

해결: `align_gate = angle_deadband` 동일 값으로 설정. 정확히:
- `|err_angle| > 0.10` → `v = 0`, `ω` active (회전만)
- `|err_angle| ≤ 0.10` → deadband 적용 → `ω = 0`, `v` active (전진만)

깨끗한 rotate-then-translate. 회전 + 전진 동시 활성 구간 없음 → 지그재그 차단.

### 2.4 v 부호 반전 (kp_linear < 0)

라이브: 사람이 멀어질 때 robot이 멀어짐 (반대 방향). 사람이 가까이 올 때 robot이 가까이 옴. → vicpinky의 `+linear.x` 가 **카메라가 보는 방향과 반대**.

= 카메라가 vicpinky의 "뒤" 방향에 향함 (또는 vicpinky의 "전진" 정의가 반대). 실 검증 후속.

**즉시 fix**: `kp_linear: -0.4` (음수). err_dist > 0 (사람 멀다) → `v < 0` (vicpinky 후진 = 카메라 방향 = 사람 쪽 이동) ✓

⚠ **사이드 효과**: scan_stop_dist 가드가 `v > 0` 일 때만 발동. 부호 반전 후 사람 방향 이동(`v < 0`)에는 미작동. **scan 안전 가드 부분 무효화** — 후속에 카메라/로봇 frame 정렬 또는 가드 부호 조건 수정 필요.

### 2.5 person_detector compressed transport

raw `/robot_cam/image_raw` 640x480 rgb8 ~ 25 MB/s. WiFi 부하 + latency 누적 → 사용자 "프레임 전송이 느리다".

**전환**: person_detector → `/robot_cam/image_raw/compressed` (sensor_msgs/CompressedImage, JPEG). v4l2_camera_node 가 image_transport plugin 으로 자동 발행 중. cv2.imdecode + cvtColor BGR→RGB 후 mediapipe.

JPEG ~50 KB/frame × 30 fps ≈ **1.5 MB/s, 약 17x 절약**.

`use_compressed` 파라미터 (기본 True). False 로 raw 폴백 가능.

`rqt_image_view` 도 `/robot_cam/image_raw/compressed` 토픽으로 띄우면 동일 효과.

### 2.6 라이브 검증 (1차)

```
[follow] cmd_rate=20.0Hz v=+0.00 w=-0.07 err_angle=-0.11 err_dist=+0.00 bbox_h=480
[follow] cmd_rate=20.0Hz v=+0.00 w=+0.11 err_angle=+0.18 err_dist=+0.00 bbox_h=480
[follow] cmd_rate=20.0Hz v=+0.00 w=+0.00 err_angle=+0.00 err_dist=+0.00 bbox_h=475
```

해석:
- 사용자 처음 좌우 흔들림 (err_angle ±0.18) → ω ±0.11 (이전 ±0.80) — 약 7배 calmer
- 곧 deadband 안 정착 → ω=0 → 사용자: "부드러워짐" ✓
- bbox_h=473~480 saturated → err_dist=0 (deadband 안) → v=0 ✓
- detection 67~83% — 양호

이후 사용자 피드백 → 추가 조정 (지그재그 발견, 부호 반전 발견, 회전 너무 작음 → 0.20rad/s 회복, 1m target 으로 변경, compressed transport 적용).

---

## 3. 위/아래 클립 — 의도된 close-range saturation

사용자 화면 보기: 머리/발이 frame 위/아래 잘림. 원인 + 의미:

- target_height_ratio=0.97 = bbox 높이가 frame 거의 가득 (~50cm 거리, 게임용)
- 새 카메라 살짝 위 → 그 거리에서 머리 잡혀도 발 frame 밖
- bbox_h가 480px에 saturated → `err_dist = 0.97 - 1.0 = -0.03` 하지만 deadband 0.05 안 → **자동으로 0 처리** ✓

**알고리즘 영향**:
- 거리 신호: saturated, 의미 잃음. 하지만 deadband 덕에 의도치 않은 backup 안 함.
- 회전 신호: cx 사용 — 클립 무관. 정상 작동.
- 안전: scan_stop_dist=0.8m로 robot이 0.8m 안 침투. 사용자가 능동적으로 가까이 옴.

→ **의도된 동작**. 사용자가 1번(그대로) 선택. 게임 close-range 시나리오에 완벽 맞음.

---

## 4. v4l2_camera_node 노드 등록 hung 문제 (1회)

첫 launch 시 `/person_detector` 노드가 ros graph에 등록 안 됨 (process는 alive). 재시작 시 정상. 정확한 원인 미상. mediapipe 초기화 race 가능성. 재현 시 추가 조사 — 현재 의심 항목:
- python 출력 buffering (해결: `PYTHONUNBUFFERED=1` 설정)
- 첫 실행 후 mediapipe XNNPACK delegate caching 영향

본 세션은 `PYTHONUNBUFFERED=1`로 재시작 후 정상 동작. 후속 검증 시 다시 모니터링.

---

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` | 노드 default 보수화 (kp_w 1.2→0.4, max_w 0.8→0.25, angle_deadband 0.05→0.10, max_v 0.30→0.20, kp_v 0.6→0.4) + EMA `angle_smoothing_alpha` 0.2 신규 + `align_gate` 0.2 신규 + detection_lost 시 EMA reset |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py` | follow_controller params override: target_h_ratio 0.5 (1m), scan_stop_dist 0.45, kp_v −0.4 (sign flip), kp_w 0.35, max_w 0.20, align_gate 0.10 |
| `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/person_detector_node.py` | `use_compressed` 파라미터(기본 True) — `/robot_cam/image_raw/compressed` 구독 + cv2.imdecode + BGR→RGB. `_should_skip` / `_infer_and_publish` 헬퍼 추출. raw fallback 유지 |

---

## 6. 다음 / TODO 갱신

### 후속 (관련성)
- [ ] **camera SoT 정정**: `docs/cafe_npc_camera_architecture.md` §3 `RPC-20F` (그대로 두되 칩셋 Sunplus 1bcf:2281, "SNAP U2" 식별 추가). HCAM01N 이력은 별 메모.
- [ ] **MJPG 1080p 경로 복구**: v4l2_camera_node 0.7.1의 cv_bridge 빈 encoding 예외 — 별 빌드 또는 image_transport 우회 시 RPC-20F의 1920x1080 활용 가능.
- [ ] **autofocus 활용**: RPC-20F는 autofocus continuous 지원. 거리 변화 시 자동 초점 — close-range 게임에 이상적. v4l2_camera_node param 노출 확인 필요.
- [ ] **follow_controller 노드 등록 hung 재현/원인 추적**: PYTHONUNBUFFERED=1 외 추가 가드 필요할 수도.

### CLAUDE.md TODO
- 신규 `[~] 카메라 RPC-20F 교체 (2026-05-04, autofocus + 1080p 능력 / YUYV 640x480 운용 / SoT 정정 필요)` 추가

---

### 6.1 후속 (관련성 가까움)

- [ ] **vicpinky frame vs camera 정렬 검증**: `kp_linear < 0` 으로 우회 중. URDF/카메라 마운트 점검 후 양수로 복귀 + scan 가드 정상 동작 회복.
- [ ] **scan_stop_dist 부호 조건**: 현 가드는 `v > 0` 만. 부호 반전된 follow에서 v 어떤 방향이든 사람과 거리 좁히면 차단되도록 일반화.
- [ ] **MJPG 1080p 경로 복구**: v4l2_camera_node 0.7.1 cv_bridge 빈 encoding 예외. RPC-20F 1920x1080 능력 활용 시 별 해결 필요.
- [ ] **autofocus 활용**: RPC-20F autofocus continuous 컨트롤. 거리 변화 시 자동 초점 — close-range 게임에 이상적. v4l2_camera 파라미터 확인.

---

## 7. 한 줄 요약

> RPC-20F 교체 (autofocus + 1080p 능력, USB ID 1bcf:2281). v4l2_camera MJPG 빌드 제약 동일 → YUYV 640x480 운용. follow 라이브 튜닝 3 회: 회전 게인 1/3 절감 + EMA + align_gate + 1m target + v 부호 반전 + compressed transport. 사용자 "잘 따라와" + "부드러워짐" 확인. scan 가드 부호 / MJPG / autofocus 후속.
