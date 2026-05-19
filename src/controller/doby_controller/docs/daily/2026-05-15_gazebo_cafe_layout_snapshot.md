# 2026-05-15 Gazebo 카페 배치 스냅샷 (오전 작업 중간 기록)

본 회고는 2026-05-14 의 mapv5_mocamap 셋업 이후 오늘 색/외형 변경 작업 중 사용자 요청
"가구 배치도 기록" 에 따라 작성. **좌표 동결 (어제 picker 21:28 저장본 그대로)**, 외형
(색/채도/바닥) 만 갱신 중.

## 좌표 SoT

| 항목 | x | y | z | yaw | 비고 |
|---|---|---|---|---|---|
| **map** | `mapv5_mocamap.pgm` 0.05m/px, origin (-51.320, -6.624, 0) | | | | mapv5 raw 손편집 + furniture cleanup + 1 wall 수동 제거 |
| **floor 중심** | -41.545 | -0.374 | -0.01 | — | 19.55 × 12.50 m, 점 그리드 PBR (오전 신규) |
| **bar_counter** | -33.387 | 0.826 | 0.00 | 3.142 (π) | 카운터 정면 = -y 방향 |
| **open_arm** | -33.787 | 1.359 | 0.00 | 3.142 (π) | 카운터 옆 floor 직립 (z=0 보정) |
| **pinky_home** | -34.370 | 0.926 | 0.00 | -1.5708 (-π/2) | tables.yaml home_pose seed |
| **pinky_spawn** | -34.303 | 0.893 | 0.05 | -1.5708 | launch_mapv5_moca.launch.xml 의 spawn |
| **T01** | -33.553 | -1.424 | 0.00 | 0.0 | 카운터 정남 단독 |
| **T02** | -38.353 | -2.374 | 0.00 | 0.0 | 중앙 그룹 남쪽 |
| **T03** | -38.353 | -1.641 | 0.00 | 0.0 | 중앙 그룹 북쪽 (T02 페어) |
| **T04** | -42.237 | -1.757 | 0.00 | 0.0 | 서쪽 그룹 북쪽 |
| **T05** | -42.270 | -2.524 | 0.00 | 0.0 | 서쪽 그룹 남쪽 (T04 페어) |

## 가구 모델 / 색상 (본 회고 시점)

| 모델 | 크기 (m) | 부위 | 색상 (ambient RGB) |
|---|---|---|---|
| **cafe_table** | 0.7 × 0.7 × 0.40 | top (천판) | 비비드 블루 (0.15, 0.35, 0.85) — 오전 채도 boost |
| | | legs 4 (0.04³ × 0.37) | 짙은 navy (0.05, 0.10, 0.45) |
| **bar_counter** | 1.2 × 0.6 × 0.35 | body | 비비드 핑크 (1.0, 0.35, 0.55) — *오늘 작업 중 화이트 환원 예정* |
| | | top (상판) | 비비드 핑크 (body 와 동일) — *환원 예정* |
| | | accent strip | strong pink (0.95, 0.20, 0.45) |
| **open_arm** | 0.55m 총 키, dual-arm | base pad | 다크그레이 |
| | | aluminum columns | 실버 |
| | | pink strips 3개 | 핑크 |
| | | shoulder/forearm | 다크그레이 + 핑크 accent |
| **mapv5 walls** | extrude 0.5m 표시 높이 | walls_high.stl | 짙은 회색 (0.30, 0.30, 0.30) — 오전 변경 (0.7 → 0.3) |
| **floor_grid** ⭐ 신규 | 19.55 × 12.50 × 0.02 | albedo_map | grid.png (977×625, 0.5m 간격 점, 옅 회색 190/255) |
| **vicpinky** (URDF) | 0.629×0.500×0.147 mesh + 0.087 z_offset | base_link mesh | PinkLAB 원본 (현재 작업 중: 짙은 핑크 + 카운터 높이 riser 추가) |

## 본 회고 작성 시점까지 오전 변경

1. **`docs/daily/2026-05-15_gazebo_cafe_layout_snapshot.md`** 신규 (본 파일)
2. **`src/dobi_npc/dobi_npc_bringup/config/tables.yaml`** — frame mapv4→mapv5_mocamap, T01~T05 + home_pose 시드 (cafe_layout.yaml 동기화)
3. **`src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/serving_dispatcher_node.py`** 신규 (G-4 백업본 복원)
4. **`src/dobi_npc/dobi_npc_bringup/launch/mode_serving.launch.py`** stub → 본 구현
5. **`src/dobi_npc/dobi_npc_bringup/setup.py`** — `serving_dispatcher` entry_point 추가
6. **`src/dobi_npc/dobi_npc_bringup/package.xml`** — `nav2_msgs` exec_depend 추가
7. **`src/moca_gazebo/models/cafe_table/model.sdf`** — top 블루 / legs navy (채도 boost)
8. **`src/moca_gazebo/models/bar_counter/model.sdf`** — body+top 비비드 핑크 / strip strong accent (*환원 예정*)
9. **`src/moca_gazebo/models/mapv5/model.sdf`** — walls 회색 0.7 → 0.3
10. **`src/moca_gazebo/models/floor_grid/`** 신규 — model.config + model.sdf + textures/grid.png
11. **`src/moca_gazebo/worlds/mapv5_moca.world`** — 인라인 floor 제거 → `<include>` floor_grid

## 본 회고 작성 시점 직후 작업 예정

- **bar_counter 화이트 환원** (오전 변경 되돌리기 — body/top 백색 톤, strip 은 그대로 핑크 accent 유지 가능)
- **vicpinky riser** — 짙은 핑크 박스 (0.5 × 0.4 × 0.132m, base_link z=0.131 위 부착) → 총 높이 0.35m 카운터 매칭. 외부 패키지 `vicpinky_description` 직접 수정 X — moca_gazebo 내 wrapper xacro 신설.
  - 신규 파일: `src/moca_gazebo/urdf/vicpinky_moca.urdf.xacro` + `src/moca_gazebo/launch/upload_moca.launch.xml`
  - 변경: `launch_sim.launch.xml` 의 upload include 를 새 wrapper 로 교체
- **Gazebo 재기동**

## 좌표 변경 0 명시

본 작업 (오전 ~10:30 시점 + 직후 예정) 모두 **좌표 변경 0**. 가구 배치 (cafe_layout.yaml /
world include pose / tables.yaml) 어제 picker 21:28 저장본 그대로. 외형/색/높이만 갱신.

## 관련 메모리 / 문서

- `docs/daily/2026-05-14_gazebo_cafe_layout.md` — 어제 배치 셋업 (좌표 SoT 원본)
- `config/cafe_layout.yaml` — picker 21:28 저장본 (좌표 SoT)
- `src/dobi_npc/dobi_npc_bringup/config/tables.yaml` — 서빙 waypoint SoT (오늘 동기화)
- [[feedback_dont_touch_working_code]] — vicpinky_description 외부 의존 보존 정책 (riser 는 wrapper 로)
