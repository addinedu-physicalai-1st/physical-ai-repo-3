---
id: mode_patrol_smoke
category: mode_e2e
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_bringup
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
  - tables.yaml 가 install/share/dobi_npc_bringup/config/ 에 존재
policy_notes:
  - "§0-A 무관: 노트북 단독, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 격리"
  - "§0-B 무관: vic_pinky 자산 미참조"
  - "§11 무관: scheduler 는 NavigateToPose action client (cmd_vel 발행 X)"
---

# 목적
`mode_patrol.launch.py` 가 부팅되고 `table_occupancy_detector` + `patrol_scheduler` 두 노드가 alive 상태로 진입하는지 확인. ultralytics 미설치 시 detector 는 degrade 모드로 alive (unknown 응답).

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_patrol.launch.py &
LAUNCH_PID=$!
sleep 8
```

# 단계
1. **table_occupancy_detector 노드 등록 확인**
   Run: `ros2 node list | grep -q /table_occupancy_detector`
   Expect: exit 0

2. **patrol_scheduler 노드 등록 확인**
   Run: `ros2 node list | grep -q /patrol_scheduler`
   Expect: exit 0

3. **/table_occupancy/scan 서비스 등록 확인**
   Run: `ros2 service list | grep -q /table_occupancy/scan`
   Expect: exit 0

4. **launch 프로세스 alive 확인**
   Run: `kill -0 $LAUNCH_PID`
   Expect: exit 0

# 기대 결과
- detector + scheduler 둘 다 alive
- scan 서비스 advertise
- ultralytics 설치 여부와 무관하게 detector 본체는 alive (degrade gracefully)
- scheduler 는 Nav2 wait_for_server 로 block 상태 (smoke 는 alive 만 검증)

# 클린업
```bash
kill -INT $LAUNCH_PID 2>/dev/null
sleep 2
kill -9 $LAUNCH_PID 2>/dev/null
wait $LAUNCH_PID 2>/dev/null
unset ROS_DOMAIN_ID ROS_LOCALHOST_ONLY
```

# 알려진 이슈
- yolov8n.pt 미존재 시 detector 가 unknown 모드로 alive 유지 (CMakeLists.txt install/share/models/ 확인)
- `tables.yaml` 누락 시 scheduler spawn 직후 종료 → Step 2 fail
- /camera/image_raw 미가동 시 detector 가 frame_stale → degraded 응답 (smoke 는 alive 만 검증)
