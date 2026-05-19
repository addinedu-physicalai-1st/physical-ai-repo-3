# 2026-05-15 Gazebo 후속 — map 중앙 정렬, 키오스크 신규, 바닥 타일링, OpenARM 50% 증고

오전 스냅샷 (`2026-05-15_gazebo_cafe_layout_snapshot.md`) 이후 오후 세션 회고.
사용자가 `mapv5_mocamap.pgm` 을 다듬어 + 중앙 정렬, 키오스크/바닥/OpenARM 외형 갱신 요청.

## 1. mapv5_mocamap.pgm 재생성 → walls 메쉬 갱신

- 사용자가 PGM 다듬음 → `scripts/pgm_to_walls_stl.py maps/mapv5_mocamap.pgm \
  src/moca_gazebo/models/mapv5/meshes/walls_high.stl` 로 재생성.
- 갱신: occupied 3767 → 3968 px, triangles 8604 → 5688 (가로 인접 run-merge 효율 ↑).
- 이전 메쉬 `old/walls_high_before_20260515.stl` 백업.

## 2. 맵 중앙 정렬 → 가구/램프/spawn 일괄 shift

사용자가 PGM 의 wall 컨텐츠를 이미지 중앙으로 이동. bbox 중심 비교로 순수 translation 측정:

| 측정 | dx_px | dy_px | world Δ (dx, dy) m |
|---|---|---|---|
| bbox 중심 (이미지 차원 동일 → 신뢰) | -52.5 | -39.5 | **(-2.625, +1.975)** |
| 무게중심 (벽 밀도 영향) | -61.0 | -24.0 | (-3.052, +1.202) |

`mapv5_moca.world` 의 가구 + 램프 + launch xml spawn 모두 (-2.625, +1.975) 일괄 적용:

| 항목 | 이전 | 변경 |
|---|---|---|
| bar_counter | (-33.387, 0.826) | (-36.012 → 후일 picker 재저장 -36.070, 2.793) |
| open_arm | (-33.787, 1.359) | (-36.420, 3.276) |
| T01 | (-33.553, -1.424) | (-36.337, 0.526) |
| T02 | (-38.353, -2.374) | (-41.037, 0.243) |
| T03 | (-38.353, -1.641) | (-41.037, -0.574) |
| T04 | (-42.237, -1.757) | (-44.903, 0.243) |
| T05 | (-42.270, -2.524) | (-44.903, -0.507) |
| pinky_spawn (launch xml) | (-34.303, 0.893) | (-36.937, 2.893) |
| lamp_main_1 | (-46.0, -2.0) | (-48.625, -0.025) |
| lamp_main_2 | (-37.0, 1.0) | (-39.625, 2.975) |

유지 (이미지 frame 자체에 묶임): `model://mapv5` include pose, floor_grid pose, sun pose, GUI
camera_pose, YAML origin.

## 3. moca_decal 모델 (신설 → 제거)

- 신설: `models/moca_decal/` — 금빛 PBR 데칼 3장 (북벽/동벽/T02~T05 홀 바닥)에
  `mocadesign.png` (PNG aspect 276:121) 적용.
- 사용자 검토 결과 "위치가 모두 원하는 위치가 아니야" → world 의 `<include>` 라인만 제거.
  **모델 디렉터리는 보존** (`src/moca_gazebo/models/moca_decal/` 그대로) — 추후 위치
  재조정해 다시 부를 수 있음.

## 4. 키오스크 신규 — picker + SDF 모델

### picker 업데이트 (`scripts/place_furniture_picker.py`)

- `FURNITURE["kiosk"]` 추가: size (0.5, 0.4), color `#00bcd4` (teal — 기존 5색과 미충돌),
  z=0.0, label/model `kiosk`.
- `ORDER` 리스트의 `open_arm` 뒤 / `pinky_home` 앞에 삽입 (실가구 묶음).
- 사용자가 picker 로 배치 → Save → `config/cafe_layout.yaml` 의 `kiosk`:
  `(-35.520, 3.409, yaw=-1.571 rad)` (yaw=-π/2 → 모델 +x 화면이 -y=실내/홀 방향 향함).

