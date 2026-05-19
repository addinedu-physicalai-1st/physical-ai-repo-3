# 2026-05-17 (저녁) — 5 좌표 통일 + home dock/staging 분리 + Nav2 combo 비교 + DDS sim issue

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `2026-05-17_amcl_drift_sim_diagnosis.md` (오후 1차 — AMCL drift sim 진단)
> 본 회고: 오후 2차~저녁 — 5 좌표 통일 patch + serving T01/T02 검증 + dock/staging 분리 + Nav2 controller/planner 비교 시뮬 + DDS sim 환경 fundamental 한계 발견

---

## 1. 본 세션 범위

오전 회고 (AMCL drift sim 진단) 후 저녁 추가 진행:
- 5 좌표 (home/spawn) 통일 patch — 분산 4 군데 fix
- T01/T02 serving 검증 → home dock 운영 요구 (3cm) 와 Nav2 표준 (inflation ≥ inscribed 0.26) 모순 발견
- home dock vs staging 분리 (옵션 3 quick fix) 채택
- Nav2 combo 비교 시뮬 시작 (HMAC + A* + MPPI 사용자 제안) — DDS sim 환경 fundamental 깨짐으로 중단

---

## 2. 진행 단계별

### 2.1 5 좌표 통일 patch (저녁 초)

세션 시작 진단 — home/spawn 좌표가 5 군데 분산:

| 위치 | x | y | yaw |
|---|---|---|---|
| `cafe_layout.yaml` pinky_home | -36.903 | 2.693 | -1.571 |
| `cafe_layout.yaml` pinky_spawn | -36.887 | **2.626** | -1.571 |
| `launch_mapv5_moca.launch.xml` spawn | -36.903 | **2.743** | -1.571 |
| `nav2_params.yaml` amcl.initial_pose | -36.903 | **2.743** | -1.571 |
| `tables.yaml` home_pose | -36.887 | **2.809** | -1.5708 |
| `run_nav2_sim.sh` fallback | **-36.937** | **2.893** | -1.570 |

→ 모두 (-36.903, 2.693, -1.571) 로 sync. AMCL pose 와 GZ pose **100% 일치** (소수점 16자리까지).

효과: 이전 sim AMCL 와 GZ 의 10cm+ 차이가 사라짐. 그러나 운영 요구 (카운터 3cm 옆 dock) 와 PGM 마킹 충돌 발견 (다음 단계).

### 2.2 home 좌표 RViz 재측정 + 3cm 안전 보정

사용자 RViz 클릭 — (-36.949, 2.649, yaw=-π/2).
- bar_counter -x face 와 robot +x face gap = **1mm** (너무 가까움)
- 운영 요구 3cm gap 위해 x=-36.98 보정

5 좌표 다시 sync — (-36.98, 2.649).

### 2.3 검증 fail — "Start occupied"

```
nav2.log: GridBased plugin failed to plan from (-36.98, 2.65) to (-40.30, -0.59): "Start occupied"
```

원인 — Nav2 collision check:
- bar_counter PGM 마킹 (x ∈ [-36.65, -35.49], y ∈ [2.51, 3.07])
- robot center (-36.98, 2.649) ↔ 카운터 최근접 box point (-36.65, 2.649) 거리 **33cm**
- Nav2 표준: `inscribed (0.26) + inflation (0.30) = 56cm` 필요
- 33cm < 56cm → **start point occupied**

### 2.4 옵션 3 — dock vs staging 분리 (채택)

| 좌표 | 의미 | 값 | 거리 (카운터에서) |
|---|---|---|---|
| **pinky_home** (dock) | 외관 정차 (카운터 3cm 옆) | (-36.98, 2.649) | 33cm — Nav2 start 불가능 |
| **pinky_staging** (신규) | Nav2 path 시작점 | **(-36.98, 2.0)** | **61cm** ✓ (> 56cm) |

운영 의도:
- 실 운영 — robot 가 dock 에 정차 (외관) + 모드 시작 시 별 dock action (`opennav_docking`) 으로 un-dock
- sim — staging 에 spawn + AMCL init (검증 안전)

5 좌표 patch (staging 으로):
- cafe_layout pinky_home (dock 보존) + pinky_staging (신규) + pinky_spawn (staging 로 변경)
- tables.yaml home_pose: staging
- launch_mapv5_moca spawn: staging
- nav2_params amcl.initial_pose: staging
- run_nav2_sim fallback: staging

### 2.5 Nav2 controller/planner 비교 시뮬 시작

사용자 제안 — HMAC (Hybrid A\*) + A\* + MPPI 조합 검증. 백업 진행 후:
- `~/backup/moca_daily_20260517_nav2_combo_test/` (114MB) — src/install/git bundle/memory tar 통째 + 5 복원 시나리오 README

베이스라인 스킵 + 5 조합 (Combo 1~5) 계획:

