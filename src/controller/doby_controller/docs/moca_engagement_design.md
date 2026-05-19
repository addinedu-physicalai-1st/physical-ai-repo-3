# MOCA Engagement Mode 설계 문서

> **문서 ID**: `moca_engagement_design.md`
> **버전**: v1.0 (2026-05-17)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §2.2.5
> **관련 문서**:
> - `moca_5state_fsm_spec.md` §2.5 (S_engaging)
> - `cafe_npc_engagement_funnel.md` (학술 트랙 SoT — 6-stage funnel 학술 근거)
> - `cafe_npc_paper_master.md` Layer 1 (Isla 2005) + Layer 5 (Marzinotto 2014)
> **구현 대상**:
> - `dobi_npc_bt/src/bt_executor_node.cpp` (C++ BT 메인)
> - `dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` (BT 트리 정의)
> - `dobi_npc_bt/include/dobi_npc_bt/*.hpp` (BT 노드 8종)
> - `dobi_npc_minigame/dobi_npc_minigame/minigame_runner_node.py` (게임 dispatcher)
> - `dobi_npc_bringup/launch/mode_engaging.launch.py` (실 구현, 60 줄)
> - `dobi_npc_bringup/launch/mode_npc.launch.py` (deprecation wrapper, 2026-07-04 제거)

---

## 0. 본 문서의 범위

본 문서는 `engaging` 모드 — 한산한 카페에서 로봇이 고객에게 다가가 인사·미니게임·메뉴 제안·카운터 안내 6단계 funnel 을 수행하는 모객 행동 — 의 알고리즘과 구현 방침을 정의한다.

### 0.1 본 문서가 다루는 것

1. `engaging` 모드의 책임과 다른 모드와의 경계 (특히 guiding 과의 차이)
2. `cafe_funnel_v1.xml` BT 트리 구조 (ReactiveFallback Alarm 패턴 + 6-stage Sequence)
3. BT 노드 8 종 인터페이스 (SafetyCheck / EmotionMonitor / IdleScan / Approach / IceBreak / Minigame / Offer / LeadIn)
4. `bt_executor` C++ 노드 (ROS2 Timer 기반 tick 루프)
5. `minigame_runner` Python 노드 (PlayWait 게임 subprocess dispatcher, 카메라 3)
6. 안전 가드 (SafetyCheck 배터리/scan + EmotionMonitor V/A abort)
7. 페르소나 (4종 yaml) + Phrase Pool + Polite phrase
8. 카메라 분리 (GEVA 카메라 1, 게임 카메라 3)

### 0.2 본 문서가 다루지 않는 것

- BT.CPP 라이브러리 자체 사용법 (외부: BehaviorTree.CPP 공식 문서)
- 페르소나 별 phrase pool 디자인 (별 트랙: `cafe_npc_engagement_funnel.md`)
- 학술 근거 (Isla 2005 / Marzinotto 2014 / Russell 1980 / Salichs 2014 / Castro-González 2016 — `cafe_npc_paper_master.md`)
- 감정 인식 알고리즘 자체 (별 노드: geva_node + decision_rule, 공통 always-on)
- TTS / face_avatar 렌더링 (공통 always-on, dev_common.launch.py)

---

## 1. 모드 개요와 책임

### 1.1 engaging 모드의 목적

운영자 또는 mode_manager 가 한산 감지 시 호출. 로봇이:
1. 카페 안 고객 후보 탐지 (IdleScan)
2. Proxemic 거리 (1.5m) 까지 접근 (Approach, Nav2)
3. 페르소나별 인사 (IceBreak)
4. 미니게임 1회 (Minigame — RPS/speed_counter/cafe_ninja 중 1)
5. 메뉴 제안 (Offer)
6. 카운터 안내 (LeadIn, Nav2)

각 단계에서 SafetyCheck (배터리/scan) 또는 EmotionMonitor (V/A 부정) 알람 → 즉시 abort + idle 전이.

### 1.2 priority — 5 (최하)

`moca_5state_fsm_spec.md` priority 매트릭스 기준, engaging 은 **priority 5** (가장 낮음). serving/guiding/patrol 진행 중 engaging 요청 거부. 반대로 engaging 진행 중 serving 등 더 높은 priority 요청 오면 즉시 abort.

