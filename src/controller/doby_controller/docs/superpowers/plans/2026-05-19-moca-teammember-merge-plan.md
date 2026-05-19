# moca ↔ moca_teammember 병합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `~/moca_teammember/` 의 18 commit (person_tracking_pkg 신규 + approach_controller + follow LiDAR 거리 제어 + Nav2 스크립트) 을 `~/moca/` 로 git merge 로 통합하고, PC 측 빌드 + import 검증까지 통과시킨다.

**Architecture:** `git fetch` 로 팀원 head 가져온 뒤 `git merge --no-commit` 실행 → 5 파일 충돌 수동 해결 → 모델 가중치 별도 cp + pip 의존성 설치 + cleanup → colcon 격리 셸 빌드 → ros2 interface + python import smoke. 라이브 검증은 본 plan 범위 외.

**Tech Stack:** git (merge / fetch / tag), bash + tar/sha256sum (백업), colcon + ROS2 Jazzy (빌드), pip user site (ultralytics/boxmot), ament_python (person_tracking_pkg), ament_cmake (dobi_npc_msgs).

**Spec:** `docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md` — 사용자 결정 4건 (옵션 A merge / mode_follow+guiding 분리 운용 / pip 즉시 설치 / 양쪽 풀 백업) 반영.

**전제 / 제약:**
- 사용자 명시 (5/18 세션 마지막) `"/cmd_vel 발행 X, 실수 X"` 유지 — 본 plan 은 PC only, RPi 접근 X.
- §0-A 팀 RPi 사용 신호 시 RPi 접근 금지 — 본 plan 은 `~/moca_teammember/` 를 read-only 로만 다룸 (fetch only).
- 작업 디렉토리: `~/moca` (별도 worktree 사용 X — git merge 결과를 main 에 직접 반영).

---

## Task 0: 진입 조건 점검

**Files:** read-only 검증만, 변경 X

- [ ] **Step 0.1: PC ros2 daemon 상태 확인**

Run:
```bash
pgrep -af 'ros2 daemon|ros2 launch|colcon'
```
Expected: 출력 없음 (idle). 출력 있으면 사용자에게 보고 후 정리 승인 받기.

- [ ] **Step 0.2: PC moca 워크스페이스 프로세스 확인**

Run:
```bash
pgrep -af 'opserver|teleop_server|moca|bt_executor|mode_manager'
```
Expected: 출력 없음. 출력 있으면 `bash ~/moca/scripts/stop_all.sh` 실행 (있을 경우) 또는 사용자 보고.

- [ ] **Step 0.3: RPi 미접근 확인 (read-only ping 만)**

Run:
```bash
ping -c 1 -W 2 192.168.0.138 && echo "RPi alive" || echo "RPi unreachable"
```
Expected: 양쪽 다 OK — 본 plan 은 RPi 안 건드리므로 alive/unreachable 무관. 단 사용자에게 §0-A 신호 (다른 팀원 사용 중) 없는지 확인.

- [ ] **Step 0.4: 두 저장소 HEAD 일치 확인**

Run:
```bash
cd ~/moca && git log --oneline -1
cd ~/moca_teammember && git log --oneline -1
```
Expected:
```
~/moca:            fb9c1b9 home dock vs staging 분리 + Nav2 combo 시도 (DDS sim fragility 로 중단)
~/moca_teammember: fd62971 docs: 2026-05-18 follow 모드 LiDAR 거리 제어 + twist_mux 라우팅 수정 + 3단계 검증 작업기록
```
FAIL 시 사용자에게 head 차이 보고 후 stop.

- [ ] **Step 0.5: 디스크 여유 확인**

Run:
```bash
df -h ~ | tail -1
```
Expected: Avail ≥ 5GB. 부족하면 사용자에게 보고.

- [ ] **Step 0.6: spec 문서 존재 확인**

Run:
```bash
ls -la ~/moca/docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md
```
Expected: 파일 존재. 없으면 stop.

---

## Task 1: 백업 디렉토리 생성 + 메타 수집

**Files:**
- Create: `~/backup/moca_merge_20260519/laptop/git_state.txt`
- Create: `~/backup/moca_merge_20260519/teammember/git_state.txt`

- [ ] **Step 1.1: 백업 루트 디렉토리 생성**

Run:
```bash
mkdir -p ~/backup/moca_merge_20260519/{laptop,teammember}
ls -la ~/backup/moca_merge_20260519/
```
Expected: 2 디렉토리 (laptop, teammember) 생성.

- [ ] **Step 1.2: laptop 측 git 메타 수집**

Run:
```bash
cd ~/moca
{
  echo "=== git status (no -uall) ==="
  git status
  echo
  echo "=== git log -20 ==="
  git log --oneline -20
  echo
  echo "=== git branch -a ==="
  git branch -a
  echo
  echo "=== git tag (최근 10) ==="
  git tag --sort=-creatordate | head -10
  echo
  echo "=== git remote -v ==="
  git remote -v
} > ~/backup/moca_merge_20260519/laptop/git_state.txt
wc -l ~/backup/moca_merge_20260519/laptop/git_state.txt
```
Expected: 라인 수 50~200 사이.

- [ ] **Step 1.3: teammember 측 git 메타 수집**

Run:
```bash
cd ~/moca_teammember
{
  echo "=== git status ==="
  git status
  echo
  echo "=== git log -20 ==="
  git log --oneline -20
  echo
  echo "=== git branch -a ==="
  git branch -a
  echo
  echo "=== git remote -v ==="
  git remote -v
} > ~/backup/moca_merge_20260519/teammember/git_state.txt
wc -l ~/backup/moca_merge_20260519/teammember/git_state.txt
```
Expected: 라인 수 30~100 사이.

- [ ] **Step 1.4: 양쪽 unstaged + staged patch 저장**

Run:
```bash
cd ~/moca
git diff > ~/backup/moca_merge_20260519/laptop/moca_unstaged.patch
git diff --cached > ~/backup/moca_merge_20260519/laptop/moca_staged.patch

cd ~/moca_teammember
git diff > ~/backup/moca_merge_20260519/teammember/moca_teammember_unstaged.patch
git diff --cached > ~/backup/moca_merge_20260519/teammember/moca_teammember_staged.patch

ls -la ~/backup/moca_merge_20260519/laptop/*.patch ~/backup/moca_merge_20260519/teammember/*.patch
```
Expected: 4 patch 파일 생성 (크기 0 이어도 OK — clean tree 의미).

---

## Task 2: 양쪽 풀 tar 백업 + sha256

**Files:**
- Create: `~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz`
- Create: `~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz`
- Create: `~/backup/moca_merge_20260519/teammember/moca_teammember_src_fd62971.tar.gz`
- Create: `~/backup/moca_merge_20260519/teammember/moca_teammember_dotgit_fd62971.tar.gz`
- Create: `~/backup/moca_merge_20260519/teammember/moca_teammember_untracked.tar.gz`
- Create: `~/backup/moca_merge_20260519/teammember/person_tracking_models.tar.gz`
- Create: `~/backup/moca_merge_20260519/SHA256SUMS`

- [ ] **Step 2.1: 내 측 src tree 백업 (build/install/log/.venv 제외)**

Run:
```bash
cd ~/moca
tar czf ~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz \
  --exclude='./build' --exclude='./install' --exclude='./log' \
  --exclude='./.venv' --exclude='./maps' --exclude='./datasets' \
  --exclude='./web/static' --exclude='./models' \
  --exclude='./.git' \
  src scripts config docs games tests tools \
  CLAUDE.md README.md moca.repos requirements.txt .gitignore .pytest_cache 2>&1 | tail -5
ls -la ~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz
```
Expected: tar.gz 크기 30~80MB.

- [ ] **Step 2.2: 내 측 .git 백업 (history 보존)**

Run:
```bash
cd ~/moca
tar czf ~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz .git
ls -la ~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz
```
Expected: tar.gz 크기 10~30MB.

- [ ] **Step 2.3: 팀원 측 src tree 백업 (build/install/log/.venv 제외)**

Run:
```bash
cd ~/moca_teammember
tar czf ~/backup/moca_merge_20260519/teammember/moca_teammember_src_fd62971.tar.gz \
  --exclude='./build' --exclude='./install' --exclude='./log' --exclude='./logs' \
  --exclude='./.venv' --exclude='./maps' --exclude='./datasets' \
  --exclude='./web/static' --exclude='./models' \
  --exclude='./.git' --exclude='./group.png' --exclude='./yolov8n.pt' \
  src scripts docs games _backups \
  CLAUDE.md README.md moca.repos requirements.txt .gitignore 2>&1 | tail -5
ls -la ~/backup/moca_merge_20260519/teammember/moca_teammember_src_fd62971.tar.gz
```
Expected: tar.gz 크기 5~20MB.

