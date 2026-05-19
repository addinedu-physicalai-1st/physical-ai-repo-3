# vic_pinky RPi 연동 체크리스트 (실물 테스트 직전)

**대상**: 노트북(192.168.0.154, vic_pinky 상단 거치) + vic_pinky RPi 5(192.168.0.138, 계정 `vic`) 통합 첫 실물 테스트.
**전제**: 노트북 단독 트랙(GEVA, EmotionMonitor, TTS, face_avatar) + 후속(utter_done, face/utter sync, abort reset, hysteresis, 로그 정리, 애니메이션 v2, dwell, SafetyCheck 배터리)까지 완료된 상태.
**작성일**: 2026-05-03

---

## 0. 사전 준비 (실물 테스트 전날)

- [ ] **vic_pinky 충전 완료** — `/battery_state.percentage > 0.5` 권장. 0.2 미만이면 SafetyCheck alarm 발동해 호객 차단됨.
- [ ] **RPi에 워크스페이스 sync** — vic_pinky 자체 git이 최신인지 확인. moca 리포는 RPi에 cloning할 필요 없음 (BT executor / face_avatar / TTS 등은 노트북에서 실행).
- [ ] **노트북 mediapipe 모델 다운로드** — `~/moca/scripts/download_models.sh` 1회 실행 (이미 있으면 skip).
- [ ] **dev_all.launch 단독 정상 동작 확인** — 노트북에서만 띄워봐서 GEVA + BT funnel + face/TTS 모두 동작하는지.

---

## 1. 네트워크 / 도메인 설정

### 환경 변수 (양 머신 모두)

```bash
export ROS_DOMAIN_ID=22                    # CLAUDE.md §9 — pinklab 표준
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp # vic_pinky 기본 (변경 안 함)
```

`.bashrc`에 영구 설정 또는 검증 시점에 export.

### 네트워크 검증

```bash
# 노트북에서 RPi ping
ping -c 3 192.168.0.138

# RPi에서 노트북 ping
ssh vic@192.168.0.138
ping -c 3 192.168.0.154
```

### 양 머신 ROS 토픽 발견

```bash
# 노트북 (RPi의 vicpinky 토픽이 보여야)
ros2 topic list | grep -E "battery_state|odom|joint_states|scan|cmd_vel"
# 기대:
#   /battery_state
#   /odom
#   /joint_states
#   /scan
#   /cmd_vel

# RPi (노트북의 dobi_npc 토픽이 보여야)
ssh vic@192.168.0.138
ros2 topic list | grep -E "emotion|rapport|dialog|face_avatar"
```

토픽 안 보이면:
- ROS_DOMAIN_ID 일치 확인
- RMW 구현 동일 확인 (둘 다 fastrtps 또는 cyclonedds)
- 방화벽: `sudo ufw status` (필요 시 비활성)

---

## 2. RPi 측 vicpinky 동작 확인

### 시동
```bash
ssh vic@192.168.0.138
# vic_pinky 자체 launch (벤더 매뉴얼 참조)
ros2 launch vicpinky_bringup bringup.launch.py
```

### 핵심 토픽 발행 확인 (노트북에서)

```bash
# 배터리 상태 (1Hz, percentage 0~1)
ros2 topic echo /battery_state --field percentage --once

# Odometry
ros2 topic hz /odom

# LiDAR scan (Phase 후속 SafetyCheck 통합용)
ros2 topic hz /scan

# Joint states
ros2 topic hz /joint_states
```

### Nav2 서버 확인 (Approach 노드용)

```bash
# action server 응답
ros2 action list | grep navigate_to_pose
# /navigate_to_pose 보여야

# action info
ros2 action info /navigate_to_pose
```

---

## 3. dobi_npc 노드 동작 — 노트북에서만 실행

CLAUDE.md §3 정책: **dobi_npc 시스템은 노트북 단독 실행**. RPi는 vic_pinky bringup만 담당.

```bash
# 노트북에서
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log
```

### 시동 직후 확인 라인

`/tmp/dobi.log`에서:
- `geva_node ... loaded 8/8 expressions`
- `rapport_tracker: /emotion/state -> /rapport/event, hysteresis on=5 off=5`
- `tts_node ready: ...`
- `face_avatar_node: WINDOWED mode 800x600` (또는 FULLSCREEN)
- `Registered: 9 user + 41 builtin nodes` (BT)

---

## 4. 실물 테스트 시나리오

### 4.1 SafetyCheck 배터리 alarm

**기대**: vic_pinky 배터리가 20% 미만이면 호객 funnel 자동 차단.

```bash
# 검증 (실 배터리가 충분할 때): 합성 저전압 1회 publish
ros2 topic pub --once /battery_state sensor_msgs/msg/BatteryState "{percentage: 0.10}"
# 1Hz 실 발행이 즉시 덮어쓰지만 timing 잘 맞으면 한 cycle 동안 alarm 발동 관찰
```

기대 라인:
```
[SafetyCheck] battery low: 10.0% < 20.0% → alarm
safety_alarm: IDLE -> SUCCESS
```

### 4.2 Approach Nav2 통합

**현재 코드**: Nav2 서버 미발견 시 dummy fallback (1.0, 0.0). 서버 연결되면 실 navigate_to_pose 호출.

