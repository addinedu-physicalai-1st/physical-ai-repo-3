# MOCA 5-Mode FSM · OpServer · Web Dashboard 설계 계획서

> **문서 ID**: `moca_mode_and_opserver_plan.md`
> **버전**: v1.0 (2026-05-16)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **대상 독자**: PinkLAB 카페 케이터링 로봇 팀 (송민규, 류재상, 김진우, 김덕현, 안순혁)
> **선행 문서**: `docs/cafe_npc_system_architecture.md`, `docs/cafe_npc_implementation_plan.md`, `docs/cafe_npc_engagement_funnel.md`
> **워크스페이스**: `~/moca` (ROS2 Jazzy, BehaviorTree.CPP 4.8.3, `ROS_DOMAIN_ID=22`)

---

## 0. 문서의 목적과 범위

본 문서는 vic_pinky 서빙 로봇이 **카페 운영 현장에서 자율적으로 수행해야 할 5개 행동 모드**를 정의하고, 그 모드들이 어떤 트리거에 의해 자동/수동 전환되는지, 그리고 그 전환을 관제하는 `moca_opserver` 노드와 운영자가 사용할 `moca_web` 대시보드의 기능을 상세히 설계한다.

### 0.1 본 문서가 다루는 것

1. **5개 모드의 행위 정의**: 서빙(serving) / 순회(patrol) / 동행안내(guiding) / 대기(idle) / 모객(engaging)
2. **모드별 진입·종료 트리거** (자동/수동, 6가지 카테고리)
3. **운영자 웹 UI 메뉴와 기능 명세** (대시보드 · 모드 제어 · 테이블 모니터링 · 이벤트 로그 · 설정)
4. **moca_opserver의 통신 인터페이스** (ROS2 ↔ Web, REST + WebSocket)
5. **기존 `~/moca` 디렉토리 구조에 추가되는 신규 패키지/파일 배치**
6. **메시지·서비스 스키마 변경/추가 명세**
7. **단계별 구현 로드맵** (Phase M0~M4, 약 6주)

### 0.2 본 문서가 다루지 않는 것

- BT(BehaviorTree) 내부 노드 상세 (별도 문서 `cafe_npc_implementation_plan.md` 참조)
- Nav2 파라미터 튜닝 (`vicpinky_navigation` 패키지 영역)
- OpenARM 제조 로봇 측 시스템 (별도 워크스페이스 `~/robot_arm`)
- 미니게임 내부 로직 (별도 패키지 `dobi_npc_minigame`)

### 0.3 핵심 설계 원칙

1. **기존 자산 재사용**: 이미 동작하는 `mode_manager_node`, `serving_dispatcher`, `LaunchSupervisor`, `cafe_funnel_v1.xml` BT를 보존하고 확장한다. **재작성은 금지**.
2. **단일 진실 원본(SoT)**: 로봇 현재 모드의 SoT는 `/mode/state` 토픽. opserver와 웹은 모두 이를 구독.
3. **모드 전환은 mode_manager만 수행**: opserver는 SetMode 서비스의 *클라이언트*일 뿐, 직접 상태를 변경하지 않는다.
4. **점진적 확장**: 기존 `idle/npc/serving/follow` 4상태에서 5상태로 마이그레이션. `npc`→`engaging`, `follow`→`guiding`로 의미적 리네이밍 + `patrol` 신규 추가.
5. **점주 친화 UI**: 운영자는 IT 전문가가 아니므로 단순 버튼·뱃지·맵 위주, 디버그 정보는 별도 탭 분리.

---

## 1. 시스템 한눈에 보기

```
┌──────────────────────────────────────────────────────────────────────┐
│                       카운터 (Counter Area)                          │
│                                                                      │
│   ┌──────────┐   ┌────────────┐   ┌─────────────┐   ┌────────────┐   │
│   │  POS /   │   │  OpenARM   │   │   Pickup    │   │ moca       │   │
│   │  Kiosk   │──▶│  제조로봇  │──▶│   Table     │   │ OpServer   │   │
│   │ (주문)   │   │ (음료 조리)│   │ (음료 준비) │   │ (관제)     │   │
│   └────┬─────┘   └─────┬──────┘   └──────┬──────┘   └─────┬──────┘   │
│        │ 주문 이벤트   │ 제조 완료       │ 픽업 가능       │           │
│        └───────────────┴─────────────────┴────────────────▶│           │
│                                                            │           │
└────────────────────────────────────────────────────────────┼──────────┘
                                                             │ ROS2 DDS
                                                             │ (DOMAIN=22)
                          ┌──────────────────────────────────┼──────────┐
                          │              홀 (Hall Area)      │          │
                          │                                  ▼          │
                          │            ┌────────────────────────────┐   │
                          │            │     Vic Pinky 서빙로봇     │   │
                          │            │  ┌──────────────────────┐  │   │
                          │            │  │   mode_manager       │  │   │
                          │            │  │ ┌──────────────────┐ │  │   │
                          │            │  │ │ 5-State FSM      │ │  │   │
                          │            │  │ │ idle             │ │  │   │
                          │            │  │ │ serving          │ │  │   │
                          │            │  │ │ patrol           │ │  │   │
                          │            │  │ │ guiding          │ │  │   │
                          │            │  │ │ engaging         │ │  │   │
                          │            │  │ └──────────────────┘ │  │   │
                          │            │  └──────────────────────┘  │   │
                          │            └─────────────┬──────────────┘   │
                          │                          │                  │
                          │   ┌──────┐   ┌──────┐    │     ┌──────┐    │
                          │   │ T01  │   │ T02  │    │     │ T04  │    │
                          │   └──────┘   └──────┘    │     └──────┘    │
                          │                          │                  │
                          │              ┌──────┐    │     ┌──────┐    │
                          │              │ T03  │    │     │ T05  │    │
                          │              └──────┘    │     └──────┘    │
                          └──────────────────────────┴──────────────────┘
                                                     │
                                       ┌─────────────┼───────────────┐
                                       │             ▼               │
                                       │  Operator (Manager)         │
                                       │  ┌─────────────────────┐    │
                                       │  │  moca_web Dashboard │    │
                                       │  │  (브라우저)         │    │
                                       │  └─────────────────────┘    │
                                       └─────────────────────────────┘
```

**핵심 데이터 흐름 3종**:
1. **POS → OpServer → 로봇**: 주문/제조완료/픽업가능 이벤트가 OpServer를 통해 로봇 모드 전환을 일으킨다.
2. **로봇 → OpServer → 웹**: 로봇 현재 모드·위치·배터리·테이블 점유 정보가 OpServer를 거쳐 웹 대시보드에 실시간 표시된다.
3. **웹 → OpServer → 로봇**: 운영자의 수동 모드 전환 명령이 OpServer를 거쳐 mode_manager에 전달된다.

---

## 2. 5-State FSM 정의

### 2.1 모드 일람

| 모드 ID (English) | 한글명 | 역할 한 줄 요약 | 기존 4상태 매핑 |
|---|---|---|---|
| `idle` | 대기 | home_pose에서 다음 명령 대기 | (그대로) `idle` |
| `serving` | 서빙 | 픽업 테이블의 음료를 지정 테이블로 배달 후 home 복귀 | (그대로) `serving` |
| `patrol` | 순회 | 5분 주기로 전 테이블을 돌며 점유/식사완료 감지 → OpServer 보고 | **신규** |
| `guiding` | 동행 안내 | 카운터에서 결제 완료한 고객을 빈 테이블까지 인솔 | (리네이밍) `follow` |
| `engaging` | 모객 | 한산 시 매장 근처 행인에게 접근·홍보·미니게임·감정분석 후 매장 유도 | (리네이밍) `npc` |

> **마이그레이션 정책**: `npc`→`engaging`, `follow`→`guiding`는 의미 명확화를 위한 리네이밍. 기존 BT/launch 파일명은 새 ID로 일괄 변경하되, 기존 `mode_npc.launch.py`는 `mode_engaging.launch.py`로 이름만 바꾸고 내부 BT는 그대로 재사용 (cafe_funnel_v1.xml).

### 2.2 모드별 상세 명세

각 모드는 다음 8개 속성으로 정의한다:

```
- ID          : 영문 식별자
- 진입 트리거 : 자동/수동
- 사용 노드   : launch가 spawn하는 ROS 노드 목록
- 핵심 토픽   : 입출력 토픽
- 종료 조건   : 무엇이 충족되면 자동으로 idle로 복귀하는가
- 우선순위    : 다른 모드 요청이 동시에 들어왔을 때
- params 스키마: SetMode 서비스의 params JSON 키
- KPI         : OpServer가 수집하는 모드 단위 지표
```

#### 2.2.1 `idle` (대기)

| 속성 | 값 |
|---|---|
| 진입 트리거 | 다른 모드 종료 시 자동, 또는 운영자 수동 |
| 사용 노드 | (없음 — launch supervisor가 빈 stack 유지) |
| 핵심 토픽 | `/mode/state` 발행만 |
| 종료 조건 | 다른 모드 진입 요청 수신 |
| 우선순위 | 최저 (base 상태) |
| params 스키마 | `{}` 또는 `""` |
| KPI | `idle_total_sec`, `idle_session_count` |

**동작**: 로봇은 `home_pose`(현 `tables.yaml`: `(-36.887, 2.809, yaw=-π/2)`)에 정차. 모터는 활성 상태이지만 `/cmd_vel`는 0. LED 링은 "대기" 색상 (예: 옅은 핑크 호흡 효과).

**구현 노트**: 이미 `mode_manager_node.py`의 `LaunchSupervisor.spawn('idle', ...)`이 `idle_no_stack` 처리하므로 신규 launch 파일 불필요.

---

#### 2.2.2 `serving` (서빙)