- [ ] **Step 2.4: 팀원 측 .git 백업**

Run:
```bash
cd ~/moca_teammember
tar czf ~/backup/moca_merge_20260519/teammember/moca_teammember_dotgit_fd62971.tar.gz .git
ls -la ~/backup/moca_merge_20260519/teammember/moca_teammember_dotgit_fd62971.tar.gz
```
Expected: tar.gz 크기 5~20MB.

- [ ] **Step 2.5: 팀원 측 untracked 3 자산 백업 (.claude, group.png, yolov8n.pt)**

Run:
```bash
cd ~/moca_teammember
tar czf ~/backup/moca_merge_20260519/teammember/moca_teammember_untracked.tar.gz \
  .claude group.png yolov8n.pt 2>&1 | tail -5
ls -la ~/backup/moca_merge_20260519/teammember/moca_teammember_untracked.tar.gz
```
Expected: tar.gz 크기 6~8MB (yolov8n.pt 가 대부분).

- [ ] **Step 2.6: 팀원 측 person_tracking_pkg/models 별도 백업 (gitignore 됨)**

Run:
```bash
cd ~/moca_teammember
tar czf ~/backup/moca_merge_20260519/teammember/person_tracking_models.tar.gz \
  src/dobi_npc/person_tracking_pkg/models 2>&1 | tail -5
tar tzf ~/backup/moca_merge_20260519/teammember/person_tracking_models.tar.gz
```
Expected: tar 내용:
```
src/dobi_npc/person_tracking_pkg/models/
src/dobi_npc/person_tracking_pkg/models/yolov8n.pt
src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task
```
크기 약 12MB.

- [ ] **Step 2.7: SHA256SUMS 생성 + 검증**

Run:
```bash
cd ~/backup/moca_merge_20260519
find laptop teammember -type f \( -name '*.tar.gz' -o -name '*.patch' -o -name 'git_state.txt' \) \
  | sort | xargs sha256sum > SHA256SUMS
cat SHA256SUMS | wc -l
sha256sum -c SHA256SUMS 2>&1 | tail -20
```
Expected: 약 9~10 라인 (4 tar + 4 patch + 2 git_state) + 모두 `OK` 출력.

- [ ] **Step 2.8: 회복 절차 README 작성**

Run:
```bash
cat > ~/backup/moca_merge_20260519/README.md << 'EOF'
# moca ↔ moca_teammember 머지 백업 (2026-05-19)

## 시점
- 머지 시작 직전 (Phase 1 종료)
- 내 측 HEAD: fb9c1b9
- 팀원 측 HEAD: fd62971
- 공통 조상: 1a2971b

## 회복 시나리오 3종

### 시나리오 A: 양쪽 모두 풀 회복
```bash
bash ~/moca/scripts/stop_all.sh --hard  # 모든 작업 종료
cd ~
mv moca moca.failed_$(date +%Y%m%d_%H%M%S)
mv moca_teammember moca_teammember.failed_$(date +%Y%m%d_%H%M%S)

mkdir moca && cd moca
tar xzf ~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz
tar xzf ~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz
git apply ~/backup/moca_merge_20260519/laptop/moca_unstaged.patch || true

cd ~ && mkdir moca_teammember && cd moca_teammember
tar xzf ~/backup/moca_merge_20260519/teammember/moca_teammember_dotgit_fd62971.tar.gz
tar xzf ~/backup/moca_merge_20260519/teammember/moca_teammember_src_fd62971.tar.gz
tar xzf ~/backup/moca_merge_20260519/teammember/person_tracking_models.tar.gz
tar xzf ~/backup/moca_merge_20260519/teammember/moca_teammember_untracked.tar.gz
```

### 시나리오 B: 내 측만 회복 (머지 취소)
```bash
cd ~/moca
git merge --abort 2>/dev/null || true
git reset --hard pre-merge-teammember-20260519
# 빌드 재시도
bash --noprofile --norc -c 'source /opt/ros/jazzy/setup.bash; rm -rf build install log; colcon build --symlink-install'
```

### 시나리오 C: 팀원 측만 회복
```bash
cd ~ && rm -rf moca_teammember.broken && mv moca_teammember moca_teammember.broken
mkdir moca_teammember && cd moca_teammember
tar xzf ~/backup/moca_merge_20260519/teammember/moca_teammember_dotgit_fd62971.tar.gz
tar xzf ~/backup/moca_merge_20260519/teammember/moca_teammember_src_fd62971.tar.gz
tar xzf ~/backup/moca_merge_20260519/teammember/person_tracking_models.tar.gz
```

## 검증
```bash
cd ~/backup/moca_merge_20260519 && sha256sum -c SHA256SUMS
```
EOF
ls -la ~/backup/moca_merge_20260519/README.md
```
Expected: README.md 생성됨 (약 1.5KB).

---

## Task 3: 내 측 dirty 정리 (3 별 commit)

**Files:**
- Modify: `~/moca/games/01_cafe_ninja/src/*.py` (이미 변경됨, 의도 검토)
- Modify: `~/moca/scripts/stop_all.sh` (untracked 추가)
- Modify: `~/moca/docs/daily/2026-05-18*.md` (untracked 2건 추가)

- [ ] **Step 3.1: cafe_ninja 변경 검토**

Run:
```bash
cd ~/moca
git diff --stat games/01_cafe_ninja/ 2>&1
git status -s games/01_cafe_ninja/ 2>&1
```
Expected: 7 modified + 7 untracked files in `games/01_cafe_ninja/`. 검토 후 의도된 변경 확인.

- [ ] **Step 3.2: cafe_ninja 변경 commit**

Run:
```bash
cd ~/moca
git add games/01_cafe_ninja/
git status -s | head
git commit -m "cafe_ninja: sprite + ninja silhouette + tests 추가 + theme/ui_renderer 정리

5/18 작업분. ninja_silhouette/cafe_ninja_sprite 신규 노드 + ui_renderer 갱신.
머지 전 별 commit 으로 분리 — 본 머지(2026-05-19 팀원 통합)와 무관.
"
git log --oneline -1
```
Expected: 새 commit hash 출력 + 변경 lines 50+.

- [ ] **Step 3.3: scripts/stop_all.sh commit**

Run:
```bash
cd ~/moca
git add scripts/stop_all.sh
git status -s
git commit -m "scripts/stop_all.sh: PC + RPi 일괄 종료 wrapper

5/18 세션 1 작업분. stop_moca.sh + stop_robot_cam.sh + stop_vic_bringup.sh
+ stop_sim.sh 묶음. --hard / --purge-shm 옵션 포함. 회고
docs/daily/2026-05-18_rpi_live_attempt_pc_sot_sync_incident.md §1 참조.
"
git log --oneline -1
```
Expected: 새 commit hash 출력.

- [ ] **Step 3.4: docs/daily 2 회고 commit**

Run:
```bash
cd ~/moca
git add docs/daily/2026-05-18_rpi_live_attempt_pc_sot_sync_incident.md \
        docs/daily/2026-05-18b_session2_bringup_revival_short.md
git status -s
git commit -m "docs: 2026-05-18 회고 2건 (RPi 라이브 시도 + 세션 2 bringup 재시도)

세션 1: PC SoT sync 사고 + teleop WASD 미해결 + 5/14 백업 복원
세션 2: bringup 9 노드 spawn 성공, 토픽 검증 미진입
"
git log --oneline -1
```
Expected: 새 commit hash 출력.

- [ ] **Step 3.5: clean tree 검증**

Run:
```bash
cd ~/moca
git status
```
Expected: `nothing to commit, working tree clean`. 만약 untracked 잔재 있으면 별도 검토.

---

## Task 4: pre-merge safety tag + branch

**Files:** git tag + branch only

- [ ] **Step 4.1: pre-merge tag 생성**

Run:
```bash
cd ~/moca
git tag pre-merge-teammember-20260519
git tag --list | grep teammember
```
Expected: `pre-merge-teammember-20260519` 출력.

- [ ] **Step 4.2: pre-merge branch 생성 (현 HEAD 보존)**

