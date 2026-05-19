# 2026-05-17 — DB schema 초안 + floorplan 동적 마커/사각형/yaw + waypoints/gates

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `2026-05-17_ui_polish_floorplan_clock.md` (오전 — UI 정리, floorplan tview.png 정적 교체)
> 본 회고: 오후~저녁 — DB 설계 + floorplan 동적 마커 복구 + 시뮬 검증 + 사각형/waypoints/gates 통합
> 커밋: `77ead68`, `c15c9c3`, `5ecd2e2` (3건)

---

## 1. 본 세션 범위

오전 회고 (UI 정리) 후 오후 사용자가 어제 회고 + 본 세션 KPI 영구 DB 항목 진입. 두 트랙 묶음:

| 트랙 | 작업 |
|---|---|
| **A. DB 설계** | `docs/moca_db_schema.md` v0.1 초안 + `CLAUDE.md §10 M4+ ToDo` (PG 설치 추후 연기) |
| **B. floorplan 동적 마커 복구** | tview.png 위 SVG overlay + 좌표 affine + store 바인딩 |
| **C. MAP 편집 버튼** | dashboard → REST → `place_furniture_picker.py` subprocess |
| **D. AMCL pose 통합** | opserver `/amcl_pose` 구독 — map frame 우선, /odom fallback |
| **E. tables.yaml + picker sync** | T01~T05 정차 좌표 + waypoints/gates 섹션 + 사각형 마커 + yaw 회전 |
| **F. Doby/DDooby 상태 헤더** | `<robot-status>` Web Component — SAFE 옆 2 robot Online/Offline 표시 |

## 2. 산출물 누적

### 2.1 DB schema (commit 77ead68)

`docs/moca_db_schema.md` v0.1 (677줄):

- **엔진**: PostgreSQL 16 on 5090 (192.168.0.133, NTP master 와 일관)
- **3 DB 분리** — `moca_orders` (ACID 5년 / 한국 세법) / `moca_telemetry` (1년) / `moca_kpi` (무기한)
- **14 테이블** — orders + payments / events + mode_transitions + rapport_events + minigame_results + patrol_runs + table_reports + guiding_runs + safety_events + utter_log / daily/weekly/monthly_summary + table_kpi
- **ROS msg ↔ DB 매핑** 매트릭스 + down-sampling 규칙
- **인덱스/파티셔닝** — `events` 만 월별 RANGE (pg_partman)
- **보존/백업/PII** — pg_dump nightly + WAL archiving + 5년 보존 + USB 반출 (점주 폐업)
- **library** — asyncpg + Alembic, reporter_node 분리안
- **10 미해결** — D1 (sim 분리 정책), D2 (snapshot 보존), D3 (TimescaleDB), D4 (replica), D8 (reporter 위치) 등

`CLAUDE.md §10` 에 **M4+ ToDo 섹션** 추가 — DB 협의 ⏸ + floorplan 동적 마커 + alarm_dwell + cache busting + NTP 6대 + 라이트 테마 + i18n.

**5090 PG 실 설치는 연기** (사용자 결정) — 본 문서가 설계 SoT, 인프라는 별 트랙.

### 2.2 floorplan 동적 마커 1차 (commit c15c9c3)

`floorplan-view.js` 통째 rewrite:
- SVG viewBox 1251×788, tview.png image href + 마커 4종
- **6점 affine → 5점 affine** 재계산 (HOME outlier 제외, 잔차 ±10px → **±2px**)
  ```
  px = 82.2331*x + 2.5426*y + 4010.7028
  py = -0.8722*x - 79.5863*y + 374.5820
  ```
- HOME 마커 — 소문자 `home` 라벨 박스 직접 (965, 174). affine 안 맞음 (ROS x scale 만 어긋남).
- robot 초기 transform `rotate(90)` — home_pose yaw=-π/2 (남쪽) 정합