| 속성 | 값 |
|---|---|
| 진입 트리거 | **자동**: OpServer가 OpenARM "제조완료" 이벤트 수신 후 SetMode 호출 / **수동**: 웹 UI 강제 |
| 사용 노드 | `serving_dispatcher_node` (기존), Nav2 (vicpinky_navigation 외부 가동) |
| 핵심 토픽 | 입력: `/serving/goto_table` (큐 추가) / 출력: `/serving/state` (1Hz JSON) |
| 종료 조건 | 큐 소진 + home 복귀 완료 → 자동 idle |
| 우선순위 | 1 (최상위, 영업 직결) |
| params 스키마 | `{"waypoint": "T01" \| "T02" \| ... \| "T05"}` |
| KPI | `serving_total_count`, `serving_avg_duration_sec`, `serving_per_table_count` |

**동작**:
1. OpServer가 OpenARM에서 "음료 ID `D-2026-05-16-0042`가 픽업 테이블에 준비됨, 목표 테이블 `T03`" 이벤트를 수신.
2. OpServer가 `/mode/request` (SetMode)를 `requested_mode="serving", params='{"waypoint":"T03"}'`로 호출.
3. mode_manager가 가드 통과 후 `mode_serving.launch.py` spawn.
4. `serving_dispatcher_node`가 픽업 테이블 → T03 → home_pose 시퀀스를 Nav2 NavigateToPose action으로 수행. (현재는 첫 명령 = T03 도착 + dwell + home. **확장 필요**: 픽업 테이블 경유 단계 추가 — §6.2)
5. 도착 후 5초 dwell (고객 음료 수령 시간) → home 복귀 → `/serving/state` "idle" 상태 → mode_manager는 launch 종료 안 함 (큐 다시 채워질 가능성). 일정 시간 idle 유지 후 mode_manager 타임아웃으로 idle 모드로 전이.

**확장 포인트**:
- 큐가 비어있지 않으면 home 복귀 생략하고 다음 테이블로 이동 (이미 dispatcher가 구현)
- OpenARM 측에서 "픽업 테이블에 음료 배치 완료" 신호를 별도 토픽 `/pickup/ready` (custom msg)로 받으면 dispatcher가 픽업 테이블 → 목표 테이블 2단계 nav 수행 (§6.2에서 상세 설계)

---

#### 2.2.3 `patrol` (순회) — **신규**

| 속성 | 값 |
|---|---|
| 진입 트리거 | **자동**: `idle` 상태 진입 후 5분 경과 시 / **수동**: 웹 UI 버튼 |
| 사용 노드 | `patrol_scheduler_node` (신규), Nav2, `table_occupancy_detector_node` (신규) |
| 핵심 토픽 | 입력: 카메라 (`/camera/image_raw`), `/scan` / 출력: `/patrol/state`, `/patrol/table_report` |
| 종료 조건 | 전 테이블 1회 순회 완료 → home 복귀 → 자동 idle |
| 우선순위 | 3 (idle 위 / serving 아래) |
| params 스키마 | `{"sweep_mode": "all" \| "priority_only", "report_to_opserver": true}` |
| KPI | `patrol_total_count`, `patrol_avg_duration_sec`, `patrol_occupied_detected`, `patrol_finished_detected` |

**동작**:
1. mode_manager의 idle 상태에서 내부 카운터가 5분 도달 → 자동으로 `SetMode("patrol")` 트리거 (mode_manager 내부 타이머로 처리 vs. opserver 외부 트리거 — **§3.3에서 결정 사유 설명, 결정: opserver가 트리거**).
2. `mode_patrol.launch.py` spawn → `patrol_scheduler_node` 가동.
3. 노드는 `tables.yaml`의 T01~T05를 순서대로 Nav2로 방문.
4. 각 테이블 도착 시 1초 정지 → `table_occupancy_detector_node`가 카메라+LiDAR로 테이블 상태 추론:
   - **empty**: 의자에 사람 없음, 테이블 위 식기 없음
   - **occupied**: 사람 감지 (YOLOv8 person class)
   - **finished**: 사람 없음, 테이블 위 빈 컵/접시 감지 → 청소 필요 알람
5. 각 테이블 결과를 `/patrol/table_report` (custom msg `TableReport`)로 발행 → OpServer가 수집.
6. 순회 완료 → home 복귀 → idle 전이.

**확장 포인트**:
- M2 단계: 점유 감지는 단순 YOLO person 검출만. M3에서 식기 검출 (YOLO custom class `empty_cup`, `used_plate`).
- 순회 우선순위: 직전 사이클에서 occupied였던 테이블 우선 (식사 종료 시점 예측).

---

#### 2.2.4 `guiding` (동행 안내) — 기존 `follow` 리네이밍 + 확장

| 속성 | 값 |
|---|---|
| 진입 트리거 | **자동**: POS 결제 완료 → OpServer "안내 명령" / **수동**: 웹 UI |
| 사용 노드 | `guiding_controller_node` (기존 `follow_controller_node` 확장) |
| 핵심 토픽 | 입력: `/robot_cam/persons` (Detection2DArray), `/scan` / 출력: `/cmd_vel`, `/guiding/state` |
| 종료 조건 | 목표 테이블 도착 + 고객 도착 확인 → 자동 idle (home 복귀) |
| 우선순위 | 2 (serving 다음) |
| params 스키마 | `{"target_table": "T02", "customer_id": "C-2026-05-16-0017"}` |
| KPI | `guiding_total_count`, `guiding_avg_duration_sec`, `guiding_lost_customer_count` |

**동작**:
1. 고객이 카운터에서 주문/결제 완료 → POS가 OpServer에 "T02 안내 요청" 전송.
2. OpServer가 빈 테이블 확인 후 (`patrol`이 수집한 최근 점유 정보 참조) → `SetMode("guiding", params='{"target_table":"T02"}')`.
3. `mode_guiding.launch.py` spawn:
   - `guiding_controller_node`: 카운터에서 고객 1명을 person_detector로 lock-on → Nav2 NavigateToPose("T02") 진행하면서 카메라로 고객 추적 유지 → 고객이 일정 거리 이상 떨어지면 정지/대기.
   - 발화: "이 테이블로 안내드릴게요" → 도착 후 "여기서 편히 즐겨주세요" (dialog_router 경유).
4. 도착 + 고객 추적 confirm → idle.

**기존 자산 활용**:
- `follow_controller_node.py`의 P 제어 + 안전 가드 그대로 사용. 단, 기존은 "주인 추적" (반응형 cmd_vel), `guiding`은 "고객을 목적지로 인도" (Nav2 주도 + 카메라로 follower 확인)이므로 **로직 재설계 필요**.
- `follow` → `guiding` 이름 변경 = 단순 패키지 리네이밍 + 내부 알고리즘 약 50% 신규.

---

#### 2.2.5 `engaging` (모객) — 기존 `npc` 리네이밍

| 속성 | 값 |
|---|---|
| 진입 트리거 | **수동만**: 웹 UI "모객 시작" 버튼 (한산 시점 점주 판단) |
| 사용 노드 | `bt_executor_node` + `cafe_funnel_v1.xml`, dialog/emotion/minigame 스택 |
| 핵심 토픽 | 입력: `/emotion/state`, `/rapport/event` / 출력: `/utter/request`, `/face_avatar/expression` |
| 종료 조건 | 6단계 funnel 완료 OR EmotionMonitor abort OR 운영자 종료 버튼 → idle |
| 우선순위 | 5 (최저 활동 모드) |
| params 스키마 | `{"persona": "casual_browser" \| "friendly_child" \| "professional_adult"}` |
| KPI | `engaging_total_count`, `engaging_conversion_count`, `engaging_abort_count` |

**동작**: 기존 `cafe_funnel_v1.xml`의 6단계 BT (IdleScan → Approach → IceBreak → Minigame → Offer → LeadIn) 그대로 실행. 변경 없음.

**리네이밍 작업**:
- `mode_npc.launch.py` → `mode_engaging.launch.py`
- `SetMode` 검증 로직 `VALID_MODES` 튜플 업데이트
- BT XML 내부 변경 없음

---

### 2.3 5-State FSM 다이어그램

```
                                  ┌─────────────────┐
                                  │ (전원 ON)        │
                                  └────────┬────────┘
                                           │
                                           ▼
              ┌─────────────────────────────────────────────────┐
              │                                                  │
              │                    idle (대기)                   │◀──┐
              │                                                  │   │
              │      home_pose 정차, /mode/state="idle" 발행      │   │
              │                                                  │   │
              └─┬──────────────┬────────────────┬───────────────┘   │
                │              │                │                    │
                │ POS주문      │ idle 5분       │ POS결제완료         │ 종료
                │ +제조완료    │ 경과           │ +빈테이블 확인       │ (모든 모드)
                │ (OpServer)   │ (OpServer)     │ (OpServer)           │
                │              │                │                    │
                ▼              ▼                ▼              ┌─────┴──────┐
        ┌─────────────┐  ┌──────────┐    ┌────────────┐        │             │
        │   serving   │  │  patrol  │    │  guiding   │        │             │
        │  (서빙)     │  │ (순회)   │    │ (동행안내) │        │             │
        └──────┬──────┘  └────┬─────┘    └─────┬──────┘        │             │
               │              │                 │              │             │
        도착+dwell+home  5테이블 순회+home  목적지+confirm       │             │
                                                                ▲             │
                                                                │             │
                                                                │             │
              ┌─────────────────────────────────────────────────┘             │
              │                                                                │
              │          웹 UI "모객 시작" 버튼 (운영자 수동)                  │
              │                                                                │
              ▼                                                                │
        ┌────────────┐                                                          │
        │  engaging  │──────────────────────────────────────────────────────────┘
        │  (모객)    │
        └────────────┘
              ▲
              │   funnel 완료 OR abort OR 운영자 STOP
              │
              └─── (전이 직전: cafe_funnel BT가 종료 → mode_manager가 idle 강제)


┌───────────────── 가드 (모든 전이에 공통 적용) ─────────────────┐
│  ◦ battery < 0.20 → idle 외 모드 모두 거부 ("battery_low")      │
│  ◦ /rapport abort_trigger 발생 시 5초간 idle 강제              │
│  ◦ transition_in_progress 중에는 신규 요청 거부                │
└──────────────────────────────────────────────────────────────────┘
```

