# 2026-05-14 (오후) — Gazebo 카페 디자인 (D-1~D-4) + BT 학술 토론

**작업자**: 공국진 (Stephen)
**범위**: mapv5 의 시뮬 환경을 moca 카페 시나리오에 맞게 디자인 (벽 높이 축소 + 외곽 smoothing + 카페 가구 추가) + BT vs FSM 채택 근거 학술 정리
**상태**: D-1~D-3 라이브 검증 통과. D-4 (mapv5_moca.world) 가구 spawn 완료, 위치 조정은 사용자 후속.
**관련**: 오전 회고 `2026-05-14_navigation_sim_setup_and_safeguards.md` 의 연속. CLAUDE.md §11 + §0-A 박혀있는 안전 정책 그대로 적용 (RPi 접근 0, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1).

---

## 1. 한 줄

mapv5 시뮬 환경의 벽 디자인 다듬기 (높이 75% 축소 + 외곽 Taubin smoothing) + 카페 가구 시드 (OpenARM + 음식 제조 테이블 + 고객 T01~T05) 신규 추가. **모든 작업 PinkLAB 원본 동결 + moca 전용 패키지 안에서만 수행**. BT 채택 근거 (5-stage funnel, FSM 폭발) 학술 정리.

---

## 2. D-1 ~ D-4 단계별 결과

### D-1 — 벽 높이 50% (`<scale>1 1 0.5</scale>`)
- 위치: `src/moca_gazebo/models/mapv5/model.sdf` (visual + collision × 2 = 4 곳)
- 원본 STL (2.0m 높이) 보존, SDF scale 만으로 1.0m 표시.
- 결과: 사용자 시각 OK.

### D-2 — 벽 높이 추가 50% (`<scale>1 1 0.25</scale>`)
- 원본 대비 **25% (50cm)**.
- LiDAR mount Z 계산 = 0.087 (chassis) + 0.12 (mount) + 0.03 (laser) = **0.237m ≈ 24cm**.
- 0.5m wall 은 LiDAR 위 26cm 여유 — 인식 안전.
- 0.25m 이하는 LiDAR 빔 임계점 → Nav2 obstacle 인식 불가.
- 결과: 사용자 시각 OK.

### D-3 — 외곽 라인 Taubin Smoothing
- 도구: `scripts/smooth_wall_mesh.py` 신규 — numpy + scipy.sparse (시스템 apt). trimesh 미사용.
- 알고리즘: Taubin λ|μ 필터 (λ=0.5 / μ=-0.53, 10 iter). lock_z=True (top/bottom 평면 보존, XY 외곽만 smooth).
- 결과:
  - walls_high: bbox 13.45 → 13.44m (Z 2.0 그대로), vertex 평균 변위 1.3cm
  - walls_low: bbox 6.75 → 6.74m, 평균 1.3cm
- **함정 발견**: Gazebo 가 `_smooth.stl` uri 를 안정적으로 해결 못함 (cache 또는 lazy load). 우회:
  - 원본 자산은 `maps/mapv5_config/meshes/` 에 사용자 제공본으로 보존
  - `src/moca_gazebo/models/mapv5/meshes/walls_*.stl` 자체를 smoothed 로 덮어쓰기
  - model.sdf uri 는 원본 이름 (`walls_high.stl`) 유지
- 결과: 사용자 시각 OK.

### D-4 — `mapv5_moca.world` 신규 (모카 카페 시나리오)
- 신규 모델 3 폴더:
  - `cafe_table/` — 사각형 0.7×0.7×0.72m + 4 다리. 크림 화이트 천판 + 우드 다리. (1차 cylinder 천판 → 사용자 피드백 후 사각형으로 변경)
  - `prep_station/` — 1.2×0.6×0.85m 작업대. 흰 상판 + 우드 본체 + **핑크 strip** + 다크 그레이 arm_mount. PinkLAB 컬러 반영.
  - `open_arm/` — LeRobot SO-100 style 5DoF 시각 placeholder. 다크 그레이 본체 + **핑크 shoulder/wrist** + 흰 그리퍼.
