# moca ↔ moca_teammember 병합 설계 (2026-05-19)

> SoT 문서. 본 spec 승인 후 `docs/superpowers/plans/` 에 step-by-step 실행 plan 생성.
> 작성: 2026-05-19 (doby)
> 사용자 결정 4건 (옵션 A merge / mode_follow+guiding 분리 운용 / pip 병합 직후 설치 / 양쪽 풀 백업) 반영.

---

## 0. 요약

`~/moca_teammember/` 의 18 commit (person_tracking_pkg 신규 + approach_controller + follow LiDAR 거리 제어 + Nav2 스크립트) 을 `~/moca/` 로 **git merge** 로 통합. 공통 조상 `1a2971b` 기준 양쪽 분기, 5 파일 충돌 후보 (그 중 1 건은 의미 충돌). 머지 후 ROS2 빌드 + 핵심 노드 import 검증 통과까지를 본 spec 범위로 함. 라이브 (RPi) 검증은 별 트랙.

**예상 소요**: 2~3 시간 (백업 30 분 + 머지 + 충돌 해결 60 분 + 빌드 + 검증 30 분 + 회고 30 분)

**전제**:
- 사용자 명시 제약 (5/18 세션 마지막) `"/cmd_vel 발행 X, 실수 X"` 유지 — 본 spec 은 빌드/import 검증까지만, 라이브 검증 X.
- §0-A 팀 RPi 사용 신호 시 RPi 접근 금지 — 현재 5/18 09:31 해제 상태이나 본 spec 작업은 **PC only**.

---

## 1. 두 저장소 형상 (재확인)

| 항목 | `~/moca` (내 측) | `~/moca_teammember` (팀원) |
|---|---|---|
| HEAD | `fb9c1b9` | `fd62971` |
| 공통 조상 | `1a2971b` (2026-05-08) | 동일 |
| 분기 commits | 43 (+31735/-250, 210 files) | 18 (+2337/-27, 30 files) |
| 주요 트랙 | 운영 UI / 5-state FSM / floorplan / DB schema / AMCL drift | person_tracking_pkg / follow LiDAR / Nav2 스크립트 |
| 빌드 가능 | 5/18 백업본 기준 ✓ | ✓ (build/ install/ 존재) |

---

## 2. 머지 후 최종 상태 (목표)

### 2.1 신규 자산 (팀원 → 내 측 추가)

| 카테고리 | 자산 | 위치 |
|---|---|---|
| 신규 패키지 | `person_tracking_pkg` (ament_python, 3 nodes) | `src/dobi_npc/person_tracking_pkg/` |
| 신규 메시지 | `PersonTrack.msg`, `PersonTrackArray.msg` | `src/dobi_npc/dobi_npc_msgs/msg/` |
| 신규 스크립트 | `run_3stage.sh`, `run_nav2.sh`, `stop_nav2.sh` | `scripts/` |
| 신규 문서 | `2026-05-14_..._person_tracking.md` 외 5 일일 회고 | `docs/daily/` |
| 백업 | `vicpinky_navigation_launch/*.bak_*` | `_backups/` (신규 디렉토리) |
| 모델 가중치 | `yolov8n.pt` (6.5MB), `pose_landmarker_lite.task` (5.5MB) | `src/dobi_npc/person_tracking_pkg/models/` (gitignored) |

### 2.2 양쪽 동시 변경 5 파일 — 해결 방향

| 파일 | 해결 |
|---|---|
| `dobi_npc_msgs/CMakeLists.txt` | **union** — 7 msg (내 5 + 팀원 2) + 3 srv + sensor_msgs depend |
| `mode_manager_node.py` | 내 측 base + 팀원 NaN 패치 (`_on_battery` 의 `math.isfinite`). **추가 변경**: `VALID_MODES` 에 `'follow'` 추가 (사용자 결정 — follow + guiding 분리 운용). `LEGACY_MODE_ALIAS` 에서 `'follow'` 제거, `'npc'` 만 유지. |
| `dev_common.launch.py` | 내 측 base + 팀원 3 node append (person_tracking_node, group_approach_node, approach_controller_node). docstring 7-node → **9-node** 갱신 (팀원 의도 통합). |
| `mode_follow.launch.py` | **사용자 결정 — 팀원 본 채택** (실제 follow_controller spawn + 라이브 튜닝). 내 측 deprecated wrapper 결정은 본 머지에서 **철회**. mode_guiding.launch.py 는 별도 유지. |
| `CLAUDE.md` | 내 측 base + 팀원의 §RPi scp 규칙 섹션만 가져옴 (다른 변경은 내 측에 이미 동등 내용 존재). 5/19 본 spec 추가 시 `*마지막 갱신*` 라인 일괄 갱신. |

