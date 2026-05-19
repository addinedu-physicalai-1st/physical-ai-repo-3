# follow 라이브 튜닝 세션 — 8건 발견 + 코드 patch 5종 + GUI 신규

**작업일**: 2026-05-07 (~05-08 새벽)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "follow_controller 재튜닝 (HCAM01N 화각 vs RPC-20F 차이)"
**선행 회고**: `2026-05-06_follow_postmortem_and_infra.md` (follow 검증 미완)
**상태**: follow stack 동작 확인 + 라이브 GUI 도구 마련. follow 실 동작 검증 (사람 1m 거리 안정 추종) 자체는 target_h_ratio mismatch 로 미완.

---

## 0. 시작 컨텍스트

선행 세션 (2026-05-06) postmortem:
- 좀비 / E-Stop / USB serial lock / cmd_vel race / USB power 등 7건 사고로 follow 실 검증 미완
- 다음 시도 전 인프라 보강 가이드 명문화

본 세션 목표: vic_pinky 충전 후 follow 라이브 동작 검증 + HCAM01N 화각 기준 재튜닝.

세션 진입 직후 RPi ping 실패 → 사용자가 RPi 살림.

---

## 1. 발견 사고/함정 8건

### 1.1 카메라 모델 변경 — HCAM01N → abko FHD1080p

사용자가 RPi 직결 카메라를 **abko FHD1080p (Alcorlink `2ce3:c670`, USB 2.0 Camera)** 로 교체. 기존 HCAM01N (Microdia `0c45:6367`) 가정한 SoT (`docs/cafe_npc_camera_architecture.md` §3) 와 불일치.

지원 사이즈 (실측):
- 640x360, 640x480, 1024x768, 1152x864, 1280x720, 1280x1024, 1920x1080
- **320x240 미지원** (이게 §1.4 사고 원인)
- YUYV / MJPG 둘 다 지원 (HCAM01N 의 MJPG 즉사 제약과 무관)
- 디바이스 경로: `/dev/video1` (HCAM01N 시절 video0 아님)
- USB sysfs: `/sys/bus/usb/devices/4-1/` (우연히 동일)

### 1.2 DDS multicast 차단 — run_robot_cam.sh / run_vic_bringup.sh 미패치

선행 회고 (2026-05-07) 에서 발견된 Wi-Fi multicast 차단 — `run_teleop_ui.sh` 만 ROS_STATIC_PEERS 패치됐고 다른 두 launcher 미패치 상태.

증상: 카메라 노드는 RPi 에 떠 있는데 노트북에서 `/robot_cam/image_raw` 토픽 publisher 1 / subscription 0 로 보임. person_detector 가 못 받음.

### 1.3 vicpinky_bringup 모터 fail 재현 (회고 §2.3)

`Failed to set velocity mode! Shutting down.` — 사용자 본체 직접 작업으로 해결:
- 1차: E-Stop 풀기 (USB 케이블 정리 중 의도치 눌렸을 가능성)
- 2차: 본체 power cycle (실제로 1차로 해결됨)

### 1.4 v4l2_camera_node 의 "Success" lie

`image_size:=[320,240]` 요청 시 v4l2_camera_node 가 "Requesting format: 320x240 YUYV" → "Success" 출력하지만 카메라가 320x240 미지원이라 driver 가 가까운 사이즈 (640x480) 로 silently fallback. 노드는 fallback 모름. 결과 토픽은 640x480 이지만 노드 입장 320 으로 처리.

### 1.5 follow_controller / person_detector 라이브 param 무반응

`__init__` 에서만 param 읽고 self.* 인스턴스 변수에 박힘. `add_on_set_parameters_callback` 없음. 즉 `ros2 param set` 으로 게인/max/score_threshold/detect_rate 변경해도 control loop / detector 는 init 값 그대로 동작.

세션 중반에 사용자가 "회전 늦다" / "bbox 안 뜬다" 보고에 대해 라이브 set 으로 응답했지만 모두 무반응. 노드 재시동만이 유일한 적용 방법이었음.

### 1.6 image 사이즈 mismatch 가 직진 차단의 진짜 원인

§1.4 + §1.5 결합 효과:
- 카메라 320x240 시동 명령 → 실제 640x480 fallback (§1.4)
- follow_controller 는 init 시 image_w/h=640/480 가정 (라이브 set 무반응 §1.5)
- 또는 우리가 launch param 으로 320/240 박은 경우 — 카메라가 실제론 640x480 → bbox 좌표는 0~640, 0~480 이지만 follow 는 320/240 가정 → err_angle 항상 0.5 이상 → align_gate trigger → **v=0 강제**, 회전만

