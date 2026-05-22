# 2026-05-20 — follower 시스템 전체 검증 + 버그픽스

> 작성: 2026-05-20 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: run_follower.sh 전체 검증 + 데모 영상 촬영 + 1인 추종 구현 착수

---

## 0. 본 세션 목적

어제(2026-05-19) 수정된 코드(MediaPipe 제거, EMA 필터, 거리 비례 Kp, YOLO26 GPU)를 실물 테스트.
검증 순서: YOLO26 GPU 감지 → 지그재그 수정 → 바퀴/모터 → DBSCAN 그룹 접근 → 파라미터 튜닝 → 데모 영상.

---

## 1. 발견한 버그 및 수정

### 1.1 run_robot_cam.sh — `if false;` 버그

**증상**: 카메라 노드가 시작 안 됨. `/robot_cam/image_raw/compressed` publisher count = 0.

**원인**: `scripts/run_robot_cam.sh` Step 4 (v4l2_camera_node 기동 블록) 전체가 `if false; then`으로 감싸져 있어서 절대 실행 안 됨. 기존 노드를 죽이기만 하고 새로 시작하지 않는 상태.

**수정**: `if false;` → `if true;` (1줄)

### 1.2 dev_common.launch.py — `dbscan_eps: 50.0` (테스트값 잔존)

**증상**: 2명이 카메라 앞에 서 있어도 각각 별도 그룹(group_count=2, 각 1명)으로 분리됨. group_approach_node가 min_group_size=2 조건을 만족하는 그룹을 못 찾아 로봇 안 움직임.

**원인**: launch 파일에 멀티그룹 테스트용 `dbscan_eps: 50.0`이 그대로 남아있었음. 실물 환경에서는 두 사람의 bbox 중심 거리가 50px 이상이라 개별 그룹으로 분리됨.

**수정**: `dbscan_eps: 50.0` → `450.0`

### 1.3 dev_common.launch.py — `min_group_size: 1` → `2`

**증상**: 1명만 서 있어도 그룹으로 인식하고 로봇이 접근함.

**수정**: `min_group_size: 1` → `2` (2명 이상이어야 그룹으로 인식)

### 1.4 dev_common.launch.py 중복 실행

**증상**: 로봇이 전혀 안 움직임 (또는 지그재그). `ros2 node list`에 approach_controller_node, person_tracking_node 등 핵심 노드들이 2개씩 중복.

**원인**: 터미널 두 곳에서 dev_common.launch.py가 각각 실행됨 (20:06, 20:27). 두 approach_controller가 서로 간섭.

**수정**: 나중에 실행된 프로세스 그룹 강제 종료 (kill -SIGINT).

### 1.5 ros2 param set 은 노드 내부 변수에 반영 안 됨

**발견**: `ros2 param set /person_tracking_node dbscan_eps 450.0`을 해도 노드 내부 `self._dbscan` 객체는 init 때 생성된 eps=50.0 그대로 유지.

**이유**: DBSCAN, min_group_size, no_group_threshold 모두 `__init__`에서 한 번만 읽어서 저장. ros2 param set은 파라미터 서버만 업데이트.

**해결 방법**: 올바른 파라미터로 노드 재시작 필요 (`ros2 run ... --ros-args -p param:=value`).

---

## 2. 카메라 교체

**기존**: HCAM01N (Microdia) — USB 접촉 불량, `Error dequeueing buffer: No such device (19)` 반복 발생.

**교체**: SNAP U2 (RPC-20F) — `/dev/video0`, **30Hz 안정** 발행.

run_robot_cam.sh의 자동 탐색 로직(HCAM01N grep)에 해당 안 되지만 fallback /dev/video0으로 정상 인식.

---

## 3. 검증 결과

| 항목 | 결과 |
|---|---|
| run_follower.sh 실행 | ✅ 정상 |
| YOLO26n GPU 감지 | ✅ RTX 4060, 30Hz 카메라 기준 정상 |
| 지그재그 → 일직선 접근 | ✅ EMA 필터 + 거리 비례 Kp 효과 확인 |
| 바퀴 회전 + 모터 전달 | ✅ /bt/cmd_vel → twist_mux → /cmd_vel 정상 |
| DBSCAN 2명 → 그룹 1개 → 접근 | ✅ dbscan_eps=450.0으로 수정 후 정상 |
| 1명 단독 → 접근 안 함 | ✅ min_group_size=2 적용 |
| 데모 영상 | 📹 가라 영상 확보, 정식 영상 재촬영 필요 |

---

## 4. 최종 파라미터 (검증 완료 기준)

| 파라미터 | 값 | 노드 |
|---|---|---|
| dbscan_eps | 450.0 | person_tracking_node |
| yolo_model_path | yolo26n.pt | person_tracking_node |
| yolo_device | cuda:0 | person_tracking_node |
| min_group_size | 2 | group_approach_node |
| no_group_threshold | 2 | group_approach_node |
| angular_gain (kp_far) | 0.8 | approach_controller_node |
| kp_near | 0.3 | approach_controller_node |
| bh_near | 0.5 | approach_controller_node |
| pose_ema_alpha | 0.4 | approach_controller_node |
| dead_zone | 0.10 | approach_controller_node |

---

## 5. 현재 실행 상태 (세션 종료 시점)

- person_tracking_node: 수동 재시작 (dbscan_eps=450, yolo26n.pt GPU)
- group_approach_node: 수동 재시작 (min_group_size=2, no_group_threshold=2)
- approach_controller_node: dev_common launch에서 실행 중
- 카메라: SNAP U2 /dev/video0, 30Hz 정상

⚠ 다음 세션 시작 시 run_follower.sh 전체 재시작 권장 (수동 재시작된 노드들과 launch 노드가 혼재).

---

## 6. 다음 세션 진입점 (2026-05-21)

1. **1인 추종 PD 제어 구현** ← 최우선
   - follow 모드에서 1명을 추종하는 PD 제어
   - approach_controller_node 구조 참고
2. Visual Re-ID + MediaPipe Pose 1인 추종 중 확인
3. 전체 통합 테스트 (run_follower.sh 처음부터)
4. 데모 영상 재촬영 (그룹 감지 + 접근 + 1인 추종 방향 따라가기)

---

*다음 갱신: 2026-05-21 1인 추종 구현 후*