### 1.3 guiding 과의 차이

| 항목 | engaging | guiding |
|---|---|---|
| 트리거 | 한산 시 (운영자 또는 자동) | 결제 완료 고객이 안내 요청 |
| 방향 | 로봇 → 고객 (접근) | 로봇 → 빈 테이블 (앞장) |
| 사람 인식 | IdleScan (천장/외장 카메라) | customer lock-on (외장 카메라) |
| 대화 | 6-stage funnel (긴 대화) | 짧은 안내 (테이블 도착) |
| 게임 | 있음 (Minigame stage) | 없음 |
| Nav2 | Approach + LeadIn 2회 | 단발 (목표 테이블 1회) |
| 종료 | LeadIn 후 idle | 테이블 도착 + 고객 안착 후 idle |

핵심: engaging 은 **고객 발견 → 관계 형성**, guiding 은 **고객 lock-on → 동행 안내**.

### 1.4 노드 분리 정책

engaging 은 **두 노드 stack** (`bt_executor` + `minigame_runner`):
- `bt_executor` (C++): BT 메인. 6-stage funnel 진행.
- `minigame_runner` (Python): 게임 subprocess dispatcher. BT 의 Minigame stage 에서 `/minigame/start` String 발행 → runner 가 game.py subprocess 띄움.

이유: BT 는 C++ (BehaviorTree.CPP), 게임은 Python (mediapipe + opencv + pygame). 프로세스 격리 + subprocess wrapper 패턴이 깔끔.

---

## 2. cafe_funnel_v1.xml BT 트리 구조

### 2.1 ReactiveFallback Alarm 패턴

```xml
<root BTCPP_format="4">
  <BehaviorTree ID="MainTree">
    <ReactiveFallback name="root_alarm_fallback">

      <SafetyCheck name="safety_alarm"
                   battery_min="0.20" scan_min_dist="1.0" scan_min_range="0.25"
                   scan_alarm_enabled="true"/>

      <EmotionMonitor name="emotion_alarm"/>

      <Sequence name="cafe_funnel">
        <IdleScan name="stage1_idle_scan" customer_id="{customer_id}"/>
        <Approach name="stage2_approach"
                  customer_id="{customer_id}"
                  social_distance="1.5" abort_threshold="1.0"/>
        <IceBreak name="stage3_ice_break" phrase_pool_id="casual_browser"/>
        <Minigame name="stage4_minigame" game_type="rotate"
                  rapport_delta="{rapport_delta}"/>
        <Offer name="stage5_offer" menu_category="default"/>
        <LeadIn name="stage6_lead_in" counter_pose_id="counter_default"/>
      </Sequence>

    </ReactiveFallback>
  </BehaviorTree>
</root>
```

### 2.2 ReactiveFallback 채택 이유

`ReactiveFallback` (= 매 tick 마다 모든 자식을 왼쪽부터 재평가) — Sequence 가 RUNNING 중이어도 매 tick 마다 SafetyCheck/EmotionMonitor 다시 평가 → abort 즉시 작동.

`Fallback` (non-reactive) 는 앞 자식의 RUNNING/FAILURE 한 번 본 뒤 latch — abort 가 다음 tick 까지 지연됨.

### 2.3 알람 의미 반전 (정상 FAILURE / 위험 SUCCESS)

`SafetyCheck` 와 `EmotionMonitor` 는 **위험 시 SUCCESS 반환** — ReactiveFallback 가 SUCCESS 보고 즉시 abort (자식 Sequence 무시).

| 상태 | SafetyCheck | EmotionMonitor | Sequence |
|---|---|---|---|
| 정상 (배터리 OK + scan 안전 + V/A 긍정) | FAILURE | FAILURE | 실행 (RUNNING) |
| 배터리 < 20% 또는 scan < 1.0m | **SUCCESS** | (재평가 안 함) | abort |
| V/A abort_trigger (anger / boredom) | FAILURE | **SUCCESS** | abort |

### 2.4 Stage 진화 (Phase 별)

