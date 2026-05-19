# 2026-05-17 — AMCL drift sim 진단 (Gazebo wall 정합 → 정합 OK 확정, fundamental AMCL likelihood 문제)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `2026-05-17_db_schema_floorplan_waypoints_gates.md` §8 (영상 촬영 시도 + AMCL drift 발견, E 옵션 보류)
> 본 회고: 영상 촬영 막힌 root cause 본격 진단 + 5 patches 적용 + sim 한계 확정
> 결과: sim 영상 촬영 본 세션 불가능. 다음 세션 cartographer / RPi 라이브 검토 필요.

---

## 1. 본 세션 범위 — M4+ ToDo §1 "Gazebo wall ↔ PGM map 정합 진단"

CLAUDE.md §10 M4+ ToDo #1 진행. 어제 회고 가설: "Gazebo `mapv5_moca.world` wall SDF ↔ `mapv5_mocamap.pgm` pixel 정합 X 가능성". 영상 촬영 + Gazebo 데모 + 라이브 Nav2 검증의 전제 조건.

본 세션 Phase 1~5 진단 진행. 원 가설 **기각**, 새 root cause 확정, 5 patches 적용. 그러나 fundamental AMCL likelihood field 문제 — sim 영상 본 세션 불가능 확정.

---

## 2. 진단 단계별

### Phase 1 — 정적 evidence 수집 (원 가설 기각)

| 가설 | 결과 |
|---|---|
| Wall STL ↔ PGM 정합 X | **기각**. `walls_high.stl` (May 15 10:32) 가 현 `mapv5_mocamap.pgm` (May 15 10:29) 직후 재생성 + `mapv5_moca.world` line 211 `<pose>-51.320 -6.624 0 0 0 0</pose>` 가 STL pixel-space 좌표 [0~19.55] × [0~12.5] 를 map origin 으로 정확 평행이동 |
| `use_sim_time` mismatch | **기각**. `bringup_launch.xml` 가 `use_sim_time:=True` launch arg 를 모든 노드에 cascade. yaml 의 `False` override |
| Initial pose 좌표 오류 | 미세 차이만 (launch hardcode (-36.903, 2.743) vs cafe_layout.yaml pinky_spawn (-36.887, 2.626), 12cm) — root cause 아님 |

`pgm_to_walls_stl.py` 가 origin 적용 안 하고 pixel-space 좌표 STL 출력. world include 의 `<pose>` 가 origin offset 적용 — 양쪽 정합 OK.

### Phase 2 — 라이브 evidence 수집

이미 가동 중 시뮬에서 직접 측정 (`gz model --model pinky` + `ros2 topic echo /amcl_pose`):

| 측정 | 값 |
|---|---|
| Gazebo robot | (-36.974, 2.700, yaw=-π/2) — 정상 spawn |
| AMCL pose | **(-36.909, -1.566, yaw=+π/2)** — y 4.27m + yaw 180° flip |
| AMCL covariance | xx=0.058, yy=0.030 — 작음 (wrong 위치를 "확신") |

→ **mirror basin lock-in** (y flip + yaw flip). 카페가 E-W 14m × N-S 12m 박스 + 가구 N-S 대칭 → AMCL scan match likelihood 양 mirror 위치 비슷.

`/initialpose` 수동 재발행 → AMCL 즉시 spawn 복귀 ✓. 단발 fix 가능하나 motion 시 다시 drift.

### Phase 3 — 단계별 patch 시도

**A patch — recovery_alpha 끄기:**
```yaml
# nav2_params.yaml AMCL 섹션
recovery_alpha_fast: 0.1 → 0.0
recovery_alpha_slow: 0.001 → 0.0
```
효과: 작은 motion (0.2m) AMCL stable ✓. Nav2 sweep (1.5m) yaw flip 진행 (-1.58 → -2.08 → +2.69) — 부족.