### SDF 모델 (`models/kiosk/`) — 반복 수정 후 최종 v4

| 버전 | 총높이 | 화면 | 비고 |
|---|---|---|---|
| v1 | ~1.47 m | landscape 0.46 × 0.36 + mocadesign 금빛 emissive | 초기 |
| v2 | 0.50 m | 단색 navy | "벽 높이로" 지시 (즉시 v3 으로 대체) |
| v3 | 1.00 m | landscape 0.46 × 0.28, 단색 navy | mocadesign 제거 |
| v4 | 1.00 m | **portrait 0.26 × 0.46 (9:16)** | "세로로 길게" — 최종 |
| v5 | 1.00 m | 듀얼 portrait (footprint Y 0.40→0.70) | 롤백 ("키오스크가 2개 존재") |

**최종 v4 구조** (footprint 0.50 × 0.40 m, 총높이 1.00 m, +x = 화면면):

| Link | z_center | size (X×Y×Z) m | 충돌 |
|---|---|---|---|
| base | 0.040 | 0.500 × 0.400 × 0.080 | O |
| column | 0.290 | 0.080 × 0.300 × 0.420 | O |
| housing | 0.750 | 0.060 × 0.300 × 0.500 | O |
| screen | 0.750 | 0.005 × 0.260 × 0.460 | X (visual only) |
| bezel L/R | 0.750 (y=±0.140) | 0.006 × 0.012 × 0.480 | X (시안 글로우) |

`materials/textures/` 디렉터리 + `mocadesign.png` 도 v3 단계에서 제거 (단색 다크 네이비 +
시안 베젤 글로우).

## 5. 바닥 텍스처 — bottom.png + UV 타일링

- `bottom.png` (548×541 RGBA) 를 `floor_grid/textures/` 로 복사. 이전 `grid.png` 는
  `old_grid_20260515.png` 로 백업.
- 처음엔 box 에 stretched 적용 → 사용자 "원본 비율로 복수개 채우기" 요청.
- 박스 → **OBJ 메쉬** 로 전환: `meshes/floor_plane.obj` (19.55 × 12.50 m 평면, +z normal,
  UV `[0, 19.55] × [0, 12.50]` → 1.0 m 당 한 번 반복 = 약 20 × 12 회 타일링).
- MTL 동봉 (`floor_plane.mtl`) — OBJ 머티리얼 경고 해소용. SDF `<material><albedo_map>`
  이 최종 우선.
- 충돌은 가벼운 박스 그대로 (mesh collision 회피).

## 6. OpenARM 모델 +50% 증고

- 사용자 "OpenARM 높이가 너무 낮아. 50% 추가" → 모든 Z (`<pose>` z + `<box> size_z` +
  `<cylinder> length`) **×1.5 스케일**. 스피어/작은 logo cylinder 직경/두께는 보존
  (비례 유지).
- 총높이 **0.55 m → 0.825 m**. 컬럼 0.42 → 0.63, shoulder_block z 0.50 → 0.75.
- 배치 좌표 유지 (-36.420, 3.276). 베이스 패드 하단이 floor (z=0) 에 그대로 닿음.

