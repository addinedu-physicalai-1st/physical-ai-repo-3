# 카페 호객 로봇 — 안전 영역(Safety Zone) 침입 시 일시정지/재개 메커니즘

**작성일**: 2026-05-08
**프로젝트**: Dobi Barista 호객 BT
**대상 시스템**: Vic Pinky Pro (모바일 베이스, ≤ 0.3 m/s) + RPLiDAR 360° + USB 카메라 2대 + ROS2 Jazzy + BehaviorTree.CPP 4.8.3 + 노트북-RPi 분산
**관련 문서**: `cafe_npc_paper_master.md` (학술 척추), `cafe_npc_system_architecture.md`, `cafe_npc_engagement_funnel.md`, `cafe_npc_camera_architecture.md`, `cafe_npc_implementation_plan.md`
**문서 성격**: 기술 조사(학술 + 표준 + 현업 + ROS2) + 우리 시스템 적용 계획 통합본

---

## 0. Executive Summary

카페에서 점주/손님/객체가 로봇 작업 영역에 침입할 때 호객을 **abort 하지 않고 일시정지 후 재개**하는 메커니즘을 설계해야 한다. 이는 단순한 BT halt 가 아니라, **IEC 60204-1 Stop Category 2 + Monitored Standstill** 의 표준 정의에 정확히 대응하는 동작이며, 자동 재개가 표준적으로 허용된다 (단 dwell hysteresis + 점진적 가속 + 재개 의도 표현 필수).

**조사 결론 5가지**:

1. **표준 매핑은 이미 명확하다**. 1차 표준은 **EN/KS B ISO 13482** (mobile servant robot, Type 1.2, PL=d 요구). 일시정지/재개는 **IEC 60204-1 Cat 2**. 이중 영역 모델은 **ISO 3691-4** (Warning + Protective). 산식은 **ISO/TS 15066 SSM** 으로 정량 검증 (현재 1.0m 임계값이 표준 산출값과 일치).
2. **학술과 현업 모두 "Freeze ≠ Pause" 를 강조**. Trautman 2010 의 Freezing Robot Problem 이후 사회적 큐(intent signaling) 동반 pause 가 1차 시민. 현업에서도 Diligent Moxi(의도 표현), Savioke Relay(chirp+nod), Pudu BellaBot(고양이 표정+excuse me) 모두 같은 패턴.
3. **ROS2 Jazzy 에 검증된 인프라가 있다**. `nav2_collision_monitor` (cmd_vel 차단) + `nav2_collision_detector` (알람만) + `twist_mux` (e-stop 통합) + `nav2_velocity_smoother` (감속 곡선) 4개 패키지 조합으로 즉시 도입 가능. 자체 구현은 비효율.
4. **분산 DDS 환경의 함정**. cmd_vel 차단 노드는 **반드시 RPi (zlac_driver 옆)** 에 배치. 노트북 배치 시 Wi-Fi 단절 = fail-open. 본 시스템 이미 unicast peers 적용됐으므로 RPi 측 launch 추가만 필요.
5. **현재 자산이 학술적으로 옳은 방향**. abort_dwell_sec=2.0, rapport hysteresis 5프레임, face_avatar 8 어휘, persona phrase pool — 모두 학술 권고와 정합. 신규 작업은 (a) **이중 영역(Warning+Protective) 분리**, (b) **사람/사물 fusion**, (c) **재개 jerk limit**, (d) **stage-aware SSM 임계값**, (e) **사회적 의도 표현 큐 (TTS+face_avatar)**.

**최우선 작업 (D+1~D+7 도입 가능)**:
```bash
sudo apt install ros-jazzy-nav2-collision-monitor \
                 ros-jazzy-nav2-velocity-smoother \
                 ros-jazzy-twist-mux \
                 ros-jazzy-laser-filters
```
RPi 측 vicpinky bringup 에 4개 노드 lifecycle 통합 + BT 의 SafetyCheck 에 `IsCollisionFree` Condition 추가 → live 검증.

---

## 1. 학술적 근거 (요약)

상세는 본 보고서 §1.A 에. 핵심 통찰:

| 통찰 | 학술 근거 | 우리 적용 |
|---|---|---|
| Stage 별 SSM 임계값 동적 스위칭 | Bdiwi 2022, Byner 2019 | APPROACH=1.5m / ICEBREAK=1.0m / MINIGAME=0.6m |
| Freeze 가 아닌 사회적 pause | Trautman 2010, Mavrogiannis 2023 | avoid → slow → pause-with-signal → abort 4단 결정 |
| Peek-and-pass (좁은 통로 통과율 16.7→73.1%) | Williams 2024 (arXiv:2403.13284) | Approach 노드에 적용 가능 (후속) |
| 재개 충돌 1.7× 빈번 → dwell + jerk limit + yielding 큐 | Babel 2022 | velocity_smoother max_decel + 재개 발화 stage 추가 |
| Hysteresis 일관 적용 | Marvel 2017, Iovino 2022 | 모든 토글에 진입/퇴출 분리 (이미 rapport에 적용) |
| Eye-gaze acknowledgment 가능 | Skantze 계열, PMC 12485069 | Phase 5 후속 (mediapipe head pose) |

### 1.A SSM 분리거리 공식 — 우리 시스템 산출값

ISO/TS 15066 §5.5 + Marvel & Norcross 2017:

```
S(t₀) ≥ ∫(t₀ → t₀+TR+TS) vH(τ)dτ      ← Sh (Human travel)
       + ∫(t₀ → t₀+TR)    vR(τ)dτ      ← Sr (Robot reaction travel)
       + ∫(t₀+TR → t₀+TR+TS) vS(τ)dτ   ← Ss (Robot stopping travel)
       + (C + ZS + ZR)                  ← 마진 (intrusion + sensor + robot uncertainty)
```

**Vic Pinky 산출**:
- vR = 0.3 m/s, vS = 0.15 m/s (감속 평균), vH = 1.6 m/s (ISO 13855 walking)
- TR ≈ 100ms (LiDAR 10Hz + ROS2 latency), TS ≈ 200~400ms (브레이크)
- Sh = 1.6 × 0.5 = **0.8 m**
- Sr = 0.3 × 0.1 = **0.03 m**
- Ss = 0.15 × 0.3 = **0.05 m**
- C ≈ **0.1~0.2 m** (카페 환경 — ISO 13855 손 도달 0.85m 는 과대; 보행자 침입이 risk model)
- ZS ≈ **0.03 m** (RPLiDAR 노이즈), ZR ≈ **0.05 m** (odom drift)
- **합계 S ≈ 1.0~1.1 m** ⇐ 현재 SafetyCheck 1.0m 임계값이 **표준적으로 합리적임을 사후 검증**

