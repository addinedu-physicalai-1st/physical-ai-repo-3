# Dobi Barista 시스템 아키텍처

> **이 문서는 누구를 위한 것인가**: PinkLAB의 다른 팀원 또는 본 프로젝트에 새로 합류하는 동료가 시스템 전체 구조를 한 번에 파악할 수 있도록 작성된 단일 진실 원본(SoT) 문서다. 코드를 읽기 전에 이 문서를 먼저 읽으면 각 컴포넌트가 왜 존재하고 어떻게 연결되는지 이해할 수 있다.
>
> **읽는 순서 권장**:
> 1. §1 한눈에 보기 — 30초 요약
> 2. §2 시나리오 — 로봇이 실제로 어떻게 움직이는지
> 3. §3~5 컴포넌트 / 메시지 / 상태 머신 — 구조 상세
> 4. §6~8 안전 / 실행 / 진척도 — 실무 정보
> 5. §9 용어집 — 모르는 단어 나오면 여기로

---

## 1. 시스템 한눈에 보기

**한 줄 정의**: 카페에서 호객 / 서빙 / 주인 따라가기를 자율로 수행하는 모바일 로봇의 결정·표현 시스템.

**하드웨어**:
- **Vic Pinky Pro** — PinkLAB 모바일 베이스. RPi 5(라즈베리파이 5)가 모터·센서·LiDAR를 제어
- **노트북** — Vic Pinky 상단에 거치. 무거운 인지(웹캠 얼굴 분석)·결정·표현(얼굴 GUI·TTS)을 담당

**왜 두 머신으로 나눴나**: RPi는 실시간 모터 제어와 센서 발행에 집중하고, 무거운 컴퓨팅(MediaPipe, edge-tts, pygame GUI)은 노트북이 감당. ROS 2 토픽으로 둘이 통신 (`ROS_DOMAIN_ID=22`).

```
       ┌─────────────────────────────────────────────────────┐
       │                노트북 (vic_pinky 상단)               │
       │                                                     │
       │   ┌──────────┐   ┌──────────┐   ┌────────────┐      │
       │   │ 얼굴 인지 │──▶│ 결정 BT  │──▶│ 발화/표정  │      │
       │   │ (웹캠)    │   │          │   │ (스피커/   │      │
       │   │           │   │          │   │  GUI)      │      │
       │   └──────────┘   └──────────┘   └────────────┘      │
       │                       ▲                              │
       │                ┌──────┴──────┐                       │
       │                │ 모드 매니저  │                       │
       │                │ (4상태 FSM) │ ◀── 운영자 UI          │
       │                └─────────────┘                       │
       └─────────────────────┬───────────────────────────────┘
                             │ Wi-Fi (ROS 2 DDS)
                             ▼
       ┌─────────────────────────────────────────────────────┐
       │       RPi 5 (vic_pinky 본체, 모터 제어)               │
       │   배터리 / 휠 / LiDAR / Nav2 / cmd_vel               │
       └─────────────────────────────────────────────────────┘
```

**현재 가능한 것**:
- 카페 호객 한 사이클(고객 감지 → 접근 → 인사 → 메뉴 제안 → 카운터 안내) — 노트북 + RPi 통합 환경에서 검증됨
- 운영자 명령으로 모드 전환 인터페이스(대기/호객/서빙/팔로우) — 골격 동작
- 진행 중 호객을 끊지 않고 운영자 발화 끼워넣기 — 우선순위 큐로 직렬화
- 배터리 저전압 / 안전 알람 시 자동 대기 모드

**아직 안 된 것** (자세한 건 §7):
- 실제 서빙 모드 주행 (Nav2 waypoint follower) — 인터페이스만 있음
- 주인 추적 모드 (person tracker) — 디자인만 있음
- 운영자 UI 실 화면 (모드 버튼 + 상태 표시) — 인터페이스만 있음
- 자동 트리거 (POS 주문 들어오면 자동 서빙 등)

---

## 2. 시나리오로 보는 동작

### 시나리오 A — 호객 한 사이클 (현재 동작)