| Phase | 변경 |
|---|---|
| Phase 1 W1 | 6 stage 더미 (SUCCESS 만 반환) + safety_check skeleton |
| Phase 1 W2 | Approach → Nav2 NavigateToPose action client |
| Phase 1 W3 | IceBreak/Offer → persona-aware phrase pool |
| Phase 2 W4 | EmotionMonitor 추가, /rapport/event 구독 |
| Phase 2 후속 | hysteresis_ms / rapport_delta 출력 포트 |
| Phase 3 | Minigame → RPS/speed_counter/cafe_ninja 3 게임 subprocess |
| Phase 5 (TBD) | XAI / Learning (Iovino 2022 미해결) |

---

## 3. BT 노드 8 종 인터페이스

### 3.1 SafetyCheck (Stage 0a)

**파일**: `include/dobi_npc_bt/safety_check.hpp`
**클래스**: `BT::ConditionNode`

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `battery_min` | double | 0.20 | percentage 임계 (20%) |
| `scan_min_dist` | double | 1.0 | scan 가까운 obstacle alarm 임계 (m) |
| `scan_min_range` | double | 0.25 | scan_min_dist 이하 빔 무시 (vicpinky 섀시 자기반사 0.18~0.21m 마스킹) |
| `scan_alarm_enabled` | string ("true"/"false") | "true" | scan alarm 활성 |

**tick() 반환**:
- `SUCCESS` — 알람 (배터리 < battery_min 또는 scan < scan_min_dist) → ReactiveFallback abort
- `FAILURE` — 정상 → 다음 자식 진입

**구독 토픽**:
- `/battery_state` (sensor_msgs/BatteryState, 1Hz)
- `/scan` (sensor_msgs/LaserScan, 5Hz)

### 3.2 EmotionMonitor (Stage 0b)

**파일**: `include/dobi_npc_bt/emotion_monitor.hpp`

**구독 토픽**:
- `/rapport/event` (dobi_npc_msgs/RapportEvent) — rapport_tracker 가 GEVA + decision_rule 통합 결과 발행

**tick() 반환**:
- `SUCCESS` — event_type=="abort_trigger" 수신 → abort
- `FAILURE` — 정상 / engagement_up / neutral_continue

**Russell V·A 임계** (rapport_tracker 가 발행 측):
- abort_trigger: V < -0.5 (강한 negative) 또는 A < -0.3 (boredom)
- engagement_up: V > 0.3 & A > 0.2 (긍정 + 활발)

### 3.3 IdleScan (Stage 1)

**파일**: `include/dobi_npc_bt/idle_scan.hpp`

**Input/Output ports**:
| 포트 | 방향 | 타입 | 의미 |
|---|---|---|---|
| `customer_id` | OUT | string | 탐지된 고객 ID (다음 단계 input) |

**구독 토픽**:
- W2 시점: `/customer_pose` (사용자 결정, 천장 카메라 또는 외장)
- 현재: dummy id 발행 (W2 통합 대기)

### 3.4 Approach (Stage 2)

**파일**: `include/dobi_npc_bt/approach.hpp`

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `customer_id` | string | (Stage 1 의 output) | 접근 대상 |
| `social_distance` | double | 1.5 | Proxemic social zone (m) — 정지 거리 |
| `abort_threshold` | double | 1.0 | 더 가까이 가면 abort (m) |

**액션 클라이언트**: `navigate_to_pose` (Nav2)

**알고리즘**:
1. customer_id 의 PoseStamped 조회 (TF 또는 토픽)
2. customer → robot 방향 단위 벡터 계산
3. customer 위치 - (단위벡터 × social_distance) 가 goal
4. Nav2 NavigateToPose 단발 호출
5. dispatcher 가 도착하면 SUCCESS, 충돌/abort 면 FAILURE

⚠ **현재 sim AMCL drift 한계** — Approach Nav2 실패 가능성. `docs/cafe_npc_rpi_live_amcl_checklist.md` 참조.

### 3.5 IceBreak (Stage 3)

**파일**: `include/dobi_npc_bt/ice_break.hpp` (utter_action_base.hpp 상속)

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `phrase_pool_id` | string | `casual_browser` | persona_manager 의 phrase pool key |

**발행 토픽**:
- `/dialog/request` (std_msgs/String) — persona_manager 가 받아서 random phrase 선택 → `/dialog/router_in`

