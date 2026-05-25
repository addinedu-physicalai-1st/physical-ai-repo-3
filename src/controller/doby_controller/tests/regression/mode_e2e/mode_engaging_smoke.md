---
id: mode_engaging_smoke
category: mode_e2e
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_bringup
  - package: dobi_npc_bt
  - package: dobi_npc_minigame
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
  - cafe_funnel_v1.xml 가 install/share/dobi_npc_bt/ 에 존재
policy_notes:
  - "§0-A 무관: 노트북 단독, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 격리"
  - "§0-B 무관: vic_pinky 자산 미참조"
  - "§11 무관: bt_executor 는 NavigateToPose action client (cmd_vel 발행 X)"
---

# 목적
`mode_engaging.launch.py` (이전 mode_npc) 가 부팅되고 `bt_executor` + `minigame_runner` 두 노드가 alive 상태로 진입하는지 확인. 카메라 3 미연결 / Nav2 미가동 환경에서도 노드 본체는 alive (BT 는 SafetyCheck 에서 wait, minigame_runner 는 idle).

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_engaging.launch.py &
LAUNCH_PID=$!
sleep 8
```

# 단계
1. **bt_executor 노드 등록 확인**
   Run: `ros2 node list | grep -q /bt_executor`
   Expect: exit 0

2. **minigame_runner 노드 등록 확인**
   Run: `ros2 node list | grep -q /minigame_runner`
   Expect: exit 0

3. **/minigame/start 토픽 등록 확인**
   Run: `ros2 topic list | grep -q /minigame/start`
   Expect: exit 0

4. **launch 프로세스 alive 확인**
   Run: `kill -0 $LAUNCH_PID`
   Expect: exit 0

# 기대 결과
- bt_executor + minigame_runner 둘 다 alive
- `/minigame/start` 토픽 등록 (minigame_runner 가 구독)
- `/battery_state` 미수신 시 bt_executor 의 SafetyCheck 가 wait — 노드 자체는 alive
- minigame_runner 는 game subprocess 미실행 idle 상태 (CPU 부담 0)

# 클린업
```bash
kill -INT $LAUNCH_PID 2>/dev/null
sleep 2
kill -9 $LAUNCH_PID 2>/dev/null
wait $LAUNCH_PID 2>/dev/null
unset ROS_DOMAIN_ID ROS_LOCALHOST_ONLY
```

# 알려진 이슈
- `cafe_funnel_v1.xml` 누락 시 bt_executor spawn 직후 종료 → Step 1 fail (install/share/dobi_npc_bt/ 경로 확인)
- BehaviorTree.CPP 4.8.3 미설치 시 bt_executor 빌드 실패 → moca_build 실패로 사전 감지
- mode_npc.launch.py 호출 시 동일 결과 (deprecation wrapper, mode_engaging.launch.py 위임)
- 카메라 3 (game_camera_index=2) 미연결 시에도 minigame_runner 본체는 alive — 게임 subprocess 시작 시점에만 카메라 open