```
1. 노트북 웹캠이 손님 얼굴을 잡는다
   → MediaPipe가 얼굴 표정을 분석해서 "감정 좌표 (V, A)" 발행
2. rapport_tracker가 표정을 누적 관찰 (히스테리시스)
   → 미소 등 긍정 신호면 "engagement_up", 화남 등 부정 신호 지속이면 "abort_trigger"
3. BT(Behavior Tree)가 호객 funnel을 진행한다:
   ├─ 안전 체크 (배터리, 감정 알람) — 정상이면 다음으로
   ├─ 고객 후보 좌표를 받아 (현재는 합성 좌표 publisher)
   ├─ 1.5m 거리까지 접근 (Nav2)
   ├─ 인사: "안녕하세요! 오늘 어떤 음료가 끌리세요?"
   ├─ 메뉴 제안: "오늘은 시그니처 라떼가 잘 나가요"
   └─ 카운터 안내: "주문하실 거 정해지셨으면 카운터 쪽으로..."
4. 발화는 dialog_router를 거친다 — 다른 모드도 같은 채널을 쓰므로 충돌 방지
5. tts_node가 edge-tts로 음성 합성하고 pygame으로 재생
   동시에 face_avatar(노트북 풀스크린)에 어울리는 표정 GIF 출력
6. 손님이 화내면 rapport_tracker가 abort_trigger 발행 → BT가 funnel 중단 → 인사로 복귀
```

### 시나리오 B — 모드 전환 (디자인, 일부 구현)

```
1. 로봇이 NPC 모드로 호객 중
2. 운영자(또는 향후 POS 시스템)가 "테이블 5번 서빙" 명령
   → mode_manager 서비스 호출: SetMode(serving, {"waypoint": "table_5"})
3. mode_manager가 검증:
   - 배터리 OK? 안전 알람 없음? → 통과
   - NPC 스택 정리하고 서빙 스택 시동 (현재는 로그만, 실 launch 제어는 미구현)
4. 진행 중이던 NPC 인사 발화는 끝까지 마치고 (dialog_router가 큐로 관리),
   서빙 안내 발화로 전환 ("3번 테이블 음료 도착했습니다" 등)
5. Nav2가 테이블 5번 좌표로 주행 (서빙 스택 구현 예정)
6. 도착하면 SetMode(idle)로 복귀, 카운터 옆 대기
7. 한산해지면 다시 SetMode(npc)로 호객 재개
```

### 시나리오 C — 안전 알람

```
1. NPC 모드로 호객 중
2. /battery_state percentage가 0.20 미만으로 떨어짐 OR
   감정 인지에서 손님 화남 abort_trigger 발생
3. BT의 root ReactiveFallback이 매 tick 체크 → SafetyCheck/EmotionMonitor가 SUCCESS(=알람)
4. funnel 중단, BT는 알람 해소까지 대기
5. mode_manager도 abort_trigger 인지 → 강제로 idle 모드 전환
   + 5초 동안 다시 NPC/서빙/팔로우 요청 거부
```

---

## 3. 컴포넌트(노드) 별 역할

각 노드가 무엇을 받아 무엇을 내보내는지 평이한 말로 정리. 코드 위치는 표 마지막 컬럼.

### 인지 (Perception)

| 노드 | 하는 일 | 입력 | 출력 | 위치 |
|---|---|---|---|---|
| `geva_node` | 노트북 웹캠 영상에서 얼굴을 찾고 표정을 분석해 감정 좌표(V=쾌-불쾌, A=흥분-진정)로 변환 | 웹캠 (cv2) | `/emotion/state` | `dobi_npc_emotion/geva_node.py` |
| `rapport_tracker` | 매 프레임 감정 좌표를 누적해 "라포 변화 이벤트"로 정리. 단발 부정 감정으로 abort 안 되도록 ON/OFF 연속 카운트(히스테리시스) | `/emotion/state` | `/rapport/event` | `dobi_npc_emotion/rapport_tracker_node.py` |

### 결정 (Decision)

| 노드 | 하는 일 | 입력 | 출력 | 위치 |
|---|---|---|---|---|
| `bt_executor` | BehaviorTree.CPP가 cafe_funnel XML을 실행. NPC 모드의 호객 funnel(인사→접근→발화→안내) 진행. 안전·감정 알람을 매 tick 평가 | `/rapport/event`, `/customer_pose`, `/battery_state` | `/dialog/request`, `/cmd_vel`(Nav2 통해) | `dobi_npc_bt/` (C++) |
| `mode_manager` | 4상태 FSM(대기/NPC/서빙/팔로우). 운영자 요청을 받아 모드 전환 결정. 배터리/안전 가드 검사. 현재는 모드 stack 시동/종료가 stub(로그만) | `/mode/request`(srv), `/battery_state`, `/rapport/event` | `/mode/state`(1Hz) | `dobi_npc_bringup/mode_manager_node.py` |

### 표현 (Expression)