**시나리오**:
1. vic_pinky bringup + Nav2 stack 띄움
2. dev_all.launch 시동
3. funnel 진입 시 `[Approach]` 로그 확인:
   - 서버 연결 OK이면: `[Approach] Nav2 'navigate_to_pose' 서버 연결 OK` (없으면 추가 로그 필요)
   - 서버 미발견이면: `[Approach] Nav2 ... 서버 미발견 (1.0s). BT 단독 fallback`

**알려진 위험** (Phase 1 W2 회고): Approach가 `/customer_pose` 미수신 시 dummy 좌표 (1.0, 0.0) 사용 → vic_pinky가 랜덤 방향으로 1m 이동. 실물에서 안전 위험. **첫 테스트는 손으로 vic_pinky 잡고 진행 또는 cmd_vel 수동 차단**.

### 4.3 cafe_funnel 1 사이클 통합

**시나리오**:
1. 노트북 카메라 앞에 평범한 표정으로 위치
2. `dev_all.launch` 시동
3. BT 사이클이 자동 진행:
   - SafetyCheck FAILURE (정상 배터리)
   - EmotionMonitor FAILURE (평범 표정 = neutral_continue)
   - cafe_funnel: IdleScan → Approach → IceBreak → Minigame → Offer → LeadIn
4. 각 stage에서 음성/표정 동기화 + utter_done 박자 확인
5. 전체 사이클 약 15~20초 (3 utter × 3~5초)

### 4.4 abort 시나리오 — 합성 또는 카메라

**합성** (가장 통제 가능):
```bash
# 별도 터미널 — abort_trigger 직접 publish (rapport_tracker 우회)
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: -1.0, reason: 'manual',
    emotion: {valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}}"
```

기대 (3 컴포넌트 동시):
- `[EmotionMonitor] abort_trigger ON`
- `[tts_node] abort_trigger → mixer.stop()`
- `[face_avatar] abort_trigger → face: <X> -> basic (dwell 2.0s)`

**카메라** (V<-0.5 ∧ A>+0.4 충족 + hysteresis 5프레임 연속):
- 강한 angry 또는 fear 표정을 0.5초 이상 유지
- rapport_tracker 로그: `event: ... -> abort_trigger`

---

## 5. 주의 사항 / 위험

### 안전
- **Approach가 dummy goal을 Nav2에 보낼 위험** (W2 회고): /customer_pose 미수신 + Nav2 서버 연결 시. 첫 실물 테스트엔 vic_pinky 비상 정지(cmd_vel 차단) 준비.
- **저전압 시 vic_pinky 자체 보호** + dobi_npc SafetyCheck alarm 둘 다. 이중 안전.
- **음성 출력**: 카페 환경 가정. 노트북 스피커 충분한지. 너무 시끄러우면 손님 부담.

### 자동 동작 차단 옵션 (검증 시)
- BT만 띄우고 vic_pinky cmd_vel 안 보내려면: Approach 노드가 dummy일 때 `/cmd_vel` publish 안 함 (이미 그렇게 됨, W2 회고 §3 참조)
- TTS 끄려면: `tts_node` 노드만 빼고 다른 5개 띄우기 (dev_all.launch 수정 또는 직접 ros2 run)

### 좀비 정리
모든 검증 후:
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
pgrep -af "geva|rapport|bt_executor|persona|face_avatar|tts_node" | grep -v grep || echo "정리됨"
```

---

## 6. 결과 보고 항목 (실물 테스트 후 회고용)

| 항목 | 통과 / 실패 / 메모 |
|---|---|
| RPi-노트북 ROS 토픽 발견 | |
| /battery_state 1Hz 수신 (실 배터리) | |
| SafetyCheck 정상 배터리에서 FAILURE 유지 | |
| SafetyCheck 합성 저전압에서 alarm 발동 | |
| Nav2 서버 연결 (Approach) | |
| Nav2 dummy goal 송신 여부 (안전 확인) | |
| cafe_funnel 1 사이클 정상 (15~20초) | |
| utter_done 박자 자연 (음성 잘림 없음) | |
| face/utter 시작 동기화 (시각/청각 일치) | |
| abort 합성 publish — 3 컴포넌트 반응 | |
| abort 카메라 시도 — hysteresis 작동 | |
| 좀비 누적 여부 | |

---

## 7. 보류된 후속 (실물 테스트 결과 후 결정)

- **W2.5 GEFA**: RPi USB 카메라(RPC-20F) → 자세/접근/회피 분석 노드
- **decision_rule_node**: GEVA + GEFA fusion (Salichs 2014)
- **min_confidence 임계**: rapport_tracker GEVA 신뢰도 게이팅
- **Approach 안전 정책 강화**: dummy goal 시 Nav2 송신 금지 명시
- **SafetyCheck /scan 통합**: 1.0m 이내 인간 감지 추가
- **face_avatar brightest 시작 옵션**: fade-in 검정 회피
- **음성/표정 dwell 통합**: tts_node에 abort dwell

---

**상태**: 실물 테스트 직전 점검 가능. 모든 항목은 노트북-only 검증 또는 RPi 연결 후 검증.
