# 2026-05-14 — Navigation 시뮬 환경 셋업 + 안전 정책 박기 (G-1~G-3)

**작업자**: 공국진 (Stephen)
**범위**: Gazebo dry-run 인프라 (`moca_gazebo` + `moca_navigation` 신규 패키지) + Navigation 코드 분리 원칙 + RPi 접근 차단 정책 + 일일 백업 정책
**상태**: G-1, G-2, G-3 통과. G-4 (서빙 자산 복원) 부터 잔존.
**관련**: CLAUDE.md §0-A §7 §11, 메모리 4 신규/갱신

---

## 1. 한 줄

teleop_ui + Nav2 동시 가동 시 발견된 **직진 못함** 증상의 root cause 2 개 (R1, R2) 박고, mapv5 정합 Gazebo dry-run 인프라를 PinkLAB 원본 동결한 채 신규 `moca_gazebo` + `moca_navigation` 패키지로 분리 셋업.

---

## 2. 본 세션 배경

서빙 모드 (테이블 waypoint Nav2 자율 주행) 첫 구현. 메모리 `project_mode_serving.md` 는 2026-05-12 본 구현 완료라고 적혀 있었지만 실제 main 에는 자산 부재 — 사용자가 2026-05-13 에 DDS/teleop 디버깅 후 main 통째 롤백 (`~/moca_releases/moca_0513backup_동작안함/`). 백업본의 코드는 home_pose 캡처까지 라이브 통과했으나 T01~T05 + 실 nav 검증 미완. 게다가 라이브 검증 시 **직진 못함** 증상으로 사용자가 명시. root cause 분석 + 시뮬 dry-run 인프라부터 새로 정공법으로 진행.

추가 제약 강화:
- **팀 동료가 실물 vic_pinky 사용 중** → Claude 의 RPi 접근 절대 금지
- **잘되는 소스는 절대 수정 X** (사용자 강조 재확인) — PinkLAB 원본 + dobi_npc 검증 자산 동결
- **매일 작업 시작 전 백업** (오늘부터 적용)

---

## 3. 핵심 결정 6 가지

### 3.1 직진 못함 root cause 2 개 (R1, R2)

**R1**: `teleop_server.py:_tick()` 1113-1136 — idle 모드 + alive timeout 만료 시에도 50ms 주기로 `/joy/cmd_vel` (priority **100**) 발행. twist_mux 가 영구 활성 → Nav2 `/bt/cmd_vel` (priority 80) 영구 차단. **patch 잔존** (사용자 사전 승인 후).

**R2**: RPi `vicpinky_bringup` 의 `velocity_smoother` 노드와 Nav2 `navigation_launch.xml` 의 `velocity_smoother` **노드 이름 중복**. 같은 DDS 도메인 22 에서 2 instance → lifecycle service 라우팅 혼선 → cmd_vel chain 일부 끊김. **moca_navigation 자체 launch 에서 `nav2_velocity_smoother` 로 rename — vicpinky_navigation 원본 미수정.**

### 3.2 잘되는 소스 절대 동결 + 신규 패키지로 분리

PinkLAB 원본 (`src/shared/vic_pinky/`) + dobi_npc 검증 자산 단 한 글자도 수정 X. 모든 Navigation 인프라는 신규 패키지로:
- `src/moca_gazebo/` — Gazebo 시뮬 (mapv5 자산 + launch_sim 사본 + spawn arg P-C patch)
- `src/moca_navigation/` — Nav2 stack (vicpinky_navigation 사본 + R2 patch + mapv5 default map)

vicpinky_gazebo 의 COLCON_IGNORE 도 유지 — 빌드 영향 0.

### 3.3 mapv5 = mapv4 정합 Gazebo 완성 세트