| 노드 | 하는 일 | 입력 | 출력 | 위치 |
|---|---|---|---|---|
| `persona_manager` | YAML로 정의된 페르소나(친근/전문/캐주얼) 중 하나를 선택. BT의 stage_id를 받으면 그 페르소나의 phrase pool에서 한 문장 골라 발화 요청으로 packing | `/dialog/request`(stage_id), `/set_persona`(srv) | `/dialog/router_in` | `dobi_npc_dialog/persona_manager_node.py` |
| `dialog_router` | 여러 모드(NPC, 서빙, 팔로우, 운영자, 안전)가 모두 발화/표정을 쓰니 충돌 방지. **우선순위 큐**로 직렬화. preempt 옵션이 있으면 큐 head로. 한 번에 한 발화만 출력 | `/dialog/router_in`(여러 publisher), `/dialog/utter_done` | `/dialog/utter` | `dobi_npc_dialog/dialog_router_node.py` |
| `tts_node` | edge-tts 클라우드 API로 텍스트 → mp3 합성. pygame.mixer로 재생. 재생 직전에 어울리는 표정을 face_avatar에 발행 (음성·표정 동기화). 완료되면 utter_done 발행 | `/dialog/utter`, `/rapport/event`(abort 시 mixer.stop) | `/face_avatar/expression`, `/dialog/utter_done` | `dobi_npc_dialog/tts_node.py` |
| `face_avatar` | 노트북 화면에 풀스크린(또는 윈도우) GIF로 8가지 표정 애니메이션 재생. pygame 기반. 자산은 vic_pinky 공식 패키지의 `emotion/*.gif` 8개 재활용 (vic_pinky 본체엔 LCD 없음) | `/face_avatar/expression` | (화면) | `dobi_npc_dialog/face_avatar_node.py` |

### 보조 / 운영

| 노드/스크립트 | 하는 일 | 위치 |
|---|---|---|
| `fake_customer_publisher` | GEFA(자세 분석) 노드가 아직 없으니 임시로 `/customer_pose`를 합성 발행 (3.0m 전방 등) | `dobi_npc_bringup/fake_customer_publisher.py` |
| `cmd_vel_watch.py` | `/cmd_vel`을 모니터해 임계 초과 시 알림. 옵션으로 RPi bringup을 SSH로 종료(비상 정지) | `scripts/cmd_vel_watch.py` |
| `run_teleop_ui.sh` | RPi에 SSH해서 vic_pinky bringup + USB 카메라를 자동 기동, 노트북에서 웹 teleop UI(8765 포트)를 띄움 | `scripts/run_teleop_ui.sh` |

### vic_pinky bringup (RPi에서 동작, 외부 패키지)

| 토픽 | 내용 |
|---|---|
| `/odom` | 로봇 위치 추정 (휠 오도메트리) |
| `/joint_states` | 휠 관절 상태 |
| `/battery_state` | 배터리 percentage (1Hz, 7S Li-ion. 본 프로젝트가 자체 추가) |
| `/scan` | RPLiDAR 스캔 (Nav2 장애물용) |
| `/cmd_vel` | 모터 속도 명령 (구독해서 ZLAC 모터 제어) |
| `/navigate_to_pose` | Nav2 액션 서버 (Approach 노드가 클라이언트로 호출) |

---

## 4. 패키지 구성

```
~/physical-ai-repo-3/src/controller/doby_controller/   (2026-05-19 이전 `~/moca/`)
├── src/
│   ├── shared/
│   │   └── vic_pinky/                  PinkLAB 공식 패키지 (자체 git 서브)
│   │       ├── vicpinky_description    URDF, 메시 (노트북 빌드)
│   │       ├── vicpinky_navigation     Nav2 파라미터 (노트북 빌드)
│   │       ├── vicpinky_bringup        모터/센서 launch (RPi 전용, 노트북엔 COLCON_IGNORE)
│   │       └── vicpinky_emotion        LCD용 패키지. 본 프로젝트는 LCD 없으니 노드 미사용,
│   │                                   자산(emotion/*.gif 8개)만 face_avatar에서 참조
│   │
│   └── dobi_npc/                       본 프로젝트 (6 패키지)
│       ├── dobi_npc_msgs/              커스텀 인터페이스
│       │   ├── msg/EmotionState.msg          감정 좌표 + 신뢰도
│       │   ├── msg/RapportEvent.msg          라포 이벤트 (engagement_up/down/abort_trigger/...)
│       │   ├── msg/MinigameResult.msg        가위바위보 결과 (Phase 3 예정)
│       │   ├── msg/UtterRequest.msg          발화 요청 + 라우팅 메타(source/priority/preempt)
│       │   ├── msg/ModeState.msg             현 모드 + 가드 상태 (1Hz publish)
│       │   ├── srv/SetPersona.srv            페르소나 전환
│       │   └── srv/SetMode.srv               운영 모드 전환
│       │
│       ├── dobi_npc_bt/                BT.CPP C++ 노드 + cafe_funnel XML
│       │   ├── include/dobi_npc_bt/    각 stage 노드 (SafetyCheck, IdleScan, Approach, ...)
│       │   └── bt_xml/cafe_funnel_v1.xml
│       │
│       ├── dobi_npc_emotion/           Python 인지 노드 (geva, rapport_tracker)
│       │
│       ├── dobi_npc_dialog/            Python 발화/표현
│       │   └── (persona_manager, dialog_router, tts_node, face_avatar)
│       │
│       ├── dobi_npc_minigame/          가위바위보 (Phase 3 stub)
│       │
│       └── dobi_npc_bringup/           통합 launch + 보조 노드
│           ├── launch/dev_all.launch.py     8 노드 통합 launch
│           └── (fake_customer_publisher, mode_manager)
│
├── docs/
│   ├── cafe_npc_paper_master.md            학술 토대 (6 layer 논문)
│   ├── cafe_npc_implementation_plan.md     16주 구현 계획
│   ├── cafe_npc_camera_architecture.md     카메라 3 역할
│   ├── cafe_npc_engagement_funnel.md       호객 funnel 기획
│   ├── cafe_npc_system_architecture.md     본 문서
│   ├── rpi_integration_checklist.md        실물 테스트 체크리스트
│   └── daily/                              일일 회고 (트랙별)
│
├── scripts/                            운영 스크립트
└── CLAUDE.md                           프로젝트 컨텍스트 + 작업 규칙
```

