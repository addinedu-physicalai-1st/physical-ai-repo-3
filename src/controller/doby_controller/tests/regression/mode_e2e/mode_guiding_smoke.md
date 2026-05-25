---
id: mode_guiding_smoke
category: mode_e2e
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_bringup
  - package: dobi_npc_emotion
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
  - tables.yaml 가 install/share/dobi_npc_bringup/config/ 에 존재
policy_notes:
  - "§0-A 무관: 노트북 단독, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 격리"
  - "§0-B 무관: vic_pinky 자산 미참조"
  - "§11 무관: guiding_controller 는 NavigateToPose action client (cmd_vel 발행 X)"
---

# 목적
`mode_guiding.launch.py` 가 부팅되고 `person_detector` + `guiding_controller` 두 노드가 alive 상태로 진입하는지 확인. 카메라/Nav2 미가동 환경에서도 노드 본체는 alive.

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_guiding.launch.py params_json:='{"target_table":"T02","customer_id":"smoke-test"}' &
LAUNCH_PID=$!
sleep 8
```

# 단계
1. **person_detector 노드 등록 확인**
   Run: `ros2 node list | grep -q /person_detector`
   Expect: exit 0

2. **guiding_controller 노드 등록 확인**
   Run: `ros2 node list | grep -q /guiding_controller`
   Expect: exit 0

3. **/guiding/state 토픽 등록 확인**
   Run: `ros2 topic list | grep -q /guiding/state`
   Expect: exit 0

4. **launch 프로세스 alive 확인**
   Run: `kill -0 $LAUNCH_PID`
   Expect: exit 0

# 기대 결과
- person_detector + guiding_controller 둘 다 alive
- `/guiding/state` 토픽 등록 (1Hz 발행, smoke 는 등록만 검증)
- 카메라 미연결 시 person_detector 는 alive 유지 (input wait 상태)
- Nav2 미가동 시 guiding_controller 는 wait_for_server block (alive)

# 클린업
```bash
kill -INT $LAUNCH_PID 2>/dev/null
sleep 2
kill -9 $LAUNCH_PID 2>/dev/null
wait $LAUNCH_PID 2>/dev/null
unset ROS_DOMAIN_ID ROS_LOCALHOST_ONLY
```

# 알려진 이슈
- mediapipe / efficientdet_lite0 미설치 시 person_detector spawn 직후 종료 → Step 1 fail (CLAUDE.md §7 의존성 확인)
- `tables.yaml` 누락 시 guiding_controller 즉시 종료 → Step 2 fail
- params_json 누락 시 controller 가 target_table 결정 못 함 — 본 smoke 는 dummy params 전달