## 7. 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `maps/mapv5_mocamap.pgm` | 사용자 정돈 + 중앙 정렬 |
| `src/moca_gazebo/models/mapv5/meshes/walls_high.stl` | 재생성 (이전본 backup) |
| `src/moca_gazebo/models/mapv5/meshes/mesh_info.txt` | 메타 갱신 |
| `src/moca_gazebo/worlds/mapv5_moca.world` | 가구 7 + spawn + 램프 2 shift, kiosk include, decal include 추가→삭제 |
| `src/moca_gazebo/launch/launch_mapv5_moca.launch.xml` | spawn pose 2회 갱신 |
| `src/moca_gazebo/models/kiosk/` | 신규 (model.config + model.sdf, 5회 수정) |
| `src/moca_gazebo/models/moca_decal/` | 신규 (보존, world include 만 제거) |
| `src/moca_gazebo/models/floor_grid/textures/bottom.png` | 추가 (root 사본) |
| `src/moca_gazebo/models/floor_grid/textures/old_grid_20260515.png` | 이전 grid backup |
| `src/moca_gazebo/models/floor_grid/meshes/floor_plane.obj` + `.mtl` | 신규 (UV 1m 타일) |
| `src/moca_gazebo/models/floor_grid/model.sdf` | box → mesh |
| `src/moca_gazebo/models/open_arm/model.sdf` | Z ×1.5 일괄 |
| `scripts/place_furniture_picker.py` | kiosk FURNITURE/ORDER 항목 |
| `config/cafe_layout.yaml` | picker save (가구 7 + 키오스크) |
| `mocadesign.png`, `bottom.png` | root 에 사용자 업로드 (작업 입력) |

## 8. 후속 / 미해결

- `dobi_npc_bringup/config/tables.yaml` 의 서빙 waypoint 좌표 미동기화 — 가구가 (-2.625, +1.975) 시프트되었으므로 라이브 진입 전 sync 필요.
- `moca_decal` 모델은 보존만 — 위치 재조정 후 재include 시 재사용.
- 바닥 1 m 타일이 시각적으로 너무 작/크면 OBJ 의 UV 스케일 조정 (현재 image-space `[0, 19.55] × [0, 12.50]`).
- v4 키오스크 collision 은 housing/column/base 만 — 베젤/screen 은 visual only (Nav2 obstacle 처리 시 사소한 차이).
- `mocadesign.png` (root) 는 decal 모델 안에 사본 있음. 위치 재배치 결정 보류 중이라 root 파일 유지.

## 9. 참고 명령

```bash
# 가제보 (격리 도메인)
ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1 \
  ros2 launch moca_gazebo launch_mapv5_moca.launch.xml

# 가구 picker
python3 scripts/place_furniture_picker.py

# PGM 정돈 후 wall 메쉬 재생성
python3 scripts/pgm_to_walls_stl.py maps/mapv5_mocamap.pgm \
  src/moca_gazebo/models/mapv5/meshes/walls_high.stl
```

## 10. 관련 메모리 / 문서

- `docs/daily/2026-05-15_gazebo_cafe_layout_snapshot.md` — 오늘 오전 (좌표 동결 + 외형
  갱신)
- `docs/daily/2026-05-14_gazebo_cafe_layout.md` — 어제 picker 배치 설정 원본
- [[feedback_terminology_mogaek]] — 새 docs 는 "모객" 사용 (본 회고는 카페 인테리어/시뮬 자산이라
  모객/호객 어휘 없음)
- [[feedback_dont_touch_working_code]] — 외부 패키지 vicpinky_description 미수정, 본 작업 모두
  moca_gazebo 내부에 한정

---

## 11. 추가 — 월드 동결 지시 + 광고 배너 신설 (16~17시 추가 작업)

### 11.1 사용자 동결 지시

§7 작업 (kiosk v4 / 바닥 UV 타일 / OpenARM ×1.5 / 데칼 제거 / 가구 sync) 완료 후 사용자
"현재 월드의 설정 값들은 변경 안되도록 잘 유지해줘" → 메모리 영구화:

- [[feedback_freeze_gazebo_world_20260515]] — `mapv5_moca.world` / `launch_mapv5_moca.launch.xml`
  / kiosk·banner·floor_grid·open_arm·mapv5 SDF / `cafe_layout.yaml` / picker FURNITURE 의
  SoT 값들 임의 변경 금지. 사용자 명시 지시 한정.
- `MEMORY.md` 에 인덱스 등재.

### 11.2 광고 배너 신규 — roll-up 자립형

사용자 "광고 천들을 벽면에 두르고 싶어" → 정정 "벽면 앞에 세우는 방식". 자립형 X 배너 패턴.