### 2.3 팀원-only 파일 수정 1 건 — 그대로 적용

- `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` — LiDAR 거리 기반 제어 로직 +21 lines. 충돌 X, git merge 자동 적용.

### 2.4 머지 후 즉시 정정 (Hidden 함정 7건)

| # | 함정 | 정정 |
|---|---|---|
| F1 | `person_tracking_pkg/package.xml <description>` em-dash 사용 — `Person tracking — YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose` | ASCII 로 변경: `Person tracking - YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose` |
| F2 | `models/*.pt`, `*.task` git 미포함 | 머지 직후 `cp -v` 로 별도 복사 (sha256 검증) |
| F3 | `ultralytics`, `boxmot` 미설치 | `pip install --user ultralytics boxmot` + numpy/cv2 transitive cleanup 검증 |
| F4 | 워크스페이스 루트 `yolov8n.pt` 중복 6.5MB | **머지 시 무시** (gitignored, .git 에 없음). 만약 어떤 경로로 복사돼도 즉시 삭제 |
| F5 | `scripts/run_3stage.sh`, `run_nav2.sh` 의 `~/moca/` 절대경로 잔재 | SCRIPT_DIR 기반으로 정정 (CLAUDE.md §7 상대경로 컨벤션) — **본 머지 spec 에서는 보존 (Quick-fix), 별 트랙으로 후속** |
| F6 | 내 측 untracked `scripts/stop_all.sh` (5/18 작성) | 머지 시작 전 별 commit (또는 stash). `cafe_ninja/*` 변경 7 + 신규 7 파일도 별 commit |
| F7 | 팀원 `_backups/` 도입 — 내 측 `.gitignore` 영향 검토 | `.gitignore` diff 0 (양쪽 동일). `_backups/` 는 untracked 가 아닌 commit 됨 — 그대로 받아들임 |

---

## 3. 절차 (8 phase)

### Phase 0 — 진입 조건 점검 (5 min)

- [ ] PC ros2 daemon idle (`pgrep -f 'ros2 daemon'` → 정리)
- [ ] PC moca/opserver/teleop_ui 모두 down
- [ ] RPi bringup 9 노드 모두 종료 — `ssh vic@192.168.0.138 'pgrep -af ros2'` 확인
- [ ] §0-A (RPi 접근 금지 신호) 미발효 확인
- [ ] 디스크 여유 ≥ 5GB (`df -h ~`)
- [ ] `~/moca/` HEAD `fb9c1b9`, `~/moca_teammember/` HEAD `fd62971` 일치 확인

### Phase 1 — 양쪽 풀 백업 (30 min)

목적: 사용자 결정 (양쪽 풀 백업). 머지 실패 시 100% 복원 가능 상태 보장.

`~/backup/moca_merge_20260519/` 생성, 2 sub:

```
~/backup/moca_merge_20260519/
├── laptop/
│   ├── git_state.txt                    # git status + git log -20 + git branch -a
│   ├── moca_unstaged.patch              # git diff (working tree)
│   ├── moca_staged.patch                # git diff --cached
│   ├── moca_src_fb9c1b9.tar.gz          # src/ scripts/ config/ docs/ CLAUDE.md README.md moca.repos .gitignore
│   └── moca_dotgit_fb9c1b9.tar.gz       # .git/ 전체 (history 보존)
├── teammember/
│   ├── git_state.txt                    # 동일
│   ├── moca_teammember_unstaged.patch   # `cd ~/moca_teammember && git diff`
│   ├── moca_teammember_untracked.tar.gz # .claude/, group.png, yolov8n.pt (untracked 3건)
│   ├── moca_teammember_src_fd62971.tar.gz  # src/ scripts/ docs/ CLAUDE.md README.md _backups/
│   ├── moca_teammember_dotgit_fd62971.tar.gz  # .git/ 전체
│   └── person_tracking_models.tar.gz    # src/dobi_npc/person_tracking_pkg/models/{yolov8n.pt, pose_landmarker_lite.task} 12MB (gitignore 됨, 별도 보존)
├── SHA256SUMS                           # 모든 tar/patch sha256
└── README.md                            # 회복 절차 (3 시나리오: 양쪽 회복 / 내 측만 / 팀원만)
```

검증: `sha256sum -c SHA256SUMS` 통과 + `tar tzf` 로 모든 tar 무결성 확인.

### Phase 2 — 머지 전 정리 (10 min)

내 측 dirty 8 (7 modified + 1 untracked) 정리:

- [ ] `cafe_ninja` 변경 7개 + 신규 7개 검토 — 의도된 변경이면 별 commit, 아니면 stash
- [ ] `scripts/stop_all.sh` (untracked, 5/18 작성) — 의도된 추가이면 별 commit
- [ ] `docs/daily/2026-05-18_*.md` 2 개 (untracked) — 별 commit
- [ ] `git status` clean 검증

→ **3 commit 추가 예상**: `(a) cafe_ninja 진행분`, `(b) scripts/stop_all.sh 도입`, `(c) docs: 2026-05-18 회고 2건`. 본 머지와 분리해서 git log 가독성 ↑.

### Phase 3 — git merge 실행 (15 min)

```bash
cd ~/moca
# 안전 표시 tag + branch
git tag pre-merge-teammember-20260519
git branch backup-pre-merge-teammember-20260519

# 팀원 head fetch (별 remote 추가 없이 직접 path)
git fetch ~/moca_teammember main

# 머지 시도 — no-commit 으로 충돌 검토
git merge --no-commit --no-ff FETCH_HEAD \
    -m "merge: integrate teammate person_tracking_pkg + follow LiDAR routing (18 commits)"
```

예상 결과: **5 파일 충돌 마커**. `git status` 에 `both modified` 로 표시.

### Phase 4 — 5 파일 충돌 해결 (30 min)

순서 (의존성 낮은 것 → 높은 것):

1. **`dobi_npc_msgs/CMakeLists.txt`** (mechanical union)
   - 양쪽 msg 라인 모두 추가: 7 msg (RapportEvent, EmotionState, MinigameResult, UtterRequest, ModeState, **PersonTrack, PersonTrackArray**, PatrolState, TableReport, GuidingState, OpEvent, OperatorCommand — 합 12 msg) + 3 srv (SetPersona, SetMode, GetTableStatus, SetPatrolSchedule, ScanTable — 합 5 srv)
   - DEPENDENCIES: `std_msgs builtin_interfaces sensor_msgs`

2. **`dev_common.launch.py`** (내 측 base + 팀원 append)
   - docstring: 9-node 로 갱신 (내 측 docstring + 팀원 person_tracking 3 줄 추가)
   - LaunchDescription: 내 측 7 Node + 팀원 3 Node append (person_tracking_node, group_approach_node, approach_controller_node)

3. **`mode_manager_node.py`** (내 측 base + 패치 2건)
   - `VALID_MODES` 에 `'follow'` 추가 → `('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')`
   - `LEGACY_MODE_ALIAS` 에서 `'follow'` 제거, `'npc': 'engaging'` 만 남김
   - `_on_battery`: 팀원의 NaN 패치 적용 (`math.isfinite` check)
   - docstring 5-state → **6-state** (idle + 5 active) 표기 갱신

4. **`mode_follow.launch.py`** (사용자 결정 — 팀원 본 채택)
   - 내 측의 deprecated wrapper 결정 **철회**
   - 팀원 본 (`a7c84ee → 1e25209` diff 적용본) 전체 채택
   - mode_guiding.launch.py 는 별도 유지 (변경 X)

5. **`CLAUDE.md`** (내 측 base + 팀원 §RPi scp 규칙 섹션 picking)
   - 팀원 추가 섹션 중 `### RPi scp 경로 규칙 (2026-05-18 사고에서 확립)` 만 내 측 §7 작업규칙 끝부분 (package.xml 함정 다음) 에 삽입
   - `*마지막 갱신:*` 라인 → `2026-05-19 (팀원 person_tracking + follow LiDAR 통합 머지)`
   - `*다음 갱신 예정:*` → `머지 빌드/import 검증 후 라이브 검증`

### Phase 5 — 함정 7건 정정 (15 min)

- [ ] **F1**: `person_tracking_pkg/package.xml <description>` em-dash → ASCII hyphen
- [ ] **F2**: 모델 가중치 별도 복사
  ```bash
  mkdir -p ~/moca/src/dobi_npc/person_tracking_pkg/models
  cp -v ~/moca_teammember/src/dobi_npc/person_tracking_pkg/models/yolov8n.pt \
        ~/moca/src/dobi_npc/person_tracking_pkg/models/
  cp -v ~/moca_teammember/src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task \
        ~/moca/src/dobi_npc/person_tracking_pkg/models/
  sha256sum ~/moca/src/dobi_npc/person_tracking_pkg/models/*
  ```