**B patch — beam_skip 활성화:**
```yaml
do_beamskip: false → true
```
효과: yaw flip 폭 감소 (-2.69 → -1.78). 그러나 여전 wrong basin entry. **새 issue 발견**: Nav2 "SUCCEEDED" 보고지만 GZ robot 1cm 만 이동 → AMCL 가 T01 영역 (-37.03, 0.71) 으로 jump → goal_checker 가 0.22m tolerance 안이라 도달 판정 → 거짓 success.

### Phase 4 — cmd_vel chain 진단

가설: RPi twist_mux 가 sim 에 없어서 `/bt/cmd_vel → /cmd_vel` chain 끊김. 라이브 hz 측정:

| 단계 | hz |
|---|---|
| /cmd_vel_nav (controller 출력) | **0** |
| /bt/cmd_vel (smoother 출력) | **not published** |
| /cmd_vel (bridge input) | **0** |
| /odom (Gazebo) | 55Hz 정상 |

→ chain 깨짐 X. **controller_server 자체가 cmd_vel 발행 안 함.** nav2.log: `"GridBased plugin failed to plan from (-39.29, 2.93) to (-37.12, 0.54): Failed to create plan with tolerance of: 0.500000"` (반복). AMCL drift (-39.29, 2.93) → planner 가 robot 가 벽 안에 있다고 인식 → path fail → controller silence.

cmd_vel chain 가설 **기각**. 진짜 root cause: AMCL drift → planner fail.

### Phase 5 — PGM 가구 추가 + yaml self-init only

**C patch — init covariance 작게** (`run_nav2_sim.sh`):
```yaml
covariance: xx/yy 0.25 → 0.05 (σ 22cm)
covariance: yaw 0.0685 → 0.005 (σ 4°)
```

**D patch — PGM 가구 19개 추가** (`scripts/pgm_add_furniture.py` 신규):
- Vic Pinky LiDAR mount = base_link + 0.15m
- bar_counter base 1.16×0.56 (top 0.32m, leg 닿음)
- kiosk base 0.5×0.4
- T01~T05 cafe_table leg cluster 0.2×0.2 (top 0.37m 안 닿음)
- B01~B04 banner 0.4×1.0
- L01~L03 floor_lamp 0.4×0.4, P01~P05 bonsai 0.3×0.3
- OpenARM skip (z=0.89, LiDAR 안 닿음)
- PGM occupied 3968 → 5634 px (+1666)

효과: planner failure **해결** ✓. nav2.log: "Passing new path to controller" + "Reached the goal!" + "Goal succeeded" 정상 흐름. 그러나 GZ robot 1cm 만 이동 — controller 가 짧게 발행 후 즉시 "Reached" 판정 (AMCL drift 때문).

**E patch — yaml self-init only** (`scripts/run_nav2_sim.sh`):
외부 `/initialpose` pub 15회 retry 제거. yaml `set_initial_pose=true` self-init 만. 이유: "Failed to transform initial pose in time" 반복 + covariance reset 으로 wrong jump 트리거 의심.

결과: T+5s AMCL=(-36.919, 2.184) — y 0.56m jump (1cm motion 직후). T+15s AMCL=(-37.001, 0.525) — T01 매우 가까이 → controller "Reached" 거짓 판정. **여전 동일 패턴.** 외부 pub 원인 아님.

---

## 3. 적용된 5 patches (영구)

| # | 파일 | 변경 |
|---|---|---|
| A | `src/moca_navigation/params/nav2_params.yaml` line 32-34 | `recovery_alpha_fast: 0.1 → 0.0`, `recovery_alpha_slow: 0.001 → 0.0` |
| B | `src/moca_navigation/params/nav2_params.yaml` line 19 | `do_beamskip: false → true` (주석 추가) |
| C | `scripts/run_nav2_sim.sh` line 202-207 | covariance xx/yy 0.25 → 0.05, yaw 0.0685 → 0.005 |
| D | `maps/mapv5_mocamap.pgm` + `scripts/pgm_add_furniture.py` (신규) | 19 가구 (bar_counter + kiosk + 5 cafe_table + 4 banner + 3 lamp + 5 bonsai) occupancy 추가. 백업: `maps/old/mapv5_mocamap_before_furniture_addition_20260517.pgm` |
| E | `scripts/run_nav2_sim.sh` line 183-216 | 외부 `/initialpose` pub 15회 retry → AMCL yaml self-init 대기만 |