| # | Planner | Controller | inflation | xy_tol |
|---|---|---|---|---|
| 1 | NavfnPlanner | DWB | 0.30 | 0.25 |
| 2 | **SmacPlannerHybrid** | DWB | 0.30 | 0.25 |
| 3 | NavfnPlanner | **RPP** | 0.30 | 0.10 |
| 4 | **SmacPlannerHybrid** | **MPPI** | 0.30 | 0.10 |
| 5 | **SmacPlannerHybrid** | **RPP** | 0.30 | 0.10 |

### 2.6 Combo 2 (SmacPlannerHybrid + DWB) 결과

- staging spawn ✓ "Start occupied" 해결
- 그러나 robot 0cm 이동
- nav2.log: "Reached the goal!" 거짓 (path empty 또는 controller 즉시 reach)
- 의심: `motion_model_for_search: "DUBIN"` vicpinky differential drive 부적합 (DUBIN = forward-only car)

### 2.7 OPTION B (Navfn + DWB + inflation 0.10 + xy_tol 0.50) 시도

비교 위한 sanity check — robot 0cm 이동 동일. nav2.log 의 reach 보고만.

### 2.8 DDS sim 환경 fundamental 깨짐 발견

POST /api/v1/mode 응답:
```
{"status":"error","code":"ROBOT_OFFLINE","message":"/mode/state stale or never received"}
```

mode_manager process 가동 + /mode/state 토픽 등록 (publisher 1, subscriber 1) 그러나 데이터 실제 안 흐름.

mode_manager.log:
```
RTPS_TRANSPORT_SHM Error: Failed init_port fastrtps_port7008: open_and_lock_file failed
```

DDS shared memory transport port lock 실패. SHM cleanup (`rm /dev/shm/fastrtps_*`) + sim restart 도 효과 X.

OPTION D (mode_manager 우회, action 직접 호출) 도 동일 fail — `ros2 action send_goal /navigate_to_pose` 도 응답 X.

**sim 통신 환경 자체 깨짐 — 본 비교 시뮬 진행 불가능.**

---

## 3. 시도된 patches (영구 적용)

### 3.1 dock vs staging 분리 (보존)

| 파일 | 변경 |
|---|---|
| `config/cafe_layout.yaml` | pinky_home (dock, -36.98, 2.649) + **pinky_staging 신규 (-36.98, 2.0)** + pinky_spawn (staging 로 변경) |
| `src/dobi_npc/dobi_npc_bringup/config/tables.yaml` | home_pose: staging (-36.98, 2.0) |
| `src/moca_gazebo/launch/launch_mapv5_moca.launch.xml` | spawn_x/y: staging (-36.98, 2.0) |
| `src/moca_navigation/params/nav2_params.yaml` | amcl.initial_pose: staging (-36.98, 2.0) |
| `scripts/run_nav2_sim.sh` | SPAWN_X/Y fallback: staging (-36.98, 2.0) |

### 3.2 nav2_params.yaml 현 상태 (OPTION B)

| 파라미터 | 값 |
|---|---|
| planner | NavfnPlanner (Dijkstra, use_astar=false) |
| controller | DWB (DWBLocalPlanner) |
| inflation_radius | 0.10 (inscribed 0.26 보다 작음, Nav2 WARN) |
| xy_goal_tolerance | 0.50 |
| yaw_goal_tolerance | 0.10 |
| AMCL recovery_alpha | 0.0/0.0 (어제 patch) |
| AMCL do_beamskip | true |
| AMCL set_initial_pose | true + (-36.98, 2.0) |

다음 세션 비교 시뮬 진행 시 시작 yaml. 또는 combo 별로 다시 patch.

---

## 4. 발견 / 결정

### 4.1 ★ 운영 dock 3cm + Nav2 표준 모순

운영 요구 — robot center 가 카운터 3cm 옆 dock.
Nav2 표준 — `inscribed (0.26) + inflation (0.30) = 56cm` 안에 obstacle 없어야 path 가능.

→ 표준 Nav2 만으로 3cm dock **불가능**. opennav_docking 같은 별 dock action 필수.

본 세션 quick fix — dock vs staging 분리. dock 은 외관 정차 만 (Nav2 와 무관), staging 이 path 시작/종료. 후속 — opennav_docking 통합 (DockRobot / UndockRobot action) 또는 자체 micro-step 노드.

### 4.2 ★ SmacPlannerHybrid + vicpinky differential drive 부적합

`motion_model_for_search: "DUBIN"` 는 forward-only car (Tesla). vicpinky 는 differential drive (제자리 회전).

대안:
- `motion_model_for_search: "REEDS_SHEPP"` (forward+reverse) — vicpinky 에 더 적합
- 또는 `SmacPlanner2D` (Hybrid 아닌 일반 A\*) — differential drive 에 더 자연

다음 세션 비교 시뮬 시 시도.

### 4.3 ★ DDS SHM transport sim 환경 fragility

`Failed init_port fastrtps_port7008: open_and_lock_file failed` — DDS shared memory port lock 실패. 이전 sim restart 들의 stale shared memory 또는 다른 process 점유.

SHM cleanup + ros2 daemon restart + sim restart 모두 효과 X. fundamental 깨짐.