Run:
```bash
cd ~/moca
git branch backup-pre-merge-teammember-20260519
git branch -a | grep teammember
```
Expected: `backup-pre-merge-teammember-20260519` 출력.

- [ ] **Step 4.3: 현 HEAD 기록**

Run:
```bash
cd ~/moca
git rev-parse HEAD > /tmp/moca_pre_merge_head.txt
cat /tmp/moca_pre_merge_head.txt
```
Expected: 40 자 hash + Task 3 commit 3건 반영된 head (fb9c1b9 + 3 commit ahead).

---

## Task 5: git fetch + merge --no-commit

**Files:** git operations only

- [ ] **Step 5.1: 팀원 head fetch**

Run:
```bash
cd ~/moca
git fetch ~/moca_teammember main 2>&1 | tail -5
git rev-parse FETCH_HEAD
```
Expected: `fd62971...` 출력 (팀원 head).

- [ ] **Step 5.2: merge-base 재확인 (공통 조상)**

Run:
```bash
cd ~/moca
git merge-base HEAD FETCH_HEAD
```
Expected: `1a2971b5ab076a76634c0c5085afa3fa1f5d8b4e` 그대로.

- [ ] **Step 5.3: merge --no-commit 시도**

Run:
```bash
cd ~/moca
git merge --no-commit --no-ff FETCH_HEAD \
  -m "merge: integrate teammate person_tracking_pkg + follow LiDAR routing (18 commits)" \
  2>&1 | tee /tmp/moca_merge_output.txt
```
Expected: 출력에 `CONFLICT` 라인 5개 (5 파일 충돌) + 마지막에 `Automatic merge failed; fix conflicts and then commit the result.`

- [ ] **Step 5.4: 충돌 파일 5건 확인**

Run:
```bash
cd ~/moca
git diff --name-only --diff-filter=U
```
Expected (정확히 5 파일):
```
CLAUDE.md
src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py
src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py
src/dobi_npc/dobi_npc_msgs/CMakeLists.txt
```
FAIL 시 충돌 파일 수 다르면 사용자에게 보고.

- [ ] **Step 5.5: 신규 파일 추가 확인 (팀원-only, 충돌 X)**

Run:
```bash
cd ~/moca
git diff --name-only --diff-filter=A HEAD 2>&1 | head -30
```
Expected 신규 파일 약 23개 (person_tracking_pkg 8 + msg 2 + scripts 3 + docs 6 + _backups 2 + follow_controller_node 등). 일부 발췌:
```
_backups/vicpinky_navigation_launch/bringup_launch.xml.bak_20260514_105256
_backups/vicpinky_navigation_launch/navigation_launch.xml.bak_20260514_105256
docs/daily/2026-05-14_integration_person_tracking.md
...
src/dobi_npc/person_tracking_pkg/setup.py
```

---

## Task 6: 충돌 해결 #1 — dobi_npc_msgs/CMakeLists.txt (union)

**Files:**
- Modify: `~/moca/src/dobi_npc/dobi_npc_msgs/CMakeLists.txt`

- [ ] **Step 6.1: 충돌 마커 확인**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_msgs/CMakeLists.txt
```
Expected: 충돌 마커 라인 출력 (3 라인 — `<<<<<<< HEAD`, `=======`, `>>>>>>>`).

- [ ] **Step 6.2: union 으로 해결**

Edit `~/moca/src/dobi_npc/dobi_npc_msgs/CMakeLists.txt` — 충돌 블록을 다음으로 완전 교체 (충돌 마커 모두 제거):

```cmake
cmake_minimum_required(VERSION 3.8)
project(dobi_npc_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/EmotionState.msg"
  "msg/RapportEvent.msg"
  "msg/MinigameResult.msg"
  "msg/UtterRequest.msg"
  "msg/ModeState.msg"
  "msg/PatrolState.msg"
  "msg/TableReport.msg"
  "msg/GuidingState.msg"
  "msg/OpEvent.msg"
  "msg/OperatorCommand.msg"
  "msg/PersonTrack.msg"
  "msg/PersonTrackArray.msg"
  "srv/SetPersona.srv"
  "srv/SetMode.srv"
  "srv/GetTableStatus.srv"
  "srv/SetPatrolSchedule.srv"
  "srv/ScanTable.srv"
  DEPENDENCIES std_msgs builtin_interfaces sensor_msgs
)

ament_export_dependencies(rosidl_default_runtime)
```

(BUILD_TESTING 블록은 원래대로 유지 — 본 step 은 `rosidl_generate_interfaces` 블록 + find_package 위 부분만 다룸. 파일 끝의 `if(BUILD_TESTING) ... endif()` + `ament_package()` 는 변경 X.)

- [ ] **Step 6.3: 충돌 마커 제거 검증**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_msgs/CMakeLists.txt && echo "FAIL: 마커 잔재" || echo "OK: 마커 제거됨"
```
Expected: `OK: 마커 제거됨`.

- [ ] **Step 6.4: msg + srv 라인 수 검증**

Run:
```bash
cd ~/moca
grep -c '"msg/' src/dobi_npc/dobi_npc_msgs/CMakeLists.txt
grep -c '"srv/' src/dobi_npc/dobi_npc_msgs/CMakeLists.txt
```
Expected: msg 12 라인, srv 5 라인.

- [ ] **Step 6.5: git add 로 충돌 해결 표시**

Run:
```bash
cd ~/moca
git add src/dobi_npc/dobi_npc_msgs/CMakeLists.txt
git diff --name-only --diff-filter=U
```
Expected: 충돌 파일 4개 남음 (CMakeLists.txt 제거됨).

---

## Task 7: 충돌 해결 #2 — dev_common.launch.py (내 base + 팀원 3 노드 append)

**Files:**
- Modify: `~/moca/src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py`

- [ ] **Step 7.1: 충돌 마커 확인**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py
```
Expected: 충돌 마커 라인 출력.

- [ ] **Step 7.2: docstring 9-node 로 갱신**

파일 상단 docstring (첫 줄 `"""dev_common.launch.py` 부터 `"""` 닫기까지) 을 다음으로 교체 (충돌 마커 포함된 docstring 영역만):

```python
"""dev_common.launch.py — 공통 always-on 층 (B 단계).

mode_manager 가 모드별 stack 을 spawn/kill 할 때 살아있어야 하는 노드들.
모드와 무관하게 항상 켜져 있는 인지/표현/오케스트레이션 9 노드.

구성:
  geva_node             (웹캠 → /emotion/state)
  rapport_tracker       (/emotion/state → /rapport/event)
  persona_manager       (/dialog/request → /dialog/router_in)
  dialog_router         (/dialog/router_in → /dialog/utter)
  face_avatar           (/face_avatar/expression → 풀스크린/윈도우 GIF 표시)
  tts_node              (/dialog/utter → 음성 출력)
  mode_manager          (/mode/request, /mode/state, mode stack spawn/kill)
  person_tracking_node  (/robot_cam/image_raw → /person_tracking/tracks)
  group_approach_node   (/person_tracking/tracks → /person_tracking/approach_target)
  approach_controller_node (/person_tracking/approach_target → /cmd_vel)

person_tracking_node 전제: run_robot_cam.sh 로 /robot_cam/image_raw 가 발행 중이어야 함.

mode_manager 가 spawn 하는 모드별 stack 은 별도 launch:
  mode_engaging.launch.py  (bt_executor, cafe_funnel_v1.xml)
  mode_serving.launch.py   (Nav2 + serving_dispatcher)
  mode_patrol.launch.py    (Nav2 + patrol scheduler)
  mode_guiding.launch.py   (Nav2 + guiding_controller, M1 임시 follow stack 재사용)
  mode_follow.launch.py    (follow_controller — LiDAR 거리 기반)

launch 인자:
  fullscreen:=true|false   face_avatar 풀스크린 (기본 false)
  default_persona:=...     persona_manager 기본 페르소나 (기본 casual_browser)
  initial_mode:=idle|serving|patrol|guiding|engaging|follow   mode_manager 초기 모드 (기본 idle)
                                                              legacy npc 도 자동 변환 (M3 종료까지)

검증 시동: ros2 launch dobi_npc_bringup dev_common.launch.py
운영자 패널: bash scripts/run_operator_ui.sh (워크스페이스 루트에서, 별 터미널)
모드 전환: 운영자 패널 또는 ros2 service call /mode/request
"""
```

- [ ] **Step 7.3: LaunchDescription 끝 부분에 팀원 3 노드 append**

파일 끝 `LaunchDescription([` 안의 마지막 노드 (`mode_manager` Node) 다음, 닫는 `])` 직전에 다음 3 노드 블록 삽입 (충돌 마커 모두 제거하면서):

```python
        Node(
            package='person_tracking_pkg', executable='person_tracking_node',
            name='person_tracking_node', output='screen',
            parameters=[{
                'input_topic': '/robot_cam/image_raw',
                'use_compressed': True,
                'publish_visualization': True,
                'dbscan_eps': 50.0,   # [멀티그룹 테스트용] 프린트 분리 — 실물 시 450.0으로 원복
            }],
        ),
        Node(
            package='person_tracking_pkg', executable='group_approach_node',
            name='group_approach_node', output='screen',
            parameters=[{
                'min_group_size': 1,
            }],
        ),
        Node(
            package='person_tracking_pkg', executable='approach_controller_node',
            name='approach_controller_node', output='screen',
            parameters=[{
                'linear_speed':    0.15,
                'angular_gain':    1.8,   # Kp
                'derivative_gain': 0.3,   # Kd
                'ema_alpha':       0.3,   # D항 노이즈 필터 (작을수록 강한 필터)
                'dead_zone':       0.05,
                'close_threshold': 0.999,  # bbox 높이 비율 기준 (0~1, 클수록 가까움)
                'pose_timeout':    1.0,
            }],
        ),
    ])