### 2.4 모드 전이표 (Transition Matrix)

행 = 현재 모드, 열 = 목표 모드. 셀 값 = 허용 여부 + 트리거 종류.

|  현재 \ 목표  | idle | serving | patrol | guiding | engaging |
|---|:---:|:---:|:---:|:---:|:---:|
| **idle** | — | 자동(A1)/수동 | 자동(A2)/수동 | 자동(A3)/수동 | 수동만 |
| **serving** | 자동(완료) | (큐 추가만) | 거부(busy) | 거부(busy) | 거부(busy) |
| **patrol** | 자동(완료) | **선점(A1)** | — | **선점(A3)** | 거부(busy) |
| **guiding** | 자동(완료) | 거부(busy) | 거부(busy) | (큐 추가만) | 거부(busy) |
| **engaging** | 자동(완료) /수동STOP | **선점(A1)** | **선점(A2)** | **선점(A3)** | — |

**트리거 코드**:
- **A1**: OpenARM 제조완료 + 픽업테이블 음료 준비 → serving 진입
- **A2**: idle 5분 경과 → patrol 진입
- **A3**: POS 결제완료 + 빈테이블 확보 → guiding 진입

**선점(preempt) 정책**: serving(우선순위 1)과 guiding(우선순위 2)은 patrol/engaging 중에도 즉시 진입 가능. mode_manager가 SIGTERM으로 기존 stack을 죽이고 새 stack spawn. 단, serving 진행 중 또 다른 serving 요청은 큐에만 추가 (dispatcher의 `/serving/goto_table` 토픽 활용).

---

## 3. 트리거 시스템 설계

### 3.1 트리거의 6가지 카테고리

| # | 카테고리 | 발생 위치 | 영향 모드 | 통신 방식 |
|---|---|---|---|---|
| T1 | 외부 이벤트 (POS/제조) | OpenARM, POS | serving, guiding | POS→OpServer (HTTP) |
| T2 | 시간 기반 | OpServer 타이머 | patrol | OpServer 내부 |
| T3 | 운영자 수동 | 웹 UI | 모든 모드 | WebSocket→OpServer→ROS |
| T4 | 안전 가드 | 로봇 자체 | 강제 idle | `/battery_state`, `/rapport/event` |
| T5 | 행위 완료 | 로봇 자체 | 자동 idle 복귀 | 각 모드 dispatcher 내부 |
| T6 | 우선순위 선점 | OpServer 판단 | 모든 모드 | OpServer→SetMode |

### 3.2 트리거별 상세 시퀀스

#### T1-A: 제조완료 → serving (자동)

```
OpenARM 제조로봇                OpServer                mode_manager           serving_dispatcher
      │                            │                         │                       │
      │ HTTP POST /api/v1/pickup   │                         │                       │
      │   {drink_id, target_table} │                         │                       │
      ├───────────────────────────▶│                         │                       │
      │                            │ 큐에 저장 (drink_id ↔   │                       │
      │                            │  table 매핑)            │                       │
      │                            │                         │                       │
      │                            │ (현재 모드 == idle ?)   │                       │
      │                            │  YES → SetMode 호출      │                       │
      │                            │                         │                       │
      │                            │ SetMode("serving",      │                       │
      │                            │  {"waypoint":"T03"})    │                       │
      │                            ├────────────────────────▶│                       │
      │                            │                         │ 가드 체크 OK           │
      │                            │                         │ launch spawn          │
      │                            │                         ├──────────────────────▶│
      │                            │   "transition_started"  │                       │
      │                            │◀────────────────────────┤                       │
      │                            │                         │                       │
      │                            │                         │  Nav2 진행 → 도착     │
      │                            │                         │                       │
      │                            │ /serving/state          │                       │
      │                            │◀────────────────────────┼───────────────────────┤
      │                            │  ("dwell"/"complete")   │                       │
      │                            │                         │                       │
      │                            │ home 복귀 후 idle 전이   │                       │
      │                            │  → 다음 큐 항목 있으면   │                       │
      │                            │  다시 SetMode 호출       │                       │
```

#### T1-B: POS 결제완료 → guiding (자동)

```
POS Kiosk           OpServer              mode_manager       guiding_controller
   │                   │                      │                    │
   │ HTTP POST         │                      │                    │
   │  /api/v1/order    │                      │                    │
   │   {customer_id,   │                      │                    │
   │    table_request} │                      │                    │
   ├──────────────────▶│                      │                    │
   │                   │ 빈 테이블 조회       │                    │
   │                   │ (patrol 최신 데이터) │                    │
   │                   │                      │                    │
   │                   │ assign T02           │                    │
   │                   │                      │                    │
   │                   │ SetMode("guiding",   │                    │
   │                   │   {"target":"T02"})  │                    │
   │                   ├─────────────────────▶│                    │
   │                   │                      │ launch spawn       │
   │                   │                      ├───────────────────▶│
   │                   │                      │                    │
   │                   │                      │  카운터→T02 안내   │
   │                   │                      │                    │
   │                   │ /guiding/state       │                    │
   │                   │◀─────────────────────┼────────────────────┤
   │                   │  ("arrived")         │                    │
   │                   │                      │                    │
   │ "안내 완료 알림"  │                      │                    │
   │◀──────────────────┤                      │                    │
```

#### T2: idle 5분 경과 → patrol (자동)

**설계 결정**: 타이머는 `mode_manager` 내부가 아닌 **OpServer**가 관리한다.

**이유**:
1. mode_manager는 ROS 노드로 가벼운 FSM 관리에 집중. 비즈니스 룰(주기 변경, 영업시간별 다른 주기, 야간 비활성 등)은 OpServer가 적합.
2. 점주가 웹 UI에서 "순회 주기 5분 → 10분" 변경 시 OpServer 설정 파일만 수정하면 됨. mode_manager 재기동 불필요.
3. 영업 종료 후 자동 순회 차단 같은 정책 확장 용이.

```
OpServer                                   mode_manager
   │                                            │
   │ /mode/state 구독 → current_mode="idle"     │
   │◀───────────────────────────────────────────┤
   │  (entered_at 기록)                          │
   │                                            │
   │ ┌── 5분 타이머 시작 ──┐                    │
   │ │  매초 체크:         │                    │
   │ │   - 영업시간 내?    │                    │
   │ │   - 배터리 > 20%?   │                    │
   │ │   - 5분 경과?       │                    │
   │ └─────────────────────┘                    │
   │                                            │
   │ 5분 경과 + 조건 충족                       │
   │                                            │
   │ SetMode("patrol", {"sweep_mode":"all"})    │
   ├───────────────────────────────────────────▶│
   │                                            │
```

#### T3: 운영자 수동 (웹 UI)

```
브라우저 (운영자)         moca_web (FastAPI)        OpServer (ROS 노드)        mode_manager
    │                          │                          │                          │
    │ 버튼 클릭               │                          │                          │
    │  "모객 시작"            │                          │                          │
    │                          │                          │                          │
    │ WebSocket send           │                          │                          │
    │  {action:"set_mode",     │                          │                          │
    │   mode:"engaging",       │                          │                          │
    │   params:{"persona":     │                          │                          │
    │    "casual_browser"}}    │                          │                          │
    ├─────────────────────────▶│                          │                          │
    │                          │ ROS service call         │                          │
    │                          │ via OpServer client      │                          │
    │                          ├─────────────────────────▶│                          │
    │                          │                          │ SetMode 서비스 호출      │
    │                          │                          ├─────────────────────────▶│
    │                          │                          │   transition_started      │
    │                          │                          │◀─────────────────────────┤
    │ WebSocket recv           │                          │                          │
    │  {result:"ok",           │                          │                          │
    │   mode:"engaging"}       │                          │                          │
    │◀─────────────────────────┤                          │                          │
    │                          │                          │                          │
    │ /mode/state 변경         │                          │                          │
    │  ws에 push               │ /mode/state subscribe    │                          │
    │  ─────────────────────── │ ────────────────────────│◀─────────────────────────┤
    │  UI 모드 뱃지 업데이트   │ (1Hz)                    │                          │
```

#### T4: 안전 가드 (강제 idle)

기존 mode_manager_node.py의 _on_rapport 콜백이 이미 구현. 변경 없음. OpServer는 `/mode/state.last_reject_reason` 모니터링으로 가드 발동 사실을 웹에 알림.

#### T5: 행위 완료 (자동 idle)

각 모드의 dispatcher/controller가 임무 완료 시 자체적으로 launch를 종료하지 않고, **OpServer가 `/serving/state`, `/patrol/state` 등의 "complete" 상태를 감지하여 SetMode("idle") 호출**.

**이유**: 모드별 dispatcher가 직접 모드 전환을 일으키면 책임 분산. OpServer가 외부 조율자(orchestrator) 역할.

#### T6: 우선순위 선점

```
시점 t0: 로봇 patrol 진행 중, T02 도착
시점 t1: OpenARM에서 "T04 음료 준비 완료" 이벤트 도착

OpServer 의사결정 로직:
  if current_mode == "patrol" and event == "pickup_ready":
    if get_priority("serving") < get_priority("patrol"):  # 1 < 3 → true
      log("preempt: patrol → serving")
      call SetMode("serving", {"waypoint": "T04"})
      → mode_manager가 patrol launch SIGTERM + serving launch spawn
      → 서빙 완료 후 idle → (5분 후) patrol 재시작
```

### 3.3 트리거 우선순위 규칙

```
priority_table = {
    "idle":     99,   # 가장 낮은 우선순위 = 양보
    "engaging":  5,   # 운영자 명시 명령이므로 약간 높음
    "patrol":    3,   # 자동 백그라운드 작업
    "guiding":   2,   # 고객 응대
    "serving":   1,   # 영업 직결 최상위
}
```