**구독 토픽**:
- `/dialog/utter_done` (std_msgs/Empty 또는 String) — TTS 완료 신호

**동작**:
1. `/dialog/request` 발행 (stage_id: "ice_break", phrase_pool_id 포함)
2. tick 마다 RUNNING 반환
3. `/dialog/utter_done` 수신 시 SUCCESS

### 3.6 Minigame (Stage 4)

**파일**: `include/dobi_npc_bt/minigame.hpp`

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `game_type` | string | `rotate` | rps / speed_counter / cafe_ninja / rotate / random |
| `rapport_delta` | double | (output) | 게임 결과 rapport 가중치 |

**발행 토픽**: `/minigame/start` (std_msgs/String) — game_id 발행
**구독 토픽**: `/minigame/result` (dobi_npc_msgs/MinigameResult) — game 결과 (customer_wins/robot_wins/ties/rounds_played/completed/duration_sec)

**동작**:
1. game_type="rotate" 시 cycle counter 로 game 선택 (rps → speed_counter → cafe_ninja → rps ...)
2. `/minigame/start` 발행 (string game_id)
3. minigame_runner 가 game.py subprocess 실행 + result publish
4. result 수신 시 customer_win_rate 계산 → rapport_delta 출력 (0.7 목표, Castro-González 2016)
5. SUCCESS 반환

### 3.7 Offer (Stage 5)

**파일**: `include/dobi_npc_bt/offer.hpp` (utter_action_base.hpp 상속)

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `menu_category` | string | `default` | persona 별 메뉴 카테고리 (warm_drink / cold_drink 등) |

**동작**: IceBreak 와 동상 (utter_action_base 패턴). `/dialog/request` 발행 → utter_done 대기 → SUCCESS.

### 3.8 LeadIn (Stage 6)

**파일**: `include/dobi_npc_bt/lead_in.hpp`

**Input ports**:
| 포트 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `counter_pose_id` | string | `counter_default` | 카운터 정차 좌표 ID |

**액션 클라이언트**: `navigate_to_pose` (Nav2) — 카운터 위치로 단발 nav.

**동작**:
1. counter_pose_id 의 PoseStamped 조회 (tables.yaml 또는 별 yaml)
2. Nav2 NavigateToPose 단발 + 도착 시 SUCCESS
3. 도착 후 "여기서 주문하세요" 발화 (자체 또는 별 stage)

---

## 4. bt_executor 노드

### 4.1 파일

`src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp`

### 4.2 파라미터

| 이름 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `bt_xml_path` | string | `""` | 빈 값이면 패키지 share 의 `bt_xml/cafe_funnel_v1.xml` |
| `tick_period_ms` | int | 100 | BT tick 주기 (10Hz) |

### 4.3 동작

1. BehaviorTreeFactory 에 8 BT 노드 + dummy 등록
2. xml 로드 → BT::Tree 생성
3. ROS2 WallTimer 100ms 마다 `tree.tickOnce()` 호출
4. NodeStatus 변화 시 INFO 로깅 (스팸 방지)
5. FilteredCoutLogger 로 BT 내부 노이즈 필터 (IDLE 관련 전이 제외)

### 4.4 BehaviorTree.CPP 버전

`ros-jazzy-behaviortree-cpp 4.8.3-1noble` (apt 공식, Phase 1~5 동안 동결). CLAUDE.md §7 의 외부 의존성 버전 정책.

### 4.5 dev_common 의존

engaging 진입 전 dev_common.launch.py 가 떠 있어야 함 — 7 노드 (geva / rapport_tracker / persona_manager / dialog_router / face_avatar / tts_node / mode_manager) 가 BT 의 토픽 (rapport/event, dialog/request, dialog/utter_done 등) 처리.

dev_common 없으면 BT 가 tick 진행하다 utter_done 안 와서 IceBreak stage 에서 RUNNING 영구 stuck.

---

## 5. minigame_runner_node 설계

### 5.1 파일

`src/dobi_npc/dobi_npc_minigame/dobi_npc_minigame/minigame_runner_node.py`

### 5.2 인터페이스

**파라미터**:
| 이름 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `game_camera_index` | int | 2 | cv2.VideoCapture 인덱스 (카메라 3, 외장 RPC-20F) |