---

## 2. 표준 매핑 (요약)

상세는 본 보고서 §2.A 에.

### 2.1 표준 트리 — 우리 시스템에 적용되는 위계

```
┌─────────────────────────────────────────────────────────────────┐
│  [1차 적합 표준]                                                │
│   EN ISO 13482:2014 + KS B ISO 13482  (mobile servant robot)    │
│   - Type 1.2 (mobile fast servant) → 최소 PL=d (ISO 13849-1)    │
│   - 보호 정지 공간 (protective stop space) 정의                  │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│  [보조 — 산식/모델]                                              │
│   ISO/TS 15066:2016    SSM 분리거리 공식 (정량 검증)              │
│   ISO 3691-4:2023      이중 영역 (Warning + Protective)           │
│   IEC 60204-1 §9.2.2   Stop Category 0/1/2 + Monitored Standstill│
│   ISO 13849-1:2023     PL=d Category 3 architecture              │
│   ISO 13855            인체 도달 시간 표준값 (vH=1.6 m/s)         │
└─────────────────────────────────────────────────────────────────┘

[비적용 — 명시적 scope 제외]
   ANSI/A3 R15.08-1-2020   "industrial environment with trained personnel"
                           "lack of uncontrolled access by members of the public"
                           카페는 명시적 미적용
```

### 2.2 정지 정책 매트릭스 — 표준 매핑

| 정지 사유 | Stop Category | 재개 방식 | 표준 근거 | 본 시스템 구현 위치 |
|---|---|---|---|---|
| 사람 < 1.0m (SafetyCheck) | **Cat 2 + Monitored** | 자동 (dwell + hysteresis) | ISO/TS 15066 SSM, ISO 13482 §6 | 본 문서 §3 신규 PauseGate |
| LiDAR scan obstacle | Cat 2 + Monitored | 자동 (dwell) | ISO 3691-4 protective field | 본 문서 §3 신규 PauseGate |
| 손님 abort 감정 (V<−0.5, A>+0.4) | Cat 2 (UI 한정) | 자동 (BT funnel reset) | ISO 13482 §5 (psychological harm) | 기존 EmotionMonitor |
| 배터리 < 20% | Cat 1 (감속 후 복귀) | 충전 후 자동 | ISO 13482 §5.13 | 기존 SafetyCheck (배터리) |
| 점주 e-stop 버튼 (미래) | Cat 0 또는 1 | **manual reset 필수** | ISO 13850, NFPA 79 | Phase 후속 (물리 버튼) |
| 시스템 fault (sensor 끊김) | Cat 1 | manual reset 권장 | ISO 13849 PL=d | 신규 health monitor (후속) |

**핵심 결론**: 우리가 구현하려는 "작업 영역 침입 → 일시정지 → 자동 재개" 는 **Cat 2 + Monitored Standstill** 으로 표준 정합적이며, ISO/TS 15066 §5.5 와 ISO 3691-4 Annex A 에서 자동 재개가 명시적으로 허용된다.

### 2.3 공공장소 갭 — 표준이 다루지 않는 영역

ACM TROHI 2021 (Salem et al., "On the Safety of Mobile Robots Serving in Public Spaces") 가 EN ISO 13482:2014 의 갭을 학술적으로 지적:
- (1) **군중(crowds)** 명시 미흡
- (2) **사회적 규범/proxemics** 미반영
- (3) **사람의 미숙/돌발 행동** 가정 부재

본 시스템은 이 갭을 **BT funnel 의 emotional abort + dwell hysteresis + 점주 override** 로 보강하는 설계다. 회고/논문 작성 시 이 갭을 명기 권장.

---

## 3. 현업 사례 비교 (요약)

상세는 본 보고서 §3.A 에. 가장 정합도 높은 4개 모델 결합:

| 모델 | 차용 항목 | 우리 구현 |
|---|---|---|
| **MiR AMR + SICK microScan3** | 2단계 zone (Warning + Protective), 속도 의존 zone switching, ISO 13849 Cat 3 PL=d | nav2_collision_monitor 의 VelocityPolygon |
| **Pudu BellaBot** | "비키면 자동 재개, 막히면 음성 안내 후 운영자 알림" 3단 timer | dwell_to_warn(2s) → warn_voice(+3s) → operator_alert(+5s) |
| **Diligent Moxi** | 사전 의도 표현 (intent signaling) — 다음 동작을 시각/음성으로 미리 알림 | face_avatar 표정 + TTS 의 stage 전환 큐 |
| **Savioke Relay** | 좁은 호텔 복도, chirp + nod + 표정 (음성 없음 — 침묵 모드) | 점주 인식 시 침묵 양보 (Phase 후속) |
| **Starship** | 정면/측면 이분법 (정면 정지 / 측면 감속) — Freezing Robot Problem 회피 | 장애물 angle ±30° 이내만 정지, 그 외 감속 |
| **UR PolyScope** (대조군) | Safety Plane × 8 의 4모드 (Disabled/Normal/Reduced/Trigger) | persona YAML 의 safety section 으로 차등화 |

### 3.1 알림 채널 — 3중화 표준

Keenon T8/W3 표준: **음성 + 표정/디스플레이 + LED**. 우리 시스템 매핑:

```
음성 (TTS)            → "잠시만요" / "다시 모실게요" — persona phrase pool
표정 (face_avatar)    → basic(중립) → interest(재개 알림)
LED (vic_pinky 하단)  → 노란색(warning) / 빨간색(protective) — 신규 토픽 /safety/state
```

LED 채널은 신규 추가가 필요. ROS2 토픽 `/safety/state` (enum: NORMAL/WARNING/PROTECTIVE) 발행 → vic_pinky 측 LED 구독자 추가.

---

## 4. ROS2 도구 스택 (요약)

상세는 본 보고서 §4.A 에. 권장 cmd_vel 파이프라인:

```
[BT Approach]   [follow_controller]  [teleop joy]  [e_stop 버튼(향후)]
       │              │                  │              │
       │/bt/cmd_vel   │/follow/cmd_vel  │/joy/cmd_vel  │/e_stop (Bool)
       └──────┬───────┴──────────────────┘              │
              ↓                                         │
       twist_mux  (priority + lock)        ←────────────┘
              ↓ /cmd_vel_raw
       nav2_velocity_smoother  (max_decel 큼, jerk limit)
              ↓ /cmd_vel_smoothed
       nav2_collision_monitor  (Stop polygon 0.4m + Slowdown polygon 0.7m)
              ↓ /cmd_vel
       vic_pinky bringup → zlac_driver

       (병렬 — 사회적 거리)
       nav2_collision_detector → /collision_detector_state
              ↓ (어댑터 노드)
       /safety/zone_intrusion (SafetyZoneState)
              ↓
       BT IsCollisionFree Condition + face_avatar/TTS 의도 큐
```