**선점 규칙**: `priority[new] < priority[current]`이면 OpServer가 SetMode 호출. 같거나 크면 거부 (또는 큐잉).

---

## 4. 통신 인터페이스 설계

### 4.1 ROS2 토픽·서비스 일람

| 이름 | 타입 | 발행 | 구독 | 주기/이벤트 | 비고 |
|---|---|---|---|---|---|
| `/mode/state` | `ModeState` | mode_manager | opserver, web | 1Hz | 기존 |
| `/mode/request` | `SetMode.srv` | (모두) | mode_manager | 이벤트 | 기존 |
| `/battery_state` | `BatteryState` | 로봇 HW | mode_manager, opserver | 5Hz | 기존 |
| `/serving/state` | `String` (JSON) | serving_dispatcher | opserver, web | 1Hz | 기존 |
| `/serving/goto_table` | `String` | (외부) | serving_dispatcher | 이벤트 | 기존 |
| `/patrol/state` | `PatrolState` (신규) | patrol_scheduler | opserver, web | 1Hz | **신규** |
| `/patrol/table_report` | `TableReport` (신규) | table_occupancy_detector | opserver | 테이블별 이벤트 | **신규** |
| `/guiding/state` | `GuidingState` (신규) | guiding_controller | opserver, web | 1Hz | **신규** |
| `/opserver/event` | `OpEvent` (신규) | opserver | web | 이벤트 | **신규** (외부 이벤트 echo) |
| `/operator/command` | `OperatorCommand` (신규) | opserver | (모든 모드 dispatcher) | 이벤트 | **신규** |
| `/utter/request` | `UtterRequest` | (모든 모드) | dialog_router | 이벤트 | 기존 |
| `/rapport/event` | `RapportEvent` | rapport_tracker | mode_manager, BT | 이벤트 | 기존 |

### 4.2 신규 메시지 정의

**`PatrolState.msg`** — `dobi_npc_msgs/msg/PatrolState.msg`
```
# patrol_scheduler_node 발행 (1Hz)
std_msgs/Header header
string current_state          # "scanning" | "moving" | "report" | "returning" | "done"
string current_table          # 현재 방문 중/직전 테이블 ID (예: "T03")
uint32 tables_visited         # 이번 사이클 누적 방문 수
uint32 tables_total           # 5 (T01~T05)
float32 progress              # 0.0 ~ 1.0
builtin_interfaces/Time started_at
```

**`TableReport.msg`** — `dobi_npc_msgs/msg/TableReport.msg`
```
# table_occupancy_detector_node 발행 (테이블 방문 시 이벤트)
std_msgs/Header header
string table_id               # "T01" ~ "T05"
string occupancy              # "empty" | "occupied" | "finished" | "unknown"
uint8 person_count            # YOLO person 검출 수
bool dishes_detected          # 빈 컵/접시 감지 여부 (M3)
float32 confidence            # 0.0 ~ 1.0
sensor_msgs/CompressedImage snapshot  # 디버깅용 1장 (M3에서 선택적)
```

**`GuidingState.msg`** — `dobi_npc_msgs/msg/GuidingState.msg`
```
# guiding_controller_node 발행 (1Hz)
std_msgs/Header header
string current_state          # "lockon" | "moving" | "waiting_customer" | "arrived" | "lost"
string target_table           # 목표 테이블 ID
string customer_id            # POS가 부여한 고객 식별자
float32 distance_to_target    # m
float32 distance_to_customer  # m (카메라 추정)
bool customer_in_sight        # 카메라에 보이는지
```

**`OpEvent.msg`** — `dobi_npc_msgs/msg/OpEvent.msg`
```
# opserver가 외부 이벤트를 ROS 도메인에 echo (디버깅/로깅용)
std_msgs/Header header
string event_id               # UUID
string source                 # "pos" | "openarm" | "operator" | "timer" | "guard"
string event_type             # "order_placed" | "pickup_ready" | "guide_request" | "manual_mode" | ...
string payload                # JSON 원본
string outcome                # "accepted" | "queued" | "rejected:<reason>"
```

**`OperatorCommand.msg`** — `dobi_npc_msgs/msg/OperatorCommand.msg`
```
# 운영자 수동 제어 명령 (mode 외의 미세 제어, 발화, 표정 등)
std_msgs/Header header
string command_type           # "utter" | "express" | "stop_emergency" | "resume" | "skip_table"
string payload                # JSON
```

### 4.3 신규 서비스 정의

**`GetTableStatus.srv`** — `dobi_npc_msgs/srv/GetTableStatus.srv`
```
# OpServer가 web에 테이블 현황 응답 (REST API의 ROS 백엔드)
string table_id           # 비우면 전체 반환
---
bool success
string status_json        # [{"id":"T01","occupancy":"occupied","last_update":"..."}, ...]
```

**`SetPatrolSchedule.srv`** — `dobi_npc_msgs/srv/SetPatrolSchedule.srv`
```
# 운영자가 순회 주기/활성화 설정
float32 interval_minutes  # 기본 5.0
bool enabled              # false면 자동 patrol 차단
string active_hours       # "09:00-22:00" (영업시간)
---
bool success
string reason
```

### 4.4 REST API 명세 (POS/OpenARM → OpServer)

OpServer는 ROS와 외부(HTTP)를 동시에 다루는 게이트웨이. 외부 시스템과의 인터페이스는 다음과 같다.

**Base URL**: `http://<opserver_host>:8800/api/v1`

| 메서드 | 경로 | 요청 본문 | 응답 | 트리거 |
|---|---|---|---|---|
| POST | `/order` | `{order_id, customer_id, items, paid_at}` | `{accepted, queued_position}` | T1-A 사전 단계 |
| POST | `/pickup` | `{drink_id, order_id, target_table, ready_at}` | `{serving_mode_requested}` | T1-A |
| POST | `/guide` | `{customer_id, requested_at, preferred_table}` | `{assigned_table, eta_sec}` | T1-B |
| GET | `/status` | — | `{mode, battery, tables[], queue[]}` | 조회 |
| GET | `/tables` | — | `[{id, occupancy, last_update}, ...]` | 조회 |
| POST | `/mode` | `{mode, params}` | `{success, reason}` | T3 (디버깅/외부 통합용) |

### 4.5 WebSocket 채널 (Web ↔ OpServer)

**Endpoint**: `ws://<opserver_host>:8800/ws/dashboard`

**Client → Server 메시지**:
```json
{"type": "set_mode", "mode": "engaging", "params": {"persona": "casual_browser"}}
{"type": "skip_table", "table_id": "T03"}
{"type": "emergency_stop"}
{"type": "set_patrol_schedule", "interval_minutes": 7, "enabled": true}
{"type": "utter", "text": "안녕하세요"}
```

**Server → Client 메시지** (구독자 모두에게 broadcast):
```json
{"type": "mode_state", "current_mode": "serving", "battery": 0.87, "safety_ok": true, ...}
{"type": "table_update", "table_id": "T02", "occupancy": "occupied", "ts": "..."}
{"type": "serving_progress", "current_target": "T03", "queue_size": 2}
{"type": "event_log", "level": "info", "msg": "patrol completed", "ts": "..."}
{"type": "alarm", "code": "battery_low", "value": 0.18}
```

### 4.6 통신 토폴로지 다이어그램

```
                  ┌──────────────┐  ┌──────────────┐
                  │ POS / Kiosk  │  │  OpenARM     │
                  │ (Counter)    │  │  제조로봇    │
                  └──────┬───────┘  └──────┬───────┘
                         │                  │
                         │ HTTP POST        │ HTTP POST
                         │ /api/v1/order    │ /api/v1/pickup
                         │ /api/v1/guide    │
                         │                  │
                         └────────┬─────────┘
                                  │
                                  ▼
                  ┌──────────────────────────────────┐
                  │      moca_opserver_node          │
                  │  (ROS Node + FastAPI server)     │
                  │                                  │
                  │  - REST API :8800                │
                  │  - WebSocket :8800/ws/dashboard  │
                  │  - 5분 patrol 타이머             │
                  │  - 이벤트 큐                     │
                  │  - 모드 우선순위 판단            │
                  └────┬──────────────┬──────────────┘
                       │              │
                       │ ROS topics   │ WebSocket
                       │ + service    │
                       ▼              ▼
              ┌────────────────┐  ┌──────────────────┐
              │ mode_manager   │  │  moca_web        │
              │ + dispatchers  │  │  (Browser)       │
              │ + bt_executor  │  │                  │
              └────────────────┘  └──────────────────┘
                       ▲
                       │ ROS topics
                       │
              ┌────────┴─────────────┐
              │  Sensors / Actuators │
              │  (camera, LiDAR,     │
              │   motors, LED, ...)  │
              └──────────────────────┘
```

---

## 5. 디렉토리 구조 설계 (기존 `~/moca` 확장)

### 5.1 변경 원칙

- 기존 `src/dobi_npc/*` 패키지는 **그대로 보존**. 내부 노드 추가/수정만.
- 신규 패키지는 `src/moca_opserver/`, `src/moca_web/`로 추가.
- 메시지/서비스 신규는 기존 `src/dobi_npc/dobi_npc_msgs/`에 추가 (워크스페이스 메시지 통일).
- 문서는 `docs/`에 일관성 있는 파일명 규칙으로 추가.

### 5.2 확장 후 디렉토리 트리