**구독**:
| 토픽 | 타입 | 용도 |
|---|---|---|
| `/minigame/start` | std_msgs/String | game_id (rps / speed_counter / cafe_ninja) |

**발행**:
| 토픽 | 타입 | 용도 |
|---|---|---|
| `/minigame/result` | dobi_npc_msgs/MinigameResult | 게임 결과 |
| `/face_avatar/suspend` | std_msgs/Empty | 게임 시작 전 face_avatar 디스플레이 양보 |
| `/face_avatar/resume` | std_msgs/Empty | 게임 종료 후 face_avatar 복귀 |

### 5.3 흐름

1. `/minigame/start` 수신 → registry lookup (game_id → game.py 경로)
2. `/face_avatar/suspend` publish + settle 대기 (~0.5s)
3. 5초 카운트다운 + 게임 룰 표시 (pygame 풀스크린, ESC 중도 포기)
4. subprocess: `python3 game.py --auto-play --difficulty <diff> --auto-exit N --ready-delay D --result-json <tmp> --camera-index 2`
5. subprocess wait (timeout). SIGTERM/SIGKILL fallback.
6. JSON 결과 파싱 → MinigameResult publish (game_id 보존)
7. `/face_avatar/resume` publish → IDLE 복귀

### 5.4 게임 registry

| game_id | 경로 | 의도 |
|---|---|---|
| `rps` | `games/06_rps_evolution/src/game.py` | 가위바위보 (Castro-González 2016 학술 정합) |
| `speed_counter` | `games/07_speed_counter/src/game.py` | 손가락 카운트 (reaction time) |
| `cafe_ninja` | `games/01_cafe_ninja/src/game.py` | 손동작 베기 (fun + 활발) |

games 디렉토리: `games/` (워크스페이스 루트, gitignore 가능성). [[project_playwait_integration]] 메모리 — 5단계 패턴 (카피 + game.py 4 patch + minigame_runner registry + BT game_pool + 라이브 검증).

### 5.5 카메라 분리 정책 (2026-05-06)

| 카메라 | 용도 | 인덱스 |
|---|---|---|
| 1 (노트북 내장) | GEVA 얼굴 V·A | 0 |
| 2 (RPi 직결 abko FHD1080p) | GEFA / follow person detection | (RPi 측) |
| 3 (노트북 외장 RPC-20F) | 게임 손 인식 | **2** |

이전 (2026-05-04~05): 게임 + GEVA 동시 카메라 1 사용 시 점유 충돌 + Salichs 2014 abort_trigger 학술 정합 깨짐 (게임 중 GEVA suspend 했음). 카메라 3 분리 후 GEVA 게임 중에도 가동 → abort_trigger 정상.

⚠ `/geva/suspend|resume` 흐름은 폐기 (2026-05-06). 메모리 [[project_camera_architecture]] SoT.

### 5.6 result JSON 스키마

```json
{
  "customer_wins": 7,
  "robot_wins": 2,
  "ties": 1,
  "rounds_played": 10,
  "completed": true,
  "duration_sec": 45.2
}
```

`customer_win_rate = customer_wins / rounds_played`. Castro-González 2016 목표 0.7 (engagement > winning).

---

## 6. mode_engaging.launch.py 설계

### 6.1 노드 구성

```python
return LaunchDescription([
    game_camera_index_arg,
    Node(
        package='dobi_npc_bt', executable='bt_executor',
        name='bt_executor', output='screen',
    ),
    Node(
        package='dobi_npc_minigame', executable='minigame_runner',
        name='minigame_runner', output='screen',
        parameters=[{
            'game_camera_index': ParameterValue(
                LaunchConfiguration('game_camera_index'),
                value_type=int),
        }],
    ),
])
```

### 6.2 launch arg

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `game_camera_index` | int | 2 | 카메라 3 (노트북 외장 RPC-20F). `/dev/video2` 일반적이나 환경별 조정. |

### 6.3 dev_common 의존

mode_engaging.launch.py 는 dev_common.launch.py 의 7 always-on 노드 (geva/rapport_tracker/persona_manager/dialog_router/face_avatar/tts/mode_manager) **을 스폰하지 않음**. 진입 전 미리 가동되어 있어야 함.

