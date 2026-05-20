---
id: rapport_ema_smoke
category: perception
depth: smoke
duration_sec: 20
requires:
  - package: dobi_npc_emotion
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (RPi 미사용, DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
rapport_tracker_node 의 confidence-weighted EMA 가 V·A jitter 흡수 + smoothed
V·A 를 RapportEvent.emotion 에 발행하는지 확인.

spec: docs/superpowers/specs/2026-05-20-rapport-averaging-window-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 run dobi_npc_emotion rapport_tracker_node &
RAPPORT_PID=$!
sleep 2
```

# 단계

1. **노드 alive + 토픽 등록**
   Run: `ros2 topic list | grep -q /rapport/event`
   Expect: exit 0

2. **outlier 흡수 — single frame V=-1.0 A=+1.0 conf=1.0 publish → abort_trigger 안 발생**

   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -1.0, arousal: 1.0, confidence: 1.0, source: "face", flags: []}'
   sleep 0.5
   ros2 topic echo --once /rapport/event > /tmp/rapport_outlier.txt
   ```
   Expect: `/tmp/rapport_outlier.txt` 안 `event_type: neutral_continue` 또는 `engagement_down` (abort_trigger 아님)

3. **sustained abort — 10 frame V=-0.7 A=+0.6 conf=1.0 publish → abort_trigger 발생**

   ```bash
   for i in $(seq 1 10); do
     ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
       '{header: {frame_id: ""}, valence: -0.7, arousal: 0.6, confidence: 1.0, source: "face", flags: []}'
     sleep 0.1
   done
   sleep 0.3
   ros2 topic echo --once /rapport/event > /tmp/rapport_abort.txt
   ```
   Expect: `/tmp/rapport_abort.txt` 안 `event_type: abort_trigger`

4. **conf gate skip — conf=0.2 frame 후 smoothed 변경 없음**

   ```bash
   # 먼저 sustained neutral 로 EMA 안정화
   for i in $(seq 1 5); do
     ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
       '{header: {frame_id: ""}, valence: 0.0, arousal: 0.0, confidence: 1.0, source: "face", flags: []}'
     sleep 0.1
   done
   # outlier with low conf
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -1.0, arousal: 1.0, confidence: 0.2, source: "face", flags: []}'
   sleep 0.3
   ros2 topic echo --once /rapport/event > /tmp/rapport_gate.txt
   ```
   Expect: `/tmp/rapport_gate.txt` 안 `event_type: neutral_continue` (low conf 무시)

5. **노드 alive 확인**
   Run: `kill -0 $RAPPORT_PID`
   Expect: exit 0

# 기대 결과
- outlier 1 frame 흡수 (single frame V=-1.0 → abort_trigger 안 발생)
- sustained abort 10 frame → abort_trigger
- low confidence frame skip
- 노드 alive

# 클린업
```bash
kill $RAPPORT_PID 2>/dev/null
wait $RAPPORT_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once 의 discovery race — 첫 publish 가 drop 될 수 있음 (sleep 추가).
- abort streak 5 frame 임계 — 9 frame 미만이면 trigger 안 됨.