```
~/moca/
├── CLAUDE.md                          (기존, 갱신 필요: 5-state 반영)
├── README.md                          (기존)
├── moca.repos                         (기존)
├── requirements.txt                   (기존)
│
├── config/                            (기존)
│   ├── cafe_layout.yaml               (기존)
│   └── personas/                      (기존)
│
├── docs/                              (기존 + 신규 문서)
│   ├── cafe_npc_system_architecture.md       (기존)
│   ├── cafe_npc_implementation_plan.md       (기존)
│   ├── cafe_npc_engagement_funnel.md         (기존)
│   ├── cafe_npc_camera_architecture.md       (기존)
│   ├── cafe_npc_safety_zone.md               (기존)
│   ├── cafe_npc_paper_master.md              (기존)
│   ├── moca_mode_and_opserver_plan.md        ★ 본 문서
│   ├── moca_5state_fsm_spec.md               ★ 신규 (M0 산출물)
│   ├── moca_opserver_api_spec.md             ★ 신규 (M1 산출물)
│   ├── moca_web_dashboard_spec.md            ★ 신규 (M3 산출물)
│   ├── moca_patrol_design.md                 ★ 신규 (M2 산출물)
│   ├── moca_guiding_design.md                ★ 신규 (M2 산출물)
│   └── daily/                                (기존 회고)
│       └── 2026-05-16_moca_mode_and_opserver_plan.md  ★ 오늘 회고
│
├── maps/                              (기존)
├── images/                            (기존)
├── models/                            (기존, YOLO weights)
├── games/                             (기존, mini-game assets)
├── datasets/                          (기존)
├── log/, build/, install/             (기존, colcon)
│
├── scripts/                           (기존 + 신규)
│   ├── (기존 모든 .sh, .py 유지)
│   ├── run_opserver.sh                ★ 신규
│   ├── stop_opserver.sh               ★ 신규
│   ├── run_moca_web.sh                ★ 신규
│   └── stop_moca_web.sh               ★ 신규
│
├── tools/                             (기존)
│
├── web/                               (기존, teleop_server)
│   ├── teleop_server.py               (기존, 유지 — moca_web과 별개)
│   └── static/                        (기존)
│
└── src/
    ├── dobi_npc/                      (기존)
    │   ├── dobi_npc_msgs/             (메시지 패키지 — 신규 5종 추가)
    │   │   ├── msg/
    │   │   │   ├── EmotionState.msg              (기존)
    │   │   │   ├── MinigameResult.msg            (기존)
    │   │   │   ├── ModeState.msg                 (기존, 필드 추가)
    │   │   │   ├── RapportEvent.msg              (기존)
    │   │   │   ├── UtterRequest.msg              (기존)
    │   │   │   ├── PatrolState.msg               ★ 신규
    │   │   │   ├── TableReport.msg               ★ 신규
    │   │   │   ├── GuidingState.msg              ★ 신규
    │   │   │   ├── OpEvent.msg                   ★ 신규
    │   │   │   └── OperatorCommand.msg           ★ 신규
    │   │   ├── srv/
    │   │   │   ├── SetMode.srv                   (기존, VALID_MODES 확장)
    │   │   │   ├── SetPersona.srv                (기존)
    │   │   │   ├── GetTableStatus.srv            ★ 신규
    │   │   │   └── SetPatrolSchedule.srv         ★ 신규
    │   │   └── CMakeLists.txt                    (수정: 신규 msg/srv 등록)
    │   │
    │   ├── dobi_npc_bringup/                     (기존, 노드/launch 확장)
    │   │   ├── dobi_npc_bringup/
    │   │   │   ├── mode_manager_node.py          (수정: VALID_MODES 5종)
    │   │   │   ├── serving_dispatcher_node.py    (수정: 픽업 테이블 경유 옵션)
    │   │   │   ├── follow_controller_node.py     (유지 또는 guiding 분리)
    │   │   │   ├── guiding_controller_node.py    ★ 신규 (follow에서 분기)
    │   │   │   ├── patrol_scheduler_node.py      ★ 신규
    │   │   │   ├── table_occupancy_detector_node.py ★ 신규
    │   │   │   ├── fake_customer_publisher.py    (기존, 시뮬용)
    │   │   │   └── mode_stack_stub.py            (기존)
    │   │   ├── config/
    │   │   │   ├── tables.yaml                   (기존)
    │   │   │   ├── patrol_config.yaml            ★ 신규 (순회 순서/주기 기본값)
    │   │   │   └── occupancy_thresholds.yaml     ★ 신규 (YOLO conf threshold)
    │   │   └── launch/
    │   │       ├── dev_all.launch.py             (수정: 5-state 반영)
    │   │       ├── dev_common.launch.py          (기존)
    │   │       ├── mode_serving.launch.py        (기존)
    │   │       ├── mode_engaging.launch.py       ★ 신규 (mode_npc 리네이밍)
    │   │       ├── mode_npc.launch.py            (deprecated, 호환 wrapper)
    │   │       ├── mode_guiding.launch.py        ★ 신규 (mode_follow 리네이밍 확장)
    │   │       ├── mode_follow.launch.py         (deprecated, 호환 wrapper)
    │   │       ├── mode_patrol.launch.py         ★ 신규
    │   │       └── sim_funnel_demo.launch.py     (기존)
    │   │
    │   ├── dobi_npc_bt/                          (기존, 변경 최소)
    │   ├── dobi_npc_dialog/                      (기존)
    │   ├── dobi_npc_emotion/                     (기존)
    │   └── dobi_npc_minigame/                    (기존)
    │
    ├── moca_gazebo/                              (기존)
    ├── moca_navigation/                          (기존)
    ├── shared/vic_pinky/                         (기존)
    │
    ├── moca_opserver/                            ★ 신규 패키지 (Python ament)
    │   ├── package.xml
    │   ├── setup.py
    │   ├── setup.cfg
    │   ├── resource/moca_opserver
    │   ├── config/
    │   │   ├── opserver_config.yaml              # 영업시간, 우선순위, 주기 기본값
    │   │   └── api_keys.yaml.example             # POS/OpenARM 인증 (선택)
    │   ├── launch/
    │   │   └── opserver.launch.py
    │   ├── moca_opserver/
    │   │   ├── __init__.py
    │   │   ├── opserver_node.py                  # 메인 ROS 노드 (FastAPI host)
    │   │   ├── rest_api.py                       # FastAPI 라우터 정의
    │   │   ├── ws_hub.py                         # WebSocket broadcast 허브
    │   │   ├── event_queue.py                    # 이벤트 큐/우선순위 판단
    │   │   ├── mode_orchestrator.py              # SetMode 호출 정책 + 선점 판단
    │   │   ├── patrol_scheduler.py               # 5분 타이머 (mode 외부 트리거)
    │   │   ├── table_registry.py                 # 테이블 점유 상태 캐시
    │   │   ├── serving_queue.py                  # OpenARM → 서빙 큐 관리
    │   │   ├── auth.py                           # API key 검증 (선택)
    │   │   └── schemas.py                        # pydantic 모델 (REST/WS)
    │   └── test/
    │       ├── test_rest_api.py
    │       ├── test_orchestrator.py
    │       └── test_event_queue.py
    │
    └── moca_web/                                 ★ 신규 패키지 (Python ament + static)
        ├── package.xml
        ├── setup.py
        ├── setup.cfg
        ├── resource/moca_web
        ├── launch/
        │   └── moca_web.launch.py                # 단독 실행용 (FastAPI static host)
        ├── moca_web/
        │   ├── __init__.py
        │   └── web_server.py                     # 정적 파일 서빙 (또는 opserver와 통합)
        └── static/
            ├── index.html                        # 대시보드 메인
            ├── pages/
            │   ├── dashboard.html                # 메인 대시보드
            │   ├── modes.html                    # 모드 제어 패널
            │   ├── tables.html                   # 테이블 그리드 뷰
            │   ├── events.html                   # 이벤트 로그
            │   ├── analytics.html                # KPI 통계
            │   └── settings.html                 # 설정 (주기, 영업시간)
            ├── components/
            │   ├── mode-badge.js                 # 모드 표시 컴포넌트
            │   ├── table-card.js                 # 테이블 카드
            │   ├── battery-gauge.js              # 배터리 게이지
            │   └── event-feed.js                 # 실시간 이벤트 피드
            ├── css/
            │   ├── main.css
            │   └── theme-dark.css
            ├── js/
            │   ├── api.js                        # REST/WS 클라이언트
            │   ├── store.js                      # 상태 관리 (vanilla pub-sub)
            │   └── app.js
            └── assets/
                ├── logo.png
                ├── floorplan.svg                 # 매장 평면도
                └── icons/
```

### 5.3 신규/수정 파일 통계

| 분류 | 신규 | 수정 |
|---|---|---|
| 메시지/서비스 | msg 5종, srv 2종 | ModeState 1종 (필드 추가) |
| ROS 노드 (Python) | 3개 (patrol_scheduler, table_occupancy_detector, guiding_controller) | 2개 (mode_manager, serving_dispatcher) |
| launch 파일 | 3개 (engaging, guiding, patrol) | 2개 (dev_all, mode_npc/follow는 wrapper) |
| 신규 패키지 | 2개 (moca_opserver, moca_web) | — |
| 설정 파일 | 2개 (patrol_config.yaml, opserver_config.yaml) | — |
| 문서 | 5개 (.md) | CLAUDE.md |
| 스크립트 | 4개 (.sh) | — |

---

## 6. 핵심 컴포넌트 상세 설계

### 6.1 mode_manager_node 확장 (5-state)

**변경 사항** (`mode_manager_node.py`):
```python
# 변경 전
VALID_MODES = ('idle', 'npc', 'serving', 'follow')

# 변경 후
VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging')

# 후방 호환 alias (warning 로그 + 자동 변환)
LEGACY_MODE_ALIAS = {
    'npc': 'engaging',
    'follow': 'guiding',
}
```

`_on_request` 핸들러 진입부에 추가:
```python
if req_mode in LEGACY_MODE_ALIAS:
    new_mode = LEGACY_MODE_ALIAS[req_mode]
    self.get_logger().warn(
        f'legacy mode "{req_mode}" → "{new_mode}" 자동 변환 '
        f'(deprecation: M3 까지만 지원)')
    req_mode = new_mode
```