### 빌드 / 실행

```bash
# 빌드
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install

# 또는 scripts/moca_env.sh 를 source 한 후 (2026-05-19 부터, .bashrc 미수정)
source ~/physical-ai-repo-3/src/controller/doby_controller/scripts/moca_env.sh
moca_build       # 격리 셸 콜콘 빌드 (robot_arm 자동 source 영향 회피)
moca_activate    # 빌드 결과 활성화
moca_clean       # build/install/log 삭제
```

### 시동 (노트북 단독, RPi 없이도 face/TTS는 동작)

```bash
source /opt/ros/jazzy/setup.bash
source ~/physical-ai-repo-3/src/controller/doby_controller/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py
```

### 시동 (RPi와 통합)

```bash
# 노트북에서 (RPi bringup도 SSH로 자동 기동, USB 캠 미연결이면 SKIP_CAM=1)
bash ~/physical-ai-repo-3/src/controller/doby_controller/scripts/run_teleop_ui.sh         # 또는 SKIP_CAM=1 bash ...
# teleop으로 안전한 위치 이동 후
bash ~/physical-ai-repo-3/src/controller/doby_controller/scripts/stop_teleop_ui.sh        # bringup은 유지
ros2 launch dobi_npc_bringup dev_all.launch.py
```

---

## 5. 메시지 흐름 (토픽/서비스 카탈로그)

### 핵심 토픽

| 토픽 | 메시지 | 누가 발행 | 누가 구독 | 역할 |
|---|---|---|---|---|
| `/emotion/state` | `EmotionState` | `geva_node` | `rapport_tracker` | 매 프레임 감정 좌표 (10Hz) |
| `/rapport/event` | `RapportEvent` | `rapport_tracker` | `bt_executor`, `tts_node`, `mode_manager` | 라포 변화 + 안전 abort_trigger |
| `/dialog/request` | `String` | `bt_executor` (utter nodes) | `persona_manager` | "icebreak", "offer", "leadin" 같은 stage_id |
| `/dialog/router_in` | `UtterRequest` | `persona_manager` (NPC), 향후 서빙/팔로우/운영자 | `dialog_router` | 발화 요청 + source/priority/preempt 라벨 |
| `/dialog/utter` | `UtterRequest` | `dialog_router` | `tts_node` | 직렬화된 단일 발화 (큐 head) |
| `/dialog/utter_done` | `Empty` | `tts_node` | `bt_executor`, `dialog_router` | 발화 완료 신호 |
| `/face_avatar/expression` | `String` | `tts_node` (mixer.play 직전) | `face_avatar` | 8 어휘 표정 (basic/hello/happy/fun/interest/bored/sad/angry) |
| `/customer_pose` | `PoseStamped` | `fake_customer_publisher` (Phase 2까지) | `bt_executor` (Approach) | 고객 좌표 |
| `/mode/state` | `ModeState` | `mode_manager` | (운영자 UI 예정) | 현 모드 + battery_ok + safety_ok + last_reject (1Hz) |
| `/battery_state` | `BatteryState` | vic_pinky bringup | `bt_executor` (SafetyCheck), `mode_manager` | 배터리 percentage (1Hz) |
| `/cmd_vel` | `Twist` | Nav2 / teleop | vic_pinky bringup, `cmd_vel_watch` (모니터) | 모터 속도 명령 |

### 서비스