### 4.1 노드별 책임 분담

| 노드 | 책임 | 배치 | Stop Category |
|---|---|---|---|
| `twist_mux` | cmd_vel 우선순위 통합 + e-stop bool lock | **RPi** | (라우팅) |
| `nav2_velocity_smoother` | 가속/감속 곡선 + jerk limit | **RPi** | (재개 시 ramp-up) |
| `nav2_collision_monitor` | 물리 충돌 zone (Stop 0.4m, Slowdown 0.7m) | **RPi** | **Cat 2 + Monitored** |
| `nav2_collision_detector` | 사회적 zone (1.2m Hall personal, 알람만) | RPi 또는 노트북 | (이벤트 발행) |
| 신규 `safety_zone_adapter` | collision_detector_state → SafetyZoneState 변환 | 노트북 | (메시지 변환) |
| `bt_executor` (BT IsCollisionFree) | BT 의 Cat 2 정지 동기화 | 노트북 | RUNNING 유지 |
| `face_avatar` / `tts_node` | 의도 표현 큐 (intent signaling) | 노트북 | (HRI 채널) |

**분산 DDS 핵심**: cmd_vel 차단 4 노드(twist_mux + smoother + monitor + zlac_driver)는 **물리적으로 같은 호스트(RPi)** 에 있어야 fail-safe. Wi-Fi 단절 시에도 collision_monitor 가 `/cmd_vel_smoothed` 토픽을 차단해서 zlac_driver 가 0 출력으로 자동 정지.

### 4.2 BT 패턴 — ReactiveSequence 표준

BehaviorTree.CPP 4.8.3:

```xml
<!-- cafe_funnel_v1.xml — 신규 SafetyZone 통합 -->
<ReactiveFallback>
  <SafetyCheck/>          <!-- 기존: 배터리 + 정면 충돌 임박 (Cat 1/2) -->
  <EmotionMonitor/>       <!-- 기존: 손님 abort 감정 (Cat 2 UI 한정) -->
  <ReactiveSequence>      <!-- 신규: 작업 영역 일시정지 (Cat 2 + Monitored) -->
    <IsZoneClear/>          <!-- Condition: SafetyZoneState.intruded == false -->
    <Inverter><IsZoneIntruded/></Inverter>  <!-- 또는 동치 -->
    <CafeFunnel/>           <!-- 5-stage funnel (RUNNING 유지) -->
  </ReactiveSequence>
</ReactiveFallback>
```

**핵심**: `IsZoneClear` Condition 이 FAILURE 가 되면 ReactiveSequence 가 cafe_funnel 의 **현재 진행 중 노드를 halt() 호출** — 단, halt 의 의미를 "일시정지" 로 재정의하기 위해 별도 메커니즘이 필요. 자세한 설계는 §5 참조.

---

## 5. 통합 설계 — 카페 호객 로봇 PauseGate 메커니즘

### 5.1 개념 모델 — 3계층 안전

기존 2계층(SafetyCheck + EmotionMonitor) → **3계층** 으로 확장:

```
Layer 1: Hard Safety (Cat 1)
  [SafetyCheck] 배터리 < 20% OR /scan 정면 < 0.4m (즉시 충돌 임박)
  → ReactiveFallback halt → mode_manager idle 강제 (5s dwell)
  → 표준: ISO 13482 §5, IEC 60204-1 Cat 1
  → 동작: 호객 abort + 충전소 복귀 또는 운영자 알림

Layer 2: Soft Safety / Pause (Cat 2 + Monitored)  ← 신규 ★
  [PauseGate] /scan 정면 < 1.0m OR /scan 측면 < 0.5m
              OR person_detector 1.2m 이내
  → cafe_funnel RUNNING 유지 + cmd_vel 차단 + utter 큐 hold + 의도 표현
  → 표준: IEC 60204-1 Cat 2, ISO 3691-4 Warning/Protective, ISO/TS 15066 SSM
  → 동작: 일시정지 → 해제 시 같은 자리 재개

Layer 3: Social Abort (Cat 2 UI 한정)
  [EmotionMonitor] /rapport/event abort_trigger (V<−0.5, A>+0.4 5프레임)
  → cafe_funnel halt → mode_manager idle 전이
  → 표준: ISO 13482 §5 psychological harm
  → 동작: 호객 포기 (재시작 시 새 cycle)
```

**Layer 2 가 본 작업의 핵심**. Layer 1 과 Layer 3 는 기존 동작 유지.

### 5.2 Zone 정의 — 이중 영역 + 속도 의존

ISO 3691-4 + MiR/SICK 패턴 차용. nav2_collision_monitor 의 VelocityPolygon 사용:

```yaml
# nav2_collision_monitor.yaml
collision_monitor:
  ros__parameters:
    base_frame_id: "base_link"
    odom_frame_id: "odom"
    cmd_vel_in_topic: "cmd_vel_smoothed"
    cmd_vel_out_topic: "cmd_vel"
    state_topic: "collision_monitor_state"
    transform_tolerance: 0.5
    source_timeout: 2.0
    base_shift_correction: true
    enable_stamped_cmd_vel: false   # vic_pinky bringup 호환 고정

    polygons: ["PolygonStop", "PolygonSlow"]
    observation_sources: ["scan"]

    PolygonStop:
      type: "polygon"
      points: "[[0.40, 0.30], [0.40, -0.30], [-0.10, -0.30], [-0.10, 0.30]]"
      action_type: "stop"            # Cat 2 — cmd_vel 차단
      min_points: 4
      visualize: true
      polygon_pub_topic: "polygon_stop"

    PolygonSlow:
      type: "polygon"
      points: "[[0.70, 0.45], [0.70, -0.45], [-0.20, -0.45], [-0.20, 0.45]]"
      action_type: "slowdown"
      slowdown_ratio: 0.4            # 40% 속도로 감속
      min_points: 4
      visualize: true
      polygon_pub_topic: "polygon_slow"

    scan:
      type: "scan"
      topic: "/scan"
      min_height: 0.0
      max_height: 1.0
```