각 patch 효과:
- A → 작은 motion stable
- B → yaw flip 폭 감소
- C → init covariance 강화 (효과 검증 어려움)
- D → **planner failure 해결** (큰 진전)
- E → 외부 pub 원인 아닌 것 확인

---

## 4. 잔존 root cause (다음 세션 진단 필요)

**AMCL likelihood field 의 fundamental 문제** — 5 patches 모두 적용에도 motion 1cm 직후 wrong basin jump.

핵심 단서:
1. AMCL self-init 직후 spawn 위치 OK (Phase 5 검증)
2. NavigateToPose 받은 직후 controller 가 cmd_vel 짧게 발행
3. Robot 1cm 이동 → odom 변화 → AMCL motion update 트리거
4. Motion update 후 scan match → wrong basin likelihood > home basin likelihood
5. AMCL 가 wrong basin 으로 collapse
6. Controller 가 robot 가 T01 도달 판정 (tolerance 0.25m 안) → cmd_vel zero → robot 정지

**왜 wrong basin likelihood 가 더 높은가:**
- 카페 N-S 12m × E-W 14m 박스. 가구 분포가 N-S 양쪽 대칭.
- Spawn (-36.9, 2.7) 는 NE 코너 — 벽 가까이라 LiDAR scan 정보 적음 (북/동 두 벽만 거리 짧음).
- Wrong basin (-36.9, 0.5~0.7) 는 카페 중앙 — 4방 가구 + 벽 정보 풍부.
- AMCL likelihood field 가 wrong basin 을 매력적으로 평가.
- Recovery 끄기 + cov 작게 + 가구 PGM 추가 — 균형 좁혔지만 못 깨뜨림.

---

## 5. 다음 세션 후보

### Option A — sim deeper patches (시도 가치 중)
- `alpha1~5: 0.05 → 0.01` (motion model noise 최소)
- `sigma_hit: 0.2 → 0.05` (likelihood field sharp 화)
- `z_hit: 0.95` 등 weight 조정
- `controller.general_goal_checker.xy_goal_tolerance: 0.25 → 0.05` (controller 도달 판정 엄격)

### Option B — spawn 위치 카페 중앙 이동 (시도 가치 높)
현 spawn (-36.9, 2.7) = NE 코너 vicpinky_home plate. 카페 중앙 (-41, 0) 부근으로 이동:
- launch_mapv5_moca.launch.xml spawn_x/y 변경
- cafe_layout.yaml `pinky_home` + `pinky_spawn` 변경
- nav2_params.yaml `amcl.initial_pose` 변경
- mode_manager 의 home 좌표 변경
- world 의 vicpinky_home dock plate 모델 (현 없음 — 좌표만 기록) 이동
- 단점: 실 카페 운영 시 dock 위치 정해진 곳 (NE 코너 벽 가까이 — 충전소). spawn 이동은 sim 만 가능, 실 운영 X.

### Option C — Cartographer 등 다른 localization (큰 작업)
- AMCL Mark-Liu particle filter 대신 Cartographer 의 graph-based SLAM
- 또는 SLAM Toolbox (continuous re-localization)
- ros-jazzy-cartographer-ros / slam_toolbox 패키지
- 작업: nav2_params.yaml localization 섹션 교체, launch 변경
- 대안: ndt_localizer (NDT-based)

### Option D — RPi 라이브 (sim 우회, 영상 가장 적합)
- §0-A 해제 (팀 작업 종료 신호 + 명시 해제) 필요
- DOMAIN=22 + STATIC_PEERS + bringup
- 실 lidar 노이즈 + 동적 카페 배치 → AMCL 더 안정 가능성
- 가장 빠른 영상 촬영 경로

