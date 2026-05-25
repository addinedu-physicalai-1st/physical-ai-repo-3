---
id: mode_idle_smoke
category: mode_e2e
depth: smoke
duration_sec: 15
requires:
  - package: dobi_npc_bringup
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 격리"
  - "§0-B 무관: vic_pinky 자산 미참조"
  - "§11 무관: cmd_vel 토픽 발행 X"
---

# 목적
mode_manager 노드가 standalone 으로 부팅되어 `current_mode='idle'` 을 `/mode/state` 로 발행하는지 확인. idle 은 launch stack 없음 (mode_manager no_stack ok).

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 run dobi_npc_bringup mode_manager &
MM_PID=$!
sleep 3
```

# 단계
1. **노드 등록 확인**
   Run: `ros2 node list | grep -q /mode_manager`
   Expect: exit 0

2. **/mode/state 발행 확인**
   Run: `timeout 5 ros2 topic echo --once /mode/state`
   Expect: stdout 에 `current_mode: idle` 포함

3. **노드 alive 확인**
   Run: `kill -0 $MM_PID`
   Expect: exit 0 (프로세스 살아있음)

# 기대 결과
- `/mode/state` `current_mode` 필드 = `"idle"`
- `battery_ok`, `safety_ok` 필드 존재 (값은 환경에 따라 다름 — 발행 자체만 검증)

# 클린업
```bash
kill $MM_PID 2>/dev/null
wait $MM_PID 2>/dev/null
unset ROS_DOMAIN_ID ROS_LOCALHOST_ONLY
```

# 알려진 이슈
- DOMAIN=22 (라이브) 환경에서는 §0-A 정책 확인 필수 → 본 smoke 는 DOMAIN=99 격리 가정
- mode_manager 가 `/battery_state` 미수신 시 `battery_ok=false` 로 표기 — smoke 단계에선 정상
