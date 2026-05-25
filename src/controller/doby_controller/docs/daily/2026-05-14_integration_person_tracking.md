# 2026-05-14 — person_tracking_pkg 통합 + Nav2 연동 검증

## 작업 개요

팀원이 텔레옵 소스에 Nav2를 통합해 보내준 moca 워크스페이스를 기준으로,
본인 작업인 `person_tracking_pkg`를 최종 통합하고 문제를 점검·해결했다.

---

## 1. 팀원 Nav2 통합 검증

팀원이 추가한 항목:
- `scripts/run_nav2.sh` / `scripts/stop_nav2.sh` — smac_hybrid + MPPI 기동/정지 스크립트
- `dobi_npc_msgs/PersonTrack.msg`, `PersonTrackArray.msg` — 추적 메시지 정의
- `CMakeLists.txt` — 신규 메시지 등록

cmd_vel 체인 전체 연결 확인:

```
/joy/cmd_vel  (priority 100) ← teleop_server.py
/bt/cmd_vel   (priority  80) ← Nav2 controller (bringup_smachybrid_mppi_launch.xml)
/follow/cmd_vel (priority 50) ← follow_controller_node
        ↓
   twist_mux → /cmd_vel_raw
        ↓
   velocity_smoother → /cmd_vel_smoothed
        ↓
   collision_monitor → /cmd_vel → zlac_driver
```

주요 검증 포인트:
- `bringup_smachybrid_mppi_launch.xml`: `cmd_vel_topic="/bt/cmd_vel"`, `use_velocity_smoother=False` ✅
- `teleop_server.py:998`: `/joy/cmd_vel` 발행 ✅
- `follow_controller_node.py:54`: `cmd_vel_topic='/follow/cmd_vel'` ✅
- `twist_mux.yaml` → `bringup.launch.xml` → `velocity_smoother.yaml` → `collision_monitor.yaml` 전 구간 연결 확인 ✅
- `run_nav2.sh`: 시계 drift 검사, RPi bringup 환경 검증, AMCL active 대기, lifecycle watcher 포함 ✅

결론: **텔레옵 ↔ Nav2 통합 이상 없음.**

---

## 2. person_tracking_pkg 통합

### 패키지 구성
- `person_tracking_node.py`: YOLOv8 + BoT-SORT + DBSCAN + MediaPipe Pose
  - 구독: `/robot_cam/image_raw` (run_robot_cam.sh 발행)
  - 발행: `/person_tracking/tracks` (PersonTrackArray)
- `group_approach_node.py`: 가장 큰 그룹 선정
  - 구독: `/person_tracking/tracks`
  - 발행: `/person_tracking/approach_target` (Int32, group_id)

### 통합 작업
- `dev_common.launch.py`에 `person_tracking_node` + `group_approach_node` 추가
  - `input_topic: /robot_cam/image_raw`, `use_compressed: True`
  - `min_group_size: 2`
- `camera.launch.py` (패키지 내장)는 moca에서 **미사용** — `run_robot_cam.sh`가 이미 `/robot_cam/image_raw` 담당

### 충돌 없음 확인
- `person_detector_node` (mode_follow, `/image_raw`) vs `person_tracking_node` (`/robot_cam/image_raw`) — 서로 다른 카메라/토픽, 충돌 없음
- 토픽 중복 없음, 노드 이름 중복 없음

---

## 3. 발견 및 해결 — pip 의존성 충돌

### 문제
`ultralytics`(YOLOv8) pip 설치 시 numpy 2.x + opencv pip 버전이 함께 설치되어 moca 기준 위반:

| 항목 | 충돌 상태 | moca 기준 |
|---|---|---|
| numpy | 2.4.4 (pip user site) | 1.26.4 (시스템 apt) |
| opencv-python | 4.9.0 (pip) | — |
| opencv-contrib-python | 4.13.0 (pip) | 4.6.0 (시스템 apt) |

ROS 노드 실행 시 cv_bridge(시스템 cv2 4.6.0 기준 컴파일)가 pip cv2 4.13.0을 로딩해 런타임 충돌 위험.

### 해결
```bash
pip uninstall --yes numpy opencv-python opencv-contrib-python
```

결과:
- numpy: 1.26.4 (시스템 apt) ✅
- cv2: 4.6.0 (시스템 apt) ✅
- ultralytics 8.4.48, boxmot, sklearn: 시스템 버전으로 정상 동작 확인 ✅
- cv_bridge: 정상 ✅

---

## 4. 빌드 검증

```bash
colcon build --packages-select dobi_npc_msgs person_tracking_pkg dobi_npc_bringup
# → 3개 패키지 모두 통과
```

---

## 5. 커밋

```
13ff8b6 person_tracking_pkg 통합 + Nav2 기동 스크립트 추가
```

---

---

## 6. 전체 점검 — 추가 문제 발견 및 해결

### 빌드 캐시 문제
pip numpy 제거 후 전체 빌드 시 `dobi_npc_msgs` 빌드 실패:
```
fatal error: numpy/ndarrayobject.h: No such file or directory
```
원인: 이전 빌드 캐시가 pip numpy 경로를 참조하고 있었음.
해결: `build/dobi_npc_msgs` 삭제 후 재빌드 → 전체 9개 패키지 통과.

### matplotlib pip 충돌
numpy/opencv와 동일한 패턴으로 pip matplotlib 3.10.9이 user site에 설치되어
시스템 apt matplotlib 3.6.3과 중복, `Axes3D` import 경고 발생.
```bash
pip uninstall --yes matplotlib
```
결과: 시스템 apt matplotlib 3.6.3 복원, ultralytics 정상 동작 확인.