`components.css`:
- `.fp-home / .fp-table-{empty/occupied/finished/unknown} / .fp-robot-*`
- `.card-head-flex` + `.btn-map-edit` (핫핑크)

`rest_api.py`:
- `POST /api/v1/launch/map_picker` — `subprocess.Popen(scripts/place_furniture_picker.py)` + DISPLAY env fallback + pgrep 중복 가드 + start_new_session

`dashboard.html`:
- 평면도 카드 h3 flex 헤더 + "MAP 편집" 버튼 + 토스트 + 디바운스

### 2.3 사용자 라이브 검증 + Gazebo 시뮬

`bash scripts/run_sim.sh --no-rviz --cleanup` 풀스택:
- Gazebo + Nav2 + dashboard 자동 기동
- `POST /mode patrol` → 5 테이블 sweep + robot 마커 이동
- `gz service /world/mapv5_moca/set_pose` + `/initialpose` 로 T01→T05→HOME 순환 teleport (사용자 시각 검증)
- AMCL pose 각 위치 5-10cm 오차 (정상)

**root cause 발견** — opserver 가 `/odom` (odom frame) 만 구독해서 robot 가 home_pose 에 있어도 좌표 (0,0) 표시. floorplan affine 은 map frame 기준이라 마커 home 라벨 옆 안 옴.

**Fix**: opserver `/amcl_pose` 구독 추가 (commit 5ecd2e2):
```python
def _on_amcl_pose(self, msg: PoseWithCovarianceStamped):
    ...
    self._has_amcl_pose = True
# _on_odom: if self._has_amcl_pose: return  # AMCL 우선
```

### 2.4 사용자 picker 등록 → sync (commit 5ecd2e2)

사용자가 MAP 편집 버튼 + picker 로 T01~T05 좌표 재등록 (실 robot 정차 pose):
- T01: (-37.12, 0.543, yaw=-π/2)
- T02: (-40.303, -0.591, yaw=+π/2)
- T03: (-40.287, 0.276, yaw=+π/2)
- T04: (-45.653, 0.276, yaw=-π/2)
- T05: (-45.67, -0.557, yaw=-π/2)

→ `tables.yaml` + `floorplan-view.js TABLES` 양쪽 sync, `approach_dist=0.0` (좌표 자체가 정차 pose).

사용자가 tview.png 라벨 swap fix (T02/T03 텍스트 정정) 도 업로드 — `src/.../static/assets/tview.png` 카피.

### 2.5 사각형 마커 + yaw 회전 (commit 5ecd2e2)

사용자 요청 — 모든 마커 사각형 + 색상 보존:
- T01~T05 사각형 (48×36) + yaw 회전 — 정차 방향 시각화
- HOME 사각형 outline (50×38) + yaw=-π/2
- gate1~3 사각형 (18×74, long edge 가 yaw 수직 — 문 폭) — picker 등록값 cafe_layout.yaml sync
- robot 사각형 (30×24, Vic Pinky footprint 비율) + 화살표

