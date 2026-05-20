---
id: engagement_timeline_smoke
category: perception
depth: smoke
duration_sec: 25
requires:
  - package: dobi_npc_emotion
  - package: dobi_npc_msgs
  - package: moca_opserver
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
policy_notes:
  - "§0-A 무관: 노트북 단독 (DOMAIN=99 sim 격리)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
opserver 의 engagement_score EMA 가 RapportEvent.weight 누적 + track_id 변경 시
cold start + WS payload 에 'engagement' 필드 정상 전파 확인.

spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

ros2 launch moca_opserver opserver.launch.py &
OPS_PID=$!
sleep 3
```

# 단계

1. **opserver 준비**
   Run: `curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8800/api/v1/health`
   Expect: `200`

2. **engagement.score = 0 (초기, RapportEvent 없음)**
   WebSocket /ws/v1/engaging 1 메시지 확인:
   ```bash
   python3 -c "
   import asyncio, json
   import websockets
   async def main():
       async with websockets.connect('ws://localhost:8800/ws/v1/engaging') as ws:
           raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
           d = json.loads(raw)
           print('score:', d['engagement']['score'])
           print('score_history:', len(d['engagement']['score_history']))
           print('rapport_markers:', len(d['engagement']['rapport_markers']))
   asyncio.run(main())
   "
   ```
   Expect: `score: 0.0` + `score_history: 0` + `rapport_markers: 0`.

3. **RapportEvent 시퀀스 publish — engagement_up × 5 + abort_trigger × 1**
   ```bash
   for i in 1 2 3 4 5; do
     ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
       "{header: {frame_id: \"\"}, event_type: \"engagement_up\", weight: 0.5, reason: \"test\", emotion: {valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
     sleep 0.1
   done
   sleep 0.3
   ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
     "{header: {frame_id: \"\"}, event_type: \"abort_trigger\", weight: -1.0, reason: \"test\", emotion: {valence: -0.7, arousal: 0.6, confidence: 0.85, source: \"face\", flags: [], track_id: 42, group_id: 0}}"
   sleep 0.5
   ```
   WS 재확인 + score / score_history 길이 / marker types 출력. Expect: `score` 약 0 근처 + `score_history: 6` + `rapport_markers: 6` + `marker types: [engagement_up × 5, abort_trigger × 1]`.

4. **track_id 변경 (42 → 99) → score cold start**
   ```bash
   ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
     "{header: {frame_id: \"\"}, event_type: \"engagement_up\", weight: 0.5, reason: \"test\", emotion: {valence: 0.3, arousal: 0.1, confidence: 0.85, source: \"face\", flags: [], track_id: 99, group_id: 1}}"
   sleep 0.5
   ```
   opserver stdout 에서 `engagement_score cold start: track_id 42 → 99` 로그 확인.

5. **노드 alive**
   Run: `kill -0 $OPS_PID`
   Expect: exit 0

# 기대 결과
- engagement_snapshot 의 3 필드 (score / score_history / rapport_markers) 정상 노출
- engagement_up/abort_trigger marker 만 누적 (neutral_continue 제외)
- track_id 변경 시 cold start 로그
- opserver alive

# 클린업
```bash
kill $OPS_PID 2>/dev/null
wait $OPS_PID 2>/dev/null
```

# 알려진 이슈
- ros2 topic pub --once discovery race — sleep 적용
- 회귀 시스템 v1 검증 단계라 본 항목 등록만, last_status 는 라이브 검증 후 supervisor 갱신.