**선택 기준**:
- PolygonStop: 0.40m × 0.60m 직사각형 — vic_pinky 차폭 0.30m + SSM 마진. ISO 3691-4 protective field.
- PolygonSlow: 0.70m × 0.90m 직사각형 — Warning field. 손님이 다가올 때 자연스러운 감속.
- 자기반사 0.18~0.21m 는 PolygonStop 후방을 -0.10m 부터 시작해 자체 마스킹 (또는 laser_filters/LaserScanRangeFilter 0.25m prefilter 병행).

**향후 VelocityPolygon 전환** (D+7 이후): 정지/전진/회전 3 sub-polygon — 회전 시 측면 zone 확장.

### 5.3 사회적 zone — 별도 collision_detector

물리 충돌 외에 **Hall personal zone (1.2m)** 침입을 별도 메커니즘으로 감지. 이 zone 은 cmd_vel 차단이 아니라 BT 에 이벤트만 발행:

```yaml
# nav2_collision_detector.yaml
collision_detector:
  ros__parameters:
    frequency: 10.0
    base_frame_id: "base_link"
    transform_tolerance: 0.1
    source_timeout: 2.0

    polygons: ["PolygonSocial"]
    observation_sources: ["scan"]

    PolygonSocial:
      type: "polygon"
      points: "[[1.20, 0.80], [1.20, -0.80], [-0.30, -0.80], [-0.30, 0.80]]"
      action_type: "none"  # 알람만, cmd_vel 차단 X
      min_points: 4
      visualize: true
```

**출력**: `/collision_detector_state` (`nav2_msgs/CollisionDetectorState`) → 어댑터 노드 → `/safety/zone_intrusion` (`dobi_npc_msgs/SafetyZoneState`).

### 5.4 신규 메시지 정의

```
# dobi_npc_msgs/msg/SafetyZoneState.msg
std_msgs/Header header
bool intruded
string zone_type           # "protective" | "warning" | "social"
string source              # "scan" | "vision" | "fused"
float32 distance_m         # 가장 가까운 침입 거리 (-1.0 if N/A)
float32 angle_rad          # 침입 방향 (정면 0, 좌 +π/2, 우 -π/2)
string reason              # "scan_protective_polygon" | "person_detector_close" | ...
uint32 intruded_count      # hysteresis 카운터 (디버깅용)
```

```
# dobi_npc_msgs/msg/RobotSafetyStatus.msg
# (industrial_msgs/RobotStatus 의 ROS2 미릴리스 보강 — 자체 정의)
std_msgs/Header header
uint8 mode                 # 0=AUTO, 1=MANUAL, 2=DISABLED
bool e_stopped             # 비상정지 활성
bool drives_powered        # 모터 전원
bool motion_possible       # 동작 가능 (Cat 2 정지 시 false)
bool in_motion
bool in_error
string error_code
SafetyZoneState[] active_zones  # 현재 침입된 zone 목록
```

### 5.5 신규 노드 설계

#### 5.5.1 `safety_zone_monitor_node` (위치: `dobi_npc_emotion` 또는 신규 `dobi_npc_safety`)

**책임**: `/scan` + `/robot_cam/persons` + `/collision_detector_state` 를 통합해 `/safety/zone_intrusion` 발행.

```python
# pseudo
class SafetyZoneMonitorNode(Node):
    def __init__(self):
        # 입력
        self.scan_sub = ...    # /scan
        self.persons_sub = ... # /robot_cam/persons
        self.detector_sub = ... # /collision_detector_state
        # 출력
        self.zone_pub = self.create_publisher(SafetyZoneState, "/safety/zone_intrusion", 10)
        # hysteresis
        self.intruded_count = 0
        self.cleared_count = 0

    def on_tick(self):
        # 1. /scan 정면 ±60° 부채꼴 0.3~1.0m 검사
        # 2. /robot_cam/persons bbox + 카메라 intrinsic → 거리 추정
        # 3. /collision_detector_state social polygon 결과
        # 4. fusion: any() 로 intruded 결정
        # 5. hysteresis: 진입(5 frame), 퇴출(10 frame, 더 길게)
        # 6. publish SafetyZoneState
```

**Hysteresis 정책**:
- 진입(intrude): 5 프레임 연속 (0.5s @ 10Hz)
- 퇴출(clear): 10 프레임 연속 (1.0s @ 10Hz) — 채터링 방지 (Marvel 2017)
- no_signal 처리: scan timeout > 2s OR confidence ≤ 0 → 카운트 동결

#### 5.5.2 BT 노드: `IsZoneClear` (Condition)

```cpp
// dobi_npc_bt/include/dobi_npc_bt/is_zone_clear.hpp
class IsZoneClear : public BT::ConditionNode {
public:
  IsZoneClear(const std::string& name, const BT::NodeConfig& config)
    : BT::ConditionNode(name, config) {
    auto node = config.blackboard->get<rclcpp::Node::SharedPtr>("node");
    sub_ = node->create_subscription<SafetyZoneState>(
      "/safety/zone_intrusion", 10,
      [this](SafetyZoneState::SharedPtr msg) { last_ = *msg; });
  }

  static BT::PortsList providedPorts() {
    return { BT::OutputPort<std::string>("zone_type"),
             BT::OutputPort<float>("distance_m") };
  }

  BT::NodeStatus tick() override {
    if (!last_.has_value()) return BT::NodeStatus::SUCCESS;  // 메시지 없음 = 안전 가정
    if (last_->intruded) {
      setOutput("zone_type", last_->zone_type);
      setOutput("distance_m", last_->distance_m);
      return BT::NodeStatus::FAILURE;  // 침입 = 일시정지 트리거
    }
    return BT::NodeStatus::SUCCESS;
  }
};
```

#### 5.5.3 BT 통합 — cafe_funnel_v1.xml 갱신

```xml
<root BTCPP_format="4">
  <BehaviorTree ID="MainTree">
    <ReactiveFallback name="root_alarm">
      <!-- Layer 1: Hard safety (기존) -->
      <SafetyCheck/>

      <!-- Layer 3: Social abort (기존) -->
      <EmotionMonitor/>

      <!-- Layer 2: Pause/Resume (신규) -->
      <ReactiveSequence name="pause_gate">
        <IsZoneClear zone_type="{intruded_zone}"/>
        <CafeFunnel/>
      </ReactiveSequence>
    </ReactiveFallback>
  </BehaviorTree>
</root>
```

