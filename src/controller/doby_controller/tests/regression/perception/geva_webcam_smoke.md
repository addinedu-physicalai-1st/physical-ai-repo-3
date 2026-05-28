---
id: geva_webcam_smoke
category: perception
depth: smoke
duration_sec: 15
requires:
  - device: camera_1
  - package: dobi_npc_emotion
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
  - mediapipe 0.10.14 user pip 설치됨 (CLAUDE.md §7)
policy_notes:
  - "§0-A 무관: 노트북 단독 (RPi 미사용)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
GEVA 노드(`geva_node`)가 노트북 웹캠(`camera_1`)을 열고 `/emotion/state` 토픽을 발행하는지 확인.

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run dobi_npc_emotion geva_node &
GEVA_PID=$!
sleep 3
```

# 단계
1. **토픽 등록 확인**
   Run: `ros2 topic list | grep -q /emotion/state`
   Expect: exit 0 (토픽 존재)

2. **메시지 발행 확인**
   Run: `timeout 5 ros2 topic echo --once /emotion/state`
   Expect: stdout 에 `source: "face"` 포함 + `confidence:` 값이 0 초과

3. **노드 alive 확인**
   Run: `kill -0 $GEVA_PID`
   Expect: exit 0 (프로세스 살아있음)

# 기대 결과
- `/emotion/state` 발행 주기 ≥ 1Hz (Hz 단위 별도 측정 미포함, v1 은 1회 echo 로 충분)
- `valence`, `arousal` 범위 [-1.0, 1.0] (echo 결과 시각 확인)
- `source = "face"`

# 클린업
```bash
kill $GEVA_PID 2>/dev/null
wait $GEVA_PID 2>/dev/null
```

# 알려진 이슈
- mediapipe `0.10.14` user pip 미설치 시 `geva_node` import 실패 → precondition 미달로 skip
- 웹캠 미연결 (`/dev/video0` 없음) 시 노드 spawn 직후 종료 → Step 3 fail
- 시스템 numpy 2.x 면 cv_bridge 충돌 → `pip uninstall numpy opencv-contrib-python` 후 시스템 apt numpy 1.26.4 복구 필요 (CLAUDE.md §7)