### 최종 전체 점검 결과

| 항목 | 상태 |
|---|---|
| 전체 빌드 (9개 패키지) | ✅ |
| 패키지/메시지 등록 | ✅ |
| launch 파일 파싱 | ✅ |
| numpy 1.26.4 / cv2 4.6.0 / matplotlib 3.6.3 (시스템 apt) | ✅ |
| cv_bridge / ultralytics / boxmot / sklearn / mediapipe | ✅ |
| 스크립트 실행 권한 | ✅ |
| git 상태 | 클린 ✅ |

---

## 7. person_tracking_node.py — 3개 누락 기능 추가 (moca 기준 구현)

원본 소스(`/home/soon/Desktop/driving/person_tracking_step1.py`)에 있던 3개 기능이
통합 과정에서 ROS2 변환이 안 된 상태였음. moca 표준에 맞춰 구현.

### 7-1. BoT-SORT → `/customer_pose` (PoseStamped) 변환

- 추가 구독: `/person_tracking/approach_target` (Int32) — group_approach_node 가 선정한 그룹 ID
- 추가 발행: `/customer_pose` (PoseStamped) — frame_id=`robot_cam_link`, x=bbox_cx/W, y=bbox_cy/H (0~1 정규화)
- 로직: 타깃 그룹 내 가장 큰 bbox 사람 한 명 선정 → PoseStamped.position.x/y 에 정규화 좌표 기입

### 7-2. InvalidHandle 레이스컨디션 수정

- `self._alive = True` 플래그 추가
- `_cb_compressed`, `_cb_image`, `_publish_customer_pose` 진입 시 `if not self._alive: return`
- `destroy_node()` 에서 `self._alive = False` 먼저 세팅 후 리소스 해제
- 이유: destroy_node() 호출과 콜백 동시 진입 시 MediaPipe/YOLO 핸들 해제 후 참조 방지

### 7-3. 타이머 콜백 executor 독점 수정

- `MutuallyExclusiveCallbackGroup` 2개 분리: `_cb_group_img` (이미지), `_cb_group_ctrl` (제어)
- 이미지 구독 2종 → `_cb_group_img` 지정
- approach_target 구독 → `_cb_group_ctrl` 지정
- `main()`: `MultiThreadedExecutor(num_threads=2)` 로 변경
- 이유: SingleThreadedExecutor 에서 이미지 처리(무거운 연산)가 제어 콜백을 블로킹하는 문제 해결

### 빌드 재검증

```bash
colcon build --packages-select person_tracking_pkg
# Finished <<< person_tracking_pkg [1.53s]
```

import smoke test 통과:
```
import OK — InvalidHandle/executor/customer_pose 구현 확인
```

---

## 8. moca 기준 토픽명 확정

원본 체크리스트의 토픽명/메시지 형식이 moca 기준으로 변경 적용됨. 이후 모든 작업에서 아래 moca 기준 사용:

| 원본 체크리스트 | moca 기준 (확정) |
|---|---|
| `/robot_cam/persons` (Detection2DArray) | `/person_tracking/tracks` (PersonTrackArray) |
| `/cluster_groups` (JSON) | `PersonTrack.group_id` 필드에 통합 |
| `/robot_cam/annotated` | `/person_tracking/image` |

---

## 9. 3단계 소프트웨어 연결 확인 완료

| 항목 | 상태 |
|---|---|
| Vic Pinky bringup 실행 + `/odom`, `/scan`, `/joint_states`, `/battery_state` 토픽 발행 | ✅ |
| RPi(192.168.0.138) ↔ 노트북(ROS_DOMAIN_ID=22) ROS2 네트워크 통신 연결 | ✅ |
| 노트북 카메라로 실제 사람 감지 + 그룹 분류 + ID 고정 + 골격 표시 | ✅ |
| `/person_tracking/image` 실시간 처리 영상 출력 | ✅ |
| `group_approach_node` 실행 + 그룹 감지 시 `/bt/cmd_vel` 체인 발행 | ✅ |

---

## 다음 단계 — 3단계 실물 동작 검증 (내일)

실행 순서:
```bash
# 터미널 1
bash ~/moca/scripts/run_robot_cam.sh

# 터미널 2
bash ~/moca/scripts/run_nav2.sh

# 터미널 3
ros2 launch dobi_npc_bringup dev_common.launch.py
```

검증 항목:
1. `/bt/cmd_vel` → twist_mux → `/cmd_vel` → Vic Pinky 모터 실제 전달 확인
2. Vic Pinky 바퀴 실제 회전 및 이동 눈으로 확인
3. 2명 이상 감지 시 DBSCAN 그룹 → 로봇 실제 그룹 방향 접근 확인
4. 접근 거리 및 속도 파라미터 튜닝 (너무 가깝거나 멀지 않게)
5. 1인 추종 PD 제어 구현 및 검증 (사람 이동 시 거리·방향 유지)

부가 확인:
- `run_robot_cam.sh` RPi HCAM01N `/robot_cam/image_raw` 발행 확인
- SafetyCheck `/scan` 1.0m 임계값 + `scan_min_range=0.25m` 실물 튜닝
- `target_height_ratio=0.5` 라이브 캘리브 (follow_controller, HCAM01N 화각 기준)
- `group_approach_node` → `/customer_pose` → BT → Nav2 → `/bt/cmd_vel` end-to-end 체인 확인