**동작**:
- `IsZoneClear` SUCCESS → cafe_funnel tick 진행 (정상 호객)
- `IsZoneClear` FAILURE → ReactiveSequence FAILURE → cafe_funnel halt() 호출 (일시정지)
- 단, **halt 의 시맨틱이 cleanup 이 아닌 freeze 가 되도록** 각 BT 노드 onHalted() 갱신 필요 (§5.6)

#### 5.5.4 onHalted() 시맨틱 — Pause vs Abort

기존 onHalted() 는 Approach 의 cancel_all_goals + Minigame 의 subprocess kill 등 **abort cleanup** 동작이다. PauseGate 에서는 다른 의미가 필요:

**선택 A: onHalted() 분기 (권장)**
- BT 부모 노드가 halt 사유를 blackboard 에 기록 (`halt_reason: "pause" | "abort"`)
- 자식 노드 onHalted() 가 blackboard 읽고 분기:
  - "pause": 상태 보존 (Approach goal 보관, Minigame subprocess 일시정지 — SIGSTOP)
  - "abort": 기존 cleanup

**선택 B: 별도 BT 토폴로지**
- PauseGate 가 cafe_funnel halt 가 아닌 cmd_vel 차단으로만 동작
- BT 자체는 RUNNING 유지, cmd_vel pipeline 의 collision_monitor 가 차단
- 단점: BT 내부 상태(예: TTS playing, minigame running) 가 정합 안 됨

**결정**: **선택 A (onHalted 분기) + Layer 2 의 nav2_collision_monitor 의 cmd_vel 차단 병행**. 이중 안전.

### 5.6 actuator 별 pause 동작

| Actuator | Pause 동작 | Resume 동작 |
|---|---|---|
| **cmd_vel (Approach, follow)** | nav2_collision_monitor 가 0 송신 (Cat 2) + BT 노드는 goal 보관 | BT 노드 goal 재송신 + smoother ramp-up |
| **TTS (진행 중 발화)** | **cut 안 함** — 자연 종료까지 대기 (Skantze gaze paradigm) | (영향 없음) |
| **TTS (큐 대기)** | dialog_router 가 hold (priority 무관) | 큐 head 부터 정상 dispatch |
| **face_avatar** | 현재 expression 유지 (basic 강제 안 함) | resume 큐 trigger 시 `interest` 잠시 → 원래 expression |
| **minigame_runner (subprocess)** | **무시** — 게임 중에는 cmd_vel 송신 X. 게임 그대로 진행 | (영향 없음) |
| **persona_manager** | (영향 없음) — 큐만 router 가 hold | (영향 없음) |
| **mode_manager** | mode 유지 (idle 강제 X) | (영향 없음) |

**핵심 차이 (Pause vs Abort)**:
- **Pause**: BT RUNNING 유지, 진행 중 발화 cut X, 게임 영향 X, mode 유지
- **Abort**: BT halt + cleanup, mixer.stop(), subprocess kill, mode_manager idle 강제

### 5.7 의도 표현 (Intent Signaling) — Diligent Moxi 패턴

Pause 진입/유지/해제 시점에 사회적 큐 발행:

```
T=0.0s   사람 1.2m 이내 진입 (warning zone)
         → /face_avatar/expression "interest" (사람 인지 표시)
         → (음성 없음 — 잠깐의 상호 인식)

T=0.5s   여전히 침입 (5 frame hysteresis 통과)
         → IsZoneClear FAILURE → cafe_funnel halt (Pause)
         → cmd_vel 0 (collision_monitor)

T=2.0s   Pause dwell 통과 (warn_voice 임계)
         → /dialog/request "pause_excuse" (priority=safety, preempt)
            → "잠시만요" 또는 "지나가세요" (페르소나별 phrase)
         → /face_avatar/expression "basic" (양보 표정)

T=5.0s   여전히 침입 (operator_alert 임계)
         → /mode/state.last_reject_reason = "long_pause"
         → 운영자 UI 알림 (향후)
         → /face_avatar/expression "bored" (또는 "interest")

T=??     사람 비킴 (cleared 10 frame hysteresis 통과)
         → IsZoneClear SUCCESS → cafe_funnel 재개
         → /dialog/request "resume_after_pause"
            → "계속 진행하겠습니다" (페르소나별)
         → /face_avatar/expression "hello" 또는 stage 복귀 expression
         → cmd_vel ramp-up (smoother max_accel limit)
```

**Babel 2022 권고 — 재개 jerk limit**: nav2_velocity_smoother 의 `max_accel: 0.3 m/s²` (현재 가정 0.5 m/s² 보다 보수적) → 0.3m/s 도달까지 1초. 보행자가 갑작스러운 가속에 놀라는 것 방지.

### 5.8 Persona YAML 확장 — safety section

```yaml
# config/personas/casual_browser.yaml
persona_id: "casual_browser"
parent: "generic"

voice: {...}
phrases: {...}
face_expression: {...}

# 신규 — safety section
safety:
  pause_warn_dwell_sec: 2.0       # Pause 진입 후 발화까지 대기
  pause_alert_dwell_sec: 5.0      # 발화 후 운영자 알림까지 대기
  resume_announce: true           # 재개 시 발화 활성화
  pause_face_expression: "basic"  # 양보 표정
  resume_face_expression: "hello" # 재개 표정
  zone_warning_m: 1.5             # 사회적 zone 임계 (페르소나별)
  zone_protective_m: 0.6
phrases:
  pause_excuse:
    ko: ["잠시만요", "지나가세요", "조심해 주세요"]
  resume_after_pause:
    ko: ["계속 진행하겠습니다", "다시 모실게요", "이제 안내드릴게요"]
```

페르소나별 차등화:
- `friendly_child`: zone_warning_m=2.0 (어린이는 좀 더 멀리), pause_excuse="안녕하세요!" 친근
- `professional_adult`: zone_warning_m=1.2 (효율 우선), pause_excuse="실례합니다" 정중

### 5.9 LED 채널 (vic_pinky 하단)

신규 토픽 `/safety/state`:
```
# dobi_npc_msgs/msg/SafetyState.msg
std_msgs/Header header
uint8 level                # 0=NORMAL, 1=WARNING, 2=PROTECTIVE, 3=ABORT
string source              # 어떤 노드가 발행했는지
```

vic_pinky 측 LED 컨트롤러는 별도 패키지 (Phase 후속). 현 단계는 토픽 발행만.

---

## 6. 적용 계획 — Phase A ~ E

각 Phase 는 **한 단계씩 검증** (Stephen 워크플로우). 빌드/실행 검증 후 다음.

### Phase A — 인프라 도입 (D+1, 0.5일)