사용자가 `maps/mapv5_config/` 에 미리 작성해둔 자산 — mapv4.pgm 의 occupancy 를 wall mesh (`walls_high.stl` 810KB + `walls_low.stl` 220KB) 로 extrude. mesh_info.txt 의 spawn 권장 좌표 (-38.81, -2.13). 신 PGM `mapv5.pgm` 도 같이. 즉 Nav2 측 (mapv5.yaml) + Gazebo 측 (mapv5.world + model) 둘 다 동일 좌표계 정합 — **시뮬 검증 ↔ 라이브 동일 좌표 호환**.

### 3.4 spawn 함정 — launch_sim P-C patch

`vicpinky_gazebo/launch_sim.launch.xml` 은 create 노드의 spawn 위치 하드코딩 (-x 14 -y -16 -z 0.3). mapv5.world 범위 (-51.32~-31.77, -6.62~5.88) 밖. moca_gazebo 의 launch_sim 사본에 spawn_x/y/z/yaw arg 추가 (default = mapv5 권장 좌표) + create 노드 args 변수화. **vicpinky_gazebo 원본 미수정**, default 가 mapv5 권장이라 launch_mapv5 호출 시 자연스럽게 작동.

### 3.5 RPi 절대 접근 차단 (조건부, 사용자 명시까지)

CLAUDE.md §0-A 박음. 금지 명령: `ssh vic@192.168.0.138`, `sshpass`, `scp ... 192.168.0.138`, `ros2 daemon --remote`. 금지 스크립트: `run_teleop_ui.sh` (step 3 자동 RPi SSH bringup). PC 단독: `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1` (시뮬 도메인 격리 + loopback 격리 이중).

### 3.6 일일 백업 정책 (2026-05-14~)

CLAUDE.md §7 박음. 작업 시작 전 매일 1회 PC+RPi 백업. RPi SSH 불가 시 작업 보류 (단 RPi 사용자 측에서 사용 중이면 PC 만 + 라이브 자산 변경 X 보장 시 진행 OK). 위치: `~/backup/moca_daily_YYYYMMDD[_HHMM]/`. 백업 본 보존 — 덮어쓰기 X.

---

## 4. 산출

### 4.1 신규 패키지

| 패키지 | 파일 | 용도 |
|---|---|---|
| `src/moca_gazebo/` | 12 (CMakeLists + package + launch 3 + worlds 1 + models/mapv5 5 + params 1) | Gazebo 시뮬 (mapv5 정합) |
| `src/moca_navigation/` | 8 (CMakeLists + package + launch 4 + params 1 + rviz 1) | Nav2 stack (R2 적용) |

빌드 통과 (`colcon build --packages-select moca_gazebo moca_navigation` 격리 셸). install/share 정상.

### 4.2 CLAUDE.md 갱신
- 신규 §0-A (팀 작업 중 RPi 접근 금지)
- 신규 §7 일일 백업 루틴
- 신규 §11 Navigation 모드 코드 분리 원칙

### 4.3 메모리 신규/갱신
- 신규 `feedback_daily_backup_routine.md`
- 신규 `feedback_no_rpi_when_team_working.md`
- 신규 `project_navigation_code_separation.md`
- 갱신 `feedback_dont_touch_working_code.md` (2026-05-14 재강조 명문화)
- 갱신 `MEMORY.md` 인덱스 (3 신규 등록)

### 4.4 백업 본 (이중 백업)
- `~/backup/moca_daily_20260514/` (오전 — 작업 시작 전 PC + RPi)
- `~/backup/moca_daily_20260514_1109/` (G-3 완료 후 PC + 메모리 사본)

---

## 5. G-3 라이브 검증 결과

| 항목 | 결과 |
|---|---|
| Gazebo 가동 (PID 26331) | ✅ |
| mapv5.world 로드 | ✅ |
| 로봇 spawn (-40.02, -0.47, 0.3) | ✅ `Entity creation successful` |
| parameter_bridge (clock/tf/scan/odom/cmd_vel/joint_states) | ✅ 매핑 시작 |
| 사용자 GUI 시각 확인 | ✅ "가제보 잘 동작해" |

---

## 6. 발견 사항 (후속 검토)