**입력**: `~/moca/mocanewdesign.png` (487×385 RGBA, aspect 1.27:1).

**신규 모델** `src/moca_gazebo/models/banner/`:
- `model.config` + `model.sdf`
- `materials/textures/mocanewdesign.png` (root 사본)

구조 (+x = 광고면, footprint 0.40 × 1.00 m, 총높이 1.325 m):

| Link | z_center | size (X×Y×Z) m | 충돌 |
|---|---|---|---|
| foot | 0.015 | 0.400 × 1.000 × 0.030 | O (다크 차콜) |
| mast | 0.280 | 0.040 × 0.040 × 0.500 | O (실버 알루미늄) |
| panel | 0.925 | 0.050 × 1.000 × 0.790 | X (visual only, PBR `metalness=0 roughness=0.8` 매트 fabric) |

panel 1.00 × 0.79 → 이미지 487:385 비율 그대로 (왜곡 X).

### 11.3 picker — B01~B05 슬롯 + banners YAML 섹션

`scripts/place_furniture_picker.py`:
- `FURNITURE["B01"~"B05"]`: size (0.4, 1.0), color `#ff7043` (오렌지), label/model `banner`
- `ORDER` 끝에 5개 추가 (T05 뒤)
- `save_yaml` → 신규 `banners:` 섹션 (tables/furniture 와 분리)
- `load_yaml` → `banners` 섹션도 로드

### 11.4 사용자 배치 (B01, B02) → world include

`config/cafe_layout.yaml` `banners:` 섹션 사용자 저장:

| Banner | x | y | yaw (rad) | 위치 의미 |
|---|---|---|---|---|
| B01 | -38.053 | 3.959 | -1.571 (-π/2) | 북벽 (y≈4.176) 앞 22 cm, 홀 중앙 부근 |
| B02 | -35.787 | 3.943 | -1.571 | 북벽 앞 22 cm, bar_counter 가까이 |

둘 다 광고면(+x) = **남쪽 (홀 내부 향함)**.

`mapv5_moca.world` 끝에 `<include name="B01/B02"><uri>model://banner</uri>` 2 라인 추가.
다른 가구 좌표/include 미수정 (동결 준수).

### 11.5 추가 변경 파일

| 파일 | 변경 |
|---|---|
| `src/moca_gazebo/models/banner/` | 신규 (config + sdf + texture) |
| `scripts/place_furniture_picker.py` | B01~B05 FURNITURE/ORDER + save/load banners 섹션 |
| `config/cafe_layout.yaml` | banners: B01, B02 신설 |
| `src/moca_gazebo/worlds/mapv5_moca.world` | B01, B02 include 2 라인 추가 (끝부분) |
| `~/.claude/projects/-home-gjkong-moca/memory/feedback_freeze_gazebo_world_20260515.md` | 신규 메모리 |
| `~/.claude/projects/-home-gjkong-moca/memory/MEMORY.md` | 인덱스 1줄 추가 |
| `mocanewdesign.png` | root 에 사용자 업로드 (작업 입력) |

### 11.6 후속 / 미해결 (§8 에 추가)

- B03~B05 슬롯은 picker 에 준비됨. 사용자가 추가 배치 시 같은 절차로 world 반영.
- 배너 panel 텍스처는 PBR `metalness=0` 매트 fabric. 카페 조명에서 시각 확인 후 emissive 추가 여부 결정.
- 배너 collision 은 foot + mast 만. panel 은 visual only (Nav2 obstacle 우회 가능 — 의도된 trade-off).

### 11.7 신규 SoT — 동결 대상 추가

본 §11 추가 자산도 [[feedback_freeze_gazebo_world_20260515]] 동결 SoT 에 포함됨 (사용자
명시 변경 지시 한정):

- `models/banner/` SDF (1.325 m roll-up X 스타일)
- `cafe_layout.yaml` 의 `banners:` B01, B02 좌표
- `mapv5_moca.world` 끝의 B01, B02 include
- `scripts/place_furniture_picker.py` 의 B01~B05 슬롯 정의