**목표**: ROS2 안전 도구 4종 apt 설치 + twist_mux 통합 (cmd_vel pipeline 의 첫 단계).

**작업**:
- A1. apt 설치 (RPi 측):
  ```bash
  sudo apt install ros-jazzy-nav2-collision-monitor \
                   ros-jazzy-nav2-velocity-smoother \
                   ros-jazzy-twist-mux \
                   ros-jazzy-laser-filters
  ```
- A2. RPi 측 `vicpinky_bringup` launch 에 `twist_mux` 통합:
  - 입력: `/bt/cmd_vel`, `/follow/cmd_vel`, `/joy/cmd_vel`
  - 우선순위 lock: `/e_stop` (Bool)
  - 출력: `/cmd_vel_raw`
- A3. 기존 follow_controller_node, BT Approach 의 cmd_vel 발행 토픽명을 `/follow/cmd_vel`, `/bt/cmd_vel` 로 변경 (rename only).
- A4. live 검증:
  - twist_mux 가 정상 라우팅하는지 (rqt_graph)
  - follow 모드 + teleop 동시 활성 시 우선순위
  - `/e_stop` true publish → cmd_vel 즉시 0

**검증 통과 조건**: follow 모드 정상 작동 + e_stop bool publish 시 즉시 정지.

**Task 추가**:
- `apt 4 패키지 설치`
- `RPi vicpinky_bringup launch 에 twist_mux 통합`
- `cmd_vel 토픽 rename + follow_controller/Approach 갱신`
- `Phase A live 검증`

### Phase B — Velocity Smoother + Collision Monitor (D+2~3, 1일)

**목표**: cmd_vel pipeline 에 smoother + monitor 추가. 물리 충돌 zone 차단.

**작업**:
- B1. `nav2_velocity_smoother` 설정 (`config/safety/velocity_smoother.yaml`):
  - max_velocity: [0.3, 0.0, 1.0]
  - max_accel: [0.3, 0.0, 1.5] (Babel 2022 권고 보수적)
  - max_decel: [-0.8, 0.0, -1.5] (감속은 빠르게)
  - velocity_timeout: 1.0
- B2. `nav2_collision_monitor` 설정 (§5.2 참조):
  - PolygonStop (0.40m × 0.60m, action_type=stop)
  - PolygonSlow (0.70m × 0.90m, action_type=slowdown, ratio=0.4)
  - source: `/scan`
- B3. RPi launch 통합:
  ```
  twist_mux → /cmd_vel_raw
    → velocity_smoother → /cmd_vel_smoothed
    → collision_monitor → /cmd_vel
    → zlac_driver
  ```
- B4. lifecycle_manager 등록 (configure/activate 자동화).
- B5. RViz polygon 시각 검증 + 사람/벽 접근 라이브 측정.

**검증 통과 조건**:
- 사람이 0.4m 이내 → cmd_vel 즉시 0 (BT 는 RUNNING 유지)
- 사람이 0.7m 이내 → 0.4× 속도 감속
- 사람이 0.7m 밖 → 정상 속도

**Task 추가**:
- `velocity_smoother + collision_monitor 설정 작성`
- `RPi launch lifecycle 통합`
- `Phase B live 검증 (정지/감속 polygon 측정)`

### Phase C — BT IsCollisionFree Condition + Pause 시맨틱 (D+4~5, 2일)

**목표**: BT 가 collision_monitor 와 동기화. cafe_funnel pause/resume 시맨틱 정착.

**작업**:
- C1. `dobi_npc_msgs/msg/SafetyZoneState.msg` 정의 + 빌드.
- C2. `nav2_collision_detector` 설정 (사회적 zone 1.2m, action_type=none).
- C3. 신규 노드 `safety_zone_monitor_node` (Python, `dobi_npc_emotion` 또는 신규 `dobi_npc_safety` 패키지):
  - 입력: `/scan`, `/robot_cam/persons`, `/collision_detector_state`
  - 출력: `/safety/zone_intrusion`
  - hysteresis (진입 5 / 퇴출 10)
- C4. BT 노드 `IsZoneClear` Condition (C++, `dobi_npc_bt/include/dobi_npc_bt/is_zone_clear.hpp`).
- C5. cafe_funnel_v1.xml 갱신 — `<ReactiveSequence>` 안에 IsZoneClear + CafeFunnel.
- C6. **각 BT 노드 onHalted() 분기** (선택 A):
  - blackboard `halt_reason` 읽기
  - "pause": 상태 보존 (Approach goal 보관, Minigame SIGSTOP — Phase 후속)
  - "abort": 기존 cleanup
- C7. live 검증:
  - 사람 1.2m 진입 → BT pause + cmd_vel 0 + face_avatar 유지
  - 사람 비킴 → BT 재개 + cmd_vel ramp-up

**검증 통과 조건**:
- BT 가 RUNNING 상태로 일시정지 + 자동 재개
- pause 중 진행 중 TTS 자연 종료 (cut 안 됨)
- Minigame 진행 중에는 pause 영향 없음 (cmd_vel 송신 X)

**Task 추가**:
- `SafetyZoneState 메시지 정의`
- `safety_zone_monitor_node 구현`
- `IsZoneClear BT Condition 구현`
- `cafe_funnel_v1.xml pause gate 통합`
- `BT 노드 onHalted() pause/abort 분기`
- `Phase C live 검증`

### Phase D — 의도 표현 (Intent Signaling) (D+6~8, 2일)

**목표**: Pause 진입/유지/해제 시점에 사회적 큐 (TTS + face_avatar) 자동 발행.

**작업**:
- D1. persona YAML 확장 (`safety` section + pause_excuse / resume_after_pause phrase pool).
- D2. `safety_zone_monitor_node` 가 dwell 진입 시점에 `/dialog/request` 발행:
  - T=2s: stage_id="pause_excuse" (priority=safety=0, preempt=true)
  - T=재개 시: stage_id="resume_after_pause"
- D3. `face_avatar` 가 SafetyZoneState 구독 + 진입/해제 시 expression 변경 큐.
- D4. dialog_router 에 priority=safety (0) 추가 + preempt 로직 검증.
- D5. live 검증:
  - 사람 진입 → 2초 후 "잠시만요" 발화
  - 사람 비킴 → "계속 진행하겠습니다" 발화 + cmd_vel ramp-up
  - 페르소나별 phrase 정상 lookup

**검증 통과 조건**:
- 의도 표현 음성 + 표정이 시점에 맞게 발행
- 진행 중 다른 발화 cut 없이 자연 종료 후 pause_excuse dispatch