### Option E — 시뮬 + 수동 teleport 데모 (영상 약식)
- Gazebo viewport 만 녹화 (robot 가 sim 안 정상 navigation X)
- Dashboard floorplan 마커는 robot teleport (gz service set_pose) 로 수동 이동
- patrol/serving 자율 영상 X, 시각 데모 영상 O

---

## 6. 본 세션 발견 (별 root cause 아님, 그러나 중요)

### 6.1 ★ cmd_vel chain 가설 — 시뮬에서 chain OK

§11 의 RPi 측 chain (twist_mux → smoother → collision_monitor → zlac_driver) 는 시뮬에 없음. 시뮬은:
- Nav2: controller_server → `/cmd_vel_nav` → nav2_velocity_smoother → `/bt/cmd_vel`
- Gazebo bridge: `/cmd_vel` 받음 (NOT `/bt/cmd_vel`)
- **따라서 `/bt/cmd_vel` → `/cmd_vel` 변환 chain 가설** — 그러나 실제 controller_server 가 발행 0 (Phase 4), 즉 chain 깨짐 X — upstream 0.

만약 추후 시뮬에서 cmd_vel 실 흐름 필요 → topic_tools relay 또는 spawn.launch.xml 의 bridge cmd_vel → bt/cmd_vel remap 변경 검토. 본 세션 영상 컨텍스트에선 무관.

### 6.2 ★ AMCL set_initial_pose 의 covariance default

Nav2 AMCL `set_initial_pose=true` + `initial_pose.x/y/z/yaw` 가 yaml self-init. 그러나 init covariance 별 param 없음 — Nav2 default 사용 (xx/yy=0.5², yaw=π/6²). 외부 `/initialpose` publish 만 covariance custom 가능. C-1 patch (covariance 작게) 효과 미미 — yaml self-init 우선 사용 시 외부 cov 무시.

---

## 7. 메모리 갱신 후보

- [[project_amcl_drift_sim_limitation]] (신규) — sim N-S symmetric 카페 + spawn NE 코너 → AMCL mirror basin lock-in. 5 patches 다 적용해도 motion 1cm 직후 wrong basin jump. 다음: spawn 중앙 이동, cartographer, RPi 라이브.
- [[feedback_amcl_self_init_vs_external_pub]] (신규) — Nav2 AMCL set_initial_pose=true 사용 시 외부 /initialpose pub 불필요. 외부 pub 시 "Failed to transform initial pose in time" + covariance reset 사고 가능.
- [[project_pgm_add_furniture_pattern]] (신규) — Gazebo sim 가구를 PGM 에 마킹하는 script + LiDAR mount 높이 (0.15m) 기준 footprint 선정.

기존 메모리 정합:
- [[feedback_dont_touch_working_code]] ✓ — 5 patches 모두 reversible, 기존 코드 보존
- [[feedback_relative_path_convention]] ✓ — script 모두 SCRIPT_DIR + argparse
- [[project_navigation_code_separation]] ✓ — Nav2 patches 만, teleop_ui 점유 자산 무관
- [[feedback_no_rpi_when_team_working]] ✓ — sim DOMAIN=99 + LOCALHOST_ONLY=1 만

---

## 8. 다음 단계 (CLAUDE.md §10 M4+ ToDo 갱신 후보)

- [x] **Gazebo wall ↔ PGM 정합 진단** — 본 세션 완료. **정합 OK 확정**, 본 가설 기각.
- [ ] **AMCL fundamental likelihood field 문제 진단** ⚠ — 5 patches 적용에도 wrong basin lock-in. 다음 세션 deeper patches (sigma_hit, alpha, controller tolerance) 또는 다른 localization (cartographer).
- [ ] **spawn 위치 검토** — 카페 중앙 이동 시 sim AMCL 안정 가능성. 실 운영 dock 위치는 NE 코너 보존.
- [ ] **영상 촬영 전제** — sim AMCL 해결 후 또는 RPi 라이브 우회.

---

## 9. 변경 통계