| 서비스 | 메시지 | 서버 | 클라이언트 | 용도 |
|---|---|---|---|---|
| `/set_persona` | `SetPersona` | `persona_manager` | (운영자, 자동) | 페르소나 전환 |
| `/mode/request` | `SetMode` | `mode_manager` | (운영자 UI 예정) | 운영 모드 전환 |

### 액션

| 액션 | 메시지 | 서버 | 클라이언트 | 용도 |
|---|---|---|---|---|
| `/navigate_to_pose` | `nav2_msgs/NavigateToPose` | vic_pinky bringup | `bt_executor` (Approach) | Proxemic 좌표 주행 |

### 메시지 타입 상세

```
EmotionState
  Header header
  float32 valence      -1.0(불쾌) ~ +1.0(쾌)
  float32 arousal      -1.0(진정) ~ +1.0(흥분)
  float32 confidence   0.0 ~ 1.0
  string source        "face" | "voice" | "fused"
  string[] flags       ["mask_smile", "voice_only", ...]

RapportEvent
  Header header
  string event_type    "engagement_up" | "engagement_down" | "abort_trigger" | "neutral_continue"
  float32 weight       -1.0(강한 부정) ~ +1.0(강한 긍정)
  EmotionState emotion 이벤트를 일으킨 감정
  string reason        "anger_detected" | "smile_genuine" | ...

UtterRequest
  Header header
  string text                  발화 텍스트
  string voice / rate / pitch  TTS 엔진 메타
  string face_expression       동기화할 표정 (mixer.play 직전 발행)
  string persona_id, stage_id  추적용
  # 라우팅 메타
  string source                "npc" | "serving" | "follow" | "operator" | "safety"
  uint8 priority               0=safety / 10=operator / 20=serving / 30=npc / 255=lowest
  bool preempt                 true → 큐 head 배치

ModeState
  Header header
  string current_mode          "idle" | "npc" | "serving" | "follow"
  Time entered_at
  string params                JSON snapshot (예: {"waypoint":"table_5"})
  bool battery_ok / safety_ok  가드 통과 여부
  string last_reject_reason    직전 reject 사유

SetMode (요청)
  string requested_mode        "idle" | "npc" | "serving" | "follow"
  string params                JSON
SetMode (응답)
  bool success
  string current_mode          응답 시점 실제 모드
  string reason                실패 사유
```

---

## 6. 상태 머신

### 6.1 운영 모드 FSM (mode_manager, 4상태)

운영 모드는 "지금 로봇이 뭘 하고 있는가"를 한 단어로 표현한다.

```
                            ┌──────────────────────────────┐
                            │           idle (대기)          │
                            │  공통층만 살아있음              │
                            │  카운터 옆 정지, 다음 명령 대기  │
                            └──┬─────┬─────┬───────────────┘
                               │     │     │
              SetMode("npc")   │     │     │  SetMode("follow", {target})
                               ▼     │     ▼
                    ┌──────────┐    │    ┌──────────────┐
                    │   npc    │    │    │   follow     │
                    │  (호객)  │    │    │ (주인 추적)   │
                    │  cafe_   │    │    │ (디자인만)    │
                    │  funnel  │    │    │              │
                    └────┬─────┘    │    └──────┬───────┘
                         │          ▼           │
                         │   ┌─────────────┐    │
                         └──▶│   serving   │◀───┘
                             │ (waypoint 주행)│
                             │ (디자인만)     │
                             └─────┬─────────┘
                                   │
              가드 발동 → 어디서든 강제 idle
              (배터리 < 20% 또는 abort_trigger)
```

**전이 규칙**:
- 모든 모드 간 전환 허용 (운영자 수동 트리거 우선)
- **idle 외 전환은** 배터리 OK + 안전 알람 없음 통과 필요
- **idle로의 전환은 무조건 허용** (안전 fall-back)
- 안전 알람 발생 시 5초 dwell 동안 idle 외 모드 거부

**현재 cut**: 모드 전환 시 실제로 stack을 시동/종료하는 부분은 stub 로그만. 실 launch 제어는 다음 트랙에서 추가 예정.

### 6.2 호객 BT — cafe_funnel (NPC 모드 안의 행동 트리)

NPC 모드일 때 bt_executor가 실행하는 BehaviorTree. BehaviorTree.CPP 4.8.3 사용.