**launch 파일 매핑**:
```python
launch_file = f'mode_{mode}.launch.py'
# idle, serving, patrol, guiding, engaging
```

기존 `mode_npc.launch.py`, `mode_follow.launch.py`는 deprecation 경고 + 신규 파일 호출 wrapper로 유지:
```python
# mode_npc.launch.py (deprecated)
def generate_launch_description():
    return LaunchDescription([
        LogInfo(msg='mode_npc.launch.py is deprecated, use mode_engaging.launch.py'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                FindPackageShare('dobi_npc_bringup'), '/launch/mode_engaging.launch.py'
            ])
        )
    ])
```

### 6.2 serving_dispatcher 확장 (픽업 테이블 경유)

현재 `serving_dispatcher_node.py`는 `{"waypoint":"T03"}`을 받으면 곧장 T03로 이동한다. 실제 운영에선 **픽업 테이블에서 음료를 받은 뒤 T03**로 가야 한다.

**확장 설계**:
- `tables.yaml`에 `pickup_table` 항목 추가:
  ```yaml
  pickup_table:
    frame_id: map
    x: -36.07
    y: 2.793
    yaw: 3.142
    approach_dist: 0.3
    description: "OpenARM 옆 픽업 스테이션"
  ```
- params 확장: `{"waypoint":"T03","via_pickup":true}` (기본값 true)
- dispatcher 큐에 자동으로 [pickup_table, T03, home] 3개 push.
- pickup_table 도착 시 dwell 길게 (예: 10초) — OpenARM이 음료를 트레이에 올릴 시간.

### 6.3 patrol_scheduler_node 신규 설계

**역할**: 5개 테이블을 순서대로 방문하면서 `table_occupancy_detector_node`에게 각 테이블 정지 시점을 알림.

**파라미터**:
- `tables_yaml`: 기존 tables.yaml 재사용
- `dwell_per_table_sec`: 2.0 (도착 후 감지 대기)
- `sweep_order`: ["T01","T02","T03","T04","T05"]
- `return_home`: true

**상태머신**:
```
INIT → MOVE(T_i) → SCAN(T_i, dwell 2s) → REPORT → MOVE(T_{i+1}) → ... → RETURN_HOME → DONE
```

**핵심 의사 코드**:
```python
class PatrolScheduler(Node):
    def __init__(self):
        # ... pub /patrol/state, /patrol/table_report
        # ... action client NavigateToPose
        # ... sub /table_occupancy/result (detector 응답)

    def run_cycle(self):
        for table_id in self.sweep_order:
            self.set_state('moving', table_id)
            ok = self.nav_to(table_id)
            if not ok: continue
            self.set_state('scanning', table_id)
            report = self.request_occupancy_scan(table_id)  # detector에 요청
            self.publish_table_report(report)
            self.set_state('report', table_id)
        self.set_state('returning', '__home__')
        self.nav_to_home()
        self.set_state('done', '')
```

### 6.4 table_occupancy_detector_node 신규 설계

**역할**: 호출 시 현재 카메라 프레임 + LiDAR 스캔으로 테이블 점유 추정.

**입력**:
- `/camera/image_raw` (RGB)
- `/scan` (LaserScan, 부가)
- 서비스 요청 `/table_occupancy/scan` (`Trigger` + table_id 파라미터)

**알고리즘** (M2):
1. YOLOv8 person class inference → bbox count
2. 카메라 시야 내 person ≥ 1 → `occupied`
3. person = 0 → `empty` (M3에서 빈 식기 검출 추가)

**출력**: `/patrol/table_report` 발행 (TableReport.msg)

**M3 확장**: custom YOLO weights (`models/yolo/table_dishes.pt`)로 `empty_cup`, `used_plate` 검출 → `finished` 상태 분류.

### 6.5 guiding_controller_node 신규 설계 (follow 분기)

**기존 follow_controller**: 사람 1명을 카메라 bbox로 추적, P 제어로 cmd_vel 발행. "주인 따라가기".

**guiding**: 그 반대 — 로봇이 **앞장서서 Nav2로 목적지 이동**, 카메라로 **뒤따라오는 고객 추적**.

**핵심 로직**:
```python
class GuidingController(Node):
    def run(self, target_table, customer_id):
        # 1. 카운터에서 고객 lock-on (가장 가까운 person)
        lock = self.acquire_customer_lock(timeout=10s)

        # 2. 발화 "이쪽으로 안내해드릴게요"
        self.utter("이 테이블로 안내해드릴게요")

        # 3. Nav2 NavigateToPose(target_table) action 시작
        goal_handle = self.send_nav_goal(target_table)

        # 4. 이동 중 카메라로 customer 추적
        while not goal_handle.done():
            dist_to_customer = self.estimate_customer_distance()
            if dist_to_customer > MAX_LAG_DIST:
                # 고객이 뒤처짐 → 정지 + 대기
                self.pause_nav()
                self.utter("천천히 따라오세요")
                self.wait_until_customer_close()
                self.resume_nav()

        # 5. 도착 → "여기 앉으시면 됩니다" → 잠시 대기 → idle
        self.utter("여기서 편하게 즐겨주세요")
```

**기존 follow_controller_node.py는 deprecate**하고 (또는 mode_follow 호환 wrapper로만 유지) guiding이 신규 코드로 전면 재작성. 이름이 비슷해도 거의 다른 모듈.

### 6.6 moca_opserver_node 설계

**역할**: 외부(POS/OpenARM/Web) ↔ ROS 게이트웨이 + 비즈니스 룰 엔진.

**구조**: 단일 ROS 노드 안에 FastAPI를 임베드 (uvicorn 별도 스레드).

```python
# opserver_node.py 골격
import threading
import rclpy
from rclpy.node import Node
from fastapi import FastAPI
import uvicorn

class OpServerNode(Node):
    def __init__(self):
        super().__init__('moca_opserver')
        # ROS 구독
        self.sub_mode = self.create_subscription(ModeState, '/mode/state', self.on_mode_state, 10)
        self.sub_serving = self.create_subscription(String, '/serving/state', self.on_serving_state, 10)
        self.sub_patrol = self.create_subscription(PatrolState, '/patrol/state', self.on_patrol_state, 10)
        self.sub_table = self.create_subscription(TableReport, '/patrol/table_report', self.on_table_report, 10)
        self.sub_guiding = self.create_subscription(GuidingState, '/guiding/state', self.on_guiding_state, 10)
        self.sub_battery = self.create_subscription(BatteryState, '/battery_state', self.on_battery, 10)

        # ROS 클라이언트
        self.cli_set_mode = self.create_client(SetMode, '/mode/request')

        # ROS 발행 (echo + 명령)
        self.pub_event = self.create_publisher(OpEvent, '/opserver/event', 10)
        self.pub_op_cmd = self.create_publisher(OperatorCommand, '/operator/command', 10)

        # 내부 상태
        self.current_mode = 'idle'
        self.table_registry = TableRegistry()
        self.serving_queue = ServingQueue()
        self.orchestrator = ModeOrchestrator(self)
        self.patrol_scheduler = PatrolScheduler(self)

        # FastAPI 임베드
        self.app = build_fastapi_app(self)
        self.ws_hub = WSHub()
        threading.Thread(
            target=lambda: uvicorn.run(self.app, host='0.0.0.0', port=8800),
            daemon=True,
        ).start()
```

**핵심 책임 분리** (한 노드 안 다 모듈):
- `rest_api.py`: FastAPI 라우터 정의, request validation
- `mode_orchestrator.py`: "지금 이 이벤트로 모드 바꿔도 되나?" 판단 + SetMode 호출
- `event_queue.py`: 동시 이벤트 직렬화, 우선순위 정렬
- `table_registry.py`: 최신 점유 정보 캐시 (TTL 5분, patrol 사이클이 채움)
- `serving_queue.py`: OpenARM 픽업 큐
- `patrol_scheduler.py`: 5분 idle 타이머 + 영업시간 체크
- `ws_hub.py`: WebSocket 클라이언트 풀, broadcast

---

## 7. 운영 웹 UI 설계 (moca_web)

### 7.1 디자인 원칙

1. **점주가 한 화면에서 다 본다**: 메인 대시보드는 모드/배터리/테이블/큐 한눈에.
2. **버튼은 크고 명확하게**: 모드 전환 5개 버튼, 비상정지 빨간 버튼.
3. **다크 테마 기본**: 카페 환경 조명에 눈 부담 적게 (기존 operator.html 톤 계승).
4. **모바일 우선**: 태블릿/스마트폰에서 운영자가 들고 다님. 반응형 그리드.
5. **언어**: 한국어 기본, 영어 토글 (i18n 가벼운 string table).

### 7.2 메뉴 구조 (사이드바)

```
🏠 대시보드 (Dashboard)   ← 기본 진입
🎮 모드 제어 (Modes)
🪑 테이블 (Tables)
📋 이벤트 (Events)
📊 통계 (Analytics)
⚙️  설정 (Settings)
🛠 디버그 (Debug)          ← 개발/문제 진단용
```

### 7.3 페이지별 명세

#### 7.3.1 대시보드 (`/dashboard.html`)

