# 2026-05-15 작업기록 — approach_controller_node 구현 + 3단계 E2E 실물 검증

## 요약

3단계 소프트웨어 연결 검증을 완료했다.
approach_controller_node 를 신규 구현하고, 카메라 앞에 선 사람을 로봇이 실제로 추종하는 것을 확인했다.

---

## 1. 세션 시작 시점 상태

이전 세션에서 컴퓨터가 꺼져 작업이 중단됨. 재시작 후:
- 2단계 (ROS2 소프트웨어 통합) 는 이미 완료·커밋된 상태.
- 3단계 실물 검증 중 approach_controller_node 가 누락된 것 발견.
- 관련 미커밋 파일들 (dbscan_eps 튜닝, 히스테리시스, run_3stage.sh) 먼저 커밋 후 진행.

---

## 2. approach_controller_node 구현

### 누락 배경

`dev_common.launch.py` 에 `approach_controller_node` 를 등록했으나, 실제 Python 파일이 없었다.
`/bt/cmd_vel` Publisher count: 0 이 확인되어 발견함.

### 구현 내용

**파일**: `src/dobi_npc/person_tracking_pkg/person_tracking_pkg/approach_controller_node.py`

```
구독: /customer_pose (PoseStamped — 정규화 픽셀 cx, cy)
      /person_tracking/approach_target (Int32)
발행: /bt/cmd_vel (Twist)
```

**P 제어 로직**:
- `angular.z = -1.2 * (cx - 0.5)` — 좌우 오차를 각속도로
- `linear.x = 0.15` — cy < 0.72 (사람이 멀리 있을 때) 전진
- dead_zone 0.05 — 작은 각도 오차 무시
- pose_timeout 1.0s — 사람이 사라지면 즉시 정지

**파라미터** (dev_common.launch.py에 등록):

| 파라미터 | 기본값 |
|---|---|
| linear_speed | 0.15 m/s |
| angular_gain | 1.2 |
| dead_zone | 0.05 (정규화) |
| close_threshold | 0.72 (cy 비율) |
| pose_timeout | 1.0 s |
| cmd_rate | 10.0 Hz |

### setup.py 수정

`approach_controller_node` entry point 추가.

### dev_common.launch.py 수정

- `min_group_size` 2 → 1 (1인 감지 가능하도록)
- `approach_controller_node` Node 등록

---

## 3. 실물 검증 과정

### 환경

- 노트북 (192.168.0.139): `dev_common.launch.py` — person_tracking, group_approach, approach_controller
- RPi (192.168.0.138): vicpinky_bringup — twist_mux, velocity_smoother, collision_monitor, zlac_driver
- 카메라: `run_robot_cam.sh` — RPi USB HCAM01N → `/robot_cam/image_raw` (640x480 YUYV)

### DDS 연결 특이사항

노트북-RPi 간 DDS discovery 에 약 10초 소요됨 (Wi-Fi 유니캐스트 환경).
처음 `/bt/cmd_vel` 발행 시 RPi 측에서 수신까지 지연이 있으나, 연결 후 지속 작동.

### cmd_vel 체인 검증 결과

```
노트북: /bt/cmd_vel (approach_controller_node)
  ↓  (DDS, ~10s discovery)
RPi:  twist_mux (/cmd_vel_raw)
        ↓
      velocity_smoother (/cmd_vel_smoothed)
        ↓
      collision_monitor (/cmd_vel)
        ↓
      zlac_driver → 모터
```

모든 단계에서 `x: 0.1` 통과 확인.

### E2E 결과

카메라 앞에 사람이 서자 로봇이 실제로 추종함. **3단계 E2E 검증 완료**.

---

## 4. 발견된 이슈 및 처리

| 이슈 | 처리 |
|---|---|
| mode_manager 중복 프로세스 (6개) | 이전 세션 잔재. 현재 미정리 — 기능 동작에 영향 없음. 다음 세션 시작 시 전체 kill 필요 |
| collision_monitor TF_OLD_DATA 경고 | 재시작 직후 과거 TF 프레임 잔재. 수초 후 자동 해소됨 |
| e_stop topic echo 미수신 | SSH 새 세션의 DDS discovery 지연. 실제 lock 여부는 비영향(정상 동작 확인) |
| 수동 테스트 pub 프로세스 잔존 | kill 후 정리 완료 |

---

## 5. 커밋 목록

| 커밋 | 내용 |
|---|---|
| `4dd7892` | person_tracking_pkg: 3단계 실물 튜닝 — dbscan_eps + 히스테리시스 + run_3stage.sh |
| `2e5ffb9` | approach_controller_node: 1인 추종 P 제어 구현 + 3단계 E2E 검증 완료 |

---

## 6. 미완료 / 후속 과제

- [ ] **파라미터 튜닝**: linear_speed, angular_gain, close_threshold 라이브 검증 (오늘은 기본값으로 동작 확인만)
- [ ] **2인 이상 그룹 추종**: min_group_size=1 이므로 1인 동작 확인. 그룹 선택 로직(가장 큰 DBSCAN cluster)은 구현됨 — 다수인 테스트 필요
- [ ] **mode_manager 중복 프로세스 정리**: 세션 시작 시 기존 프로세스 전체 kill 절차 스크립트화
- [ ] **DDS 초기 연결 지연 해소**: 노트북 시작 시 RPi에 dummy pub 선행 발행하여 10초 지연 제거
- [ ] **일일 로그 작성 자동화**: run_3stage.sh 에 프로세스 정리 단계 추가

---

*작성: 2026-05-15*
*다음 세션: 파라미터 튜닝 + 그룹 추종 테스트*