- 신규 world: `mapv5_moca.world` — mapv5.world 통째 카피 + world name 변경 + topic 경로 `/world/mapv5_moca/` + 가구 7 model `<include>` 추가.
- 신규 launch: `launch_mapv5_moca.launch.xml` — `launch_sim.launch.xml` include + `world_name=mapv5_moca.world`.
- 좌표 (mapv5 wall 범위 x∈[-45.5,-32], y∈[-6.1,2.3] 안 임시 배치):
  - prep_station (-44.0, -5.0), open_arm (-44.4, -5.0, z=0.89)
  - T01 (-42, -3), T02 (-40, -3), T03 (-38, -3), T04 (-41, 0), T05 (-39, 0)
- 결과: 가구 spawn 통과. **위치는 사용자 후속 결정** — gz topic 으로 pose 추출 가능 확인.

---

## 3. 사용자 결정 흐름 (다음 세션 합류자 참조)

| 사용자 요청 | Claude 대응 |
|---|---|
| "Gazebo dry-run 하자" | 의존성 인벤토리 → COLCON_IGNORE 검토 |
| "팀 동료 실물 사용 중, RPi 접근 금지" | §0-A 박음, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 강제 |
| "mapv5 사용 + mapv5_config 카피" | 사용자 사전 자산 발견 (벽 mesh + world + launch) |
| "moca 용 별도 가제보/navigation 경로" | `src/moca_gazebo/`, `src/moca_navigation/` 신규 패키지 |
| "ROS_DOMAIN_ID=99 유지" | 시뮬 격리 도메인 확정 |
| "잘되는 소스 절대 수정 X" | [[feedback_dont_touch_working_code]] 강화 |
| "벽 50% 낮춤 → 추가 50%" | D-1, D-2 SDF scale patch |
| "벽 높이 더 낮춰도 라이다 인식?" | LiDAR mount Z 0.237m 분석, 안전 임계 0.5m 회신 |
| "외곽 라인 smooth" | Taubin Laplacian 스크립트 + STL 덮어쓰기 |
| "moca 케이터링 환경, OpenARM + 제조대 + T01~T05, 산뜻 컬러, mapv5_moca.world" | 모델 3종 + world + launch 신규 |
| "테이블 사각형, 위치 수정" | cafe_table 사각형 4 다리로 변경, 위치는 사용자 후속 |

---

## 4. 진행 중 발견 사항

### 4.1 wall collision geometry 생성 실패 (D-1 부터 지속)
```
[Dbg] The geometry element of collision [walls_high_collision] couldn't be created
[Dbg] The geometry element of collision [walls_low_collision] couldn't be created
```
- visual 만 표시, collision 자체 미작동 → 로봇이 벽 통과 가능 → Nav2 obstacle layer 영향
- 코드 흐름 검증엔 영향 X, **실 시뮬 검증 (벽 회피) 시 fix 필요**
- 후속 옵션: STL → DAE/OBJ 변환 또는 SDF `<mesh>` 옵션 (e.g. `<convex>`)

### 4.2 STL uri cache 이슈 (D-3 에서 발견)
- `walls_high_smooth.stl` 같이 새 파일을 model.sdf uri 변경 + colcon build 후에도 Gazebo 가 "uri could not be resolved" 발생
- 가능 원인: gz-sim 8 의 model resolver lazy 또는 cache. install symlink 자체는 정상.
- 회피: 새 파일 별도 추가 X, **원본 파일 자체에 덮어쓰기** + uri 미변경
- 후속: 진짜 cache 위치 (`~/.gz/`) 정리 또는 model resolver verbose 로 디버깅