| 영역 | 파일 | 변경 |
|---|---|---|
| Config | `src/moca_navigation/params/nav2_params.yaml` | A+B patch (recovery_alpha=0, do_beamskip=true) |
| Script | `scripts/run_nav2_sim.sh` | C patch (init cov) + E patch (yaml self-init only) |
| Script | `scripts/pgm_add_furniture.py` | 신규 (159 줄) — Gazebo 가구 → PGM 마킹 |
| Asset | `maps/mapv5_mocamap.pgm` | D patch (19 가구 마킹, +1666 px) |
| Backup | `maps/old/mapv5_mocamap_before_furniture_addition_20260517.pgm` | 변경 전 사본 |
| Docs | `docs/daily/2026-05-17_amcl_drift_sim_diagnosis.md` | 본 회고 |

빌드 변화 없음 — colcon build 필요 X.

---

## 10. 트러블슈팅 히스토리 (시도 → 결과 → 다음)

### 10.1 진단 가설 매트릭스

| # | 가설 | 검증 방법 | 결과 | 결론 |
|---|---|---|---|---|
| H1 | Wall SDF ↔ PGM pixel 정합 X | STL/PGM timestamp + world `<pose>` 검사 + `pgm_to_walls_stl.py` 동작 분석 | STL May 15 10:32 ↔ PGM May 15 10:29 (정합) + world `<pose>-51.32 -6.624 0 ...>` 가 origin offset 정확 적용 | **기각** |
| H2 | use_sim_time mismatch | `bringup_launch.xml` + `localization_launch.xml` 분석 + ros2 param 확인 | launch arg `use_sim_time:=True` 가 yaml `False` override (Nav2 표준 cascade) | **기각** |
| H3 | initial_pose 좌표 오류 | launch hardcode vs cafe_layout.yaml vs nav2_params.yaml 비교 | 12cm 차이만, AMCL initial cov 0.25 충분 흡수 | **기각** (root cause 아님) |
| H4 | Gazebo 가구 in /scan, PGM 가구 X → likelihood 낮음 → mirror basin attractor | PGM 가구 추가 (D patch) 후 재검증 | 가구 추가 후 planner failure 해결 ✓ 그러나 AMCL drift 여전 | **부분 인정** (보조 요인, 단일 root cause 아님) |
| H5 | recovery_alpha 가 wrong jump 트리거 | A patch (alpha=0) + 검증 | 작은 motion stable, Nav2 sweep 여전 jump | **부분 인정** |
| H6 | 외부 /initialpose pub 가 covariance reset → wrong jump | run_nav2_sim.sh 의 외부 pub 제거 (E patch) | yaml self-init 만 사용해도 동일 drift | **기각** |
| H7 | cmd_vel chain 끊김 (RPi twist_mux 없음 → /bt/cmd_vel → /cmd_vel 변환 X) | 단계별 hz 측정 (/cmd_vel_nav, /bt/cmd_vel, /cmd_vel, /odom) | controller_server 자체가 발행 0 (planner fail) — chain 깨짐 X | **기각** |
| H8 | Planner failure (start point in lethal cost — AMCL pose 가 벽 안 이라고 인식) | nav2.log WARN 확인 | "GridBased plugin failed to plan from (-39.29, 2.93) to (-37.12, 0.54)" — H4 가구 추가 후 사라짐 | **확정** (H4 의 결과) |
| **H9** | **AMCL likelihood field fundamental — N-S symmetric 카페 + spawn NE 코너 (벽 가까이 scan 정보 적음) + 가구 분포 → wrong (mirror) basin likelihood > home likelihood** | 5 patches 모두 적용 후 motion 1cm 직후 wrong basin jump 관측 | 모든 patch 영향 부족 — wrong basin attractor 깨지지 않음 | **확정 (잔존 root cause)** |

### 10.2 시도된 patches (영구 적용 5건)