```

- [ ] **Step 7.4: 충돌 마커 + 구문 검증**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py && echo "FAIL: 마커 잔재" || echo "OK: 마커 제거됨"
python3 -c "
import ast
with open('src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py') as f:
    ast.parse(f.read())
print('OK: Python syntax valid')
"
```
Expected: `OK: 마커 제거됨` + `OK: Python syntax valid`.

- [ ] **Step 7.5: 노드 갯수 검증**

Run:
```bash
cd ~/moca
grep -c "^        Node(" src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py
```
Expected: 9 (geva + rapport + persona + dialog_router + face_avatar + tts + mode_manager + 3 person_tracking).

- [ ] **Step 7.6: git add**

Run:
```bash
cd ~/moca
git add src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py
git diff --name-only --diff-filter=U
```
Expected: 충돌 파일 3개 남음.

---

## Task 8: 충돌 해결 #3 — mode_manager_node.py (FSM 6-state + NaN 패치)

**Files:**
- Modify: `~/moca/src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py`

- [ ] **Step 8.1: 충돌 마커 확인**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
```
Expected: 충돌 마커 라인 출력.

- [ ] **Step 8.2: 충돌 마커 1차 처리 — 내 측 본 채택**

먼저 충돌 마커를 내 측 (HEAD) 본으로 모두 해결. 즉 `<<<<<<< HEAD ... ======= ... >>>>>>> FETCH_HEAD` 블록에서 `<<<<<<< HEAD` 와 `=======` 사이의 내용만 남기고 나머지 (마커 + 팀원 본) 제거.

명령:
```bash
cd ~/moca
# 충돌 마커가 1군데인지 확인 (mode_manager 는 _on_battery 한 군데만 충돌 예상)
grep -c '<<<<<<<' src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
```
Expected: `1` (충돌 1군데).

수동 편집 (Edit 도구): 충돌 블록을 내 측 (HEAD) 본 — 즉 단일 라인 `self._battery_pct = float(msg.percentage)` 으로 해결. 단 이 시점에선 NaN 패치 미적용 — 다음 step 에서 적용.

`<<<<<<< HEAD` 부터 `>>>>>>> FETCH_HEAD` 까지의 충돌 블록을 다음으로 교체 (충돌 마커 모두 제거):

```python
    def _on_battery(self, msg: BatteryState):
        self._battery_pct = float(msg.percentage)
```

(주의: `def _on_battery(self, msg: BatteryState):` 라인은 충돌 블록 **밖** 일 가능성 — 충돌 마커가 함수 본문만 감쌌는지 또는 함수 시그니처까지 감쌌는지 확인 후 정확한 블록 교체.)

- [ ] **Step 8.3: 팀원 NaN 패치 적용 (math.isfinite check)**

`_on_battery` 메서드 본문을 다음으로 교체:

```python
    def _on_battery(self, msg: BatteryState):
        import math
        pct = float(msg.percentage)
        # NaN은 미수신(-1.0)으로 처리 → _battery_ok()에서 True 반환 (라이브 미연결 환경)
        self._battery_pct = pct if math.isfinite(pct) else -1.0
```

- [ ] **Step 8.4: VALID_MODES 에 'follow' 추가**

파일 line 67 부근 `VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging')` 를 다음으로 교체:

```python
VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')
```

- [ ] **Step 8.5: LEGACY_MODE_ALIAS 에서 'follow' 제거**

파일 line 69-73 부근 `LEGACY_MODE_ALIAS = { ... }` 블록을 다음으로 교체:

```python
# M3 종료(2026-07-04) 후 제거 예정. WARN 로그 후 자동 변환.
# 2026-05-19 머지: follow 는 mode_guiding 과 분리 운용하므로 alias 에서 제거.
LEGACY_MODE_ALIAS = {
    'npc': 'engaging',
}
```

- [ ] **Step 8.6: docstring 5-state → 6-state 표기 갱신**

파일 상단 docstring 의 `5-state FSM (2026-05-16 확장, ...)` 라인을 찾아 다음으로 교체:

```python
6-state FSM (2026-05-19 확장 — follow + guiding 분리 운용, docs/moca_5state_fsm_spec.md SoT):
```

그리고 그 아래 4 mode 리스트 다음에 follow 라인 추가:

```python
  follow    — 1인 reactive 추종 (person_tracking + approach_controller + LiDAR 거리). priority 4.
```

(기존 idle/serving/patrol/guiding/engaging 5 라인 + follow 1 라인 = 총 6 라인)

LEGACY 블록도 갱신:

```python
Legacy alias (M3 종료 2026-07-04 까지만 지원, WARN 로그 후 자동 변환):
  npc -> engaging
```

(기존 `follow -> guiding` 라인 제거)

- [ ] **Step 8.7: 충돌 마커 + 구문 검증**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py && echo "FAIL: 마커 잔재" || echo "OK: 마커 제거됨"
python3 -c "
import ast
with open('src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py') as f:
    ast.parse(f.read())
print('OK: Python syntax valid')
"
```
Expected: `OK: 마커 제거됨` + `OK: Python syntax valid`.

- [ ] **Step 8.8: VALID_MODES + LEGACY_MODE_ALIAS 검증**

Run:
```bash
cd ~/moca
grep -n "VALID_MODES\s*=" src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
grep -A 4 "LEGACY_MODE_ALIAS\s*=" src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py | head -6
```
Expected:
```
67:VALID_MODES = ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')
```
그리고 LEGACY_MODE_ALIAS 블록에 `'npc': 'engaging',` 한 줄만 (follow 제거됨).

- [ ] **Step 8.9: _on_battery NaN 패치 검증**

Run:
```bash
cd ~/moca
grep -A 4 "def _on_battery" src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py | head -6
```
Expected: `math.isfinite` 라인 포함.

- [ ] **Step 8.10: git add**

Run:
```bash
cd ~/moca
git add src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/mode_manager_node.py
git diff --name-only --diff-filter=U
```
Expected: 충돌 파일 2개 남음.

---

## Task 9: 충돌 해결 #4 — mode_follow.launch.py (팀원 본 채택)

**Files:**
- Modify: `~/moca/src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py`

- [ ] **Step 9.1: 충돌 파일 전체 교체 — 팀원 본 (FETCH_HEAD) 채택**

Run:
```bash
cd ~/moca
git checkout --theirs src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py
git diff --name-only --diff-filter=U
```
Expected:
- `git checkout --theirs` 출력 없음 (or 짧은 메시지)
- mode_follow.launch.py 가 unmerged 목록에서 제거됨 (또는 git add 단계까지 다시 unmerged)

- [ ] **Step 9.2: 채택 결과 검증 — 팀원 변경 적용 확인**

Run:
```bash
cd ~/moca
grep -n "kp_angular\|target_dist\|align_gate" src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py | head -10
```
Expected:
- `'kp_angular': 0.5,` 라인 존재 (1.2 가 아닌 0.5)
- `'target_dist': 0.30` 라인 존재
- `'align_gate': 0.0,` 라인 존재

- [ ] **Step 9.3: 구문 검증**

Run:
```bash
cd ~/moca
python3 -c "
import ast
with open('src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py') as f:
    ast.parse(f.read())