### 4.3 gz topic pose 추출 가능 확인
```bash
gz topic -e -t /world/mapv5_moca/pose/info -n 1
```
- 모든 model 의 현 시점 pose 출력 (position + orientation)
- 사용자가 GUI 에서 model 드래그 → 새 pose → 추출 → SDF `<pose>` 자동 갱신 가능
- Gazebo 의 영구화 (SDF write) 자동 패턴 — D-4 후속 위치 조정에 활용

### 4.4 Bash tool exit 144 반복
- 긴 명령 (sleep + ps + grep 조합) 또는 출력 큼 → harness/sandbox exit 144 (SIGUSR1 area)
- 회피: wrapper script (`/tmp/moca_sim_logs/run_sim*.sh`) + spawn 명령 짧게 + 검증은 분리 Bash 호출
- 시뮬 spawn 패턴 — 향후 모든 Gazebo 가동에 동일 패턴 적용

---

## 5. BT 학술 토론 — 다음 세션 / 논문 작성 참고

본 세션 후반 사용자가 BT vs FSM 채택 근거 깊게 토론. 정리:

### 5.1 6-Layer 청사진 그대로 BT 학파
- Layer 1 Isla 2005 (Halo 2) — BT 게임 NPC 패러다임 시작
- Layer 5 Marzinotto 2014 — BT 형식화 + Priority Safety
- Layer 6 Iovino 2022 — BT 서베이 + XAI/RL 친화
- → FSM 채택 시 6-Layer 학술 정통 손실

### 5.2 5-stage funnel + 3 계층 abort (실제 `cafe_funnel_v1.xml` 구조)
```
ReactiveFallback "root_alarm_fallback"
├── SafetyCheck      (정상 FAILURE / 위험 SUCCESS)
├── EmotionMonitor   (V·A 학술 임계, 정상 FAILURE / abort SUCCESS)
└── Sequence "cafe_funnel"
    ├── IdleScan → Approach → IceBreak → Minigame → Offer → LeadIn
```
- **Reactive Fallback 핵심**: 매 tick 왼쪽부터 전체 자식 재평가, RUNNING latch X
- 알람의 normal=FAILURE 트릭 — 위험 시만 SUCCESS → ReactiveFallback 종료 → 진행 중 Sequence halt
- 3 계층 abort:
  - Global (ReactiveFallback top): SafetyCheck, EmotionMonitor
  - Stage-level (Approach `abort_threshold="1.0"`): 노드 자체 FAILURE
  - Action-internal (Minigame `rapport_delta`): 부드러운 조정

### 5.3 FSM 상태 폭발 정량 (Phase 진화별)
| Phase | FSM transition 추정 |
|---|---|
| Phase 0 (6 stage + 1 알람) | 16 |
| Phase 2 (emotion + scan 추가) | ~40 |
| Phase B (Pause Zone) | 50+ |
| Phase 4 (페르소나 3 종) | 150+ (flat) 또는 guard 폭발 |
| Phase 5 (학습 sub-state) | 200+ + O(N²) 재폭발 |
- vs BT: 모든 phase 에서 `ReactiveFallback` 자식 1 줄 추가 + Sub-tree include 1 줄
- **silent bug 위험** — transition 누락이 type checker 에 안 잡혀 production 까지 (특히 emotion abort 누락 = 사회적 사고)

### 5.4 Statecharts (Harel 1987) 시도와 한계
- super-state + region + history pseudo-state → plain FSM 의 30~50% 개선
- 다만 moca 의 sub-tree 재사용 + 학습 sub-tree 동적 swap + XAI tick path log 까지는 부족
- BT 가 추가 80~90% 개선

### 5.5 ROS2 생태계 정합
- Nav2 자체가 BT (`bt_navigator`). `move_base` (ROS1 FSM) → Nav2 (ROS2 BT) 진화의 핵심 동기 = navigator behavior 폭발.
- moca BT 와 Nav2 BT 가 같은 `BehaviorTree.CPP 4.8.3` 생태계 — Approach 노드 안에서 NavigateToPose action 직접 호출 자연스러움.