### 6.1 wall collision geometry 생성 실패
```
[Dbg] The geometry element of collision [walls_high_collision] couldn't be created
[Dbg] The geometry element of collision [walls_low_collision] couldn't be created
```
visual 은 표시되지만 collision 미작동 → 로봇이 벽 통과 가능. Nav2 obstacle layer 영향. dry-run 코드 검증에 영향 X, **실 시뮬 검증 (벽 회피) 시 collision mesh fix 필요** (STL → DAE/OBJ 변환 또는 SDF mesh 옵션 조정).

### 6.2 ROS_LOCALHOST_ONLY deprecated 경고
Jazzy 에서 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 권장. 동작 정상 (warning 만).

### 6.3 stale install/ 정리
다른 머신 (`/home/soon/`) 빌드 잔재 7 개 (`dobi_npc_*`, `vicpinky_navigation`) install/ 에 빈 껍데기로 남아 있어 launch 시 `package not found` 에러. 삭제 후 가동 통과. src/ 의 원본 소스는 그대로 — 재빌드 시 원상 복구 가능.

### 6.4 backup 시점에 git status M CLAUDE.md
CLAUDE.md 가 unstaged 상태 — commit 안 하고 작업 진행. 다음 세션 시점에 commit 또는 PR 결정.

---

## 7. 다음 세션 잔존

### 즉시
- **G-4**: 백업본 (`~/moca_releases/moca_0513backup_동작안함/`) → main 서빙 자산 복원
  - tables.yaml (home_pose + T01~T05 시드)
  - `serving_dispatcher_node.py` (dobi_npc_bringup, NavigateToPose action client only — cmd_vel publisher 0 확인)
  - `mode_serving.launch.py` 교체 (stub → dispatcher 본 launch)
  - `setup.py` + `package.xml` append (entry_point + nav2_msgs depend)
  - 운영 UI 9 endpoint + 패널 3개 (teleop_server.py + operator.html — "이미 떠있는 서버에 라우터 추가만")

### 검증
- **G-5~G-10**: Nav2 가동 (DOMAIN=99) + 운영 UI + 서빙 모드 e2e + 라이브 검증
- **R1 patch** (teleop_server _tick idle skip) — 사용자 사전 승인 후
- **collision mesh fix** (mapv5 의 walls_high/low.stl)

### 라이브 (RPi 복귀 후)
- DOMAIN=22 로 토글, mapv5 실측 위 좌표 캡처 + 1 테이블 nav
- 회고 별도 .md

---

## 8. 작업 흐름 메모

본 세션 사용자 요청 변화 (참고용 — 다음 세션 합류 시 합리적 디코딩):
1. "오늘은 waypoint 좌표 저장 + 따라 주행 하자" → 1단계 시작
2. "이전 코드 수정 없도록 명시" → 메모리/CLAUDE.md 강화
3. "작업 시작 전 백업" → 0단계 일일 백업
4. "operator 에 waypoint 좌표 설정 기능 있어" → 백업본 `0513backup_동작안함` 발견, 메모리 stale 확인
5. "Nav2 모드 코드 충돌 꼼꼼히 체크" → R1 + R2 root cause 분석 (실제 직진 못함 증상 원인)
6. "Gazebo dry-run 하자" → vicpinky_gazebo 자산 검토
7. "팀 동료 실물 사용 중 — RPi 접근 금지" → §0-A 박음
8. "mapv5 사용 + mapv5_config 카피" → 사용자 사전 작성 자산 발견
9. "별도 moca 용 가제보/navigation 경로" → src/moca_gazebo + src/moca_navigation 분리
10. "ROS_DOMAIN_ID=99" → 시뮬 격리 도메인 확정
11. "잘되는 소스 절대 수정 X" → §3 명문화
12. "다른 머신 빌드 잔재 삭제 OK" → install/ stale 정리 승인
13. G-3 통과 후 "백업 + 작업 기록 md" → 본 회고

본 흐름 = 단계마다 사용자 의도 명확화 + Claude 의 가정 검증 + 안전 가드 박기. 검증된 워크플로우.