- [ ] **F3**: pip 설치 + cleanup
  ```bash
  pip install --user ultralytics boxmot
  # transitive cleanup 검증 — numpy/cv2 시스템 본 보호 ([[Phase 2 W4 함정]])
  python3 -c "import numpy; print(numpy.__version__, numpy.__file__)"  # 1.26.4 / /usr/lib/python3/dist-packages
  python3 -c "import cv2; print(cv2.__version__, cv2.__file__)"        # 4.6.0 / /usr/lib/python3/dist-packages
  # 만약 user site 의 2.x 가 들어왔다면 즉시 `pip uninstall --yes numpy opencv-contrib-python`
  ```
- [ ] **F4**: 워크스페이스 루트 `yolov8n.pt` 미존재 확인 (`ls ~/moca/yolov8n.pt 2>&1` → No such file)
- [ ] **F5**: `scripts/run_*.sh` 절대경로 잔재는 **본 머지 spec 에서는 보존**. 별 트랙으로 [[feedback_relative_path_convention]] 적용 후속.
- [ ] **F6, F7**: Phase 2 + Phase 3 에서 이미 처리됨

### Phase 6 — 빌드 + import 검증 (30 min)

```bash
cd ~/moca
# 격리 셸 빌드 (CLAUDE.md §7 검증 빌드 환경)
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  rm -rf build install log
  colcon build --symlink-install
'
```

검증 체크:
- [ ] `colcon build` 모든 패키지 통과 (특히 `dobi_npc_msgs` 12 msg + 5 srv 생성)
- [ ] `install/dobi_npc_msgs/share/dobi_npc_msgs/local_setup.bash` 존재 + `PersonTrack`, `PersonTrackArray` IDL 생성
- [ ] `install/person_tracking_pkg/share/person_tracking_pkg/` 존재 + **`hook/ament_prefix_path.sh` 존재** (F1 정정 확인)
- [ ] `install/person_tracking_pkg/share/person_tracking_pkg/models/yolov8n.pt` 존재
- [ ] `ros2 pkg list | grep person_tracking_pkg` 출력
- [ ] `ros2 interface show dobi_npc_msgs/msg/PersonTrack` 정상

Import smoke (no ROS spin):
- [ ] `python3 -c "from person_tracking_pkg import person_tracking_node"` (또는 `ros2 run --help` 식 진입점 확인)
- [ ] `python3 -c "from ultralytics import YOLO; from boxmot.trackers.botsort.botsort import BotSort"`
- [ ] `python3 -c "import mediapipe; print(mediapipe.__version__)"` → `0.10.14`

mode_manager 검증 (no spin):
- [ ] `python3 -c "from dobi_npc_bringup.mode_manager_node import VALID_MODES, LEGACY_MODE_ALIAS; assert 'follow' in VALID_MODES; assert 'follow' not in LEGACY_MODE_ALIAS"`

### Phase 7 — 회고 + commit (20 min)

- [ ] 본 머지 commit 메시지 작성:
  ```
  merge: integrate teammate person_tracking_pkg + follow LiDAR routing (18 commits)

  - person_tracking_pkg (YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose, 3 nodes)
  - approach_controller PD + LiDAR 거리 기반 follow_controller
  - Nav2 일괄 기동 스크립트 (run_nav2.sh, run_3stage.sh, stop_nav2.sh)
  - dobi_npc_msgs: PersonTrack/PersonTrackArray 2 msg 추가
  - mode_manager: 5-state → 6-state (follow + guiding 분리 운용, 사용자 결정)
  - mode_manager: NaN 배터리 처리 (라이브 미연결 환경)
  - CLAUDE.md: §RPi scp 경로 규칙 통합

  공통 조상 1a2971b, 양쪽 분기 commits 43 (내) + 18 (팀원).
  spec: docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md
  plan: docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md
  ```
- [ ] `docs/daily/2026-05-19_teammember_merge.md` 회고 작성 (변경 / 사고 / 발견 / 다음 일정)
- [ ] `git tag post-merge-teammember-20260519`

### Phase 8 — 라이브 검증 (별 트랙, 본 spec 범위 X)

본 spec 은 빌드/import 검증까지. 다음 항목은 별 spec 으로:
- person_tracking_node 실 카메라 (RPi `/robot_cam/image_raw`) 라이브 검증
- approach_controller PD 라이브 튜닝
- follow_controller LiDAR 거리 제어 라이브 (사용자 명시 `/cmd_vel 발행 X` 해제 후)
- F5 (절대경로 잔재) 후속 정정

---

## 4. Rollback (실패 시 회복)

### 4.1 가벼운 회복 — 머지만 취소

```bash
cd ~/moca
git merge --abort                # 충돌 중이면
git reset --hard pre-merge-teammember-20260519   # 머지 commit 후 후회 시
```

