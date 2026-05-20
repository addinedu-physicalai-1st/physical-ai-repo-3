---
id: track_id_integration_smoke
category: perception
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: person_tracking_pkg
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
EmotionState.msg 의 track_id + group_id 가 PersonTrackArray closest 의
ID 로 채워지는지 + rapport_tracker EMA 가 track_id 변경 시 cold start 하는지 확인.

spec: docs/superpowers/specs/2026-05-21-track-id-integration-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 run dobi_npc_emotion rapport_tracker &
RAPPORT_PID=$!
sleep 2
```

# 단계

1. **EmotionState msg 가 새 필드 보유 확인**
   Run: `ros2 interface show dobi_npc_msgs/msg/EmotionState | grep -E "track_id|group_id"`
   Expect: `int32 track_id` + `int32 group_id` 두 라인

2. **EmotionState publish (track_id=42 + group_id=0) → RapportEvent.emotion 에 자연 전파**
   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: 0.3, arousal: 0.1, confidence: 0.85, source: "face", flags: [], track_id: 42, group_id: 0}'
   sleep 0.5
   ros2 topic echo --once /rapport/event > /tmp/track_id_test.txt
   grep -E "track_id|group_id" /tmp/track_id_test.txt
   ```
   Expect: `track_id: 42` + `group_id: 0` 포함

3. **track_id 변경 시뮬 — EMA cold start 로그**
   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -0.2, arousal: 0.1, confidence: 0.85, source: "face", flags: [], track_id: 99, group_id: 1}'
   sleep 0.5
   ```
   rapport_tracker 로그 검사: `grep "customer 전환: track_id 42 → 99" /tmp/rapport_*.log`
   Expect: 매칭 라인 1개 (EMA cold start 로그)

4. **track_id=-1 (unknown) 시 EMA 보존 — cold start 안 함**
   ```bash
   ros2 topic pub --once /emotion/state dobi_npc_msgs/msg/EmotionState \
     '{header: {frame_id: ""}, valence: -0.2, arousal: 0.1, confidence: 0.85, source: "face", flags: [], track_id: -1, group_id: -1}'
   sleep 0.5
   ```
   rapport_tracker 로그 검사: `grep "customer 전환: track_id 99 → -1" /tmp/rapport_*.log`
   Expect: 0 매칭 (전환 로그 없음, EMA 보존)

5. **노드 alive**
   Run: `kill -0 $RAPPORT_PID`
   Expect: exit 0

# 기대 결과
- EmotionState msg 의 track_id/group_id 필드 정상
- RapportEvent.emotion 에 자연 전파
- track_id 변경 시 EMA cold start 로그
- track_id=-1 (unknown) 시 EMA 보존
- 노드 alive

# 클린업
```bash
kill $RAPPORT_PID 2>/dev/null
wait $RAPPORT_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once 의 discovery race — 첫 publish drop 가능 (sleep 추가).
- 회귀 시스템 v1 검증 단계라 본 항목 등록만, last_status 는 라이브 검증 후 supervisor 가 갱신.