print('OK: Python syntax valid')
"
```
Expected: `OK: Python syntax valid`.

- [ ] **Step 9.4: git add**

Run:
```bash
cd ~/moca
git add src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py
git diff --name-only --diff-filter=U
```
Expected: 충돌 파일 1개 남음 (CLAUDE.md).

---

## Task 10: 충돌 해결 #5 — CLAUDE.md (내 base + 팀원 §RPi scp 섹션 picking)

**Files:**
- Modify: `~/moca/CLAUDE.md`

- [ ] **Step 10.1: 충돌 마커 확인**

Run:
```bash
cd ~/moca
grep -n '<<<<<<<\|=======\|>>>>>>>' CLAUDE.md | head -20
```
Expected: 충돌 마커 라인 출력. 위치 기록.

- [ ] **Step 10.2: 내 측 본 (HEAD) 채택 — 충돌 마커 모두 ours 로 해결**

Run:
```bash
cd ~/moca
git checkout --ours CLAUDE.md
grep -n '<<<<<<<\|=======\|>>>>>>>' CLAUDE.md && echo "FAIL" || echo "OK: ours 채택, 마커 제거됨"
```
Expected: `OK: ours 채택, 마커 제거됨`.

- [ ] **Step 10.3: 팀원 §RPi scp 규칙 섹션 추출**

Run:
```bash
cd ~/moca_teammember
git show fd62971:CLAUDE.md | sed -n '/^### RPi scp 경로 규칙/,/^### /p' | sed '$d' > /tmp/rpi_scp_section.txt
cat /tmp/rpi_scp_section.txt
wc -l /tmp/rpi_scp_section.txt
```
Expected: 약 17 라인 — `### RPi scp 경로 규칙 (2026-05-18 사고에서 확립)` 으로 시작, scp 명령 + 주의사항 포함.

- [ ] **Step 10.4: §package.xml 함정 다음 anchor 위치 확인**

Run:
```bash
cd ~/moca
grep -n "^### " CLAUDE.md | grep -B1 -A1 "package.xml\|언어"
```
Expected:
```
401:### package.xml 작성 함정 (Phase 2 W4에서 발견)
407:### 언어
```

- [ ] **Step 10.5: §package.xml 끝 (406) 과 §언어 (407) 사이에 §RPi scp 섹션 삽입**

Edit `~/moca/CLAUDE.md` — line 406 (`- **패키지명/버전/메인테이너 등 다른 필드는 영향 없음** — `<description>` 노드만 함정.`) 다음 빈 줄 + `/tmp/rpi_scp_section.txt` 내용 + 빈 줄 삽입. 결과적으로 `### 언어` 가 새 섹션 다음으로 밀림.

삽입할 내용 (`/tmp/rpi_scp_section.txt` 의 내용):

```markdown
### RPi scp 경로 규칙 (2026-05-18 사고에서 확립)

**`run_vic_bringup.sh`는 `~/vicpinky_ws`에서 bringup을 실행한다. `~/moca`로 scp해도 RPi에 적용 안 됨.**

vicpinky_bringup 파일을 RPi에 반영할 때는 아래 두 경로 모두 전송해야 한다:

```bash
# 소스
scp <파일> vic@192.168.0.138:~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/launch/<파일명>

# install
scp <파일> vic@192.168.0.138:~/vicpinky_ws/install/vicpinky_bringup/share/vicpinky_bringup/launch/<파일명>
```

- scp 후 반드시 **bringup 재시작** 필요 — 실행 중인 프로세스에는 미적용
- velocity_smoother 출력 토픽 내부명: `cmd_vel_smoothed` (`smoothed_cmd_vel` 아님)
```

(주의: 내부 backtick 코드 펜스는 outer markdown 안에서 그대로 유지. Edit 도구 사용 시 정확한 indentation + 빈 줄 보존.)

- [ ] **Step 10.6: 마지막 갱신 라인 갱신**

`CLAUDE.md` 파일 끝 부분 (line ~671):
```
*마지막 갱신: 2026-05-14 (§11 추가 — Navigation 분리 원칙 + R1/R2 root cause 명문화. 일일 백업 §7 추가)*
*다음 갱신 예정: R1+R2 patch 라이브 검증 후*
```

다음으로 교체:

```
*마지막 갱신: 2026-05-19 (팀원 person_tracking + follow LiDAR 통합 머지 — §RPi scp 규칙 추가, mode_manager 6-state)*
*다음 갱신 예정: 머지 빌드/import 검증 후 라이브 검증*
```

- [ ] **Step 10.7: 삽입 결과 검증**

Run:
```bash
cd ~/moca
grep -n "### RPi scp 경로 규칙\|### package.xml 작성 함정\|### 언어" CLAUDE.md | head -5
grep -n "마지막 갱신.*2026-05-19" CLAUDE.md
```
Expected:
- `### package.xml 작성 함정` 다음 라인이 `### RPi scp 경로 규칙`, 그 다음이 `### 언어`
- `*마지막 갱신: 2026-05-19 ...*` 출력

- [ ] **Step 10.8: git add**

Run:
```bash
cd ~/moca
git add CLAUDE.md
git diff --name-only --diff-filter=U
```
Expected: 빈 출력 (모든 충돌 해결됨).

- [ ] **Step 10.9: 머지 진행 상태 검증**

Run:
```bash
cd ~/moca
git status
```
Expected: `All conflicts fixed but you are still merging.` 출력 + 스테이지된 파일 목록.

---

## Task 11: 함정 정정 — F1 person_tracking_pkg/package.xml em-dash

**Files:**
- Modify: `~/moca/src/dobi_npc/person_tracking_pkg/package.xml`

- [ ] **Step 11.1: 현재 description 확인**

Run:
```bash
cd ~/moca
grep "<description>" src/dobi_npc/person_tracking_pkg/package.xml
```
Expected: `  <description>Person tracking — YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose</description>` (em-dash 포함).

- [ ] **Step 11.2: em-dash → ASCII hyphen 변경**

Edit `~/moca/src/dobi_npc/person_tracking_pkg/package.xml`:

`<description>Person tracking — YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose</description>`

→

`<description>Person tracking - YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose</description>`

- [ ] **Step 11.3: 변경 검증 (ASCII only 확인)**

Run:
```bash
cd ~/moca
python3 -c "
with open('src/dobi_npc/person_tracking_pkg/package.xml') as f:
    text = f.read()
desc_start = text.find('<description>') + len('<description>')
desc_end = text.find('</description>')
desc = text[desc_start:desc_end]
print('description:', repr(desc))
assert desc.isascii(), 'FAIL: non-ASCII char in description'
print('OK: ASCII only')
"
```
Expected: `OK: ASCII only`.

- [ ] **Step 11.4: git add**

Run:
```bash
cd ~/moca
git add src/dobi_npc/person_tracking_pkg/package.xml
git status -s | head
```
Expected: 새 파일 staged 상태 (M 또는 AM 표기).

---

## Task 12: 함정 정정 — F2 모델 가중치 별도 복사

**Files:**
- Create: `~/moca/src/dobi_npc/person_tracking_pkg/models/yolov8n.pt`
- Create: `~/moca/src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task`

- [ ] **Step 12.1: 모델 디렉토리 생성**

Run:
```bash
cd ~/moca
mkdir -p src/dobi_npc/person_tracking_pkg/models
ls -la src/dobi_npc/person_tracking_pkg/models/
```
Expected: 빈 디렉토리 생성됨.

- [ ] **Step 12.2: 모델 가중치 복사**

Run:
```bash
cd ~/moca
cp -v ~/moca_teammember/src/dobi_npc/person_tracking_pkg/models/yolov8n.pt \
      src/dobi_npc/person_tracking_pkg/models/
cp -v ~/moca_teammember/src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task \
      src/dobi_npc/person_tracking_pkg/models/
ls -la src/dobi_npc/person_tracking_pkg/models/
```
Expected:
- `yolov8n.pt` ~6.5MB
- `pose_landmarker_lite.task` ~5.5MB

- [ ] **Step 12.3: sha256 일치 검증**

Run:
```bash
sha256sum ~/moca_teammember/src/dobi_npc/person_tracking_pkg/models/* \
          ~/moca/src/dobi_npc/person_tracking_pkg/models/* \
  | awk '{print $1}' | sort | uniq -c | sort -rn | head
```
Expected: 각 hash 가 2회씩 (`2 <hash>`) — 4 라인 = 2 unique hashes × 2.