`components.css` — `circle → rect` 셀렉터 변경, 색상/glow 토큰 모두 보존, `.fp-gate` 청록 (#00ced1).

### 2.7 Doby/DDooby 상태 헤더 (commit 본 trail)

신규 컴포넌트 `static/components/robot-status.js`:
- `<robot-status name="X" store-key="Y">` Web Component
- store-key 있으면 `store.on(key)` 동적 갱신, 없으면 정적 offline
- DOM 부분 갱신 (cacheKey dedup, 깜박 방지)

7 페이지 헤더 — SAFE 옆에 2 컴포넌트:
- `<robot-status name="Doby" store-key="online">` — Vic Pinky (mode_state 3s timeout 기준)
- `<robot-status name="DDooby">` — OpenARM (store-key 없음, 정적 offline. Phase 3 OMX 통합 시 wiring)

CSS `.robot-status--online` 초록 + glow, `.robot-status--offline` 무광 회색.

**판정 로직**:
- Doby online = `opserver._tick_robot_online` 가 `/mode/state` 마지막 수신 ≤ 3s 면 true → store.online → "Doby Online"
- sim (DOMAIN=99) / 실 통신 (DOMAIN=22) 모두 동작 — mode_manager 가 publish 중이면 자동 online
- DDooby = 영구 offline (지금) — OpenARM 자체 토픽 (`/openarm/heartbeat` 등) 추가 시 store key wiring

사이드바 footer (BATT + 로봇 온라인) 는 보존 — 사용자 의도 (헤더 추가만).

### 2.6 picker B 옵션 + gate (commit 5ecd2e2)

`scripts/place_furniture_picker.py`:
- T01_wp~T05_wp 5 entry — robot 정차 waypoint (model=None, 좌표만)
- gate1/gate2/gate3 3 entry — 출입구 entry point (size=(0.2, 0.9), yaw 수직 long edge, model=None)
- save_yaml — `_wp` suffix → `waypoints` / `gate` prefix → `gates` 섹션 분류
- load_yaml — 양쪽 섹션 추가

사용자가 picker 로 gate1~3 + yaw 등록:
- gate1 (-38.153, -1.757, yaw=-π/2)
- gate2 (-39.353, -1.824, yaw=+π/2)
- gate3 (-45.803, -2.024, yaw=-π/2)

cafe_layout.yaml 의 `gates:` 섹션에 저장됨.

## 3. 발견 / 결정

### 3.1 ★ AMCL pose vs /odom — floorplan 시각 정합

opserver 가 `/odom` (odom frame) 만 구독 → 시뮬에서 robot 가 home_pose 에 있어도 (0, 0) 표시. map frame 좌표가 필요한 floorplan affine 과 정합 X.

**Fix 패턴**: AMCL pose 우선 + odom fallback. `_has_amcl_pose` 플래그.
- Nav2 + AMCL 사용 환경 (시뮬 + 실 운영) — `/amcl_pose` map frame 좌표 사용
- AMCL 없는 환경 (소규모 데모) — `/odom` 그대로 (단 spawn 위치 = map origin 가정)

이 패턴은 [[feedback_dont_touch_working_code]] 정합 — 기존 _on_odom 보존, _on_amcl_pose 추가만.

### 3.2 ★ tables.yaml 좌표 의미 = robot 정차 pose

이전 tables.yaml T01~T05 = 가구 중심 좌표 + `approach_dist=0.5` (dispatcher 가 후방 offset 계산).

본 세션 변경: 좌표 자체 = robot 정차 pose + `approach_dist=0.0`.

장점:
- floorplan 마커 = 정차 위치 직관
- dispatcher 단순화 (보정 계산 0)
- 점주가 yaml 보고 robot 어디 정차하는지 명확

라이브에서 너무 가까우면 사용자가 picker 로 위치 재조정 또는 approach_dist 0.1~0.2 로 늘림.

### 3.3 ★ tview.png 라벨 swap 사고

이전 tview.png — 이미지 안 "T02"/"T03" 라벨 위치가 yaml 좌표와 swap. 사용자가 라벨 텍스트만 swap 해서 재업로드. 박스 위치 보존 → yaml T02 (남쪽) / T03 (북쪽) 새 라벨과 자연스럽게 정합.

### 3.4 ★ picker 의 entry 의미 분리 — B 옵션

picker FURNITURE 의 T01~T05 = cafe_table 가구 모델 위치. 그러나 사용자가 "T01~T05 = robot 정차" 의미로 사용하기 시작 — 가구 시뮬 layout 잘못됨 위험.

**B 옵션 채택**: 별 entry `T01_wp~T05_wp` 추가 — robot waypoint 만 등록 (model=None, Gazebo spawn X). 가구 T01~T05 (cafe_table) 의미는 보존.

저장 분류 추가:
- `_wp` suffix → `waypoints` 섹션
- `gate` prefix → `gates` 섹션

향후 picker 등록 흐름:
1. T01~T05: 가구 cafe_table 위치 (Gazebo 시뮬 layout)
2. T01_wp~T05_wp: robot 정차 좌표 (tables.yaml SoT)
3. gate1~3: 출입구 (engaging BT 사람 감지 ROI anchor)

### 3.5 ★ gate long edge = yaw 수직 (문 폭)

초기 정의 `size=(0.9, 0.2)` — sx=0.9 (long, yaw 방향). 사용자 지적 — 출입문은 long edge 가 통행 방향에 수직 (문 폭).

swap → `size=(0.2, 0.9)` — sx=0.2 (yaw 방향 두께), sy=0.9 (yaw 수직 문 폭). banner B01~B05 패턴 정합.

floorplan-view.js 도 `GATE_W=18, GATE_H=74` (W=두께, H=폭) 으로 명확화.

### 3.6 사각형 마커 + yaw 회전

사용자 요청 — 모든 마커 사각형 + 색상 보존.

장점:
- robot footprint 시각화 (Vic Pinky 30×24 비율)
- yaw 회전 = 정차 방향 직관
- gate long edge 가 문 폭 — 출입구 구조 식별
- circle 보다 정보량 ↑

CSS 변경 영역 — 선택자 `circle → rect`. 색상/glow 토큰 그대로 보존 (`var(--pink-primary)`, `var(--copper)` 등).

### 3.7 [[feedback_dont_touch_working_code]] / [[feedback_relative_path_convention]] / [[feedback_cache_busting_global_bump]] 정합

- opserver_node._on_odom 보존 (fallback) + _on_amcl_pose 추가만
- tables.yaml 변경은 의미 변경 (가구 → waypoint) — dispatcher 동작은 approach_dist=0.0 으로 단순화
- picker FURNITURE/ORDER/save/load — 기존 동작 (가구 T01~T05) 그대로, 신규 entry 추가만
- 7 페이지 `?v=20260517j → n` 일괄 (n = nav2 시뮬 + gate fix)
- 절대경로 0건

## 4. 빌드 / 검증 명령

```bash
# 빌드 (clean 권장 — 신규 자산 등록 시)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  colcon build --packages-select moca_opserver dobi_npc_bringup --symlink-install
'

# 시뮬 풀스택
bash scripts/run_sim.sh --no-rviz --cleanup    # Gazebo + Nav2 + dashboard

# 라이브 patrol 트리거
curl -X POST http://localhost:8800/api/v1/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"patrol","override_priority":true}'

# 수동 robot teleport (시각 검증)
gz service -s /world/mapv5_moca/set_pose --reqtype gz.msgs.Pose \
  --reptype gz.msgs.Boolean --timeout 2000 \
  --req 'name: "vicpinky", position: {x: -37.12, y: 0.543, z: 0.0}, ...'
ros2 topic pub --once /initialpose ...   # AMCL re-localize

# 시나리오 회귀 (130 unit + 17 시나리오)
python3 -m pytest src/moca_opserver/test/ src/dobi_npc/dobi_npc_bringup/test/
```

## 5. 다음 단계

### 5.1 즉시
- 일일 백업 (`~/backup/moca_daily_20260517/`) — 작업 종료
- 라이브 patrol 자연 sweep 확인 — robot 정차 좌표 (approach_dist=0.0) 가 안전한 위치인지 시각 검증

### 5.2 M4 (다음 마일스톤)
- **DB schema 팀 협의** ⏸ — D1 (sim 분리) 등 5+ 미해결 결정
- **5090 PostgreSQL 설치** (별 인프라 트랙)
- **engaging BT + gate 통합** — gate1~3 좌표 anchor 로 사람 감지 ROI, IDLE → APPROACH 트리거 조건
- **alarm_dwell teardown 최적화** — pytest 시나리오 ensure_idle 7s 누적
- **cache busting 자동화** — Makefile or build hook

### 5.3 후속 사용자 작업 (picker 추가 등록 시)
- 가구 cafe_table T01~T05 위치 재조정 (현 cafe_layout 의 T 좌표 = waypoint 의미로 잘못 사용된 결과 복구)
- L01~L05 / P01~P05 등록 (lights/plants, Gazebo 시뮬 풍부화)

## 6. 메모리 갱신

기존 메모리 정합 확인:
- `[[feedback_dont_touch_working_code]]` ✅
- `[[feedback_relative_path_convention]]` ✅
- `[[feedback_cache_busting_global_bump]]` ✅ (7 페이지 ?v= 일괄)
- `[[feedback_new_static_asset_needs_rebuild]]` ✅ (신규 자산 X — tview.png 기존 파일 갱신만)
- `[[feedback_starlette_symlink_install]]` ✅
- `[[project_m3_dashboard_complete]]` ✅ (M3 dashboard 확장 — gate/waypoint 마커)
- `[[project_navigation_code_separation]]` ✅ (opserver 가 cmd_vel publisher 추가 X, /amcl_pose 구독만)
- `[[feedback_no_rpi_when_team_working]]` ✅ (시뮬 DOMAIN=99 + LOCALHOST_ONLY=1 만)

본 작업으로 신설 메모리 후보:
- (보류) `opserver_amcl_pose_priority` — opserver `/amcl_pose` 우선 + /odom fallback 패턴. M4 진입 시 다른 노드도 같은 패턴 적용 시점에 memory 화

## 7. 변경 통계

| 영역 | 파일 | 변경 |
|---|---|---|
| Docs | `docs/moca_db_schema.md` | 신규 (677줄) |
| Docs | `CLAUDE.md §10` | M4+ ToDo 7 항목 추가 |
| Backend | `moca_opserver/opserver_node.py` | `/amcl_pose` 구독 + `_has_amcl_pose` fallback |
| Backend | `moca_opserver/rest_api.py` | `POST /api/v1/launch/map_picker` 신규 |
| Frontend | `static/components/floorplan-view.js` | 통째 rewrite (사각형 마커 + yaw + gates) |
| Frontend | `static/css/components.css` | `.fp-*` circle → rect + `.fp-gate` + `.card-head-flex` + `.btn-map-edit` |
| Frontend | `static/pages/dashboard.html` | flex 헤더 + MAP 편집 버튼 + 토스트 |
| Frontend | `static/pages/*.html` × 7 | `?v=20260517j → n` 일괄 |
| Config | `src/dobi_npc/dobi_npc_bringup/config/tables.yaml` | T01~T05 좌표/yaw sync + approach_dist=0.0 |
| Config | `config/cafe_layout.yaml` | 사용자 picker 등록 (waypoints + gates) |
| Scripts | `scripts/place_furniture_picker.py` | T01_wp~T05_wp + gate1~3 entry + 섹션 분류 |
| Assets | `src/moca_opserver/static/assets/tview.png` | 사용자 라벨 swap fix |

3 커밋 (77ead68 docs + c15c9c3 markers/picker + 5ecd2e2 final). 빌드 무회귀 (5+ 회 colcon build moca_opserver). 라이브 검증 통과 — Gazebo 풀스택 + patrol sweep + teleport 순환.

---

## 8. 영상 촬영 시도 + AMCL drift 진단 (저녁 trail)

본 세션 종료 후 사용자가 dashboard 모드 제어 → Gazebo 실 robot 영상 촬영 요청.
`scripts/run_demo_scenario.sh` (5 모드 자동) + `scripts/record_demo.sh` (ffmpeg x11grab + 시나리오) 작성.

### 8.1 1차 시나리오 검증 — OK
- patrol 120s + serving 38s + guiding 12s + engaging 10s + emergency_stop 5s 모두 정상 idle 복귀
- AMCL pose 변화 + mode 전이 + 발화 정상

### 8.2 2차 동일 시나리오 — **재현성 실패**
- patrol OK (114s)
- **serving 90s timeout** — current=serving 영구 유지
- guiding 진입 못 함 (serving 큐잉)
- 사용자 시각 — robot 마커가 평면도 **벽 위** 표시

### 8.3 Root cause 진단 — AMCL localization 발산
- Gazebo robot 실 model name = `pinky` (아닌 `vicpinky` — 이전 reset 시도 `name="vicpinky"` 가 noop 이었음)
- AMCL pose vs Gazebo 실 pose 동시 비교:
  - t=10s: AMCL (-37.13, 1.06) vs Gazebo (-36.91, 2.74) → diff 1.69m
  - t=24s: diff 4.23m
  - t=38s: diff 4.42m → idle 복귀
- **Gazebo robot 거의 안 움직임 (38s 동안 18cm)**. cmd_vel 발행자 6개인데 hz=0 — Nav2 가 path planning 실패 → cmd_vel 안 보냄
- AMCL 가 발산 — Gazebo robot 실 정지인데 추정 위치 매번 (-40, -1.7) 영역 (벽 영역) 으로 수렴

### 8.4 C-1 AMCL params patch — 효과 미미

`src/moca_navigation/params/nav2_params.yaml` (실 사용 yaml — `vicpinky_navigation` 측은 사용 X 지만 정합 위해 같이 patch):
- alpha1~5: 0.2 → **0.05** (시뮬 wheel slip 없음 적합)
- min_particles: 500 → **2000**, max_particles: 2000 → **4000**
- recovery_alpha_slow: 0 → **0.001**, recovery_alpha_fast: 0 → **0.1**

런타임 적용 확인됨. 그러나 patrol 1회 재시도 시 AMCL drift 패턴 동일 — params 변경 무관, 더 깊은 root cause.

### 8.5 진짜 Root cause 추정 — Gazebo wall SDF ↔ PGM map 정합 X

매번 AMCL 가 (-40, -1.7) 일관 영역으로 수렴 = scan match 가 그 영역 wall pattern 을 home 위치 wall 로 잘못 인식. Gazebo `mapv5_moca.world` 의 wall placement 가 `mapv5_mocamap.pgm` 의 wall pixel 위치와 일관성 X 가능성.

검증 필요:
1. mapv5_mocamap.yaml 의 origin/resolution 정확성
2. Gazebo wall SDF 좌표 ↔ PGM pixel 변환 정합
3. /scan ↔ map 시각 정합 (RViz `LaserScan` + `Map` overlay)
4. 필요 시 SLAM 재실행하여 새 map 생성 (현 Gazebo world 기준)

### 8.6 결정 (사용자 결정 — E 옵션)

**영상 촬영 보류**. 본 진단 결과 명문화 + 본 회고 trail. 다음 세션에서 Gazebo wall 정합 본격 진단.

### 8.7 후속 ToDo (CLAUDE.md §10 M4+ 추가)

- `[ ]` **Gazebo wall ↔ PGM map 정합 진단** — mapv5_moca.world wall SDF + mapv5_mocamap.pgm 비교, RViz LaserScan ↔ Map overlay 검증. 정합 X 면 SLAM 재실행 또는 wall SDF 좌표 조정. 영상 촬영 + Gazebo 데모 전제 조건.

### 8.8 신규 자산

- `scripts/run_demo_scenario.sh` — 5 모드 REST API 자동 (idle/patrol/serving/guiding/engaging/emergency_stop)
- `scripts/record_demo.sh` — ffmpeg x11grab 1920×1080 풀스크린 녹화 + 시나리오 호출 wrapper. 출력 `~/moca/recordings/demo_TS.mp4`. AMCL 정합 후 재사용 가능.

---

*다음 갱신 — Gazebo wall 정합 진단 + 영상 촬영 재시도*