**레이아웃** (반응형 그리드):
```
┌─────────────────────────────────────────────────────────────┐
│  [현재 모드]    [배터리]    [안전상태]    [Wi-Fi]            │
│   SERVING      ▓▓▓▓░ 78%     ✅ OK        ✅ -52dBm          │
│   진입 12:34                                                  │
├─────────────────────────────────────────────────────────────┤
│  📍 매장 평면도 (실시간)                                       │
│   ┌──────────────────────────────────────────────┐           │
│   │   [픽업]    [Home(🤖)]                       │           │
│   │                                              │           │
│   │   [T01]                                      │           │
│   │            [T02] [T04]                       │           │
│   │            [T03] [T05]                       │           │
│   │   ● 빈테이블  ● 점유   ● 식사완료   ● 미지   │           │
│   └──────────────────────────────────────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  🚀 빠른 모드 전환                                            │
│  [ 🏠 대기 ] [ 🍽 서빙 ] [ 🔄 순회 ] [ 🚶 안내 ] [ 🎯 모객 ] │
│                                                               │
│  🛑 비상정지 [   STOP   ]                                     │
├─────────────────────────────────────────────────────────────┤
│  📦 진행 중 작업                                              │
│  ▸ 서빙 큐: 음료2종 (D-...0042 → T03, D-...0043 → T01)        │
│  ▸ 동행 큐: 없음                                              │
│  ▸ 다음 순회: 03:22 후                                        │
├─────────────────────────────────────────────────────────────┤
│  📺 실시간 이벤트                          [더보기 →]         │
│  12:34:58  pickup_ready → serving(T03) ✅                    │
│  12:33:12  patrol completed (5 tables in 87s)                │
│  12:28:01  patrol started (timer)                            │
└─────────────────────────────────────────────────────────────┘
```

**데이터 바인딩**:
- 헤더 4종: `/mode/state` 구독 (1Hz)
- 평면도: SVG (`floorplan.svg`) + 실시간 로봇 좌표 마커 (별도 토픽 `/odom`을 opserver가 1Hz로 다운샘플 후 WS push)
- 테이블 색상: `table_registry`의 occupancy
- 모드 버튼: WS `{type:"set_mode",mode:"..."}`
- 비상정지: WS `{type:"emergency_stop"}` → opserver가 SetMode("idle") + 추가로 OperatorCommand("stop_emergency") 발행
- 큐: opserver가 broadcast하는 `serving_progress`, `guiding_progress`

#### 7.3.2 모드 제어 (`/modes.html`)

상세 모드 패널. 대시보드의 빠른 버튼보다 풍부한 컨트롤.

```
┌─────────────────────────────────────────────────────┐
│  현재 모드: SERVING                                  │
│  진입 시각: 12:34                                    │
│  파라미터: {"waypoint":"T03","via_pickup":true}     │
│  큐: [T03, T01]                                      │
├─────────────────────────────────────────────────────┤
│  🍽 서빙 모드                                        │
│   강제 시작: [테이블 ▼] [via_pickup ☑] [실행]       │
│   큐 초기화: [모두 취소]                             │
│   현재 작업 건너뛰기: [SKIP]                         │
├─────────────────────────────────────────────────────┤
│  🔄 순회 모드                                        │
│   강제 시작: [전체 ▼] [실행]                         │
│   순회 순서: [T01→T02→T03→T04→T05] 편집             │
│   자동 주기: ☑ 5분  [편집 →]                         │
├─────────────────────────────────────────────────────┤
│  🚶 동행 안내                                        │
│   강제 시작: [테이블 ▼] [고객ID 자동 생성] [실행]   │
├─────────────────────────────────────────────────────┤
│  🎯 모객 모드                                        │
│   페르소나: [casual_browser ▼]                       │
│   [시작] [중단]                                      │
├─────────────────────────────────────────────────────┤
│  💬 수동 발화                                        │
│   [텍스트 입력 .........................] [말하기]   │
│   표정: [happy ▼] [반영]                             │
└─────────────────────────────────────────────────────┘
```

#### 7.3.3 테이블 모니터링 (`/tables.html`)

5개 테이블을 카드 그리드로:

```
┌─────────────────┐  ┌─────────────────┐
│ T01             │  │ T02             │
│ ● 점유 (1명)    │  │ ● 빈            │
│ 최근: 12:34     │  │ 최근: 12:34     │
│ 누적 서빙: 12   │  │ 누적 서빙: 8    │
│ [순회 건너뛰기] │  │ [테스트 서빙 →] │
└─────────────────┘  └─────────────────┘
... (T03, T04, T05)

[전체 새로고침] [지금 순회 시작]
```

#### 7.3.4 이벤트 로그 (`/events.html`)

필터링 가능한 타임라인:
```
[필터: ☑ pickup ☑ guide ☑ mode_change ☑ alarm ☐ debug]  [내보내기 CSV]

12:34:58  INFO  pickup_ready  drink=D-0042  table=T03  →  serving started
12:34:58  INFO  mode_change   idle → serving
12:33:12  INFO  mode_change   patrol → idle (cycle done)
12:33:12  INFO  patrol_report all 5 tables scanned (1 occupied, 4 empty)
12:30:01  INFO  table_report  T02 → empty
...
12:18:33  WARN  alarm         battery_low (0.18 < 0.20) — patrol blocked
12:18:33  INFO  mode_change   patrol → idle (safety_alarm_forced_idle)
```

#### 7.3.5 통계 (`/analytics.html`)

KPI 카드 + 차트:
- **일일/주간/월간** 토글
- 서빙 횟수, 평균 서빙 시간
- 순회 횟수, 평균 순회 시간, 점유 발견율
- 동행 안내 횟수, 평균 안내 시간, 미아 발생률
- 모객 시도/전환률
- 모드별 시간 점유율 (도넛 차트)
- 배터리 사이클 / 비상정지 횟수

(Chart.js 사용)

#### 7.3.6 설정 (`/settings.html`)

```
[ 운영 설정 ]
영업 시간:  09:00 ~ 22:00  [편집]
자동 순회:  ☑ 활성  주기: 5분  [편집]
배터리 최소: 20%  [편집]

[ 안전 설정 ]
배터리 임계:    20%
순회 야간 비활성: ☑
모객 자동 종료:  ☑ (5분 후)

[ 알림 설정 ]
배터리 < 30% 시 텔레그램:  [봇 토큰 ...]  [테스트]
비상정지 발생 시 알림:      ☑

[ 시스템 ]
워크스페이스 상태: ✅ OK
ROS DOMAIN ID: 22
OpServer 버전: 0.3.0
[로그 다운로드] [설정 백업] [재기동]
```

#### 7.3.7 디버그 (`/debug.html`)

기존 `web/static/operator.html`의 기능 흡수 (개발자/Stephen 본인용):
- 모든 토픽 raw echo
- ROS service call 직접 호출 폼
- BT tick rate 그래프
- 카메라 라이브 뷰
- emotion/rapport 실시간 값

### 7.4 UX 흐름 예시

**시나리오**: 점주가 점심 한산 시간에 모객 시작.

1. 대시보드 진입 → 현재 IDLE 확인, 배터리 80%, 모든 테이블 비어있음 확인.
2. "🎯 모객" 버튼 탭 → 모달 "페르소나 선택: casual_browser / friendly_child / professional_adult" → casual_browser 선택 → "시작".
3. 1초 후 헤더 모드 뱃지가 `ENGAGING`으로 변경, 평면도의 로봇 아이콘이 홈을 떠나 매장 입구로 이동.
4. 이벤트 피드에 `mode_change idle → engaging`, `funnel stage1: idle_scan`, `stage2: approach` 순차 표시.
5. 5분 후 OpenARM에서 음료 준비 완료 이벤트 발생 → 자동 선점 → 헤더가 `SERVING`으로 전환, 이벤트 피드에 `preempt: engaging → serving (priority)`.
6. 서빙 완료 후 자동 idle 복귀.

---

## 8. 안전·예외 처리

### 8.1 SetMode 거부 사유 일람

| reason | 발생 조건 | 처리 |
|---|---|---|
| `unknown_mode:X` | VALID_MODES에 없는 모드명 | UI에 toast 표시 |
| `invalid_json_params:...` | params JSON 파싱 실패 | UI에 toast |
| `transition_in_progress` | 이전 전이 진행 중 | 1초 후 자동 재시도 (UI) |
| `battery_low:0.18<0.20` | 배터리 부족 | UI에 알림 + 충전 안내 |
| `safety_alarm_active` | abort_trigger 5초 dwell | UI에 노란 배너 |
| `spawn_failed:...` | launch 즉사 | 이벤트 로그 + 디버그 패널 |

### 8.2 OpServer 자체 가드

- **이벤트 중복 방지**: `event_id` UUID 기반 idempotent. 같은 pickup_ready 재전송 시 무시.
- **POS/OpenARM 응답 타임아웃**: 5초 미응답 시 reject + 운영자 알림.
- **WebSocket 끊김**: 자동 재연결 (클라이언트 측), 끊긴 동안 이벤트 로컬 큐.
- **로봇 미응답**: `/mode/state` 3초 이상 미수신 → 헤더에 빨간 "ROBOT OFFLINE" 표시.

### 8.3 비상정지(Emergency Stop) 정의

- 웹 UI 빨간 버튼 1회 탭 → 즉시 `OperatorCommand{command_type:"stop_emergency"}` 발행.
- mode_manager는 이 토픽 별도 구독 → 가드 무시하고 즉시 idle 강제 전이 + 5초간 신규 모드 진입 차단.
- 동시에 모든 dispatcher가 `/cmd_vel`에 0 강제 발행.
- 해제: 별도 "복귀" 버튼 → 차단 해제.

---

## 9. 단계별 구현 로드맵 (Phase M0~M4)

### 9.1 Phase M0 — 설계 확정 (1주차, ~2026-05-23)

| 작업 | 산출물 | 담당 |
|---|---|---|
| 본 계획서 리뷰 | 본 문서 v1.0 (서명) | 전체 |
| 5-state FSM 사양 분리 | `docs/moca_5state_fsm_spec.md` | Stephen |
| OpServer API 명세 분리 | `docs/moca_opserver_api_spec.md` | Stephen |
| 신규 msg/srv 머지 | dobi_npc_msgs 빌드 통과 | Stephen |

**완료 기준**: `colcon build --packages-select dobi_npc_msgs` 성공, 신규 메시지 echo 가능.

### 9.2 Phase M1 — OpServer 골격 + Web 정적 (2주차, ~2026-05-30)