### 5.6 학술 publish 측면
- moca = "학술적 정당성이 있는 BT" 가 차별점
- Phase 5 의 XAI/Learning 확장 (Iovino 2022 미해결 과제) 이 BT 위에서만 자연스러움
- FSM 으로 가면 publish 가능성 ↓

본 토론은 향후 cafe_npc_paper_master.md §Method 의 BT 채택 근거 섹션 작성 시 그대로 인용 가능.

---

## 6. 산출 (오후 추가)

### 신규 파일
- `scripts/smooth_wall_mesh.py` — Taubin Laplacian STL smoothing 도구 (재사용 가능)
- `src/moca_gazebo/models/cafe_table/` — 사각 카페 테이블 model
- `src/moca_gazebo/models/prep_station/` — 음식 제조 테이블 model
- `src/moca_gazebo/models/open_arm/` — LeRobot style 5DoF 시각 placeholder model
- `src/moca_gazebo/worlds/mapv5_moca.world` — 모카 카페 시뮬 world
- `src/moca_gazebo/launch/launch_mapv5_moca.launch.xml` — mapv5_moca 단축 launch
- `src/moca_gazebo/models/mapv5/meshes/walls_*_smooth.stl` — Taubin smoothed STL (별 파일로도 보존, 실 사용은 원본 덮어쓰기)

### 갱신 파일
- `src/moca_gazebo/models/mapv5/model.sdf` — scale Z 0.25 (벽 25% 높이) + 헤더 주석
- `src/moca_gazebo/models/mapv5/meshes/walls_{high,low}.stl` — Taubin smoothed 로 덮어쓰기 (원본은 `maps/mapv5_config/` 에 보존)

### 미수정 (확인됨)
- `src/shared/vic_pinky/` — 0 파일 변경 ✅ (mtime 검증)
- `src/dobi_npc/*` — `tables.yaml` 1 파일만 신규 (오전 작업)
- `vicpinky_gazebo` COLCON_IGNORE — 그대로 (원본 동결)

---

## 7. 다음 세션 잔존

### 즉시 (D-4 마무리)
- **테이블 위치 사용자 결정 후 반영** — gz topic 으로 pose 추출 or 사용자 직접 좌표 알려주기
- prep_station + open_arm 의 정합 (open_arm 이 prep_station 위에 정확히 mount 되는지 시각 확인)
- 추가 가구 (카운터 백, 의자 등 — 사용자 선택)

### 디자인 후속
- collision mesh fix (STL → DAE/OBJ 또는 SDF `<convex>`) — 벽 obstacle 인식 작동시키기
- 산뜻 컬러 추가 (조명 따뜻한 톤, 바닥 색상)

### 코드 (D-4 디자인 끝난 후 진행)
- R1 patch (teleop_server `_tick` idle skip)
- G-4~G-10: 백업본 → main 서빙 자산 복원 + e2e dry-run
- 시뮬 전용 부팅 스크립트 (`scripts/run_sim_ui.sh`) — RPi SSH 0, DOMAIN=99

### 라이브 (RPi 복귀 후)
- DOMAIN=22 토글, mapv5 실측 위 좌표 캡처 + 1 테이블 nav
- 회고 별 .md

---

## 8. 백업

### 본 시점 (D-4 완료 시점)
백업 폴더: `~/backup/moca_daily_20260514_<HHMM>/` (본 회고 작성 직후 생성)
- laptop tar.gz + git diff patch + 메모리 사본

### 누적 (2026-05-14 일)
- `~/backup/moca_daily_20260514/` (오전, 작업 시작 전, PC+RPi)
- `~/backup/moca_daily_20260514_1109/` (오전 G-3 완료, PC + 메모리)
- `~/backup/moca_daily_20260514_<현 시점>/` (오후 D-4 완료, PC)

각 백업은 그 시점 회복 가능 — README.md 에 회복 절차 명시.