mode_manager 의 spawn 흐름:
1. `dev_common.launch.py` 가 PC 부팅/세션 시작 시 가동 (`scripts/run_dashboard.sh` 또는 `scripts/run_real.sh`)
2. 운영자가 dashboard 에서 mode → engaging 클릭
3. mode_manager 가 `subprocess.Popen("ros2 launch dobi_npc_bringup mode_engaging.launch.py game_camera_index:=2")`
4. bt_executor + minigame_runner 2 노드 spawn
5. BT 가 dev_common 의 토픽 (rapport/event, dialog/request 등) 사용

### 6.4 mode_npc.launch.py — Deprecation Wrapper

```python
# mode_npc.launch.py (2026-07-04 제거 예정)
# Legacy 진입점 — mode_engaging.launch.py 호출 wrapper
```

mode_manager 의 LEGACY_MODE_ALIAS = {'npc': 'engaging', 'follow': 'guiding'} 가 자동 변환 + WARN 로그. M3 종료 (2026-07-04) 후 wrapper launch + alias 모두 제거.

---

## 7. 안전 / 가드 통합

### 7.1 SafetyCheck (Stage 0a)

매 BT tick (10Hz) 마다 평가:
- 배터리 < 20% (percentage 0.20) → SUCCESS → abort
- /scan < 1.0m obstacle → SUCCESS → abort (scan_min_range 0.25 마스킹 후)

abort 시 bt_executor 가 BT tick 중단 → mode_manager 가 별 trigger (`/rapport/event` weight 큰 alarm 또는 직접 service) 로 idle 강제.

### 7.2 EmotionMonitor (Stage 0b)

매 tick 평가:
- `/rapport/event.event_type == "abort_trigger"` 수신 시 SUCCESS → abort
- rapport_tracker 가 GEVA + decision_rule 통합으로 abort_trigger 판정

학술 기준 (Russell 1980 + Salichs 2014):
- V < -0.5 (강한 negative — anger, fear) → abort_trigger
- A < -0.3 (boredom) → abort_trigger
- 그 외 (neutral / mild / positive) → engagement_up 또는 neutral_continue

### 7.3 Approach abort_threshold

Stage 2 의 `abort_threshold=1.0m` — 고객과 1m 이내 진입 시 Approach FAILURE → ReactiveFallback 다음 자식 평가 (또는 Sequence 종료).

이유: 너무 가까이 가면 고객 위협 — Proxemic personal zone 침범.

### 7.4 cmd_vel 안전 pipeline

bt_executor 는 cmd_vel 직접 발행 X. Approach/LeadIn 은 Nav2 NavigateToPose action — Nav2 controller_server 가 cmd_vel 발행, Phase B pipeline (twist_mux + smoother + collision_monitor) 가 OS 레벨 차단/감속.

### 7.5 utter_done 동기화

IceBreak/Offer 의 `/dialog/utter_done` 대기 — tts_node 가 발화 완료 시 발행. 발화 도중 abort 시 utter_done 안 옴 → BT stuck 위험. utter_action_base 에 abort 시 timeout 처리.

---

## 8. 페르소나 + Phrase Pool

### 8.1 페르소나 4 종

SoT: `src/dobi_npc/dobi_npc_dialog/config/personas/*.yaml`

| persona_id | 의도 | 대상 |
|---|---|---|
| `generic` | 기본 (fallback) | 페르소나 미지정 |
| `casual_browser` | 친근한 캐주얼 | 일반 손님 |
| `friendly_child` | 어린이 친화 | 아동 동반 |
| `professional_adult` | 정중한 사회인 | 회사원 / 미팅 |

⚠ CLAUDE.md §10 의 "페르소나 3종 YAML" 은 stale — 실 코드 SoT 는 **4 종** (generic 포함).

### 8.2 YAML 구조 (예: casual_browser.yaml)

```yaml
persona_id: casual_browser
display_name: "캐주얼 손님"
voice:
  engine: edge-tts
  voice_id: ko-KR-SunHiNeural
  rate: "+0%"
  pitch: "+0Hz"
phrase_pool:
  ice_break:
    - "안녕하세요, 카페 처음이세요?"
    - "오늘 무슨 드릴까요?"
  offer:
    warm_drink:
      - "추운 날엔 따뜻한 라떼 어떠세요?"
  polite:
    - "괜찮으세요?"
    - "도움 필요하시면 말씀해주세요"
```

