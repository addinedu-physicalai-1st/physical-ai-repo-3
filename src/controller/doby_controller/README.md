# moca — Multi-module Cafe Robot Workspace

> **Doby Barista** 호객·서빙·팔로우 카페 로봇 통합 ROS2 워크스페이스
>
> Vic Pinky Pro 모바일 베이스 + 5-stage funnel BT + Russell V-A 감정 모델 + 노트북 풀스크린 얼굴 표현 + Web Dashboard

---

## 한 줄 정의

카페에서 손님에게 **모객 행위**를 하는 자율 로봇의 행동 의사결정 시스템.
Vic Pinky Pro 위에 BehaviorTree.CPP 기반 5-stage funnel BT 를 얹고, 사용자의 감정 상태 (Russell 차원 모델) 에 따라 모객 전략을 동적으로 조정.

학술 토대: 6 편의 핵심 논문 (Isla 2005 / Marzinotto 2014 / Russell 1980 / Salichs 2014 / Castro-González 2016 / Iovino 2022). 상세는 `docs/cafe_npc_paper_master.md`.

---

## 핵심 기능

### 운영 모드 5종 (5-state FSM)

`VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging')` — 코드 SoT: `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py`. FSM SoT: `docs/moca_5state_fsm_spec.md`.

| 모드 | priority | 기능 | launch |
|---|---|---|---|
| **serving** | 1 (최상) | 픽업 테이블 → 목표 테이블 배달 → home 복귀. Nav2 NavigateToPose 단발 반복 + dwell | `mode_serving.launch.py` |
| **guiding** | 2 | 카운터 결제 완료 고객을 빈 테이블로 인솔 | `mode_guiding.launch.py` |
| **patrol** | 3 | 5분 주기 전 테이블 순회 + 점유 감지 + 보고 | `mode_patrol.launch.py` |
| **engaging** | 5 | 한산 시 모객 (cafe_funnel_v1.xml 6단계 BT — IDLE→APPROACH→ICEBREAK→MINIGAME→OFFER→LEAD-IN) | `mode_engaging.launch.py` |
| **idle** | 99 | 대기, 활성 mode stack 없음. 기본 상태 | (launch 없음 — no_stack) |

**Legacy alias** (M3 종료 **2026-07-04 까지만** 지원, WARN 로그 후 자동 변환): `npc → engaging`, `follow → guiding`. 해당 deprecated launch (`mode_npc.launch.py`, `mode_follow.launch.py`) 도 7-04 후 제거 예정.

**Priority enforce**: `mode_manager` 는 priority 무관 모든 전이 허용 (운영자 수동 트리거 우선). priority enforce 책임은 `moca_opserver` 에 있음 (`docs/moca_5state_fsm_spec.md` §5).

**외부 명령** (mode 아님): `emergency_stop` (즉시 정지) / `resume` (idle 복귀). `/operator/command` 토픽.
**가드**: safety alarm (`/rapport/event` weight ≥ 임계) 또는 operator stop → 어느 상태든 idle 강제.

관련 메모리: [[project_mode_architecture]] [[project_mode_serving]] [[project_follow_live_tuning]].

### Web Dashboard (M3 완성, 2026-05-16)

`http://localhost:8800/` 에서 운영자 7 페이지 — dashboard / modes / tables / events / analytics / settings / debug.

- 실시간 평면도 (floorplan-view) — robot 마커 동적 + 테이블 점유 색상 + waypoint/gate 사각형 + yaw 회전
- NTP 6 대 sync 모니터링 (192.168.0.133 5090 master + 노트북 3 / 로봇 2 = 5 client)
- AMCL pose 우선 + /odom fallback
- Doby (Vic Pinky) / DDooby (OpenARM) 상태 헤더 (Web Component, store-key 동적 갱신)

상세: `docs/moca_web_dashboard_spec.md`.

### 비전 — 3 카메라 아키텍처

| 카메라 | 위치 | 용도 |
|---|---|---|
| 1 | 노트북 내장 | GEVA 얼굴 표정 → V·A 감정 |
| 2 | RPi 직결 (abko FHD1080p) | GEFA 자세/follow person detection |
| 3 | 노트북 외장 (RPC-20F) | 게임 손 인식 (RPS minigame) |

상세: `docs/cafe_npc_camera_architecture.md`.

### 안전 영역 (3계층 — 진행 중)

| 계층 | 내용 | 상태 |
|---|---|---|
| Hard SafetyCheck | 배터리 + lidar 0.25~1.0m alarm | ✓ 완료 |
| PauseGate | IEC 60204-1 Cat 2 Monitored Standstill (자동 재개) | C~E 미진행 |
| Social EmotionMonitor | V/A 기반 모객 abort | ✓ 완료 (rapport_tracker) |