| Patch | 파일 | 변경 | 효과 | 검증된 부작용 |
|---|---|---|---|---|
| A | `nav2_params.yaml` 32-34 | `recovery_alpha_fast/slow: 0.1/0.001 → 0.0/0.0` | 작은 motion (0.2m) AMCL stable ✓ | 큰 sweep 시 wrong basin recovery X (단점 아님 — recovery 가 wrong basin 으로 유도하던 것) |
| B | `nav2_params.yaml` 19 | `do_beamskip: false → true` | yaw flip 폭 감소 (-2.69 → -1.78) | 없음 — Nav2 표준 권장 |
| C | `run_nav2_sim.sh` 202-207 | covariance xx/yy 0.25→0.05, yaw 0.0685→0.005 | 효과 검증 어려움 (E patch 후 외부 pub 자체 제거됨) | E patch 후 사용 X 부분 |
| D | `maps/mapv5_mocamap.pgm` + `scripts/pgm_add_furniture.py` | 19 가구 (+1666 px) | **planner failure 해결** ✓ "Failed to plan" → "Passing new path" + "Reached" | 가구 위치 변경 시 PGM 재생성 필요 + sim/RPi PGM 분리 권장 |
| E | `run_nav2_sim.sh` 183-216 | 외부 /initialpose pub 15회 retry → yaml self-init 대기만 | wrong jump 원인 검증 (외부 pub 아님 확정) | yaml init covariance custom 불가 |

### 10.3 시도하지 않은 후보 (다음 세션 우선순위)

| 우선 | 후보 | 변경 위치 | 예상 효과 | 부작용 | 작업 시간 |
|---|---|---|---|---|---|
| ★★★ | **RPi 라이브** | §0-A 해제 + DOMAIN=22 | sim 한계 우회. 실 lidar 노이즈 + 동적 카페 → AMCL 더 강함 | 팀 작업 영향 확인 필요 | 즉시 (해제 후) |
| ★★★ | **cartographer 교체** | `nav2_params.yaml` localization + launch | graph-based SLAM, continuous re-localization. mirror basin 회피 | apt install + integration 학습 | 1~2 시간 |
| ★★ | sigma_hit 0.2 → 0.05 | `nav2_params.yaml` amcl 섹션 | Likelihood field sharp → wrong basin attractor 약화 | scan noise 민감 증가 | 5분 |
| ★★ | alpha1~5 0.05 → 0.01 | 동상 | Motion noise 최소 → wrong jump 진폭 감소 | 실 robot wheel slip 시 underestimate | 5분 |
| ★★ | controller xy_goal_tolerance 0.25 → 0.05 | controller_server.general_goal_checker | controller "Reached" 거짓 판정 차단 → cmd_vel 계속 발행 → robot 이동 | 실제 도착 판정 늦음 | 5분 |
| ★ | spawn 카페 중앙 (-41, 0) 이동 | launch_mapv5_moca + cafe_layout.yaml + nav2_params.yaml + mode_manager home | 4방 scan 풍부 → AMCL ambiguity 해소 | sim 만 — 실 운영 dock NE 코너 보존 | 30분 |
| ★ | SLAM Toolbox 교체 | cartographer 대안 | 비슷한 효과 | 동상 | 1 시간 |
| ✗ | recovery_alpha 다시 활성 | A patch revert | 시도 (기존 default) | wrong basin recovery 가 wrong jump 트리거 (검증됨) | — |
| ✗ | initial_pose 좌표 변경 | nav2_params.yaml | 시도 (12cm 차이) | root cause 아님 (H3 기각) | — |

---

## 11. 다음 세션 진입 체크리스트

### 11.1 현 상태 (2026-05-17 종료 시점)

- ✓ 5 patches 영구 적용 (A+B+C+D+E)
- ✓ 회고 + 메모리 3건 + CLAUDE.md M4+ 갱신 완료
- ✓ 시뮬 가동 중 (사용자 본인 작업 시 그대로, 종료 시 `bash scripts/stop_sim.sh`)
- ✗ 영상 촬영 불가 (AMCL drift 잔존)

### 11.2 다음 세션 시작 시 확인할 것