### 4.2 풀 회복 — 백업본에서 복원

```bash
# 1. 모든 작업 종료
bash ~/moca/scripts/stop_all.sh --hard

# 2. moca 백업본에서 복원
cd ~
mv moca moca.failed_merge_$(date +%Y%m%d_%H%M%S)
mkdir moca && cd moca
tar xzf ~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz
tar xzf ~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz
git status   # → fb9c1b9 일치 확인
git apply ~/backup/moca_merge_20260519/laptop/moca_unstaged.patch   # 5/18 시점 dirty 복원

# 3. 빌드
bash --noprofile --norc -c 'source /opt/ros/jazzy/setup.bash; cd ~/moca; colcon build --symlink-install'
```

### 4.3 팀원 측 회복 — 안전망

본 머지는 `~/moca_teammember/` 를 **read-only** 로 다룸 (fetch 만). 변경 X. 단 만약을 위해 `teammember/*.tar.gz` 백업 보존.

---

## 5. 검증 게이트 (각 Phase 종료 조건)

| Phase | 게이트 | 실패 시 |
|---|---|---|
| 1 | `sha256sum -c SHA256SUMS` 통과 + tar 무결성 | 백업 재시도 (디스크/권한) |
| 2 | `git status` clean | dirty 정리 또는 stash |
| 3 | merge 시작됨 (`git status` → `You have unmerged paths`) | 4.1 abort 후 재시도 |
| 4 | 5 파일 모두 `git add` + `git status` → `All conflicts fixed but you are still merging` | 충돌 마커 재검토 |
| 5 | 모델 파일 sha256 일치 + pip cleanup 확인 | F2/F3 재실행 |
| 6 | colcon 통과 + ros2 interface show + python import smoke 통과 | 4.1 abort 또는 4.2 풀 회복 |
| 7 | commit + tag + 회고 작성 완료 | — |

---

## 6. Open issues / 본 spec 범위 외

- **mode_follow + mode_guiding 분리 운용 시 운영 패널 UI 영향** — `moca_opserver` 의 mode chip / SetMode 호출이 `'follow'` 도 지원하나? **별 트랙으로 확인 필요** (본 spec 빌드 검증 단계엔 무관, 라이브 검증 시 발견 가능).
- **5-state FSM spec (`docs/moca_5state_fsm_spec.md`) 와 6-state 충돌** — 본 머지로 spec 과 코드 mismatch 발생. 6-state 로 spec 갱신 또는 follow 를 다시 alias 처리 결정 필요. 라이브 검증 트랙에서 사용자 + 팀원과 협의.
- **팀원 18 commits 의 라이브 검증 상태** — 팀원 측에서 person_tracking + follow LiDAR 가 라이브 검증 완료된 상태인지 확인 필요. 본 머지로 통합되는 것이지 검증되는 것 아님.
- **F5 절대경로 잔재** — `scripts/run_3stage.sh`, `run_nav2.sh` 의 `~/moca/` 잔재. CLAUDE.md §7 상대경로 컨벤션 위반. 본 spec 보존 결정 (Quick-fix), 별 트랙으로 SCRIPT_DIR 패턴 적용.
- **CLAUDE.md §11 navigation 분리 원칙 vs 팀원 run_nav2.sh** — `run_nav2.sh` 가 RPi bringup 재기동 시도 + Nav2 launch 직접 함. CLAUDE.md §11.1 의 `vicpinky_bringup 재기동 X` 와 충돌 가능. 라이브 검증 단계에서 사용자/팀원과 협의.

---

## 7. 참고 메모리

- [[user_assistant_name_doby]] — doby 4 덕목 (솔직/명확/꼼꼼/의리)
- [[feedback_daily_backup_routine]] — 일일 백업 루틴 (본 머지로 트리거)
- [[project_operation_architecture_pc_centric]] — PC SoT, rsync `--exclude=COLCON_IGNORE` (본 spec 은 `git fetch` 라 무관)
- [[project_zlac_velocity_mode_estop_dependency]] — 라이브 검증 진입 시 1순위 (본 spec 범위 외)
- [[project_navigation_code_separation]] — Open Issue (run_nav2.sh 와 충돌 가능)
- [[feedback_dont_touch_working_code]] — 본 머지의 핵심 원칙
- [[project_dds_wifi_multicast]] — DDS 정책 (`run_nav2.sh` 가 `ROS_STATIC_PEERS` 설정 — 정합)

---

*spec 작성: 2026-05-19 doby. 사용자 결정 4건 반영. 승인 후 implementation plan 생성.*