- [ ] **Step 12.4: gitignore 확인 (models/*.pt 가 ignore 됨)**

Run:
```bash
cd ~/moca
git check-ignore -v src/dobi_npc/person_tracking_pkg/models/yolov8n.pt \
                    src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task
```
Expected: 각 파일이 ignore 규칙에 매칭. 출력 예시:
```
.gitignore:N:*.pt    src/dobi_npc/person_tracking_pkg/models/yolov8n.pt
```
(매칭이 안 되면 gitignore 가 모델 파일 ignore 안 함 — 별도 검토 필요)

만약 gitignore 매칭이 없으면 `.gitignore` 에 다음 추가:
```
# ML 모델 가중치 (12MB+) — git LFS 또는 별도 보관
*.pt
*.task
```

---

## Task 13: 함정 정정 — F3 pip 의존성 설치 + transitive cleanup

**Files:** pip user site only — workspace 파일 변경 없음

- [ ] **Step 13.1: 설치 전 시스템 numpy/cv2 상태 기록**

Run:
```bash
python3 -c "import numpy; print('numpy', numpy.__version__, numpy.__file__)"
python3 -c "import cv2; print('cv2', cv2.__version__, cv2.__file__)"
```
Expected:
```
numpy 1.26.4 /usr/lib/python3/dist-packages/numpy/__init__.py
cv2 4.6.0 /usr/lib/python3/dist-packages/cv2/__init__.py
```

이 값은 `/tmp/pre_pip_versions.txt` 에 저장:
```bash
{
  python3 -c "import numpy; print('numpy', numpy.__version__, numpy.__file__)"
  python3 -c "import cv2; print('cv2', cv2.__version__, cv2.__file__)"
} > /tmp/pre_pip_versions.txt
cat /tmp/pre_pip_versions.txt
```

- [ ] **Step 13.2: ultralytics + boxmot 설치**

Run:
```bash
pip install --user ultralytics boxmot 2>&1 | tail -20
```
Expected: 마지막 라인 `Successfully installed ...` + 설치된 패키지 목록. 단 transitive 로 `numpy-2.x` 또는 `opencv-contrib-python` 가 user site 에 들어왔는지 다음 step 에서 검증.

- [ ] **Step 13.3: 설치 후 시스템 numpy/cv2 보호 확인**

Run:
```bash
python3 -c "import numpy; print('numpy', numpy.__version__, numpy.__file__)"
python3 -c "import cv2; print('cv2', cv2.__version__, cv2.__file__)"
```
Expected: Step 13.1 과 동일 (`numpy 1.26.4`, `cv2 4.6.0`, 시스템 dist-packages 경로). 만약 user site (~/.local) 의 2.x 가 import 되면 다음 step 으로 cleanup.

- [ ] **Step 13.4: user site 의 numpy/opencv 발견 시 제거**

Run:
```bash
ls ~/.local/lib/python*/site-packages/numpy 2>&1 | head -3
ls ~/.local/lib/python*/site-packages/cv2 2>&1 | head -3
ls ~/.local/lib/python*/site-packages/opencv* 2>&1 | head -3
```
만약 출력이 있으면 (즉 user site 에 침투):

```bash
pip uninstall --yes numpy opencv-contrib-python opencv-python 2>&1 | tail -10
# 재검증
python3 -c "import numpy; print(numpy.__version__, numpy.__file__)"
python3 -c "import cv2; print(cv2.__version__, cv2.__file__)"
```
Expected (cleanup 후): 시스템 dist-packages 의 1.26.4 / 4.6.0 으로 복귀.

- [ ] **Step 13.5: ultralytics + boxmot import smoke**

Run:
```bash
python3 -c "from ultralytics import YOLO; print('ultralytics OK')"
python3 -c "from boxmot.trackers.botsort.botsort import BotSort; print('boxmot OK')"
```
Expected: 양쪽 모두 `OK` 출력. import 에러 시 의존성 누락 — 보고.

- [ ] **Step 13.6: mediapipe 버전 재확인 ([[Phase 2 W4 pin]])**

Run:
```bash
python3 -c "import mediapipe; print('mediapipe', mediapipe.__version__)"
```
Expected: `mediapipe 0.10.14` (CLAUDE.md §7 pinned 버전).

---

## Task 14: 함정 점검 — F4 워크스페이스 루트 yolov8n.pt 미존재

**Files:** 검증만, 변경 X

- [ ] **Step 14.1: 루트 yolov8n.pt 미존재 확인**

Run:
```bash
ls -la ~/moca/yolov8n.pt 2>&1
```
Expected: `ls: cannot access '/home/gjkong/moca/yolov8n.pt': No such file or directory` (정상 — git fetch 로 untracked 자산 안 옴).

만약 파일이 있다면 (의외 케이스):
```bash
rm ~/moca/yolov8n.pt
ls ~/moca/yolov8n.pt 2>&1   # 없어야 함
```

---

## Task 15: 머지 commit

**Files:** git commit only

- [ ] **Step 15.1: 머지 전 staged 파일 검토**

Run:
```bash
cd ~/moca
git status
git diff --name-only --diff-filter=U   # 충돌 잔재 확인
```
Expected: unmerged 0건. staged 파일 약 30개 (충돌 5 + 신규 23 + person_tracking_pkg 신규 자산).

- [ ] **Step 15.2: package.xml + 모델 추가 staging 확인**

Run:
```bash
cd ~/moca
git status | grep "person_tracking_pkg/package.xml\|person_tracking_pkg/models"
```
Expected: `package.xml` staged. `models/*.pt|*.task` 는 gitignore 라 untracked.

- [ ] **Step 15.3: 머지 commit 생성**

Run:
```bash
cd ~/moca
git commit -m "$(cat <<'EOF'
merge: integrate teammate person_tracking_pkg + follow LiDAR routing (18 commits)

- person_tracking_pkg (YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose, 3 nodes)
- approach_controller PD + LiDAR 거리 기반 follow_controller
- Nav2 일괄 기동 스크립트 (run_nav2.sh, run_3stage.sh, stop_nav2.sh)
- dobi_npc_msgs: PersonTrack/PersonTrackArray 2 msg 추가 (총 12 msg + 5 srv)
- mode_manager: 5-state → 6-state (follow + guiding 분리 운용, 사용자 결정)
- mode_manager: NaN 배터리 처리 (math.isfinite, 라이브 미연결 환경)
- CLAUDE.md: §RPi scp 경로 규칙 통합 + 마지막 갱신 라인 2026-05-19 로 bump
- person_tracking_pkg/package.xml description: em-dash → ASCII (ament_python install hook 함정 회피)

공통 조상 1a2971b, 양쪽 분기 commits 43 (내) + 18 (팀원).
spec: docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md
plan: docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md
EOF
)"
git log --oneline -3
```
Expected: merge commit (2 parent) + 새 head 출력. `git log --merges` 에 표시.

- [ ] **Step 15.4: 머지 commit 검증**

Run:
```bash
cd ~/moca
git show --stat HEAD | head -15
git log --oneline -1 --pretty=format:"%h %p %s"
```
Expected:
- `%p` (parent) 에 2 hash (merge commit)
- 변경 파일 수 약 30개

---

## Task 16: colcon 격리 셸 빌드

**Files:** build/ install/ log/ 디렉토리 재생성

- [ ] **Step 16.1: 기존 빌드 산출물 정리**

Run:
```bash
cd ~/moca
rm -rf build install log
ls -la build install log 2>&1 | head -5
```
Expected: 모든 디렉토리 미존재 (`cannot access ... No such file`).

- [ ] **Step 16.2: 격리 셸 빌드 (CLAUDE.md §7 검증 빌드 환경)**

Run:
```bash
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --symlink-install 2>&1 | tail -40
'
```
Expected: 마지막 라인 `Summary: N packages finished [Xs]` (N >= 9 — vicpinky_description, vicpinky_navigation + dobi_npc 6 + person_tracking_pkg). `Aborted` / `Failed` 출력 X.

실패 시:
- `package.xml description` 함정 → Task 11 재검증
- `find_package(sensor_msgs)` 누락 → Task 6 재검증
- `from ultralytics ...` 빌드 시점 import 실패 (실 빌드는 import 안 함 — runtime 만) → 안전

- [ ] **Step 16.3: 빌드 성공 패키지 갯수 검증**

Run:
```bash
cd ~/moca
ls install/ | grep -v setup\\. | sort
```
Expected (정확히 9 디렉토리 + setup 파일):
```
dobi_npc_bringup
dobi_npc_bt
dobi_npc_dialog
dobi_npc_emotion
dobi_npc_minigame
dobi_npc_msgs
moca_navigation
moca_opserver
person_tracking_pkg
vicpinky_description
vicpinky_navigation
```
(정확한 패키지 갯수는 환경에 따라 다름 — moca_navigation/moca_opserver 가 있으면 11. 핵심은 **person_tracking_pkg 존재**.)

- [ ] **Step 16.4: ament_prefix_path hook 존재 (F1 함정 회피 검증)**

Run:
```bash
cd ~/moca
ls install/person_tracking_pkg/share/person_tracking_pkg/hook/ 2>&1
```
Expected (정상):
```
ament_prefix_path.dsv
ament_prefix_path.sh
pythonpath.dsv
pythonpath.sh
```
**FAIL 시**: `ament_prefix_path.sh` 누락 = description em-dash 잔재 — Task 11 재실행.

- [ ] **Step 16.5: 모델 가중치 install/share 반영**

Run:
```bash
cd ~/moca
ls install/person_tracking_pkg/share/person_tracking_pkg/models/ 2>&1
```
Expected:
```
yolov8n.pt
pose_landmarker_lite.task
```
**FAIL 시**: setup.py 의 `glob('models/*')` 가 빈 결과 — src 측 models/ 디렉토리 (Task 12) 누락. Task 12 재실행.

---

## Task 17: ROS2 interface + python import smoke

**Files:** runtime 검증만

- [ ] **Step 17.1: ros2 pkg list 에서 person_tracking_pkg 확인**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  ros2 pkg list | grep -E "person_tracking_pkg|dobi_npc"
'
```
Expected:
```
dobi_npc_bringup
dobi_npc_bt
dobi_npc_dialog
dobi_npc_emotion
dobi_npc_minigame
dobi_npc_msgs
person_tracking_pkg
```

- [ ] **Step 17.2: 신규 msg interface show**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  ros2 interface show dobi_npc_msgs/msg/PersonTrack
  echo "---"
  ros2 interface show dobi_npc_msgs/msg/PersonTrackArray
'
```
Expected: 각 msg 의 필드 정의 출력. 에러 X.

- [ ] **Step 17.3: 신규 msg interface list 검증 (총 12 msg)**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  ros2 interface list | grep dobi_npc_msgs | wc -l
'
```
Expected: 17 라인 (12 msg + 5 srv).

- [ ] **Step 17.4: person_tracking_pkg 노드 entry_points 검증**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  ros2 pkg executables person_tracking_pkg
'
```
Expected:
```
person_tracking_pkg approach_controller_node
person_tracking_pkg group_approach_node
person_tracking_pkg person_tracking_node
```

- [ ] **Step 17.5: python import smoke (no ROS spin)**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  python3 -c "
from ultralytics import YOLO
from boxmot.trackers.botsort.botsort import BotSort
import mediapipe
from dobi_npc_msgs.msg import PersonTrack, PersonTrackArray
print(\"All imports OK\")
print(\"mediapipe\", mediapipe.__version__)
"
'
```
Expected: `All imports OK` + `mediapipe 0.10.14`.

- [ ] **Step 17.6: mode_manager 6-state 검증**

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  python3 -c "
from dobi_npc_bringup.mode_manager_node import VALID_MODES, LEGACY_MODE_ALIAS
print(\"VALID_MODES:\", VALID_MODES)
print(\"LEGACY_MODE_ALIAS:\", LEGACY_MODE_ALIAS)
assert \"follow\" in VALID_MODES, \"FAIL: follow missing from VALID_MODES\"
assert \"follow\" not in LEGACY_MODE_ALIAS, \"FAIL: follow still in LEGACY_MODE_ALIAS\"
assert LEGACY_MODE_ALIAS == {\"npc\": \"engaging\"}, \"FAIL: LEGACY_MODE_ALIAS != {npc: engaging}\"
print(\"OK: 6-state FSM + follow/guiding 분리 운용\")
"
'
```
Expected:
```
VALID_MODES: ('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')
LEGACY_MODE_ALIAS: {'npc': 'engaging'}
OK: 6-state FSM + follow/guiding 분리 운용
```

- [ ] **Step 17.7: dev_common.launch.py launch 시동 (5초 후 SIGTERM)**

본 step 은 dry-run 형태로 launch 가 spawn 시도까지 도달하는지 검증. 카메라/lidar 미접속이라 실 노드는 실패할 수 있으나 launch 자체는 통과.

Run:
```bash
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  source ~/moca/install/setup.bash
  export ROS_DOMAIN_ID=99
  export ROS_LOCALHOST_ONLY=1
  timeout 5 ros2 launch dobi_npc_bringup dev_common.launch.py fullscreen:=false 2>&1 | tail -30 || true
'
```
Expected:
- 출력에 `[INFO] [launch]: All log files can be found below ...`
- 9 노드 spawn 시도 라인 (geva, rapport_tracker, persona_manager, dialog_router, face_avatar, tts_node, mode_manager, person_tracking_node, group_approach_node, approach_controller_node)
- 5초 후 SIGTERM 으로 종료
- `Error: ...` 가 있어도 카메라/X11 미접속 관련이면 OK (본 검증은 launch 진입 검증만)

만약 launch 파싱 에러 (Python syntax / import error) 가 있으면 Task 7 (dev_common) 재검토.

---

## Task 18: post-merge 회고 + tag

**Files:**
- Create: `~/moca/docs/daily/2026-05-19_teammember_merge.md`

- [ ] **Step 18.1: 회고 .md 작성**

Edit `~/moca/docs/daily/2026-05-19_teammember_merge.md` (신규 생성):

```markdown
# 2026-05-19 — moca_teammember 18 commits 통합 머지

> spec: `docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md`
> plan: `docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md`
> 작성: 2026-05-19 (doby)

---

## 1. 무엇을 했는가

`~/moca_teammember/` (HEAD `fd62971`) 의 18 commit 을 `~/moca/` (HEAD `fb9c1b9` + Task 3 의 3 commit = 4 commits ahead) 에 git merge 로 통합. 공통 조상 `1a2971b` (2026-05-08) 기준 양쪽 분기.

### 통합된 자산
- 신규 패키지: `person_tracking_pkg` (YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose, 3 노드)
- 신규 msg: `PersonTrack`, `PersonTrackArray` (dobi_npc_msgs, 총 12 msg + 5 srv)
- approach_controller PD 제어 + LiDAR 거리 기반 follow_controller
- 신규 스크립트: `run_3stage.sh`, `run_nav2.sh`, `stop_nav2.sh`
- 신규 문서: 일일 회고 6편 (2026-05-14 ~ 2026-05-18 person_tracking 트랙)
- _backups/vicpinky_navigation_launch/ (팀원 5/14 백업본 2 파일)
- 모델 가중치: `yolov8n.pt` (6.5MB), `pose_landmarker_lite.task` (5.5MB) — gitignore, 별도 cp

### 충돌 해결 5건
1. `dobi_npc_msgs/CMakeLists.txt` — union (12 msg + 5 srv)
2. `dev_common.launch.py` — 내 base + 팀원 3 노드 (person_tracking_node, group_approach_node, approach_controller_node) append. 7-node → 9-node.
3. `mode_manager_node.py` — 내 base + 팀원 NaN 패치 + VALID_MODES 6-state (`follow` 추가, `npc` 만 alias)
4. `mode_follow.launch.py` — 팀원 본 채택 (kp_angular 0.5, target_dist 0.30, LiDAR 거리 기반). 내 측 deprecated wrapper 결정 철회.
5. `CLAUDE.md` — 내 base + 팀원 §RPi scp 경로 규칙 섹션만 picking.

---

## 2. 사용자 결정 4건 (사전 합의)

1. 옵션 A — git merge --no-commit (팀원 18 commit history 보존)
2. mode_follow + mode_guiding 분리 운용 (둘 다 살림)
3. pip ultralytics + boxmot 머지 직후 설치 + transitive cleanup
4. PC + 팀원 양쪽 풀 백업 (~/backup/moca_merge_20260519/)

---

## 3. Hidden 함정 7건 처리

| # | 함정 | 처리 |
|---|---|---|
| F1 | person_tracking_pkg/package.xml em-dash | ASCII hyphen 으로 정정 |
| F2 | 모델 가중치 gitignore | 별도 cp + sha256 검증 |
| F3 | ultralytics/boxmot 미설치 + transitive cleanup | pip install --user + numpy/cv2 보호 |
| F4 | 워크스페이스 루트 yolov8n.pt 중복 | git fetch 로 안 옴 (정상) |
| F5 | scripts/run_*.sh ~/moca/ 절대경로 잔재 | 본 머지에선 보존, 별 트랙으로 후속 |
| F6 | 내 측 untracked 정리 | 3 별 commit (cafe_ninja + stop_all.sh + docs) |
| F7 | _backups/ 도입 | .gitignore diff 0, 그대로 받아들임 |

---

## 4. 검증 통과 항목

- [x] colcon build 격리 셸 빌드 통과 (모든 패키지)
- [x] person_tracking_pkg ament_prefix_path.sh hook 존재 (F1 회피)
- [x] models/*.pt|*.task install/share 반영
- [x] ros2 interface show PersonTrack/PersonTrackArray
- [x] ros2 pkg executables person_tracking_pkg (3 노드)
- [x] python import smoke (ultralytics, boxmot, mediapipe 0.10.14, dobi_npc_msgs.msg.PersonTrack)
- [x] mode_manager VALID_MODES 6-state + LEGACY_MODE_ALIAS = {'npc': 'engaging'}
- [x] dev_common.launch.py 5초 timeout launch 진입 OK

---

## 5. 미해결 / 후속 트랙

본 머지 spec §6 Open issues 와 동일:

1. **mode_follow + mode_guiding 분리 운용 시 운영 패널 UI 영향** — moca_opserver mode chip 의 'follow' 지원 여부 확인 필요. 라이브 검증 트랙.
2. **5-state FSM spec ↔ 6-state 코드 불일치** — `docs/moca_5state_fsm_spec.md` 갱신 필요. 팀원 + 사용자 협의 후.
3. **팀원 18 commits 라이브 검증 상태 불명** — 본 머지로 통합되었으나 검증된 것 아님.
4. **F5 절대경로 잔재** — `scripts/run_3stage.sh`, `run_nav2.sh` 의 `~/moca/` 잔재. SCRIPT_DIR 패턴 적용 별 트랙.
5. **`run_nav2.sh` vs CLAUDE.md §11 navigation 분리 원칙** — bringup 재기동 시도 등 §11.1 위반 가능. 라이브 검증 단계에서 확인.

---

## 6. 시스템 상태 (머지 완료 시점)

| 항목 | 상태 |
|---|---|
| ~/moca HEAD | merge commit (2-parent: pre-merge-teammember-20260519 + fd62971) |
| ~/moca git status | clean (단 models/*.pt 는 gitignore) |
| build/install/log | 정상 빌드 산출물 (격리 셸) |
| pip user site | ultralytics + boxmot 설치 + 시스템 numpy/cv2 보호됨 |
| ~/moca_teammember | read-only, 변경 X |
| ~/backup/moca_merge_20260519 | 양쪽 풀 백업 + SHA256SUMS 검증 통과 + README 회복 절차 3 시나리오 |
| RPi | 미접근 (본 plan 범위 외) |

---

## 7. doby 자기 평가

(작업 완료 시 채워넣기)

---

*다음 갱신: 라이브 검증 트랙 진입 후 — 사용자 명시 "/cmd_vel 발행 X" 해제 시점*
```

- [ ] **Step 18.2: 회고 commit**

Run:
```bash
cd ~/moca
git add docs/daily/2026-05-19_teammember_merge.md
git commit -m "docs: 2026-05-19 회고 — 팀원 18 commits 통합 머지 완료"
git log --oneline -1
```
Expected: 새 commit hash 출력.

- [ ] **Step 18.3: post-merge tag**

Run:
```bash
cd ~/moca
git tag post-merge-teammember-20260519
git tag --list | grep teammember
```
Expected:
```
backup-pre-merge-teammember-20260519
post-merge-teammember-20260519
pre-merge-teammember-20260519
```

- [ ] **Step 18.4: 최종 git log 확인**

Run:
```bash
cd ~/moca
git log --oneline --graph -10
```
Expected: merge commit (2 parent) 표시 + 양쪽 분기 graph + 최근 commit 들.

---

## Task 19: 최종 검증 게이트 + 사용자 보고

**Files:** 검증만, 변경 X

- [ ] **Step 19.1: 백업 SHA256SUMS 재검증**

Run:
```bash
cd ~/backup/moca_merge_20260519
sha256sum -c SHA256SUMS 2>&1 | tail -15
```
Expected: 모든 라인 `OK`.

- [ ] **Step 19.2: 머지 결과 summary 출력**

Run:
```bash
cd ~/moca
echo "=== HEAD ==="
git log --oneline -1
echo
echo "=== Merge parents ==="
git log --oneline -1 --pretty=format:"%h parents: %p%n"
echo
echo "=== Tags ==="
git tag --list | grep teammember
echo
echo "=== Branches ==="
git branch -a | grep teammember
echo
echo "=== Last 5 commits ==="
git log --oneline -5
echo
echo "=== Person tracking models ==="
ls -la src/dobi_npc/person_tracking_pkg/models/
echo
echo "=== Build summary ==="
ls install/ | wc -l
echo "install/ 패키지 갯수 위와 같음"
```

- [ ] **Step 19.3: 사용자에게 머지 완료 보고**

다음 양식으로 사용자에게 보고:

```
moca ↔ moca_teammember 머지 완료 (2026-05-19).

✅ 머지 결과
- 통합 commits: 18 (팀원) + 3 (내 측 사전 정리) = 21 commits
- 머지 commit: <hash>
- 신규 패키지: person_tracking_pkg (3 노드 + 2 msg + 모델 12MB)
- 충돌 5 파일 모두 해결
- pre-merge / post-merge tag 양쪽 보존

✅ 검증 통과
- colcon build: <N> 패키지 빌드 성공
- ament_prefix_path.sh hook 존재 (F1 회피)
- ros2 interface show PersonTrack/PersonTrackArray
- python import smoke (ultralytics, boxmot, mediapipe 0.10.14)
- mode_manager 6-state + LEGACY_MODE_ALIAS = {npc: engaging}
- dev_common.launch.py 5초 timeout launch 진입

⚠ 후속 (본 plan 범위 외)
- 라이브 검증 (사용자 명시 "/cmd_vel 발행 X" 해제 시점)
- 5-state FSM spec ↔ 6-state 코드 불일치 (docs/moca_5state_fsm_spec.md 갱신)
- F5 절대경로 잔재 (scripts/run_*.sh SCRIPT_DIR 패턴)
- run_nav2.sh ↔ CLAUDE.md §11 충돌 가능성

회고: docs/daily/2026-05-19_teammember_merge.md
```

---

## Rollback 가이드 (실패 시)

본 plan 의 각 Task 가 실패할 경우 회복 절차:

### 가벼운 회복 — 충돌 해결 단계 (Task 5~10) 실패

```bash
cd ~/moca
git merge --abort
git status   # → clean
```
이후 Task 4 의 `pre-merge-teammember-20260519` tag 가 보존되므로 재시도 가능.

### 중간 회복 — 머지 commit 후 빌드/검증 실패 (Task 16~17)

```bash
cd ~/moca
git reset --hard pre-merge-teammember-20260519
rm -rf build install log
bash --noprofile --norc -c 'source /opt/ros/jazzy/setup.bash; cd ~/moca; colcon build --symlink-install'
```

### 풀 회복 — 모든 작업 무효화

```bash
bash ~/moca/scripts/stop_all.sh --hard 2>/dev/null || true
cd ~
mv moca moca.failed_$(date +%Y%m%d_%H%M%S)
mkdir moca && cd moca
tar xzf ~/backup/moca_merge_20260519/laptop/moca_dotgit_fb9c1b9.tar.gz
tar xzf ~/backup/moca_merge_20260519/laptop/moca_src_fb9c1b9.tar.gz
git apply ~/backup/moca_merge_20260519/laptop/moca_unstaged.patch || true
```

---

*plan 작성: 2026-05-19 doby. spec 의 8 phase 를 19 Task / 약 100 step 으로 분해. TDD 패턴 대신 verification-command-driven (머지 작업 특성).*