**Task 추가**:
- `persona YAML safety section + phrase pool 추가`
- `safety_zone_monitor_node intent dispatch 통합`
- `dialog_router priority=safety 검증`
- `face_avatar SafetyZoneState 구독`
- `Phase D live 검증`

### Phase E — Freezing 회피 + 운영자 알림 (D+9~12, 2일)

**목표**: 장시간 pause 시 fallback. 운영자 인식 (LED + UI alert).

**작업**:
- E1. `safety_zone_monitor_node` 에 timer 추가:
  - T=5s: `/mode/state.last_reject_reason = "long_pause"` + `/safety/state.level = ALERT`
  - T=10s: BT 에 abort_trigger 발행 (Trautman freezing 회피 — 다른 손님으로 전환 fallback)
- E2. 신규 토픽 `/safety/state` (`SafetyState.msg`) 발행. (vic_pinky LED 구독자는 Phase 후속.)
- E3. mode_manager 가 long_pause 시점에 cur cycle abort + IDLE 복귀 (선택적).
- E4. operator UI 확장 (web/static/operator.html — 기존 자산 확장):
  - SafetyZoneState 실시간 표시
  - long_pause 알림 배너
- E5. live 검증.

**검증 통과 조건**:
- 10초 이상 pause 시 자동 abort + IDLE 복귀
- operator UI 에서 zone 침입/해제 가시화

**Task 추가**:
- `long_pause timer + freezing fallback`
- `/safety/state 토픽 발행`
- `operator UI 확장`
- `Phase E live 검증`

### Phase F — 후속 (선택, 일정 미정)

- F1. **VelocityPolygon 전환** — 정지/전진/회전 3 sub-polygon. 회전 시 측면 zone 확장.
- F2. **사람 vs 사물 fusion** — collision_detector polygon + person_detector bbox 결합. 사람 클러스터에만 SSM 적용 (Matt 2021).
- F3. **점주 인식 + 양보 모드** — face_id 또는 uniform color 인식 → operator_uniform_yield 페르소나 모드.
- F4. **Peek-and-pass** — Approach 노드에 Williams 2024 패턴 통합. 좁은 통로 통과율 개선.
- F5. **Eye-gaze acknowledgment** — mediapipe head pose 로 사람 ack 신호 → resume 트리거 (Phase 5).
- F6. **점주 e-stop 물리 버튼** — Cat 0/1 + manual reset (ISO 13850 정합).
- F7. **stage-aware SSM 임계값** — APPROACH/ICEBREAK/MINIGAME 별 zone 크기 (Bdiwi 2022).
- F8. **vic_pinky LED 컨트롤러** — `/safety/state` 구독 + GPIO/I2C LED 출력.

### 6.A 도입 일정 요약

| Phase | 기간 | 결과물 |
|---|---|---|
| A | D+1 (0.5일) | apt 설치 + twist_mux + cmd_vel rename |
| B | D+2~3 (1일) | velocity_smoother + collision_monitor (물리 zone) |
| C | D+4~5 (2일) | SafetyZoneState + IsZoneClear + cafe_funnel pause gate |
| D | D+6~8 (2일) | 의도 표현 (TTS + face_avatar) + persona YAML safety section |
| E | D+9~12 (2일) | Freezing 회피 + operator UI |
| F | 후속 | VelocityPolygon, fusion, peek-and-pass, e-stop 버튼 등 |

**총 약 7~8일 (실 작업)** — Phase A~E. Phase F 는 회고에서 우선순위 결정.

---

## 7. 미해결 / 후속 과제

### 7.1 표준 인증 갭

- **PL=d 인증 미획득**: ROS2 + BT.CPP 자체는 functional safety 인증 미보유. RPLiDAR 는 safety-rated 아님. 산업 인증 시점에서는 별도 safety controller (Pilz PNOZ, Sick Flexi Soft) + safety-rated drives/STO 필요. 카페 환경에서는 best-effort safety 로 충분하나, **인증을 받으려면 Phase F 후속 + 외부 검증 필요**.
- **공공장소 갭 (Salem 2021)**: EN ISO 13482 의 군중/돌발/proxemics 갭. 본 시스템은 BT funnel + emotional abort + 점주 override 로 보강 — 회고/논문에 명기.

### 7.2 분산 DDS 함정 모니터링

- collision_monitor + smoother + twist_mux 가 **반드시 RPi 단일 호스트** 에서 작동해야 함. Wi-Fi 단절 시 fail-safe.
- 권장: RPi 측 systemd watchdog + ros2 node 헬스 체크 (sensor freshness, BT alive). 신규 health monitor 노드 (Phase F).

### 7.3 학술 논문 작성 시 주제

본 시스템 자체가 학술 갭의 직접 사례:
- **EN ISO 13482 의 공공장소 갭** (Salem 2021) 을 BT funnel + 감성 abort 로 보강한 첫 실증 케이스
- **Russell V·A circumplex (Layer 2) + Salichs GEFA/GEVA (Layer 3) + Castro-González polite (Layer 4) + ISO/TS 15066 SSM (보조)** 결합
- **Iovino 2022 BT survey 의 "Safe AI" 미해결 과제** 에 대한 부분 답안

### 7.4 데이터 수집

Phase 4 파일럿 (N=5) 데이터 수집 항목 추가:
- pause/resume event 횟수, 평균 duration
- pause 종류 (protective / warning / social)
- pause 동안 손님 행동 변화 (V·A 추이)
- 재개 후 funnel 진행률
- near-miss / pause / abort / contact 분류

### 7.5 향후 표준 갱신 추적

- **prEN ISO 13482 개정** (2024+ 진행) — "safety requirements for service robots" 로 제목 확대. 발행 시 본 설계 재검토.
- **ISO 10218-1:2025 / -2:2025** + **ANSI/A3 R15.06-2025** — "Monitored Standstill" 명칭 변경 추적.

---

## 8. 출처 (Sources)

### 8.1 표준