### 8.3 persona_manager 동작

1. BT 의 IceBreak 가 `/dialog/request` 발행 (stage_id="ice_break", phrase_pool_id="casual_browser")
2. persona_manager 가 casual_browser.yaml 의 ice_break pool 에서 random 선택
3. `/dialog/router_in` 에 선택된 phrase + persona voice info publish
4. dialog_router 가 priority 큐 처리 → `/dialog/utter` 발행
5. tts_node 가 edge-tts 호출 → 음성 출력 + `/dialog/utter_done` 발행

### 8.4 Polite phrase (Castro-González 2016)

게임 도중 (특히 customer 가 robot 에게 진 경우) polite phrase 발화:
- "괜찮으세요?" / "한 번 더 하실래요?" / "잘 하시네요!"

목적: customer_win_rate 70% (목표) 미만 시 분위기 환기. minigame.hpp 가 game 결과 보고 polite 발화 트리거.

---

## 9. 단계별 구현

### 9.1 Phase 1 W1 — BT skeleton (완료, 2026-05-02)

✓ bt_executor + 8 stage dummy (SUCCESS only)
✓ cafe_funnel_v1.xml 정의
✓ SafetyCheck 배터리 만 (scan 미)

### 9.2 Phase 1 W2 — Nav2 통합 (완료, 2026-05-03)

✓ Approach → Nav2 NavigateToPose action client
✓ LeadIn → Nav2 단발

### 9.3 Phase 1 W3 — Phrase Pool (완료, 2026-05-03)

✓ persona 4 종 YAML
✓ persona_manager 노드 — random 선택
✓ IceBreak/Offer utter_action_base 패턴

### 9.4 Phase 2 W4 — Emotion (완료, 2026-05-02~04)

✓ EmotionMonitor BT 노드 + `/rapport/event` 구독
✓ rapport_tracker (GEVA + decision_rule 통합)
✓ TTS persona voice + face_avatar 8 표정

### 9.5 Phase 3 — Minigame (완료, 2026-05-05~06)

✓ minigame_runner subprocess wrapper
✓ 3 게임 (RPS / speed_counter / cafe_ninja) 통합
✓ 카메라 3 분리 (게임 손 인식)
✓ 5초 카운트다운 + 게임 룰 표시

### 9.6 Phase 5 (미시작) — XAI / Learning

- Iovino 2022 미해결 과제
- BT 의사결정 설명 (XAI) — 운영자가 "왜 abort 했는지" 시각 확인
- 페르소나 별 phrase pool 자동 학습 (강화학습 또는 LLM)

---

## 10. 테스트 계획

### 10.1 단위 테스트 (BT.CPP 자체)

각 BT 노드 단위 — `BT::TestNode` 또는 mock subscriber 로:
| 노드 | 케이스 |
|---|---|
| SafetyCheck | 배터리 0.21 vs 0.19 (경계), scan_min_range 마스킹 |
| EmotionMonitor | abort_trigger 수신 / engagement_up 수신 / neutral |
| Approach | customer_pose 수신 / Nav2 mock action / abort_threshold |
| Minigame | rotate 순환 / game.py mock 결과 / customer_win_rate |

### 10.2 sim 통합 (Gazebo)

`scripts/run_sim.sh` + dashboard 에서 mode → engaging 호출:
1. bt_executor 가 cafe_funnel_v1.xml tick 시작
2. SafetyCheck FAILURE (정상 배터리/scan), EmotionMonitor FAILURE (neutral)
3. IdleScan SUCCESS (dummy customer_id)
4. Approach Nav2 호출 (sim AMCL drift 한계로 실패 가능성 — `cafe_npc_rpi_live_amcl_checklist.md`)
5. IceBreak `/dialog/request` 발행 → persona phrase → TTS → utter_done → SUCCESS
6. Minigame `/minigame/start rps` → game.py subprocess → MinigameResult → SUCCESS
7. Offer → LeadIn 동상

### 10.3 라이브 (RPi + 실 카메라)