사용자 보기엔 "직진 안 함 / 안 따라옴" 으로 인식. 코드 정밀 분석 (`follow_controller_node.py` line 226-272 수동 검토) 후 발견.

### 1.7 target_h_ratio mismatch — 1m 의도 vs 0.5 default

launch default `target_height_ratio=0.5` 가 실제 1m 거리 기준 아님. abko FHD1080p 화각에서 1m 거리 사람 bbox_h/image_h 는 ~0.3 추정 (calibrate 미완). 0.5 면 ~50cm 거리 follow 가 됨.

또 사용자가 0.3 (가설값) 으로 시도해도 실 검증 시 사용자 가까이 (bbox 비율 0.6~1.0) 서 있어 err_dist 음수 일관 → robot 이 사람 멀어지려는 cmd 만 발행. 사용자 입장 "안 따라옴".

### 1.8 Wi-Fi 노트북-RPi 다른 주파수

같은 LAN 인 줄 알았으나:
- RPi: `addinedu_201class_4-5G` 5GHz 1.92 Gb/s -49 dBm
- 노트북: `addinedu_201class_2-2.4G` 2.4GHz 275 Mb/s -54 dBm

같은 SSID prefix 지만 mesh AP 두 곳에 분산. person_detector in rate 가 0.1~30Hz 흔들리는 burst 패턴의 한 원인.

---

## 2. 코드 patch 5종

### 2.1 `scripts/run_robot_cam.sh` — DDS multicast 우회

`run_teleop_ui.sh` 패턴 그대로 — 노트북 측 `ROS_STATIC_PEERS=$ROBOT_IP` + RPi nohup 안에 `ROS_STATIC_PEERS=$LAPTOP_IP`. `LAPTOP_IP=$(hostname -I | awk '{print $1}')` 자동 감지.

### 2.2 `scripts/run_vic_bringup.sh` — DDS multicast 우회

같은 패턴.

### 2.3 `src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py` — hardcoded 값 일괄 갱신

| 파라미터 | before | after | 이유 |
|---|---|---|---|
| `target_height_ratio` | 0.5 | 0.3 | 1m 거리 가설값 (calibrate 후속) |
| `image_width` | (default 640) | 640 명시 | 카메라와 일치 |
| `image_height` | (default 480) | 360 | 640x360 다운 + 카메라와 일치 |
| `scan_stop_dist` | 0.45 | 0.30 | jitter 마진 (회고 §3.1 부호 사이드 효과 + 0.46m 빠듯) |
| `kp_angular` | 0.35 | 1.2 | ~3배. 이전 너무 느림 |
| `max_angular` | 0.20 | 0.6 | 3배. 사용자 "회전 줄여" 후 1.0→0.6 |
| `kp_linear` | -0.4 | -0.8 | 절대값 ↑. saturate 까지 가속 |
| `max_linear` | (default 0.20) | 0.4 | 2배 |
| (person_detector) `score_threshold` | (default 0.4) | 0.3 | bbox 검출률 ↑ |
| (person_detector) `detect_rate_hz` | (default 10.0) | 15.0 | 카메라 burst 따라잡기 |

**중요**: 카메라 사이즈와 follow_controller 의 image_width/image_height 가 일치해야 한다는 게 §1.6 의 교훈 — 카메라 변경 시 둘 다 갱신.

### 2.4 `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` — `add_on_set_parameters_callback` 추가

`LIVE_TUNABLE` 화이트리스트:
- `kp_linear`, `kp_angular`, `max_linear`, `max_angular`
- `target_height_ratio`, `angle_deadband`, `dist_deadband`, `align_gate`
- `angle_smoothing_alpha`
- `detection_lost_sec`, `abort_dwell_sec`
- `scan_stop_dist`, `scan_min_range`, `front_arc_deg`

이외 (image_w/h, topic 이름 등) 는 노드 재시동 필요.

callback 이 self.* 인스턴스 변수 직접 갱신. 변경 시 `live param: ...` 로그 출력.

### 2.5 `scripts/follow_tuner.py` — 신규 라이브 튜닝 GUI

tkinter 단일 윈도우:
- 위: `/robot_cam/image_raw/compressed` PIL 변환 후 Label 표시 (~10Hz)
- 아래: 4 슬라이더
  - `max_linear` 0.0~1.0 (init 0.4)
  - `max_angular` 0.0~2.0 (init 0.6)
  - `kp_linear` -2.0~2.0 (init -0.8) — 부호 반전 보정 유지
  - `kp_angular` 0.0~3.0 (init 1.2)