| 작업 | 산출물 |
|---|---|
| `moca_opserver` 패키지 scaffold | package.xml, setup.py, opserver_node.py 골격 |
| FastAPI :8800 응답 | `GET /api/v1/status` JSON 응답 |
| ROS 구독: `/mode/state` echo to WS | 브라우저에서 모드 실시간 표시 |
| `moca_web` 정적 페이지 5종 골격 | dashboard.html 등 빈 페이지 + 사이드바 |
| `recommend_claude_apps` 활용 (선택) | VS Code 환경에서 작업 효율화 |

**완료 기준**: 브라우저에서 `http://localhost:8800/dashboard.html` 접속 → 현재 모드 뱃지가 mode_manager의 1Hz state와 동기화.

### 9.3 Phase M2 — patrol + guiding 신규 구현 (3-4주차)

| 작업 | 산출물 |
|---|---|
| `patrol_scheduler_node` + `mode_patrol.launch.py` | 5테이블 Nav2 순회 시뮬 통과 |
| `table_occupancy_detector_node` (YOLO person만) | TableReport 발행 |
| `guiding_controller_node` + `mode_guiding.launch.py` | 카운터→T02 안내 시뮬 |
| OpServer `mode_orchestrator.py` | 5분 타이머 patrol 자동 트리거 |
| OpServer `serving_queue.py` | OpenARM stub event → serving 자동 |
| dev_all.launch.py 5-state 통합 | 단일 launch로 전체 시뮬 |

**완료 기준**: Gazebo에서 idle → 5분 → patrol → idle → POST /api/v1/pickup → serving → idle 시나리오 완주.

### 9.4 Phase M3 — Web UI 완성 + 분석 (5주차)

| 작업 | 산출물 |
|---|---|
| 대시보드 평면도 SVG + 로봇 마커 | 실시간 위치 시각화 |
| 테이블 카드 그리드 | tables.html 완성 |
| 이벤트 피드 + CSV export | events.html 완성 |
| KPI 차트 (Chart.js) | analytics.html 일/주/월 통계 |
| 설정 페이지 + opserver_config.yaml 동기 저장 | settings.html 영업시간 변경 반영 |
| 모바일 반응형 검수 | iPad/iPhone 실기 테스트 |

**완료 기준**: 점주 시나리오 (§7.4) 5종 전체 통과.

### 9.5 Phase M4 — 실기 통합 + 회고 (6주차)

| 작업 | 산출물 |
|---|---|
| 실제 OpenARM/POS 연동 (개발 stub → 실 API) | 통합 테스트 통과 |
| Vic Pinky 실 차량에서 patrol 1주 무중단 | 회고 로그 |
| YOLO custom weights (식기 검출) — 선택 | M3+ 일정 |
| `moca_mode_and_opserver_plan.md` v2 갱신 | 본 문서 |
| 회고 `2026-XX-XX_moca_phase_m4_retro.md` | 일일 회고 |

---

## 10. 검증 시나리오 (Acceptance Tests)

### 10.1 자동 시나리오 (CI)

```bash
# A1: idle → 5분 타이머 → patrol
launch_dev_all
sleep 5  # mode_manager 안정화
verify_mode "idle"
sleep 305  # 5분 + 5초
verify_mode "patrol"

# A2: patrol 중 pickup_ready → serving 선점
launch_dev_all
sleep 60  # idle
curl -X POST http://localhost:8800/api/v1/pickup \
  -d '{"drink_id":"D-test","target_table":"T02"}'
sleep 3
verify_mode "serving"
verify_serving_target "T02"

# A3: SetMode unknown_mode 거부
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
  '{"requested_mode":"foobar","params":""}'
verify_response_field "success" false
verify_response_field "reason" "unknown_mode:foobar"

# A4: battery_low 가드
fake_publish_battery 0.15  # < 0.20
ros2 service call /mode/request ... '{"requested_mode":"patrol",...}'
verify_response_field "reason_contains" "battery_low"
```

### 10.2 점주 시나리오 (수동)

1. **아침 영업 시작**: 웹 접속 → 자동 영업시간(09:00) 진입 → idle → 5분 후 patrol 자동 시작 확인
2. **점심 러시**: 5초 간격으로 pickup 3건 → serving 큐 [T01,T03,T05] 순차 처리 확인
3. **고객 동행**: POST /guide → 자동 빈테이블 할당 + guiding → 도착 + idle 복귀
4. **한산 시간**: 운영자가 모객 시작 → engaging 진행 중 pickup 발생 → 자동 선점 확인
5. **저녁 마감**: 22:00 도달 → 자동 순회 비활성 확인 → 수동 idle 강제 → 충전

---

## 11. 위험 요소와 완화 전략

| 위험 | 영향 | 완화 |
|---|---|---|
| OpServer 단일 장애점 | 모든 자동 전환 중단 | mode_manager 자체적으로 idle은 유지, 수동 ros2 service 직접 호출 fallback |
| WebSocket 다중 클라이언트 동시 명령 충돌 | 모드 흔들림 | OpServer 측에 명령 큐 + 중복 제거 (event_id) |
| YOLO 추론 지연 → patrol 정지 시간 길어짐 | 운영 효율 | dwell_per_table_sec 튜닝, 추후 ONNX/TensorRT |
| 5-state 마이그레이션 중 legacy `npc`/`follow` 잔존 코드 | 빌드 오류 | LEGACY_MODE_ALIAS + deprecation 경고, M3까지 유지 후 제거 |
| POS HTTP 인증 미설계 | 무단 명령 수신 | M1: 로컬망 한정, M3: API key 또는 mTLS |
| Nav2 goal 실패 시 모드 진행 | 큐 정체 | 3회 재시도 후 reject + 이벤트 알림 |
| 카메라 미수신 시 patrol 정확도 | 점유 정보 부정확 | confidence < 0.5 → `unknown` 상태로 발행 |

---

## 12. 부록

### 12.1 용어집

- **FSM** (Finite State Machine): 유한 상태 기계
- **BT** (Behavior Tree): 행동 트리, 본 프로젝트의 의사결정 핵심
- **SoT** (Source of Truth): 단일 진실 원본
- **launch supervisor**: ros2 launch 자식 프로세스를 spawn/kill 관리하는 mode_manager 내부 클래스
- **선점** (preempt): 우선순위 높은 모드가 진행 중 모드를 중단시키고 진입
- **dwell**: 도착 후 정지 대기 시간 (서빙: 음료 수령 시간, patrol: 점유 감지 시간)

### 12.2 참고 학술 자료

- Isla 2005 — Behavior Tree character hierarchy (engaging 모드 페르소나)
- Russell 1980 — Affect dimensional model (감정 차원 v/a)
- Salichs 2014 — Emotion confidence (감정 신뢰도)
- Castro-González 2016 — RPS 게임 손실율 (미니게임)
- Marzinotto 2014 — BT formalization (root Fallback 패턴)
- Iovino 2022 — BT 학술 서베이

기존 `docs/cafe_npc_paper_master.md` 참조.

### 12.3 코딩 컨벤션

- Python 3.12, PEP 8, ROS2 권장 스타일
- 한글 주석 환영, 코드 식별자는 영문
- Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- 노드별 logger 사용, `print` 금지
- 새 모듈은 type hints 권장
- 일관성 유지를 위해 하루 마지막 작업 후 `docs/daily/YYYY-MM-DD_<topic>.md` 회고 작성

### 12.4 실행 명령 모음

```bash
# 빌드
cd ~/moca
colcon build --symlink-install
source install/setup.bash

# 전체 시뮬 (Gazebo + nav2 + dev_all + opserver + web)
./scripts/run_nav2_sim.sh           # 터미널 1 (기존)
./scripts/run_opserver.sh           # 터미널 2 (신규)
./scripts/run_moca_web.sh           # 터미널 3 (신규)
ros2 launch dobi_npc_bringup dev_all.launch.py  # 터미널 4

# 브라우저
firefox http://localhost:8800/dashboard.html

# 수동 모드 호출 (디버깅)
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
  "{requested_mode: 'patrol', params: '{}'}"

# 외부 이벤트 시뮬
curl -X POST http://localhost:8800/api/v1/pickup \
  -H 'Content-Type: application/json' \
  -d '{"drink_id":"D-test-0001","target_table":"T03","ready_at":"2026-05-16T13:00:00Z"}'

# 모드 상태 echo
ros2 topic echo /mode/state
ros2 topic echo /opserver/event
```

### 12.5 산출 문서 체크리스트 (M0 종료 시점)

- [ ] 본 계획서 `docs/moca_mode_and_opserver_plan.md` v1.0
- [ ] 5-state FSM 사양 `docs/moca_5state_fsm_spec.md`
- [ ] OpServer API 사양 `docs/moca_opserver_api_spec.md`
- [ ] Web 대시보드 사양 `docs/moca_web_dashboard_spec.md`
- [ ] Patrol 설계 `docs/moca_patrol_design.md`
- [ ] Guiding 설계 `docs/moca_guiding_design.md`
- [ ] 일일 회고 `docs/daily/2026-05-16_moca_mode_and_opserver_plan.md`
- [ ] CLAUDE.md 5-state 반영 업데이트

---

## 13. 다음 단계 (Stephen Action Items)

1. **본 문서 리뷰**: 모드 전이표(§2.4), 우선순위(§3.3), API 명세(§4.4), 디렉토리 배치(§5.2) 4개 섹션 집중 검토.
2. **팀 회의 안건화**: 송민규/류재상/김진우/김덕현/안순혁에게 §2(모드 정의), §3(트리거), §7(UI) 공유. 1주 내 피드백 수집.
3. **첫 M0 작업 (당일)**: `dobi_npc_msgs`에 신규 5종 msg + 2종 srv 추가 + `colcon build` 통과. 이후 `git commit -m "feat(msgs): add patrol/guiding/opserver messages for 5-state FSM"`.
4. **회고 파일 작성**: 오늘 작업 종료 시 `docs/daily/2026-05-16_moca_mode_and_opserver_plan.md`에 본 계획 수립 과정 + 의사결정 근거 + 미결 이슈 기록.

---

**End of Document**
