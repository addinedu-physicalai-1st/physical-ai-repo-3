# 2026-05-14 Gazebo 카페 셋업 — mapv5_mocamap + 가구 배치 + 모델 정비

## 요약

mocamap (사용자 손편집된 SLAM 맵) 을 Gazebo 3D world 의 SoT 로 승격하면서,
카페 가구(bar_counter + OpenARM + cafe_table x5 + vicpinky spawn) 를 picker 기반
워크플로우로 배치. 외형/높이/색상 카페 톤으로 통일.

---

## 핵심 변경

### 1. PGM 자산 (`maps/`)
- `mapv5_mocamap.pgm` — 사용자 손편집된 SLAM raw 가 새 SoT
- 가공 흐름: raw → trinary 정규화(82픽셀 비표준) → isolated noise 제거(46) → 가구 footprint 안 occ 제거(436) → vicpinky-counter 사이 14픽셀 벽 수동 제거
- 백업 보존 (롤백 가능):
  - `old/mapv5_raw.pgm`, `old/mapv5_raw_new.pgm` (raw 원본)
  - `old/mapv5_clean.pgm` (auto-clean 시도본)
  - `old/mapv5_mocamap_before_furniture_cleanup_20260514.pgm`
  - `old/mapv5_mocamap_before_wall_removal_20260514b.pgm`
- 최종 occ: 3,753 픽셀 (4,203 에서 450 감소)
- 미리보기:
  - `_preview/cafe_layout_overlay.png` — 가구 placement 시각 검증
  - `_preview/mocamap_before_after_furniture_cleanup.png` — 좌/우 diff

### 2. STL 추출 도구 복구
- `scripts/pgm_to_walls_stl.py` — 백업본 (`~/moca_05141835/`, `~/moca___/`) 에서 복원.
  5/12 main 롤백 때 삭제된 것으로 추정.
- 사용: `python3 scripts/pgm_to_walls_stl.py <pgm> <stl> [--resolution 0.05] [--wall-height 2.0] [--occ-thresh 50] [--regions <json>]`
- regions JSON 없이 walls_high.stl 단일 mesh 만 생성. walls_low (alcove 영역) 는 model.sdf 에서 link 제거 — mocamap 손편집이 옛 regions 픽셀 좌표와 어긋나서 단순화.

### 3. furniture picker GUI 신설
- `scripts/place_furniture_picker.py` — tkinter PNG 클릭 배치 + yaw 슬라이더 + `cafe_layout.yaml` 저장
- 기능: 가구 9종 (prep_station/open_arm/pinky_home/pinky_spawn/T01~T05) 클릭 → 자동 다음 선택 → yaw 슬라이더 (`0/90°/180°/-90°` 단축 버튼)
- 단축키: `ESC` = 선택 해제, `X` = 현재 배치 삭제, 우클릭 = footprint 안 가구 삭제
- 함정 fix: `tk.Listbox` 의 `exportselection=False` + `ACTIVE 인덱스 폴백` 으로 `Clear current` 작동 (`Button` 클릭 시 selection 잃는 문제)
- 출력: `config/cafe_layout.yaml` (`map:` + `furniture:` + `tables:` 섹션)
- Export `.world snippet` 기능 — SDF `<include>` 라인 클립보드용 popup

### 4. Gazebo 모델 (`src/moca_gazebo/models/`)

#### `prep_station` → `bar_counter` rename
- 디렉토리 mv + `model.config` + `model.sdf` 의 `<model name>` 갱신
- ASCII description (CLAUDE.md §7 함정 회피)

#### `cafe_table`
- 높이 0.74m → 0.20m → **0.40m** (사용자 요청 변경 반영)
- 다리: 우드 → **검정 메탈** (0.10, 0.10, 0.11 ambient)
- 천판: 크림 화이트 유지

#### `bar_counter` (구 prep_station)
- 높이 0.85m → **0.35m**
- 본체: 우드 갈색 → **에스프레소 짙은 갈색** (0.40, 0.28, 0.20)
- 핑크 strip + 흰 상판 유지
- `arm_mount` link 제거 (OpenARM 이 카운터 옆 floor 직립)
- 산수 fix: body z=0.41 → 0.405 (5mm 띄움 잔재 해소), 새 사양은 0.16