**cmd_vel pipeline 안전 노드 (RPi 단일 호스트):**
- Phase A 완료 (2026-05-09): twist_mux + e_stop_pub
- Phase B 코드 적용 (`vicpinky_bringup/launch/bringup.launch.xml`): velocity_smoother + collision_monitor lifecycle 노드. 라이브 검증 회고 미작성 — RPi 재가동 시 확인.
- Phase C~E 미진행 (SafetyZoneState + 의도 표현 + freezing 회피)

표준: ISO 13482 + IEC 60204-1 Cat 2 + ISO/TS 15066 + PL=d (best-effort). SoT: `docs/cafe_npc_safety_zone.md`.

---

## 워크스페이스 구조

```
~/moca/
├── CLAUDE.md                              ← 프로젝트 컨텍스트 (LLM/팀원 첫 읽기)
├── README.md                              ← 본 문서
├── requirements.txt                       ← Python pip 의존성
├── moca.repos                             ← vcs import 용
├── .gitignore
│
├── src/
│   ├── shared/                            ← 팀 공유
│   │   └── vic_pinky/                     ← PinkLAB 공식 (자체 git fork)
│   │       ├── vicpinky_description       ✅
│   │       ├── vicpinky_navigation        ✅
│   │       ├── vicpinky_bringup           ❌ COLCON_IGNORE (RPi only — 모터/배터리/zlac)
│   │       ├── vicpinky_gazebo            ❌ COLCON_IGNORE (moca_gazebo 로 대체)
│   │       └── vicpinky_emotion           ❌ COLCON_IGNORE (PinkyPro LCD 전용, vicpinky LCD 없음 — gif 자산만 face_avatar 재활용)
│   │
│   ├── dobi_npc/                          ← 모객 BT 시스템 (6 패키지)
│   │   ├── dobi_npc_msgs                  (커스텀 메시지 4종 + SetMode srv)
│   │   ├── dobi_npc_bt                    (C++ BT 노드, cafe_funnel_v1.xml)
│   │   ├── dobi_npc_emotion               (GEVA face V·A + rapport_tracker + decision_rule)
│   │   ├── dobi_npc_dialog                (persona_manager + tts_node + face_avatar 풀스크린)
│   │   ├── dobi_npc_minigame              (RPS evolution + speed_counter + cafe_ninja, minigame_runner subprocess)
│   │   └── dobi_npc_bringup               (mode_manager + 5 mode launch + serving_dispatcher + follow_controller + patrol_scheduler + guiding_controller)
│   │
│   ├── moca_gazebo/                       ← 시뮬 (mapv5_moca.world + 가구 SDF 모델)
│   ├── moca_navigation/                   ← Nav2 wrapper (vicpinky_navigation patch)
│   └── moca_opserver/                     ← Web Dashboard (FastAPI + static 7 페이지)
│
├── docs/
│   ├── daily/                             ← 일일 회고 (.md, 시간순)
│   ├── cafe_npc_paper_master.md           ← 학술 척추 6-Layer
│   ├── cafe_npc_implementation_plan.md    ← 16주 구현 계획
│   ├── cafe_npc_camera_architecture.md    ← 3 카메라 SoT
│   ├── cafe_npc_serving_mode.md           ← 서빙 모드 SoT
│   ├── cafe_npc_safety_zone.md            ← 안전 영역 표준 매핑 SoT
│   ├── cafe_npc_rpi_live_amcl_checklist.md← RPi 라이브 운영 매뉴얼 (12 단계, 2026-05-17)
│   ├── moca_5state_fsm_spec.md            ← 5-state FSM 인터페이스/priority/alias spec
│   ├── moca_web_dashboard_spec.md         ← Web Dashboard 7 페이지 spec
│   └── moca_db_schema.md                  ← PostgreSQL 14 테이블 설계 (M4 협의 대기)
│
├── config/
│   └── cafe_layout.yaml                   ← 가구/테이블/waypoint/gate SoT (picker 등록)
│       (※ persona YAML SoT 는 src/dobi_npc/dobi_npc_dialog/config/personas/ — 4 종:
│           generic / casual_browser / friendly_child / professional_adult)
│
├── scripts/                               ← 운영/디버깅 30+ 스크립트
├── maps/                                  ← (gitignore) PGM 맵 + 백업
└── (gitignore: build/, install/, log/, maps/, datasets/, web/, models/)
```

---

## 의존성

### 시스템 (apt)