RPi 라이브 checklist §6.5 의 "시나리오 5 — emergency_stop" 직전 단계로 engaging 1회 실 검증. 사용자 손이 카메라 3 보이게 시 minigame 진행.

### 10.4 abort 시나리오

| 케이스 | 기대 결과 |
|---|---|
| 배터리 19% (< 20% 임계) | SafetyCheck SUCCESS → abort → idle 전이 |
| `/scan` 0.5m obstacle | SafetyCheck SUCCESS → abort |
| 운영자가 손짓 + 찡그림 (V<-0.5) | EmotionMonitor SUCCESS → abort |
| 운영자 emergency_stop | mode_manager SIGTERM → bt_executor 종료 |

---

## 11. 운영자 UI 연동

### 11.1 dashboard modes 페이지

- "모객 시작" 버튼 — game_camera_index input (default 2)
- POST `/api/v1/mode` body: `{"mode":"engaging","override_priority":true}`
- engaging 은 params 없음 (BT 가 자체 진행)

### 11.2 floorplan 시각화

- BT 진행 단계 표시 (Stage 1/6: IdleScan, Stage 2/6: Approach, ...)
- Approach / LeadIn Nav2 path 시각

### 11.3 events 페이지

- `bt_stage_transition` 이벤트: IdleScan → Approach → IceBreak → ... → idle
- `abort_event`: SafetyCheck 또는 EmotionMonitor 발동
- `minigame_result`: game_id + customer_win_rate

---

## 12. 미해결 / 후속

### 12.1 IdleScan 실 구현

현재 dummy customer_id. W2 후속: 천장 카메라 (dalimi 부적합 [[project_dalimi_unsuitable]]) 또는 외장 카메라 (카메라 2 abko person detection) 통합.

### 12.2 utter_done timeout

발화 도중 abort 시 utter_done 미수신 → BT stuck. utter_action_base 에 timeout 처리 — Phase 2 후속.

### 12.3 persona 별 dwell / abort_expression 세밀화

페르소나 YAML 의 `dwell_sec` / `abort_expression` 필드 — 글로벌 → persona 별. CLAUDE.md §10 ToDo.

### 12.4 hysteresis_ms / rapport_delta 출력 포트

EmotionMonitor 가 abort 직전 hysteresis 또는 점차적 rapport 변화 표시 — Phase 2 후속.

### 12.5 LeadIn 도착 후 발화

LeadIn 이 단순 Nav2 도착만. 도착 후 "여기서 주문하세요" 자체 발화 또는 별 Stage 7 분리 검토.

---

## 13. 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1.0 | 2026-05-17 | 초안 — Phase 1~3 실 구현 기반 (BT + minigame_runner + 페르소나 4종) |

---

## 14. 부록 — 코드 SoT 매핑

| 섹션 | 코드 위치 |
|---|---|
| §2 BT xml | `dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` |
| §3.1 SafetyCheck | `dobi_npc_bt/include/dobi_npc_bt/safety_check.hpp` |
| §3.2 EmotionMonitor | `dobi_npc_bt/include/dobi_npc_bt/emotion_monitor.hpp` |
| §3.3 IdleScan | `dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp` |
| §3.4 Approach | `dobi_npc_bt/include/dobi_npc_bt/approach.hpp` |
| §3.5 IceBreak | `dobi_npc_bt/include/dobi_npc_bt/ice_break.hpp` (utter_action_base.hpp 상속) |
| §3.6 Minigame | `dobi_npc_bt/include/dobi_npc_bt/minigame.hpp` |
| §3.7 Offer | `dobi_npc_bt/include/dobi_npc_bt/offer.hpp` |
| §3.8 LeadIn | `dobi_npc_bt/include/dobi_npc_bt/lead_in.hpp` |
| §4 bt_executor | `dobi_npc_bt/src/bt_executor_node.cpp` |
| §5 minigame_runner | `dobi_npc_minigame/dobi_npc_minigame/minigame_runner_node.py` |
| §6 launch | `dobi_npc_bringup/launch/mode_engaging.launch.py` (60 줄) |
| §6.4 legacy wrapper | `dobi_npc_bringup/launch/mode_npc.launch.py` |
| §8 persona | `dobi_npc_dialog/config/personas/{generic,casual_browser,friendly_child,professional_adult}.yaml` |