- [ISO/TS 15066:2016](https://www.iso.org/standard/62996.html) — Collaborative robots
- [ISO 13482:2014](https://www.iso.org/standard/53820.html) — Personal care robots
- [ISO 3691-4:2023](https://www.iso.org/standard/83545.html) — Driverless industrial trucks
- [ISO 10218-1:2025](https://www.iso.org/standard/73933.html) — Industrial robots safety
- [ISO 13849-1:2023](https://www.iso.org/standard/73481.html) — Safety-related parts of control systems
- [ANSI/RIA R15.08-1-2020](https://webstore.ansi.org/standards/ria/ansiriar15082020) — Industrial mobile robots (비적용)
- [KS B ISO 13482 (한국)](https://www.kssn.net/search/stddetail.do?itemNo=K001010126005)
- [ISO/TS 15066 PDF (Sapienza University)](https://www.diag.uniroma1.it/deluca/pHRI_elective/ISO_TS_15066_2016_en.pdf)

### 8.2 학술 논문 (핵심)

- [Marvel & Norcross 2017 — Implementing SSM in Collaborative Robot Workcells (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5117641/)
- [Byner, Matthias, Ding 2019 — Dynamic SSM (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S073658451830259X)
- [Bdiwi et al. 2022 — Adaptive SSM Switching Zones (ResearchGate)](https://www.researchgate.net/publication/360332323)
- [Trautman & Krause 2010 — Unfreezing the Robot (PDF)](https://las.inf.ethz.ch/files/trautman10unfreezing.pdf)
- [Mavrogiannis et al. 2023 — Core Challenges of Social Robot Navigation (ACM THRI)](https://dl.acm.org/doi/10.1145/3583741)
- [Williams et al. 2024 — Look Before You Leap / Peek-and-Pass (arXiv:2403.13284)](https://arxiv.org/abs/2403.13284)
- [Yamamoto et al. 2024 — I Need to Pass Through (HRI 2024 ACM)](https://dl.acm.org/doi/10.1145/3610977.3634951)
- [Babel et al. 2022 — Safety Concerns from Robots in Pedestrian Areas (Springer)](https://link.springer.com/article/10.1007/s12369-021-00796-4)
- [Salem et al. 2021 — On the Safety of Mobile Robots Serving in Public Spaces (ACM TROHI)](https://dl.acm.org/doi/10.1145/3442678)
- [Iovino et al. 2022 — A Survey of Behavior Trees in Robotics and AI (arXiv)](https://arxiv.org/abs/2005.05842)
- [Singamaneni et al. 2024 — Social Navigation Survey (IJRR/SAGE)](https://journals.sagepub.com/doi/10.1177/02783649241230562)
- [Matt et al. 2021 — Human-Machine Differentiation in SSM (Sensors)](https://www.mdpi.com/1424-8220/21/21/7144)
- [Mosbach et al. 2025 — Deep-Learning Methods in ISO/TS 15066 (Sensors)](https://www.mdpi.com/1424-8220/25/23/7136)

### 8.3 현업 사례

- [Bear Robotics Servi Plus](https://www.bearrobotics.ai/servi-plus)
- [Pudu BellaBot 공식](https://www.pudurobotics.com/en/products/bellabot)
- [Pudu BellaBot BL100 사용자 매뉴얼](https://www.manualslib.com/manual/2038389/Pudu-Bellabot-Bl100.html)
- [Keenon T8 공식](https://www.keenon.com/en/product/T8/index.html)
- [Keenon W3 공식](https://www.keenon.com/en/product/W3/index.html)
- [Savioke Safety Instructions](https://support.savioke.com/hc/en-us/articles/360005252374-Safety-Instructions)
- [Diligent Robotics Moxi](https://www.diligentrobots.com/moxi)
- [MiR Safety](https://grobotics.eu/autonomous-mobile-robots/safety)
- [SICK microScan3 데이터시트 PDF](https://www.sick.com/media/pdf/6/56/156/dataSheet_microScan3-and-nanoScan3-safet_1615675_en.pdf)
- [Boston Dynamics Spot IFU v1.1](https://d3cjkvgbik1jtv.cloudfront.net/Spot%20IFU/spot_information_for_use_EN_v1.1.pdf)
- [UR PolyScope X SW 10.6 Handbook](https://www.universal-robots.com/manuals/EN/PDF/SW10_6/PolyX_handbook_online/PolyScope%20X_Handbook_en_Global.pdf)
- [Starship FAQ — 보행자 안전](https://www.starship.xyz/faqs/are-starship-robots-safe-for-pedestrians/)
- [Nuro Safety](https://www.nuro.ai/safety)
- [LG CLOi 서브봇 LDLIM21](https://www.lge.co.kr/service-robot/ldlim21)
- [배민로봇 (딜리)](https://robot.baemin.com/)
- [KT AI 서빙로봇](https://enterprise.kt.com/pd/P_PD_AI_RB_004.do)

### 8.4 ROS2 도구

- [Nav2 Collision Monitor 공식 docs](https://docs.nav2.org/configuration/packages/configuring-collision-monitor.html)
- [Nav2 Collision Detector docs](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-detector-node.html)
- [Nav2 Velocity Smoother docs](https://docs.nav2.org/configuration/packages/configuring-velocity-smoother.html)
- [Nav2 Costmap 2D docs](https://docs.nav2.org/configuration/packages/configuring-costmaps.html)
- [Nav2-specific BT nodes](https://docs.nav2.org/behavior_trees/overview/nav2_specific_nodes.html)
- [navigation2 GitHub — collision_monitor 소스](https://github.com/ros-navigation/navigation2/tree/main/nav2_collision_monitor)
- [BehaviorTree.CPP 공식](https://github.com/BehaviorTree/BehaviorTree.CPP)
- [BT.CPP tutorial-04 (Sequence/ReactiveSequence)](https://www.behaviortree.dev/docs/tutorial-basics/tutorial_04_sequence/)
- [twist_mux GitHub](https://github.com/ros-teleop/twist_mux)
- [robotics-upo/nav2_social_costmap_plugin](https://github.com/robotics-upo/nav2_social_costmap_plugin)
- [SICKAG/sick_safetyscanners2](https://github.com/SICKAG/sick_safetyscanners2)

### 8.5 Stop Categories / Functional Safety

- [Machinery Safety 101 — Emergency Stop Categories](https://machinerysafety101.com/2010/09/27/emergency-stop-categories/)
- [Machinery Safety 101 — Manual Reset Function](https://machinerysafety101.com/2021/05/19/understanding-safety-functions-manual-reset/)
- [Schneider Electric — Stop Category 0/1/2 FAQ](https://www.se.com/eg/en/faqs/FA225420/)
- [Pilz — EN ISO 13849-1 Performance Level](https://www.pilz.com/en-INT/support/law-standards-norms/functional-safety/en-iso-13849-1)

---

*마지막 갱신: 2026-05-08 (조사 + 적용 계획 통합 v1.0)*
*다음 갱신 예정: Phase A 완료 후 (실 측정 값 + 수정 사항 반영)*