```
ReactiveFallback (root_alarm_fallback)            ◀── 매 tick 모든 자식 재평가
├── SafetyCheck (battery_min=0.20)                ◀── 정상 FAILURE / 알람 시 SUCCESS
├── EmotionMonitor                                ◀── /rapport/event abort_trigger 시 SUCCESS
└── Sequence (cafe_funnel)                        ◀── 알람 모두 FAILURE일 때만 진입
    ├── stage1_idle_scan      고객 후보 탐지 (현재 fake_customer로 합성)
    ├── stage2_approach       Proxemic 1.5m 거리까지 Nav2 주행
    │                         abort_threshold 1.0m (너무 가까우면 FAILURE)
    │                         allow_dummy_goal=false (안전 가드: customer_pose 없으면 송신 안 함)
    ├── stage3_ice_break      페르소나 phrase pool에서 인사 발화
    ├── stage4_minigame       가위바위보 (Phase 3 예정, 현재 stub)
    ├── stage5_offer          메뉴 제안
    └── stage6_lead_in        카운터 안내
```

**왜 ReactiveFallback인가**: Sequence가 한참 돌고 있어도 매 tick마다 SafetyCheck/EmotionMonitor를 다시 평가해야 알람이 즉시 작동. 일반 Fallback은 한 번 평가하면 latch되어 알람을 늦게 본다.

### 6.3 dialog_router 우선순위 큐

여러 모드가 같은 face/TTS 자원을 공유하므로 충돌 방지 게이트가 필요.

```
publishers              router 큐 (heap)              output
─────────────────       ─────────────────────────     ──────────
persona_manager   ─┐    eff_priority = -1 if preempt
(NPC, p=30)        │              else priority
                   ├──▶ heappush (eff_priority, seq, msg)
serving (p=20)     │                                    │
follow (p=20)      │    on utter_done:                  │
operator (p=10)    │      _playing = False ─┐           │
safety (p=0)       │                        │           ▼
                   │    dispatch:           │    /dialog/utter
                   │      not _playing AND  │     → tts_node
                   │      heap nonempty     │
                   │      → heappop, publish│
                   │      → _playing=True ◀─┘
```

**우선순위**: 0=safety alarm > 10=operator > 20=serving > 30=NPC. 같은 priority 안에서는 도착 순서(seq).

**preempt** (현 cut): true이면 큐 맨 앞에 배치(eff_priority=-1)하고 다음 dispatch에서 가장 먼저 나감. **단, 진행 중 발화는 utter_done까지 기다림** — 진짜 audio cut은 미구현. 안전 alarm 즉시 중단은 별도 경로(`/rapport/event` abort_trigger → `mixer.stop()`).

### 6.4 rapport hysteresis

매 프레임 감정만 보고 abort 결정하면 false positive 너무 많음(잠깐 인상 찌푸려도 abort).

```
                                    ON 카운트 ≥ 5 (연속 V<-0.5 AND A>0.4)
                  neutral_continue ────────────────────▶ engagement_down
                       ▲                                        │
                       │                                        │
                       │ OFF 카운트 ≥ 5 (within_neutral_band)   │
                       │                                        ▼
                       └────────────────────────────  abort_trigger
```

5프레임(약 0.5초) 연속 부정 감정이 들어와야 abort, 5프레임 연속 중립이면 정상 복귀.

---

## 7. 현재 구현 상태 + 다음 단계

### 검증된 것 (실물 라이브 통과)

- **호객 한 사이클** — 노트북 + RPi 통합 환경에서 7분 라이브:
- BT funnel 정상 순환 (인사 → 메뉴 제안 → 카운터 안내 → 다시 인사)
- Approach 안전 가드 34회 작동 (customer_pose 없을 때 Nav2 송신 차단)
- /cmd_vel 의도하지 않은 명령 0건 (cmd_vel_watch 모니터 결과)
- SafetyCheck silent FAILURE (실 RPi 배터리 43.4%로 임계 통과)
- face/TTS 동기화 (음성 시작 시점에 표정 전환)

- **모드 매니저 골격**:
- 4상태 FSM, service/topic 인터페이스 정의 완료
- 5가지 reject 시나리오 정확 동작 (잘못된 모드명, 잘못된 JSON, 배터리/안전 가드)
- 안전 알람 시 강제 idle + dwell 5초 reject

- **발화 라우터 (dialog_router)**:
- NPC 단독에서 transparent 동작 (기존 흐름 그대로)
- 운영자 강제 발화 preempt=true → 현 발화 끝까지 대기 후 즉시 dispatch
- 운영자 priority=10 → NPC priority=30보다 먼저 dispatch

### 골격만 있는 것 (인터페이스 정의 + stub)

- **모드 stack 시동/종료** — mode_manager가 모드 전환 시 stub 로그만 찍음. 실제 launch 시동/종료는 다음 트랙.

- **서빙 모드 stack** — Nav2 NavigateThroughPoses 기반 waypoint follower 미구현.

- **팔로우 모드 stack** — person tracker + reactive controller 디자인만 있음.