가능 해결:
- PC 재부팅 (모든 IPC reset)
- RMW 변경 (cyclonedds, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`)
- DDS profile config (XML 로 SHM transport 비활성)
- 환경변수 `FASTRTPS_DEFAULT_PROFILES_FILE` 사용

본 세션 추가 디버깅 X. 다음 세션 (재부팅 후 또는 RPi 라이브) 진행.

### 4.4 ★ opennav_docking 패키지 이미 설치

```
ros-jazzy-opennav-docking 1.3.11
ros-jazzy-opennav-docking-bt 1.3.11
ros-jazzy-opennav-docking-core 1.3.11
```

후속 작업 — DockServer config (dock_database.yaml) + serving_dispatcher 변경 (Nav2 → DockRobot action) + mode_serving.launch.py 갱신. 2시간 추정.

---

## 5. 다음 세션 후보

### 5.1 1순위 — sim DDS 환경 fix

1. PC 재부팅 — 모든 IPC reset (가장 빠름, 5분)
2. RMW cyclonedds 시도 — `export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` (10분)
3. FastDDS XML profile 작성 (SHM 비활성, UDP 만) — 30분

### 5.2 2순위 — Nav2 combo 비교 시뮬 재시도 (DDS fix 후)

| # | Planner | Controller | 의도 |
|---|---|---|---|
| 1 | NavfnPlanner | DWB | 베이스라인 |
| 2 | SmacPlannerHybrid (motion_model REEDS_SHEPP) | DWB | gate 통과 + differential drive 적합 |
| 3 | NavfnPlanner | RPP | 정밀 dock |
| 4 | SmacPlannerHybrid | MPPI | 사용자 제안 |
| 5 | SmacPlanner2D (Hybrid 아님) | DWB | A\* + differential drive |

각 ~5분 × 5 = 25분. DDS 정상이면 가능.

### 5.3 3순위 — opennav_docking 통합 (정밀 dock)

- dock_database.yaml 작성 — home + T01~T05 각 dock_pose 등록
- DockServer launch 추가
- serving_dispatcher 변경 — Nav2 (staging 도달) + DockRobot action (3cm dock) + UndockRobot (다음 운영)
- mode_serving.launch.py 통합
- 검증

총 약 2시간.

### 5.4 4순위 — RPi 라이브 진행 (`cafe_npc_rpi_live_amcl_checklist.md`)

§0-A 해제 신호 + 12 단계 매뉴얼. sim 한계 우회 가능성.

---

## 6. 변경 통계

| 영역 | 파일 | 변경 |
|---|---|---|
| Config | `config/cafe_layout.yaml` | pinky_home (dock 보존) + pinky_staging 신규 + pinky_spawn 변경 |
| Config | `src/dobi_npc/dobi_npc_bringup/config/tables.yaml` | home_pose → staging |
| Launch | `src/moca_gazebo/launch/launch_mapv5_moca.launch.xml` | spawn → staging |
| Params | `src/moca_navigation/params/nav2_params.yaml` | amcl.initial_pose → staging + Combo 2/B 시도 후 OPTION B 잔존 (Navfn + DWB + inflation 0.10 + xy_tol 0.50) |
| Script | `scripts/run_nav2_sim.sh` | SPAWN fallback → staging |
| Backup | `~/backup/moca_daily_20260517_nav2_combo_test/` (114MB) | src/install/git bundle/memory + 5 복원 시나리오 README |
| Results | `~/backup/.../results/combo2*.log + optionB*.log` | 검증 결과 4 로그 |

빌드 변화 없음 — config yaml + launch 만 (symlink-install 자동 sync).

---

## 7. 메모리 갱신 후보

- `[[project_dock_vs_staging_separation]]` (신규) — Nav2 표준 inflation+inscribed vs 운영 3cm dock 모순 → dock/staging 분리 패턴 + opennav_docking 후속
- `[[project_sim_dds_shm_fragility]]` (신규) — sim 환경 DDS SHM port lock 실패. PC 재부팅 또는 RMW cyclonedds 권장
- `[[project_amcl_drift_sim_limitation]]` 보강 — 5 좌표 통일 효과 (AMCL = GZ 100% 일치) + dock/staging 분리 패턴 추가

---

## 8. CLAUDE.md M4+ ToDo 추가 후보

- [ ] **opennav_docking 통합** — DockServer + dock_database.yaml + serving_dispatcher 변경. 운영 3cm dock 표준 구현. SoT `docs/daily/2026-05-17_dock_staging_separation_nav2_combo_dds_issue.md` §5.3.
- [ ] **Nav2 combo 비교 시뮬 재시도** — sim DDS fix 후. NavfnPlanner / SmacPlanner2D / SmacHybrid(REEDS_SHEPP) × DWB / RPP / MPPI 비교 매트릭스. SoT 위 회고 §5.2.
- [ ] **sim DDS SHM 안정화** — PC 재부팅 또는 RMW cyclonedds 또는 FastDDS XML profile. fundamental sim fragility 해결.

---

*다음 갱신: sim DDS fix 후 또는 RPi 라이브 검증 후*