#### `open_arm` (이미지 `images/openarm.png` 참고 재작성)
- 5DoF arm 단일 → **양팔 dual-arm** 재작성
- 구성: 베이스 패드(다크그레이) + 알루미늄 양 컬럼(실버) + 핑크 strip 3개(low/mid/high) + 어깨 박스(다크그레이) + 핑크 logo dot + 좌/우 팔(shoulder sphere → upper → elbow sphere → forearm → gripper)
- 총 키 0.55m (bar_counter 0.35m 보다 0.20m 더 높음 — 사용자 요청 충족)
- world z=0.89 → **0** (floor 직립)

#### `mapv5` (벽 mesh)
- `walls_low` link 제거 (mocamap 동쪽 손편집이 옛 regions JSON 무효화)
- `walls_high.stl` 만 사용, display scale 0.25 → 표시 높이 0.5m 유지
- 옛 STL 4종 `old/` 로 백업

### 5. world / launch 동기화
- `mapv5_moca.world` — `cafe_layout.yaml` (21:28 저장본) 좌표로 가구 include 갱신
  - bar_counter: (-33.387, 0.826, 0) yaw=π
  - open_arm: (-33.787, 1.359, 0) yaw=π
  - T01: (-33.553, -1.424, 0) yaw=0
  - T02: (-38.353, -2.374, 0) yaw=0
  - T03: (-38.353, -1.641, 0) yaw=0
  - T04: (-42.237, -1.757, 0) yaw=0
  - T05: (-42.270, -2.524, 0) yaw=0
  - vicpinky_home: 모델 미신설, 좌표 주석만 (-34.370, 0.926, yaw=-π/2)
- `launch_mapv5_moca.launch.xml` — spawn (-34.303, 0.893, **0.05**) yaw=-π/2

---

## 발견 / 회고

### picker 의 yaw 화살표 의미 혼동
사용자가 picker 의 yaw 화살표(가구 정면 표시)를 **로봇 정차 waypoint heading** 으로 해석.
세 옵션 (A: 화살표 의미 명확화 / B: waypoint 별도 입력 단계 추가 / C: 가구 yaw 를
waypoint heading 으로 재정의) 중 **C** 선택 — cafe_table T01~T05 yaw 를 모두 0 으로
통일 후 후속에서 waypoint 도출하는 흐름.

### "여전히 차이가 있어" → 가구↔vicpinky 높이 불일치
가구를 벽 높이(0.5m) 에 맞춘 후에도 vicpinky(~0.20m) 와 시각적 차이 크게 보임.
vicpinky URDF mesh bbox 측정: chassis z=0.147m. 가구를 그 기준으로 재조정:
cafe_table 0.20m → 사용자 추가 요청으로 0.40m (vicpinky 의 2배).

### 가구 떠있음 원인 3가지
1. open_arm world z=0.89 (사용자가 picker 에서 그렇게 저장) — bar_counter 옆 floor 위
   직립이 의도였으므로 z=0 으로 보정
2. bar_counter `counter_body` 의 size 0.81 + z 0.41 의 산수 실수 (5mm 떠있음) —
   z=0.405 로 보정. 새 0.35m 사양은 본체 size 0.32 + z 0.16
3. vicpinky spawn z=0.3 → 동적 모델이라 떨어져 정착하지만 초기 시각상 떠있음.
   0.05 로 줄임 (충돌 회피)

### vicpinky-counter 사이 잔존 벽
가구 footprint cleanup 후에도 두 가구 사이 col=345 (x=-34.045) 의 row 94~107 에
14 픽셀 (0.65m 길이) 수직 벽이 살아있어 시각 충돌. 수동 제거 후 STL 재추출.

### `walls_low.stl` 단순화 결정
원본 mapv5_1 의 regions JSON 이 픽셀 좌표 (rmin/rmax/cmin/cmax) 기반인데, 사용자가
mocamap 동쪽 가장자리를 손편집해 alcove 영역(col 300~391) 픽셀이 바뀜. 옛 regions JSON
재사용 시 alcove low wall 이 의도와 다른 위치 — `model.sdf` 에서 walls_low link 자체
제거하고 walls_high 단일 mesh 로 통일.