- **운영자 UI 모드 패널** — `teleop_server.py`(기존 웹 UI) 확장해서 모드 버튼 + /mode/state 표시 + 강제 발화 폼 추가 예정.

### 필요한 것 (Phase 후속)

- **GEFA 노드** — RPi USB 카메라로 자세/접근/회피 인지 → /emotion/state(source="body"). RPi USB 카메라 연결은 복구됨, raw publisher만 추가하면 시작 가능.

- **decision_rule_node** — GEVA(얼굴) + GEFA(자세) → fused EmotionState (Salichs 2014 방법론).

- **/scan SafetyCheck 통합** — LiDAR 기반 1.0m 이내 인간 감지 알람.

- **tts_node /dialog/cancel** — 진짜 audio cut preempt 지원. 안전 alarm을 dialog_router 경로로 통합 가능.

- **실 Nav2 주행 검증** — 현재 `/navigate_to_pose` action server는 보이지만 표준 Nav2 노드(controller/planner/amcl)가 안 보임. 출처 확인 + map frame 확보(SLAM) 필요.

- **자동 트리거** — POS 주문, 한산도 vision 등으로 모드 자동 전환. 운영자 UI와 같은 `/mode/request` 사용.

- **Phase 3** (Week 7-9) — 가위바위보 미니게임 + Polite phrase + OpenManipulator(OMX) 가위바위보 모션.

- **Phase 4** (Week 10-12) — 통합 + N=5 파일럿 테스트.

- **Phase 5** (Week 13-16) — XAI / Learning (Iovino 2022 미해결 과제).

---

## 8. 안전 장치 (현재 5 layers)

| 층 | 메커니즘 | 위치 |
|---|---|---|
| L1 코드 (Approach) | `allow_dummy_goal=false` 기본 — `/customer_pose` 없으면 Nav2 송신 차단 | `approach.hpp` |
| L2 코드 (Approach) | `abort_threshold=1.0m` — 고객 너무 가까우면 BT FAILURE | `approach.hpp` |
| L3 코드 (SafetyCheck) | `/battery_state.percentage < 0.20` → BT 알람 | `safety_check.hpp` |
| L4 외부 (cmd_vel watch) | 임계 초과 시 RPi bringup KILL 옵션 | `scripts/cmd_vel_watch.py` |
| L5 코드 (mode_manager) | safety alarm 시 강제 idle + dwell 동안 reject | `mode_manager_node.py` |
| L6 물리 | 사용자 비상 정지 / 충전 중 모터 단절 | (수동) |

L1+L2+L3+L5는 **소스에서 차단**(잘못된 cmd_vel 자체가 발생 안 함), L4는 **하류에서 차단**(어떤 경로로든 cmd_vel 나오면 즉시 중단), L6는 최후 보루.

---

## 9. 용어집

| 용어 | 의미 |
|---|---|
| **BT** | Behavior Tree. 게임 NPC AI에서 출발한 결정 트리 구조. 본 프로젝트는 BehaviorTree.CPP 4.8.3 사용 |
| **GEVA** | 본 프로젝트 정의: **노트북 웹캠 → 얼굴 표정 → V·A 좌표** 변환. (Salichs 원어는 음성이지만 본 프로젝트는 모달리티 의도적 재정의) |
| **GEFA** | 본 프로젝트 정의: **RPi USB 카메라 → 자세/접근/회피** 분석. (Salichs 원어는 얼굴) |
| **V·A** | Russell 1980 Circumplex의 Valence(쾌-불쾌) + Arousal(흥분-진정) 2차원 감정 좌표 |
| **funnel** | 호객 5+stage Sequence. Isla 2005 game NPC 패러다임 — 점진적으로 고객 인게이지먼트 깊어짐 |
| **Proxemic** | 사람 간 사회적 거리 개념. 본 프로젝트는 social_distance=1.5m, abort_threshold=1.0m로 적용 |
| **persona** | YAML로 정의된 발화 스타일 + voice + face 매핑. 3종(casual_browser/friendly_child/professional_adult) |
| **dialog_router** | 여러 모드가 face/TTS 채널을 공유할 때 우선순위 큐로 직렬화하는 게이트 노드 |
| **mode_manager** | 4상태(idle/npc/serving/follow) FSM 노드. 운영자 명령 + 가드(배터리/안전) 처리 |
| **utter_done** | TTS 발화 완료 신호. BT가 다음 stage로 진행하기 전에 대기 |
| **abort_trigger** | rapport_tracker가 발행하는 안전 이벤트. 손님 화남 등 부정 감정 지속 시 발동 |
| **alarm** | BT의 ReactiveFallback 안에서 SafetyCheck/EmotionMonitor가 SUCCESS 반환하는 상태 = funnel 중단 |
| **stage_id** | BT의 utter 노드가 발행하는 발화 단계 식별자 ("icebreak", "offer", "leadin" 등) |
| **preempt** | dialog_router에서 발화 요청을 큐 head로 배치하는 옵션 (true이면 다음 dispatch에서 가장 먼저) |
| **dwell** | safety alarm 후 알람 효과가 지속되는 시간 (현재 5초). dwell 동안 idle 외 모드 거부 |
| **stub** | 실 구현은 미완이나 인터페이스만 있는 코드. 본 프로젝트는 mode_manager의 launch spawn/kill이 stub |