1. **§0-A 상태** — 팀 작업 중인가? 사용자가 RPi 사용 OK 명시했는가?
2. **현 patch 영구 적용 상태** — `git status` + `git log -1` 로 확인
3. **시뮬 가동 여부** — `pgrep -af "gz sim|ros2 launch moca"`. 가동 중이면 §11.3 즉시 검증 가능.
4. **본 회고 + 메모리 [[project_amcl_drift_sim_limitation]] 읽기**

### 11.3 다음 세션 실 작업 흐름 (선택지별)

**경로 A — RPi 라이브 (§0-A 해제 받은 경우):**
1. `ssh vic@192.168.0.138` 연결 검증
2. `~/cabot` 잔재 확인 (§0 위반 없는지)
3. RPi vic_pinky 측 vicpinky_navigation 의 nav2_params 확인 (PC 측 patch 와 동일한지 결정)
4. PC 에서 DOMAIN=22 + STATIC_PEERS 설정 + dashboard 가동
5. 실 spawn 위치 robot 두기 + /initialpose RViz 수동
6. patrol 1회 실 검증 + 영상 촬영

**경로 B — sim cartographer 교체:**
1. `sudo apt install ros-jazzy-cartographer-ros ros-jazzy-cartographer-rviz`
2. `src/moca_navigation/launch/localization_launch.xml` 의 amcl → cartographer 교체
3. cartographer config 작성 (carto.lua) — 카페 layout 맞춤 튜닝
4. nav2_params.yaml amcl 섹션 제거 (또는 disable)
5. sim restart + 검증

**경로 C — sim deeper patches (가벼움):**
1. nav2_params.yaml amcl 섹션 patch:
   - `sigma_hit: 0.2 → 0.05`
   - `alpha1~5: 0.05 → 0.01`
2. nav2_params.yaml controller_server.general_goal_checker:
   - `xy_goal_tolerance: 0.25 → 0.05` (yaw_goal_tolerance 도 동상)
3. sim restart + Nav2 sweep 검증
4. 효과 없으면 경로 B 또는 경로 A 로 escalate

**경로 D — spawn 카페 중앙 이동 (sim 데모만):**
1. `config/cafe_layout.yaml` `pinky_spawn` + `pinky_home` 좌표 변경 (-41, 0 부근, 가구 충돌 회피)
2. `src/moca_gazebo/launch/launch_mapv5_moca.launch.xml` spawn_x/y 동기화 또는 cafe_layout SoT 로 분기
3. `nav2_params.yaml` amcl.initial_pose 동기화
4. mode_manager 의 home 좌표 동기화 (`src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py` 또는 config)
5. sim restart + 검증
6. 단점 명시 — 실 운영 dock 위치 변경 X (분기 처리 필요)

### 11.4 회귀 검증 명령 (어느 경로든 마지막)

```bash
cd ~/moca
ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1 bash -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
# 1. AMCL pose vs Gazebo pose 비교 (drift < 0.3m 이면 fix 성공)
timeout 2 ros2 topic echo --once /amcl_pose | grep -E "x:|y:|w:" | head -5
gz model --model pinky | grep -A 1 "^  - Pose" | tail -1

# 2. NavigateToPose T01 단발 (-37.12, 0.543)
QZ=$(python3 -c "import math; print(math.sin(-1.571/2))")
QW=$(python3 -c "import math; print(math.cos(-1.571/2))")
timeout 60 ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: -37.12, y: 0.543, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: '"$QZ"', w: '"$QW"'}}}}"

# 3. Goal SUCCEEDED + Gazebo robot 가 실제 T01 도달 (gz model --model pinky) 확인 둘 다 통과 시 성공.
'
```

**성공 기준:** Goal SUCCEEDED + Gazebo robot 가 T01 (-37.12, 0.543) 근처 도달 (오차 0.3m 안) + AMCL pose 가 robot 과 일치 (drift X).

**실패 패턴 (본 세션 관찰):** Goal SUCCEEDED 거짓 보고 + robot 1cm 만 이동 + AMCL pose 가 wrong basin 으로 jump.

---

*다음 갱신: 다음 세션에서 §11.3 경로 선택 결과 + 회귀 검증 결과 반영*