### 외부 패키지 정책 vs vicpinky 외형 변경
사용자가 `images/vicpinky.png` (PINKLAB 풍 박스 + 4 코너 알루미늄 컬럼 + 핑크 상판) 참고해서
vicpinky 외형 변경 요청. 그러나 `vicpinky_description` 은 외부 의존 패키지
([[feedback_dont_touch_working_code]]) — 직접 수정 X. 3가지 길 제시 (mesh 교체 / URDF
override / Gazebo material override) — 사용자 결정 보류 상태.

---

## 변경 파일 목록

```
신규:
  config/cafe_layout.yaml
  docs/daily/2026-05-14_gazebo_cafe_layout.md
  scripts/place_furniture_picker.py
  scripts/pgm_to_walls_stl.py  (백업본 복원)
  src/moca_gazebo/models/bar_counter/  (mv from prep_station, sdf/config rename)
  maps/_preview/  (시각 미리보기 PNG 다수)
  maps/old/mapv5_mocamap_before_furniture_cleanup_20260514.pgm
  maps/old/mapv5_mocamap_before_wall_removal_20260514b.pgm

수정:
  maps/mapv5_mocamap.pgm  (auto-clean + cleanup + 1 wall removed)
  src/moca_gazebo/worlds/mapv5_moca.world  (가구 좌표 + bar_counter rename)
  src/moca_gazebo/launch/launch_mapv5_moca.launch.xml  (spawn 좌표/z)
  src/moca_gazebo/models/mapv5/model.sdf  (walls_low link 제거)
  src/moca_gazebo/models/mapv5/meshes/walls_high.stl  (mocamap 기반 재추출, 8436 tri)
  src/moca_gazebo/models/mapv5/meshes/mesh_info.txt
  src/moca_gazebo/models/cafe_table/model.sdf  (0.40m, 검정 다리)
  src/moca_gazebo/models/bar_counter/model.{config,sdf}  (0.35m, 에스프레소, rename)
  src/moca_gazebo/models/open_arm/model.{config,sdf}  (dual-arm 재작성)

삭제 (백업으로 이동):
  src/moca_gazebo/models/mapv5/meshes/old/walls_{high,low}{,_smooth}.stl
  src/moca_gazebo/models/mapv5/meshes/old/mesh_info.txt
```

---

## 미완 / 다음 일정

- [ ] **vicpinky 외형** — `images/vicpinky.png` 참고 PINKLAB 풍 (옵션 a/b/c 미결)
- [ ] **vicpinky_home dock 모델** (Task #3) — OpenARM 옆 작은 dock plate, 카페 톤
- [ ] **Nav2 map_server SoT 갱신** (Task #5) — params/nav2 측 yaml 을 `mapv5_mocamap.yaml`
  로. [[project_map_sot_mapv4]] 메모리 → mapv5_mocamap 갱신
- [ ] **tables.yaml ↔ Gazebo T01~T05 동기화** (Task #6) — `src/dobi_npc/dobi_npc_bringup/config/tables.yaml`
  의 빈 `tables: {}` 를 cafe_layout 좌표로. waypoint heading (옵션 C 도출) 도 결정
- [ ] **picker FURNITURE 의 prep_station → bar_counter rename** — 사용자가 picker 다시
  띄울 시 키 정합. cafe_layout.yaml 의 `prep_station` 키도 동기화.
- [ ] **picker open_arm z 0.89 → 0** — world include 와 정합

---

## 관련 메모리 / 문서

- [[project_map_sot_mapv4]] — SoT 갱신 후속 필요 (mapv4 → mapv5_mocamap)
- [[feedback_dont_touch_working_code]] — vicpinky_description 외부 의존 보존 정책
- [[feedback_daily_backup_routine]] — 일일 백업 (작업 시작 전, 본 작업 시작 시점에서는
  사용자 측 backup 상태 미확인)
- [[feedback_terminology_mogaek]] — 신규 docs 는 "모객" 사용 (본 회고는 시뮬 셋업 중심
  이라 호객/모객 키워드 미등장)
- `docs/daily/2026-05-14_gazebo_design_and_bt_theory.md` — 본 작업 직전 가제보 설계 회고
- `docs/daily/2026-05-14_navigation_sim_setup_and_safeguards.md` — 본 작업 직전 navigation 회고