---

## 10. 참고 문서

| 문서 | 무엇 |
|---|---|
| `docs/cafe_npc_paper_master.md` | 학술 토대 6 layer (Isla 2005 ~ Iovino 2022) |
| `docs/cafe_npc_implementation_plan.md` | 16주 구현 계획 (Phase 1~5) |
| `docs/cafe_npc_camera_architecture.md` | 카메라 3 역할 (GEVA / GEFA / Nav2 위치) |
| `docs/cafe_npc_engagement_funnel.md` | 호객 funnel 5 stage 기획 |
| `docs/rpi_integration_checklist.md` | 실물 테스트 직전 체크리스트 |
| `docs/daily/*.md` | 일일 회고 (트랙별 결정 + 검증 결과 + 발견된 위험) |
| `CLAUDE.md` | 프로젝트 컨텍스트 + 작업 규칙 (LLM/사람 모두 참조) |
| `README.md` | 빌드 가이드 |

### 일일 회고 읽는 순서 권장

1. `2026-05-01_phase0a_migration.md` — 워크스페이스 구조의 시작
2. `2026-05-04_rpi_first_contact.md` — RPi 1차 연결
3. `2026-05-04_approach_safety_patch.md` — 안전 가드 디자인
4. `2026-05-04_npc_first_live_test.md` — 첫 통합 라이브
5. `2026-05-04_dialog_router_a1.md` — 발화 라우터 도입
6. `2026-05-04_mode_manager_a2.md` — 모드 매니저 골격

---

## 11. 자주 묻는 질문

**Q. 노트북 없이 RPi만으로 호객이 가능한가요?**
A. 아니오. 얼굴 인지(MediaPipe), TTS(edge-tts), face GUI(pygame)는 모두 노트북에서 동작. RPi는 모터/센서만 담당.

**Q. ROS 2 도메인 ID는 왜 22인가요?**
A. PinkLAB 표준. 다른 로봇/시뮬과 격리.

**Q. vic_pinky 본체에 LCD가 없는데 표정은 어디 보이나요?**
A. 노트북 풀스크린 face_avatar GUI. vic_pinky 공식 패키지의 GIF 자산 8개를 그대로 재활용.

**Q. 왜 BehaviorTree와 FSM을 둘 다 쓰나요?**
A. 책임 분리. **BT (cafe_funnel)** = NPC 모드 안의 호객 행동 결정. **FSM (mode_manager)** = NPC/서빙/팔로우/대기 중 어느 모드인지 결정. BT는 동시 평가 + 트리 표현이 강하고, FSM은 4상태 단순 전환에 직관적.

**Q. dialog_router는 왜 만들었나요?**
A. NPC 호객 중에 운영자가 "주문 들어왔습니다" 발화를 끼워넣어야 하는 시나리오. 두 publisher가 동시에 face/TTS를 쓰면 충돌. router가 우선순위 큐로 직렬화.

**Q. 새 모드(예: 청소)를 추가하려면?**
A. (1) `mode_manager_node.py`의 `VALID_MODES`에 `cleaning` 추가. (2) cleaning_stack의 launch 작성. (3) cleaning stack이 `/dialog/router_in`에 source="cleaning", priority=20 정도로 발화 publish. (4) 운영자 UI에서 모드 버튼 추가.

**Q. 발화 우선순위는 어떻게 정하나요?**
A. 0=safety alarm (즉시 중단 — 단 현재 audio cut 미구현), 10=operator 강제, 20=serving 안내, 30=NPC 호객. 숫자 작을수록 우선.

**Q. 페르소나는 어떻게 추가/변경?**
A. `dobi_npc_dialog/config/personas/<name>.yaml` 작성 (parent로 generic 또는 다른 페르소나 상속 가능). `/set_persona` 서비스로 런타임 전환.

---

*마지막 갱신: 2026-05-04 (NPC 첫 통합 라이브 + dialog_router + mode_manager 골격 직후)*
*다음 갱신 시점: 운영자 UI 패널 또는 모드 stack 실 launch 제어 추가 시*
*문의: gjkong (kong@pinklab.art)*
