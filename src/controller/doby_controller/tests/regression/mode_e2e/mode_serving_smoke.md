---
id: mode_serving_smoke
category: mode_e2e
depth: smoke
duration_sec: 20
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
  - "§11 무관: dispatcher 는 NavigateToPose action client (cmd_vel 발행 X)"
---

# 목적
`mode_serving.launch.py` 가 부팅되고 `serving_dispatcher` 노드가 alive 상태로 진입하는지 확인. Nav2 미가동 환경에서도 dispatcher 노드 자체는 살아있어야 함 (action client wait_for_server 상태).

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_serving.launch.py &
LAUNCH_PID=$!
sleep 5
```

# 단계
1. **serving_dispatcher 노드 등록 확인**
   Run: `ros2 node list | grep -q /serving_dispatcher`
   Expect: exit 0

2. **/serving/state 토픽 등록 확인**
   Run: `ros2 topic list | grep -q /serving/state`
   Expect: exit 0

3. **/serving/state 메시지 발행 확인**
   Run: `timeout 5 ros2 topic echo --once /serving/state`
   Expect: stdout 에 dispatcher state 필드 (예: `status:`) 포함

4. **launch 프로세스 alive 확인**
   Run: `kill -0 $LAUNCH_PID`
   Expect: exit 0

# 기대 결과
- `serving_dispatcher` 노드 alive
- `/serving/state` 1Hz 발행 (smoke 단계는 1회 echo 로 충분)
- `tables.yaml` 정상 로드 (실패 시 dispatcher 즉시 종료 → Step 4 fail)

# 클린업
```bash
kill -INT $LAUNCH_PID 2>/dev/null
sleep 2
kill -9 $LAUNCH_PID 2>/dev/null
wait $LAUNCH_PID 2>/dev/null
unset ROS_DOMAIN_ID ROS_LOCALHOST_ONLY
```

# 알려진 이슈
- Nav2 미가동 시 dispatcher 는 NavigateToPose wait_for_server 로 block — smoke 는 노드 alive 만 확인
- `tables.yaml` 누락 시 dispatcher spawn 직후 종료 → install 경로 확인 (`install/share/dobi_npc_bringup/config/tables.yaml`)
- launch 자식 프로세스 종료가 느리면 클린업 SIGKILL fallback
