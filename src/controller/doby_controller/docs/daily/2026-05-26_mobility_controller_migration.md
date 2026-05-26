# 2026-05-26 — 주행 제어 RPi 이관 (mobility_controller)

> 작성: 2026-05-26 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: approach_controller + follow_controller → RPi mobility_controller 이관

---

## 0. 배경

추종 시나리오 전체 연동(2026-05-26 오전 작업) 완료 후,
주행 제어 코드를 RPi에서 실행하기 위해 mobility_controller 패키지로 이관.

### 이관 근거

| 구분 | 실행 위치 | 이유 |
|------|-----------|------|
| AI 연산 (YOLO, ArcFace, GEVA, target_selector) | 노트북 (GPU) | RTX 4060 — 6.9ms 추론. RPi CPU는 100~300ms로 불가 |
| 주행 제어 (approach, follow) | **RPi** | cmd_vel 발행 노드는 로컬 실행이 지연/안전 측면에서 맞음 |

카메라는 RPi에 이미 있고 (`/robot_cam/image_raw`),
AI 결과값 토픽(track_id, bbox, customer_id)만 ROS2 DDS로 넘어오면 됨.

---

## 1. 변경 내용

### mobility_controller 패키지 (신규 추가)

| 파일 | 변경 |
|------|------|
| `scripts/approach_controller_node.py` | 신규 — person_tracking_pkg에서 이관 |
| `scripts/follow_controller_node.py` | 신규 — dobi_npc_bringup에서 이관 |
| `CMakeLists.txt` | ament_cmake_python + install(PROGRAMS) 2개 추가 |
| `package.xml` | rclpy, geometry_msgs, sensor_msgs, vision_msgs, dobi_npc_msgs 의존성 추가 |
| `launch/mobility_controller.launch.py` | 두 노드 + 파라미터 추가 |

### 노트북 launch 파일 (노드 제거)

| 파일 | 변경 |
|------|------|
| `dev_common.launch.py` | approach_controller_node 제거 |
| `mode_follow.launch.py` | follow_controller 제거, unused import 정리 |

---

## 2. 이관 후 전체 아키텍처

```
노트북 (GPU)                              RPi (mobility_controller)
─────────────────────────────────        ─────────────────────────────────
person_tracking_node (YOLO26n)           approach_controller_node
customer_identity_node (ArcFace)   →→→→  follow_controller_node
geva_node (감정 분석)               DDS   mobility_controller_node (C++)
target_selector_node
rapport_tracker

발행 토픽:
  /person_tracking/tracks          →→→→  구독
  /person_tracking/approach_target →→→→  구독
  /customer_pose                   →→→→  구독
  /customer/registry               →→→→  구독
  /follow/target                   →→→→  구독
  /rapport/event                   →→→→  구독
  /scan (RPi RPLiDAR)              ←←←←  발행

결과:
  /bt/cmd_vel     (priority 80) ←←← approach_controller
  /follow/cmd_vel (priority 50) ←←← follow_controller
```

---

## 3. 기술 검증 현황

| 항목 | 상태 |
|------|------|
| mobility_controller 빌드 | ✅ |
| ros2 pkg executables 확인 (3개 등록) | ✅ |
| launch 파일 syntax 검증 | ✅ |
| 실물 RPi 배포 + 통합 테스트 | ⏳ 빅핑키 필요 |

---

## 4. RPi 배포 시 할 일

```bash
# RPi에서 (dobi_npc_msgs 빌드 필요)
cd ~/vicpinky_ws
git clone <repo> src/dobi_npc_msgs
git clone <repo> src/mobility_controller
colcon build --packages-select dobi_npc_msgs mobility_controller
source install/setup.bash
ros2 launch mobility_controller mobility_controller.launch.py
```

---

## 5. 커밋

```
aab3c88 feat(mobility): migrate driving controllers to RPi mobility_controller
```

---

## 6. 다음 세션 진입점

1. **RPi 배포** — dobi_npc_msgs + mobility_controller 빌드
2. **전체 추종 시나리오 실물 테스트** (빅핑키 필요)
   - 노트북: `dev_common.launch.py` + `mode_follow.launch.py`
   - RPi: `mobility_controller.launch.py`
   - GEVA → target_selector → follow_controller 자동 연동 확인

---

*다음 갱신: RPi 배포 + 실물 테스트 후*