```bash
sudo apt install \
    ros-jazzy-desktop ros-jazzy-nav2-bringup ros-jazzy-nav2-amcl \
    ros-jazzy-behaviortree-cpp ros-jazzy-twist-mux ros-jazzy-velocity-smoother \
    ros-jazzy-collision-monitor ros-jazzy-cartographer-ros \
    ros-jazzy-ros-gz ros-jazzy-ros-gz-bridge \
    python3-numpy python3-opencv python3-pil python3-pygame python3-yaml
```

**버전 핀:**
- BehaviorTree.CPP `4.8.3-1noble` (apt 공식, Phase 1~5 동안 동결)
- ROS2 Jazzy (Ubuntu 24.04 noble)
- numpy 1.26.4 + opencv 4.6.0 (시스템 cv_bridge 가 의존 — **pip numpy 2.x 절대 X**)

### Python pip (`requirements.txt`)

```bash
pip install --user -r requirements.txt

# mediapipe 설치 시 numpy 2.x + opencv-contrib-python 가 같이 들어와 시스템 ROS
# 충돌 → 직후 즉시 제거:
pip uninstall --yes numpy opencv-contrib-python
```

자세한 정책은 `CLAUDE.md` §7 "외부 의존성 버전 정책".

---

## 빌드 + 실행

### 빌드

```bash
cd ~/moca
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

또는 alias (`.bashrc` 등록):
```bash
moca_build       # 깨끗한 셸에서 검증 빌드 (격리)
moca_activate    # 빌드 결과 활성화
moca_clean       # build/install/log 삭제
```

### 개발 PC vs 로봇 빌드 차이

개발 PC: vicpinky_description + vicpinky_navigation + 8 본 패키지 = 8+ 패키지 빌드.
로봇 (RPi 5): `vicpinky_bringup/COLCON_IGNORE` + `vicpinky_gazebo/COLCON_IGNORE` 삭제 후 빌드.

### 실행 — Gazebo 시뮬 (DOMAIN=99 + LOCALHOST_ONLY=1)

```bash
# 풀스택 (Gazebo + Nav2 + Dashboard + 자동 브라우저)
bash scripts/run_sim.sh --no-rviz --cleanup

# 종료
bash scripts/stop_sim.sh
```

### 실행 — RPi 라이브 (DOMAIN=22)

⚠ **§0-A 진입 조건 확인** — 팀 작업 종료 신호 + 본인 명시 ("RPi 사용 OK") 필요. 묵시적 해제 X.

```bash
# 자세한 12 단계 매뉴얼: docs/cafe_npc_rpi_live_amcl_checklist.md
bash scripts/run_real.sh        # 또는 run_teleop_ui.sh + run_dashboard.sh --domain=22
bash scripts/stop_real.sh
```

### 시나리오 검증

```bash
# 시뮬 5 모드 자동 시나리오 (patrol → serving → guiding → engaging → emergency_stop)
bash scripts/run_demo_scenario.sh