- 상태줄: image 사이즈 + param service ready 표시

slider 변경 → `/follow_controller/set_parameters` 서비스 즉시 호출 (rclpy AsyncClient). callback (§2.4) 에서 self.* 갱신 + `live param: ...` 로그.

threading: rclpy.spin 별 스레드, tkinter mainloop main 스레드. drop-oldest queue 로 image frame 전달.

PIL (apt python3-pil 10.2.0) + cv2 (apt python3-opencv 4.6.0) 만 의존, 추가 설치 없음.

---

## 3. 결과 — 진전 + 잔존 문제

### 3.1 진전

- **DDS 통신 회복**: ROS_STATIC_PEERS 양쪽 명시 후 토픽 정상 흐름
- **follow stack 시동 안정**: 모든 패치 후 `image=640x360 target_h=0.30 kp_v=-0.80 kp_w=1.20 max_v=0.40 max_w=0.60 ...` 의도값 박힘
- **라이브 튜닝 가능**: follow_tuner GUI 슬라이더 → callback → cmd 즉시 반영
- **v=+0.40 saturate 도달**: 이전 v 0.12 max → max_linear 천장 도달. 적극 cmd 발행
- **노트북 5G AP 이동**: 사용자 직접 nmcli. RPi 와 같은 AP, 1.92 Gb/s

### 3.2 잔존 문제

#### 검출 burst 패턴 (DDS reliable 의심)

person_detector in rate 가 5G + 640x360 후에도 burst 패턴:
- 25Hz 안정 구간 등장 (5G 효과)
- 그러나 0.1Hz / 0.3Hz quiet 구간 여전 (10초+)
- 30Hz spike → 0.1Hz dip 패턴

가설: image_transport compressed 의 default reliable QoS 가 ACK 못 받으면 재전송 큐 쌓이고 한번에 풀림. best_effort QoS 패치 또는 RPi 측 inference (image stream 자체 안 보냄) 로 근본 해결.

#### target_h_ratio mismatch (실 follow 동작 미검증)

target_h_ratio=0.3 가설값. 사용자가 어떤 거리에 서도 bbox 비율 항상 0.4~1.0 → err_dist 일관 음수 → robot 항상 "사람 너무 가깝다, 멀어지자" cmd. 사용자 입장 "안 따라옴".

`scripts/calibrate_follow.py` 로 실측 후 결정해야 함. 또는 follow_tuner 슬라이더에 `target_height_ratio` 추가.

---

## 4. 변경 파일 (commit 후보)

| 파일 | 변경 |
|---|---|
| `scripts/run_robot_cam.sh` | DDS multicast 우회 |
| `scripts/run_vic_bringup.sh` | DDS multicast 우회 |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py` | params 일괄 갱신 (image, target_h, gains, score, detect_rate) |
| `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` | `add_on_set_parameters_callback` + LIVE_TUNABLE |
| `scripts/follow_tuner.py` | 신규 (tkinter GUI) |
| `docs/daily/2026-05-07_follow_live_tuning_session.md` | 신규 (본 회고) |

---

## 5. 후속 트랙 (우선순위)

1. **[P1] target_h_ratio 슬라이더 추가** — follow_tuner.py 에 5번째 슬라이더 (0.1~0.9 range). 라이브 캘리브 후 정확값 박기
2. **[P1] follow 실 동작 검증** — 사용자 1m 거리 안정 추종 (본 세션 본 목적, 미완)
3. **[P2] DDS QoS best_effort 검토** — `v4l2_camera_node` + image_transport plugin QoS 변경. burst 근본 해결
4. **[P2] SoT 문서 정정** — `docs/cafe_npc_camera_architecture.md` §3 = abko FHD1080p (HCAM01N → abko)
5. **[P3] follow_tuner GUI 확장** — align_gate / scan_stop_dist / abort_dwell 슬라이더, person_detector 토픽 표시 (bbox overlay)
6. **[P3] RPi 측 inference 이전 (mediapipe RPi 포팅)** — Detection2DArray 만 무선 전송 → bandwidth 95% 절감. 큰 작업. burst 근본 해결의 다른 옵션

---

## 6. 한 줄 요약

> follow 라이브 검증 시도 — 카메라 변경 (HCAM01N→abko) + 라이브 param 무반응 + image size mismatch + Wi-Fi 분산 등 8건 발견. 5종 patch (DDS / launch params / follow_controller callback / GUI 신규 / 5G 이동) 후 cmd v=0.40 saturate + DDS 통신 회복. 단 target_h_ratio mismatch 로 실 follow 동작 (1m 안정 추종) 자체는 미완.