# 영상 녹화 (ffmpeg x11grab 1920x1080)
bash scripts/record_demo.sh
```

---

## Phase 진행 상황 (2026-05-17 기준)

**두 트랙 동시 진행:**
- **학술 트랙 (Phase 0~5, 16주)** — `docs/cafe_npc_implementation_plan.md` SoT
- **운영 트랙 (M0~M4, 6주)** — `docs/moca_mode_and_opserver_plan.md` SoT (2026-05-16 추가)

### 학술 트랙 (Phase 0~5)

| Phase | 기간 | 상태 | 내용 |
|---|---|---|---|
| 0-A | 2026-05-01 | ✓ | cabot → moca 마이그레이션 + vic_pinky 보존 |
| 0-B | 2026-05-01 | ✓ | dobi_npc 6 패키지 골격 + 더미 노드 + 빌드 검증 |
| 1 (W1-3) | 2026-05-02~03 | ✓ | 5-stage funnel BT + 페르소나 4종 (generic/casual/friendly/professional) + Nav2 Approach (sim) |
| 2 (W4-6) | 2026-05-02~04 | ✓ | GEVA 웹캠 얼굴 → V·A + EmotionMonitor + TTS + face_avatar |
| 3 (W7-9) | 2026-05-05~06 | ✓ | RPS/speed_counter/cafe_ninja 3 게임 통합 + Polite phrase + 카메라 3 분리 |
| 4 (W10-12) | 2026-05-08~09 | 진행 중 | 안전 영역 Phase A 완료 (twist_mux + e_stop) + Phase B 코드 적용 (smoother + collision_monitor 라이브 검증 대기) |
| 5 (W13-16) | TBD | 미시작 | XAI / Learning (Iovino 2022 미해결 과제) |

### 운영 트랙 (M0~M4)

| 마일스톤 | 기간 | 상태 | 내용 |
|---|---|---|---|
| M0~M1 | 2026-05-16 | ✓ | 5-state opserver scaffold + mode_manager 5-state 확장 |
| M2 | 2026-05-16 | ✓ | guiding_controller (lock-on/lag 감지) + patrol_scheduler + table_occupancy_detector (M2 YOLO person, M3 식기 후속) + completion_watcher |
| M3 | 2026-05-16 | ✓ | Web Dashboard 7 페이지 (vanilla JS, 빌드 도구 없음) + NTP 6대 sync 토폴로지 + floorplan 동적 마커 |
| M4 | 2026-05-17~ | 진행 중 | DB schema v0.1 초안 (PG 5090 설치 보류, 팀 협의 대기) + Gazebo wall 정합 진단 (sim AMCL fundamental 한계 확정, 5 patches 적용, RPi 라이브 검증 대기) |

상세: `docs/daily/` 회고 (시간 역순) + `docs/cafe_npc_implementation_plan.md` (학술) + `docs/moca_mode_and_opserver_plan.md` (운영).

---

## 문서 가이드 (where to read first)

### 학술 트랙 (`docs/cafe_npc_*.md`)

1. **신규 합류자** → `CLAUDE.md` (프로젝트 컨텍스트 전체, 본 워크스페이스 첫 읽기)
2. **학술 배경** → `docs/cafe_npc_paper_master.md` (6-Layer + GEVA/GEFA 약어 매핑)
3. **시스템 아키텍처** → `docs/cafe_npc_system_architecture.md`
4. **구현 계획** → `docs/cafe_npc_implementation_plan.md` 
5. **모드별 SoT**:
   - `docs/cafe_npc_engagement_funnel.md` (모객 5-stage funnel — engaging 모드 BT)
   - `docs/cafe_npc_safety_zone.md` (안전 영역 표준 매핑 — ISO 13482 외)
6. **카메라 아키텍처** → `docs/cafe_npc_camera_architecture.md` (3 카메라)
7. **운영 매뉴얼** → `docs/cafe_npc_rpi_live_amcl_checklist.md` (RPi 라이브 12 단계, 2026-05-17)

### 운영 트랙 (`docs/moca_*.md`, M0~M4)

8. **상위 설계서** → `docs/moca_mode_and_opserver_plan.md` v1.0 (5 모드 + opserver + 대시보드 통합 설계, M0~M4 로드맵)
9. **5-state FSM 사양** → `docs/moca_5state_fsm_spec.md` v1.0 (invariant + action + guard + 동시성)
10. **모드별 설계** (5 모드 모두):
    - `docs/moca_idle_design.md` v1.0 (idle_no_stack + 공통 always-on 7 노드 invariant)
    - `docs/moca_serving_design.md` v1.0 (serving_dispatcher 4-state FSM + tables.yaml + home 복귀)
    - `docs/moca_patrol_design.md` v1.0 (patrol_scheduler + table_occupancy_detector 두 노드 IPC)
    - `docs/moca_guiding_design.md` v1.0 (guiding_controller_node FSM + 고객 lock-on/lag 감지)
    - `docs/moca_engagement_design.md` v1.0 (bt_executor + cafe_funnel_v1.xml ReactiveFallback Alarm + 8 BT 노드 + minigame_runner)
11. **OpServer API** → `docs/moca_opserver_api_spec.md` v1.0 (REST + WebSocket + 모드 선점 알고리즘)
12. **Web Dashboard** → `docs/moca_web_dashboard_spec.md` v1.0 (페이지 7종 UI/UX + vanilla JS + 반응형 + a11y)
13. **DB 설계** → `docs/moca_db_schema.md` v0.1 (PG 14 테이블, 5090 설치 보류, 팀 협의 대기)

### 일일 작업 흐름

14. **회고** → `docs/daily/YYYY-MM-DD_<topic>.md` (시간 역순, 변경 + 발견 + 다음)

---

### 작업 규칙 요약 (`CLAUDE.md` §7 발췌)

- 작업 시작 전 매일 1회 PC+RPi 백업 (`~/backup/moca_daily_YYYYMMDD/`)
- `~/cabot` 경로 절대 참조 X — `~/moca` SoT
- 팀 작업 중 RPi 접근 금지 (사용자 명시 해제까지)
- 상대경로 컨벤션 — `~/moca`, `$HOME/moca`, `/home/<user>/` 하드코딩 X
- 이전 잘 동작 검증된 코드 수정 X (필요 최소 변경)
- 한국어 주 작업 언어 (사용자 한국어 입력 시 한국어 응답)

---

## 라이선스

내부 프로젝트 (TBD). GitHub 공개 시점에 결정.

---

*마지막 갱신: 2026-05-17 (M3 dashboard 완성 + M4 진입, AMCL sim 한계 진단 직후)*
