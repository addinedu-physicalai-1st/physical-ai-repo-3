# Test Supervisor + Sub-Tester Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** moca/doby_controller 의 수동 회귀 테스트를 유형 분류 + 카탈로그화 + 재실행하는 Claude Code 서브에이전트 시스템 v1 구축 (`test-supervisor` + 6개 카테고리 sub-tester + `tests/regression/` 카탈로그 + 첫 perception smoke 테스트). **v1 = 사용자 Stephen 단독 검증 단계** — 모든 commit / batch run / policy boundary 는 Stephen 의 명시 승인 게이트 통과 필수. v2 팀 확산은 별 트랙.

**Architecture:** `.claude/agents/test-supervisor.md` 가 top-level 진입점으로 분류/디스패치를 담당하고, 도메인별 sub-tester (perception/dialog/navigation/safety/minigame/mode-e2e) 가 Agent 도구로 spawn 되어 `tests/regression/<category>/<id>.md` 절차서를 실행한다. 카탈로그 인덱스는 `tests/regression/catalog.yaml`. §0-A (RPi 조건부 금지) + §0-B (vic_pinky 수정 금지) 정책은 supervisor + navigation-tester + safety-tester 프롬프트에 인라인 명시.

**Tech Stack:** Claude Code subagent format (markdown + YAML frontmatter), Bash, ROS2 Jazzy CLI (`ros2 topic`, `ros2 node`, `ros2 interface`, launch), Python 3.12 (smoke 검증용).

**관련 문서:**
- 설계서: `docs/superpowers/specs/2026-05-19-test-supervisor-agents-design.md` (§11 승인 모델 + 롤아웃 포함)
- 정책: `CLAUDE.md` §0-A / §0-B / §7 (상대경로) / §11 (Navigation 분리)

**v1 승인 게이트 (Stephen 명시 OK 필수):**
- G1: 신규 테스트 `.md` + catalog 인덱싱 후 git commit 전
- G2: 회귀 일괄 실행 (category 단위 / all smoke / all)
- G3: §0-A / §0-B 경계 가능성 1% 이상 테스트 실행
- G4: catalog 스키마 (categories 목록, policy_blocks_vocabulary) 수정

모든 sub-tester + supervisor 프롬프트에 위 4개 게이트 인라인 명시 (각 task 에 포함).

---

## File Structure

**생성 파일:**
```
.claude/
└── agents/                                  ← 신규 디렉토리
    ├── test-supervisor.md                   ← top-level dispatcher
    ├── perception-tester.md                 ← GEVA / rapport / person_tracking
    ├── dialog-tester.md                     ← persona / TTS / face_avatar
    ├── navigation-tester.md                 ← Nav2 / serving / follow (§0-B)
    ├── safety-tester.md                     ← safety_zone / battery / scan (§0-B)
    ├── minigame-tester.md                   ← RPS + 3 games
    └── mode-e2e-tester.md                   ← full launch smoke + scenarios

tests/
└── regression/                              ← 신규 디렉토리
    ├── README.md                            ← 사람/에이전트 공통 사용 가이드
    ├── catalog.yaml                         ← 인덱스 (id, category, file, depth, tags, requires, policy)
    ├── perception/
    │   ├── .gitkeep
    │   └── geva_webcam_smoke.md            ← v1 첫 테스트
    ├── dialog/.gitkeep
    ├── navigation/.gitkeep
    ├── safety/.gitkeep
    ├── minigame/.gitkeep
    └── mode_e2e/.gitkeep
```

**수정 파일:** 없음 (vic_pinky / dobi_npc 패키지 / 기존 스크립트 일체 미수정 — §0-B + [[feedback_dont_touch_working_code]] 준수)

**책임 분리 원칙:**
- 각 sub-tester `.md` 는 자기 도메인 프롬프트만 (다른 도메인 무지)
- supervisor `.md` 는 분류 + 디스패치 로직만 (실제 실행 절차 무지)
- per-test `.md` 는 절차 + 기대값만 (분류/디스패치 무지)

---

### Task 1: 디렉토리 구조 + .gitkeep 생성

**Files:**
- Create: `.claude/agents/.gitkeep`
- Create: `tests/regression/perception/.gitkeep`
- Create: `tests/regression/dialog/.gitkeep`
- Create: `tests/regression/navigation/.gitkeep`
- Create: `tests/regression/safety/.gitkeep`
- Create: `tests/regression/minigame/.gitkeep`
- Create: `tests/regression/mode_e2e/.gitkeep`

- [ ] **Step 1: 디렉토리 + 빈 .gitkeep 파일 생성**

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
mkdir -p .claude/agents
mkdir -p tests/regression/{perception,dialog,navigation,safety,minigame,mode_e2e}
touch .claude/agents/.gitkeep
touch tests/regression/perception/.gitkeep
touch tests/regression/dialog/.gitkeep
touch tests/regression/navigation/.gitkeep
touch tests/regression/safety/.gitkeep
touch tests/regression/minigame/.gitkeep
touch tests/regression/mode_e2e/.gitkeep
```

- [ ] **Step 2: 구조 확인**

Run: `find .claude/agents tests/regression -type d`
Expected:
```
.claude/agents
tests/regression
tests/regression/perception
tests/regression/dialog
tests/regression/navigation
tests/regression/safety
tests/regression/minigame
tests/regression/mode_e2e
```

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/.gitkeep tests/regression/
git commit -m "test: scaffold regression catalog + agents directories"
```

---

### Task 2: `tests/regression/README.md` 작성

**Files:**
- Create: `tests/regression/README.md`

- [ ] **Step 1: README 작성**

```markdown
# tests/regression — moca 회귀 테스트 카탈로그

본 디렉토리는 수동으로 검증한 테스트를 `.md` 절차서로 표준화해 보관한다.
새 테스트 추가, 재실행, 카테고리 분류는 모두 **Claude Code `test-supervisor` 에이전트**가 담당한다.

## 구조

- `catalog.yaml` — 모든 테스트의 인덱스 (id, category, depth, requires, policy)
- `<category>/<id>.md` — 개별 테스트 절차서
  - 카테고리: `perception`, `dialog`, `navigation`, `safety`, `minigame`, `mode_e2e`, `infra_readonly`

## 사용법 (사용자 → Claude)

### 1) 방금 수행한 테스트를 회귀 카탈로그에 저장

```
test-supervisor 에이전트를 호출해서 방금 한 [어떤] 테스트 저장해줘
```

supervisor 가 짧게 확인 후 적절한 sub-tester 를 spawn 해서 `<category>/<id>.md` 작성 + `catalog.yaml` 인덱싱.

### 2) 회귀 실행

```
test-supervisor 로 perception 카테고리 회귀 돌려
test-supervisor 로 모든 smoke 돌려
test-supervisor 로 id geva_webcam_smoke 만 돌려
test-supervisor 로 tag nav2 만 돌려
```

### 3) 카탈로그 직접 열람

`cat catalog.yaml` 또는 `find . -name "*.md" -not -name "README.md"`.

## 정책 (CLAUDE.md 정합)

- **§0-A** (조건부 RPi 금지): supervisor 가 활성 판정 후 `policy.blocks: [rpi_ssh, live_robot]` 테스트 자동 skip
- **§0-B** (vic_pinky 수정 금지, 영구): navigation-tester / safety-tester 가 인지. `vic_pinky_write` policy 테스트는 read-only 변형 또는 skip
- 신규 테스트 작성 시 sub-tester 가 위 정책에 위배되지 않는지 자체 점검

## 절차서 스키마

각 `.md` 는 다음 frontmatter + 본문 섹션을 갖는다:

```yaml
---
id: <kebab-case-id>
category: <perception|dialog|navigation|safety|minigame|mode_e2e|infra_readonly>
depth: <smoke|behavioral>
duration_sec: <int>
requires:
  - device: <camera_1|camera_2|camera_3|webcam>
  - package: <ros pkg name>
  - sim: <gazebo|none>
preconditions:
  - <prerequisite text>
policy_notes:
  - <§0-A / §0-B 관련 메모>
---
```

본문 섹션 (Markdown):
- `# 목적`
- `# 셋업` (bash 코드 블록)
- `# 단계` (번호 매긴 검증 단계, 각자 `expect: ...` 명시)
- `# 기대 결과`
- `# 클린업` (bash 코드 블록)
- `# 알려진 이슈` (선택)

## 명명 컨벤션

테스트 id: `<subject>_<aspect>_<depth>`
- `geva_webcam_smoke` ← perception 의 GEVA 노드 웹캠 spawn smoke
- `nav2_t01_dock_dry` ← navigation 의 T01 dock 시뮬 (dry) behavioral
- `rps_70pct_win_rate` ← minigame 의 RPS 70% 승률 검증

## v1 미포함 (Out of Scope)

- CI 자동 회귀 (GitHub Actions / pre-commit)
- 결과 통계 영구 저장소
- 테스트 병렬 실행
- flaky 재시도 정책
```

Run:
```bash
cat > tests/regression/README.md << 'EOF'
[위 내용 그대로]
EOF
```

- [ ] **Step 2: 파일 확인**

Run: `wc -l tests/regression/README.md`
Expected: 약 80~90 줄

- [ ] **Step 3: Commit**

```bash
git add tests/regression/README.md
git commit -m "docs(regression): add catalog README with schema and usage"
```

---

### Task 3: `tests/regression/catalog.yaml` 빈 스켈레톤 작성

**Files:**
- Create: `tests/regression/catalog.yaml`

- [ ] **Step 1: catalog.yaml 작성**

```yaml
# tests/regression/catalog.yaml
# moca 회귀 테스트 인덱스. test-supervisor 에이전트가 read/write.
# 새 테스트는 supervisor 가 sub-tester 호출 후 자동 인덱싱.

version: 1
generated: 2026-05-19

# 카테고리 정의 (v1)
categories:
  - id: perception
    handler: perception-tester
    description: GEVA, rapport_tracker, decision_rule, person_tracking_pkg
  - id: dialog
    handler: dialog-tester
    description: persona_manager, tts_node, face_avatar_node
  - id: navigation
    handler: navigation-tester
    description: Nav2, serving_dispatcher, follow_controller, person_detector
  - id: safety
    handler: safety-tester
    description: safety_zone_monitor, twist_mux, /scan, /battery_state
  - id: minigame
    handler: minigame-tester
    description: RPS + 3 games (rps_evolution, speed_counter, cafe_ninja)
  - id: mode_e2e
    handler: mode-e2e-tester
    description: mode_npc / mode_serving / mode_follow / teleop_ui full launch
  - id: infra_readonly
    handler: safety-tester
    description: vic_pinky read-only checks, RPi ping (§0-A 활성 시 skip)

# 정책 차단 키워드 (catalog 의 tests[*].policy.blocks 에 등장 가능)
policy_blocks_vocabulary:
  - rpi_ssh           # §0-A 활성 시 차단
  - live_robot        # §0-A 활성 시 차단
  - vic_pinky_write   # §0-B 영구 차단
  - internet_required # edge-tts 등 인터넷 필요 명시

# 테스트 목록 (Task 4 이후 채워짐)
tests: []
```

Run:
```bash
cat > tests/regression/catalog.yaml << 'EOF'
[위 내용 그대로]
EOF
```

- [ ] **Step 2: YAML 검증**

Run: `python3 -c "import yaml; d = yaml.safe_load(open('tests/regression/catalog.yaml')); print(f'version={d[\"version\"]}, categories={len(d[\"categories\"])}, tests={len(d[\"tests\"])}')"`
Expected: `version=1, categories=7, tests=0`

- [ ] **Step 3: Commit**

```bash
git add tests/regression/catalog.yaml
git commit -m "feat(regression): add catalog skeleton with 7 categories"
```

---

### Task 4: 첫 회귀 테스트 — `geva_webcam_smoke.md` 작성

**Files:**
- Create: `tests/regression/perception/geva_webcam_smoke.md`

- [ ] **Step 1: 테스트 절차서 작성**

```markdown
---
id: geva_webcam_smoke
category: perception
depth: smoke
duration_sec: 15
requires:
  - device: camera_1
  - package: dobi_npc_emotion
preconditions:
  - moca_build 성공 (install/ 존재)
  - /opt/ros/jazzy/setup.bash sourced
  - install/setup.bash sourced
  - mediapipe 0.10.14 user pip 설치됨 (CLAUDE.md §7)
policy_notes:
  - "§0-A 무관: 노트북 단독 (RPi 미사용)"
  - "§0-B 무관: vic_pinky 자산 미참조"
---

# 목적
GEVA 노드(`geva_node`)가 노트북 웹캠(`camera_1`)을 열고 `/emotion/state` 토픽을 발행하는지 확인.

# 셋업
```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run dobi_npc_emotion geva_node &
GEVA_PID=$!
sleep 3
```

# 단계
1. **토픽 등록 확인**
   Run: `ros2 topic list | grep -q /emotion/state`
   Expect: exit 0 (토픽 존재)

2. **메시지 발행 확인**
   Run: `timeout 5 ros2 topic echo --once /emotion/state`
   Expect: stdout 에 `source: "face"` 포함 + `confidence:` 값이 0 초과

3. **노드 alive 확인**
   Run: `kill -0 $GEVA_PID`
   Expect: exit 0 (프로세스 살아있음)

# 기대 결과
- `/emotion/state` 발행 주기 ≥ 1Hz (Hz 단위 별도 측정 미포함, v1 은 1회 echo 로 충분)
- `valence`, `arousal` 범위 [-1.0, 1.0] (echo 결과 시각 확인)
- `source = "face"`

# 클린업
```bash
kill $GEVA_PID 2>/dev/null
wait $GEVA_PID 2>/dev/null
```

# 알려진 이슈
- mediapipe `0.10.14` user pip 미설치 시 `geva_node` import 실패 → precondition 미달로 skip
- 웹캠 미연결 (`/dev/video0` 없음) 시 노드 spawn 직후 종료 → Step 3 fail
- 시스템 numpy 2.x 면 cv_bridge 충돌 → `pip uninstall numpy opencv-contrib-python` 후 시스템 apt numpy 1.26.4 복구 필요 (CLAUDE.md §7)
```

Run:
```bash
cat > tests/regression/perception/geva_webcam_smoke.md << 'EOF'
[위 내용 그대로]
EOF
```

- [ ] **Step 2: catalog.yaml 에 인덱싱**

`tests/regression/catalog.yaml` 의 `tests:` 줄 (마지막) 을 다음으로 교체:

```yaml
tests:
  - id: geva_webcam_smoke
    category: perception
    file: perception/geva_webcam_smoke.md
    depth: smoke
    tags: [geva, webcam, phase2, perception]
    duration_estimate_sec: 15
    requires:
      - device: camera_1
      - package: dobi_npc_emotion
    policy:
      blocks: []
    added: 2026-05-19
    last_status: null
    last_run: null
```

명령:
```bash
# tests: [] 줄을 위 블록으로 교체
python3 << 'PY'
import yaml
path = 'tests/regression/catalog.yaml'
with open(path) as f:
    raw = f.read()
data = yaml.safe_load(raw)
data['tests'] = [{
    'id': 'geva_webcam_smoke',
    'category': 'perception',
    'file': 'perception/geva_webcam_smoke.md',
    'depth': 'smoke',
    'tags': ['geva', 'webcam', 'phase2', 'perception'],
    'duration_estimate_sec': 15,
    'requires': [
        {'device': 'camera_1'},
        {'package': 'dobi_npc_emotion'},
    ],
    'policy': {'blocks': []},
    'added': '2026-05-19',
    'last_status': None,
    'last_run': None,
}]
# 헤더 주석 보존 (단순 strategy: 원본 헤더 3줄 + 새 yaml)
header_lines = []
for line in raw.splitlines():
    if line.startswith('#') or line.strip() == '':
        header_lines.append(line)
    else:
        break
with open(path, 'w') as f:
    f.write('\n'.join(header_lines) + '\n')
    yaml.dump(data, f, sort_keys=False, allow_unicode=True)
print('catalog updated')
PY
```

- [ ] **Step 3: 인덱싱 검증**

Run: `python3 -c "import yaml; d = yaml.safe_load(open('tests/regression/catalog.yaml')); print(d['tests'][0]['id'])"`
Expected: `geva_webcam_smoke`

- [ ] **Step 4: Commit**

```bash
git add tests/regression/perception/geva_webcam_smoke.md tests/regression/catalog.yaml
git commit -m "test(perception): add geva_webcam_smoke as first regression test"
```

---

### Task 5: 첫 테스트 수동 검증 (verification)

본 task 는 코드 변경 없음. 작성된 절차서가 실제로 동작하는지 사용자가 직접 실행해 확인.

- [ ] **Step 1: 환경 준비 확인**

Run: `ls install/setup.bash`
Expected: 파일 존재 (없으면 `moca_build` 먼저)

Run: `pip3 show mediapipe 2>/dev/null | grep -i version`
Expected: `Version: 0.10.14` (없으면 precondition 미달 — skip 가능)

Run: `ls /dev/video0`
Expected: 디바이스 존재 (없으면 웹캠 미연결 — skip 가능)

- [ ] **Step 2: 절차서 그대로 실행**

`tests/regression/perception/geva_webcam_smoke.md` 의 셋업 + 단계 1~3 + 클린업 순차 실행.

- [ ] **Step 3: 결과 기록**

3개 단계 모두 pass 면 OK. 실패 단계 있으면:
- 알려진 이슈에 해당하는 precondition 문제 → 절차서 OK 판정 (skip 가능 케이스)
- 알려진 이슈 외 fail → 절차서 자체 결함 가능. 회고 작성 (`docs/daily/2026-05-19_geva_smoke_fail.md`) 후 사용자 확인.

(commit 없음 — verification only)

---

### Task 6: `perception-tester` 에이전트 작성

**Files:**
- Create: `.claude/agents/perception-tester.md`

- [ ] **Step 1: 에이전트 정의 작성**

```markdown
---
name: perception-tester
description: 사용자가 perception 도메인 (GEVA 웹캠 감정 인식, rapport_tracker, decision_rule, person_tracking_pkg) 의 회귀 테스트를 작성하거나 실행할 때 사용. test-supervisor 가 Agent 도구로 dispatch 한다. tests/regression/perception/ 의 .md 절차서를 실행하거나 신규 작성.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **perception 도메인 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
- 본 에이전트는 test-supervisor 가 dispatch 한 작업만 수행한다.
- supervisor 가 G1 (commit) / G2 (batch run) / G3 (정책 경계) 게이트를 이미 통과시켰다고 가정.
- 단, 본 에이전트가 절차서 작성 중 §0-A/§0-B 위반 가능성 또는 Stephen 의 사전 결정과 다른 동작 필요성 발견 시: 즉시 작업 중단 + supervisor 에 보고 (사용자 재확인 위해).
- git commit 은 supervisor 가 Stephen OK 받은 뒤 본 에이전트 결과 받아 직접 수행 (본 에이전트 단독 commit 금지).

# 도메인 범위
- `geva_node` (dobi_npc_emotion) — 노트북 웹캠 → V/A 감정 인식
- `rapport_tracker` (dobi_npc_emotion) — V/A → RapportEvent
- `decision_rule_node` (예정) — GEVA+GEFA fusion
- `person_tracking_pkg` — Detection2DArray
- 카메라 사용:
  - `camera_1` (노트북 웹캠) — primary
  - `camera_2` (RPi USB) — read-only 진단
  - `camera_3` (USB 외장 RPC-20F) — 게임용, perception 도 사용 가능

# 호출 모드
test-supervisor 가 다음 둘 중 하나로 호출:

### 모드 A: 신규 테스트 작성
prompt 예: "사용자가 방금 GEVA 웹캠 spawn 후 /emotion/state echo 로 V/A 확인했어. tests/regression/perception/geva_webcam_smoke.md 로 작성하고 catalog.yaml 에 인덱싱한 뒤 sanity check 실행해줘."

처리:
1. 절차서 작성 (스키마 — tests/regression/README.md 참조)
2. catalog.yaml 에 entry 추가 (id, category=perception, file, depth, tags, requires, policy, added=오늘날짜)
3. sanity check: 작성된 절차 직접 실행. **통과 강제 X** — 실패해도 .md 보존 + 결과 보고
4. 결과 supervisor 에 반환: `{file, catalog_updated: bool, sanity: pass|fail|skip, notes}`

### 모드 B: 기존 테스트 실행 (회귀)
prompt 예: "다음 test id 들 실행: [geva_webcam_smoke, rapport_event_threshold]"

처리 (각 id 별로):
1. catalog.yaml 에서 entry 조회 → file 경로 + requires + policy.blocks 확인
2. precondition 점검 (device 존재? package 빌드됨?)
3. policy.blocks 위반? (정상 supervisor 가 미리 거름. 방어적 재확인)
4. 절차서 frontmatter 의 `preconditions` 충족 확인
5. 본문 `# 셋업` → `# 단계` → `# 클린업` 순차 실행
6. 각 단계의 `Expect:` 비교 → pass/fail
7. 결과 반환: `{id, status: pass|fail|skip, duration_sec, failed_step, log_excerpt, reason}`

# 절차서 스키마 (tests/regression/README.md SoT)
- frontmatter: id, category, depth, duration_sec, requires, preconditions, policy_notes
- 본문: `# 목적`, `# 셋업` (bash), `# 단계` (번호 + Expect), `# 기대 결과`, `# 클린업` (bash), `# 알려진 이슈`

# 정책
- §0-A/§0-B 무관 (PC 단독 perception 노드)
- 단 카메라 2 (RPi USB) 사용 테스트는 §0-A 활성 시 supervisor 가 미리 skip — perception-tester 가 직접 ssh X
- write 권한: `tests/regression/perception/`, `tests/regression/catalog.yaml` 만. **dobi_npc 패키지 코드 절대 미수정**.

# 명령 가이드라인 (Bash 도구)
- ROS2 환경 항상 source: `source /opt/ros/jazzy/setup.bash && source install/setup.bash`
- 노드 spawn 은 `&` 백그라운드 + PID 보관 + 명시적 kill 클린업
- 타임아웃 사용: `timeout 5 ros2 topic echo --once /emotion/state`
- 절차서 외 부수 효과 (다른 노드 spawn, 디렉토리 변경) 금지

# 새 테스트 id 네이밍
`<subject>_<aspect>_<depth>` (CLAUDE.md daily 회고와 정합):
- `geva_<feature>_smoke|behavioral`
- `rapport_<event>_smoke|behavioral`
- `person_tracking_<aspect>_smoke|behavioral`

# 보고 포맷 (supervisor 에 반환)
JSON 유사 텍스트:
```
{
  "id": "geva_webcam_smoke",
  "status": "pass",
  "duration_sec": 12,
  "failed_step": null,
  "notes": "all 3 steps passed; webcam present"
}
```

실패 시:
```
{
  "id": "geva_webcam_smoke",
  "status": "fail",
  "duration_sec": 8,
  "failed_step": 2,
  "log_excerpt": "timeout 5 ros2 topic echo ... → no message received",
  "notes": "node spawned but no /emotion/state — check mediapipe install"
}
```
```

Run:
```bash
cat > .claude/agents/perception-tester.md << 'EOF'
[위 내용 그대로]
EOF
```

- [ ] **Step 2: frontmatter 검증**

Run: `head -5 .claude/agents/perception-tester.md`
Expected:
```
---
name: perception-tester
description: 사용자가 perception 도메인...
tools: Read, Write, Edit, Bash
---
```

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/perception-tester.md
git commit -m "feat(agents): add perception-tester subagent for GEVA/rapport/person_tracking"
```

---

### Task 7: `perception-tester` 디스패치 검증 (verification)

본 task 는 코드 변경 없음. 사용자가 메인 Claude 에서 Agent 도구로 직접 호출해 확인.

- [ ] **Step 1: Agent 호출 (사용자 발화)**

사용자가 메인 Claude 에게:
```
Agent 도구로 subagent_type=perception-tester 를 호출해서 다음 prompt 전달해:
"tests/regression/catalog.yaml 의 geva_webcam_smoke 테스트를 모드 B (회귀 실행) 로 실행해줘."
```

- [ ] **Step 2: 결과 확인**

기대:
- perception-tester 가 절차서 읽고 셋업 + 3단계 + 클린업 실행
- 결과 JSON 유사 텍스트 반환 (pass/fail/skip + 단계별 노트)
- catalog.yaml 의 `last_status`, `last_run` 갱신 (선택 — v1 에서 갱신하지 않아도 OK)

- [ ] **Step 3: 결과 기록**

기대대로 동작하면 다음 task 진행.
이상 동작 시 perception-tester.md 프롬프트 수정 후 재검증.

(commit 없음 — verification only)

---

### Task 8: `test-supervisor` 에이전트 작성

**Files:**
- Create: `.claude/agents/test-supervisor.md`

- [ ] **Step 1: supervisor 에이전트 정의 작성**

```markdown
---
name: test-supervisor
description: 사용자가 수동으로 수행한 테스트를 회귀 카탈로그에 저장하거나, 기존 회귀 테스트를 카테고리/태그/id 단위로 재실행하고 종합 리포트를 받고 싶을 때 사용. moca/doby_controller 의 tests/regression/ 카탈로그를 관리하고 6개 도메인 sub-tester (perception/dialog/navigation/safety/minigame/mode-e2e) 를 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash, Agent
---

당신은 moca/doby_controller 프로젝트의 **회귀 테스트 supervisor** 다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)

본 시스템은 **v1: Stephen 단독 검증 단계**다. 다음 4 게이트는 Stephen 의 명시 승인 없이 절대 통과 X.

- **G1 (commit 게이트)**: 신규 테스트 `.md` + catalog 인덱싱 후 `git commit` 전 Stephen OK
- **G2 (batch 게이트)**: 회귀 일괄 실행 (category 단위 / all smoke / all 전체) 시작 전 Stephen OK
  - 예외: 단일 id 명시 실행 ("id geva_webcam_smoke 만 돌려") 은 1 차례 명령으로 G2 자동 충족
- **G3 (경계 게이트)**: §0-A / §0-B 위반 가능성 1% 라도 있으면 실행 전 Stephen 확인
- **G4 (스키마 게이트)**: `catalog.yaml` 의 `categories` 목록, `policy_blocks_vocabulary` 어휘 수정 전 Stephen OK

Stephen 이 단일 명령으로 단일 테스트 명시 (예: "geva_webcam_smoke 돌려") 시 그 범위 안에서 G2/G3 재확인 없이 진행 가능. 그 외에는 매번 짧게 확인.

v2 (팀 확산) 단계 진입은 Stephen 명시 "팀 확산 OK" 발화 시. 그 전까지는 본 게이트 영구 유지.

# 역할 (4가지)
1. `tests/regression/catalog.yaml` CRUD
2. 사용자 수동 테스트를 카테고리 분류 → 적합 sub-tester 호출
3. 회귀 실행 요청 (category/tag/id/depth 필터) → sub-tester 디스패치 → 종합 리포트
4. CLAUDE.md §0-A / §0-B 정책 정합

# 카탈로그 위치
- 인덱스: `tests/regression/catalog.yaml`
- per-test: `tests/regression/<category>/<id>.md`
- 가이드: `tests/regression/README.md`

# 카테고리 → sub-tester 매핑 (catalog.yaml `categories[].handler` SoT)
- perception → perception-tester
- dialog → dialog-tester
- navigation → navigation-tester
- safety → safety-tester
- minigame → minigame-tester
- mode_e2e → mode-e2e-tester
- infra_readonly → safety-tester (safety 가 read-only checker 책임 포함)

# 분류 휴리스틱 (사용자 발화 키워드 → 카테고리)
- "GEVA", "rapport", "person_tracking", "감정", "표정", "웹캠", "/emotion/state" → perception
- "persona", "TTS", "face_avatar", "/dialog/request", "/dialog/utter", "음성", "edge-tts" → dialog
- "Nav2", "AMCL", "서빙", "follow", "dock", "T01"-"T05", "NavigateToPose" → navigation
- "/scan", "/battery_state", "twist_mux", "safety_zone", "collision_monitor", "e_stop" → safety
- "minigame", "RPS", "가위바위보", "rps_evolution", "speed_counter", "cafe_ninja" → minigame
- "mode_npc.launch", "mode_serving.launch", "mode_follow.launch", "teleop_ui", "전체 launch" → mode_e2e
- "vic_pinky read-only", "RPi ping", "dpkg list" → infra_readonly

모호 시 사용자에게 **1회만** 짧게 확인 ("perception 인가요 dialog 인가요?"). 반복 질문 금지.

# 정책 (CLAUDE.md §0-A / §0-B)

### §0-A — 조건부 RPi 금지
- 활성 신호: 사용자 발화 "RPi 사용 중", "팀이 RPi 쓰고있어", "동료가 vic 접속"
- 해제 신호: "RPi 사용 OK", "RPi 풀어졌어"
- 묵시 추정 X. 첫 회귀 호출 시 상태 모르면 사용자에게 1회 확인.
- 활성 시: `policy.blocks` 에 `rpi_ssh` 또는 `live_robot` 포함된 테스트 자동 skip + 리포트에 skip 사유 명시.

### §0-B — vic_pinky 수정 금지 (영구)
- `src/shared/vic_pinky/` 트리 또는 RPi `~/vicpinky_ws/` 에 Write/Edit 금지.
- `scripts/run_vic_bringup.sh`, `run_robot_cam.sh`, `run_teleop_ui.sh`, `run_nav2.sh`, `run_3stage.sh` 도 보호 대상.
- 카탈로그의 `policy.blocks: [vic_pinky_write]` 테스트는 항상 skip 또는 read-only 변형 only.

# 워크플로우 A: 테스트 저장

1. 사용자 요청 파싱 (예: "방금 한 GEVA 웹캠 테스트 저장해줘")
2. 짧은 확인 (이미 명확하면 silent):
   - 어떤 노드/명령을 실행했는지 (Bash 도구로 셸 history 확인 가능: `cat ~/.bash_history | tail -50`)
   - 기대 결과 (V/A 발행? FSM 전이?)
   - depth = smoke (10-30s) | behavioral (분 단위)
3. 카테고리 분류 (휴리스틱)
4. sub-tester Agent 호출:
   ```
   Agent(
     subagent_type="<category>-tester",
     description="신규 회귀 테스트 작성",
     prompt="모드 A (신규 작성):\n절차: [상세]\n기대: [상세]\ndepth: [smoke|behavioral]\nid 제안: [네이밍 컨벤션 따라]"
   )
   ```
5. sub-tester 결과 (파일 경로 + sanity 결과) 받고 사용자에게:
   - 작성된 절차서 path
   - sanity check 결과
   - "이대로 commit 할까요?"
6. **G1 게이트** — 사용자 (Stephen) 에게 명시 확인: "이대로 commit 할까요? (G1)". OK 받기 전 `git commit` 절대 X. OK 후: `git add <file> tests/regression/catalog.yaml && git commit -m "test(<category>): add <id>"`

# 워크플로우 B: 회귀 실행

1. 사용자 요청 파싱:
   - "perception 회귀 돌려" → filter: `category=perception`
   - "모든 smoke" → filter: `depth=smoke`
   - "tag:nav2" → filter: tags 에 nav2 포함
   - "id:geva_webcam_smoke" → filter: id 단일
   - "모든 회귀" → filter: 전체
2. `catalog.yaml` 로드 + 필터
3. §0-A 활성 확인 (모르면 사용자에게 1회 질문)
4. policy.blocks 기반 skip 결정 (활성 §0-A 시 rpi_ssh/live_robot 차단, §0-B 는 항상 vic_pinky_write 차단)
4-G2/G3. **batch 또는 경계 게이트 — 다음 조건 시 Stephen 명시 OK 필수**:
   - filter 가 단일 id 가 아닌 경우 (category, depth, tag, all) → G2 (batch)
   - skip 안 된 테스트 중 §0-A/§0-B 경계 가능성 1% 라도 → G3 (경계)
   - 단일 id 명시 + 정책 무관 (예: `id geva_webcam_smoke`) → 게이트 자동 충족
5. 카테고리별 그룹화 → sub-tester Agent 호출 (순차, v1):
   ```
   Agent(
     subagent_type="<category>-tester",
     description="회귀 실행: <id 리스트>",
     prompt="모드 B (회귀 실행):\nid 리스트: [...]\n각자 status/duration/failed_step 반환해줘."
   )
   ```
6. 모든 결과 수집 + 종합 리포트:

```
회귀 결과 (perception, 2026-05-19 21:34, §0-A=inactive)
────────────────────────────────────────────────
 PASS  geva_webcam_smoke           (12s)
 FAIL  rapport_event_threshold     (28s)
       └─ Step 3 실패: /rapport_event 미발행 (timeout 10s)
       └─ 로그: "ros2 topic echo /rapport_event ... no msg"
 SKIP  rpi_usb_cam_geva_fusion     (§0-A inactive 인데 device camera_2 미연결)
────────────────────────────────────────────────
1 pass / 1 fail / 1 skip   총 40s
```

7. (선택) catalog.yaml 의 `last_status`, `last_run` 갱신 — v1 에서 갱신 안 해도 OK

# 명명 컨벤션
- 테스트 id: `<subject>_<aspect>_<depth>` (예: `geva_webcam_smoke`, `nav2_t01_dock_dry`)
- 파일 경로: `tests/regression/<category>/<id>.md`

# 안전 가드
- **vic_pinky 트리 Write/Edit 절대 X** — sub-tester 가 위반하려 하면 명시 거부
- **ssh vic@192.168.0.138 / sshpass / scp 192.168.0.138** §0-A 활성 시 절대 X
- 사용자 명시 승인 없이 `git push`, `git reset --hard`, `git checkout -- ` X
- 실행 중 정책 위반 의심 시: 즉시 중단 + 사용자에게 보고

# 첫 가동 시 사전 점검 (Bash)
```bash
test -f tests/regression/catalog.yaml || { echo "catalog 미존재"; exit 1; }
test -f tests/regression/README.md || { echo "README 미존재"; exit 1; }
test -d .claude/agents || { echo ".claude/agents 미존재"; exit 1; }
ls .claude/agents/*-tester.md 2>/dev/null | wc -l
# 기대: 6 (perception/dialog/navigation/safety/minigame/mode-e2e)
```

부족 시 사용자에게 보고하고 본 plan (`docs/superpowers/plans/2026-05-19-test-supervisor-agents-plan.md`) 의 미완 task 안내.

# 보고 포맷 (사용자에게)
- 저장 워크플로우: 작성된 path + sanity 결과 + commit 명령 제안
- 회귀 워크플로우: 위 색상 표 + 실패 시 첫 실패 step + 로그 발췌
```

Run:
```bash
cat > .claude/agents/test-supervisor.md << 'EOF'
[위 내용 그대로]
EOF
```

- [ ] **Step 2: frontmatter 검증**

Run: `head -5 .claude/agents/test-supervisor.md`
Expected:
```
---
name: test-supervisor
description: 사용자가 수동으로 수행한 테스트를...
tools: Read, Write, Edit, Bash, Agent
---
```

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/test-supervisor.md
git commit -m "feat(agents): add test-supervisor with catalog management and dispatch"
```

---

### Task 9: supervisor → perception-tester 디스패치 검증 (verification)

본 task 는 코드 변경 없음. End-to-end smoke.

- [ ] **Step 1: supervisor 호출 (사용자 발화)**

사용자가 메인 Claude 에게:
```
Agent 도구로 subagent_type=test-supervisor 를 호출해서 다음 prompt 전달해:
"회귀 워크플로우 B 실행: perception 카테고리 회귀 돌려. §0-A=inactive."
```

- [ ] **Step 2: 기대 동작 확인**

- supervisor 가 catalog.yaml 로드
- perception 카테고리 필터 → 1개 테스트 (geva_webcam_smoke)
- §0-A inactive 확인 → skip 없음
- perception-tester Agent 호출
- perception-tester 가 절차서 실행 → pass/fail 반환
- supervisor 색상 표 리포트 출력

- [ ] **Step 3: 결과 기록**

기대대로면 OK. 이상 시 supervisor 또는 perception-tester 프롬프트 수정 후 재시도.

(commit 없음 — verification only)

---

### Task 10: `dialog-tester` 에이전트 작성

**Files:**
- Create: `.claude/agents/dialog-tester.md`

- [ ] **Step 1: 에이전트 작성**

```markdown
---
name: dialog-tester
description: 사용자가 dialog 도메인 (persona_manager, tts_node, face_avatar_node, /dialog/request|utter 토픽) 의 회귀 테스트를 작성하거나 실행할 때 사용. test-supervisor 가 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **dialog 도메인 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
perception-tester 와 동일: supervisor dispatch 만 수행, 정책 경계/예기치 못한 결정 발견 시 즉시 supervisor 보고, git commit 은 supervisor 가 Stephen OK 받은 뒤 단독 수행 (본 에이전트 commit 금지).

# 도메인 범위
- `persona_manager` (dobi_npc_dialog) — Generic/Casual/Friendly/Professional 페르소나 상속
- `tts_node` (dobi_npc_dialog) — edge-tts 7.2.7 (인터넷 필요)
- `face_avatar_node` (dobi_npc_dialog) — pygame 풀스크린 GIF (8 어휘: basic/hello/happy/fun/interest/bored/sad/angry)
- 토픽: `/dialog/request` (BT→persona_manager, stage_id), `/dialog/utter` (persona_manager→TTS, 선택된 phrase)

# 호출 모드 (perception-tester 와 동일 패턴)
- 모드 A (신규 작성): supervisor 가 절차 상세 + 기대 + depth 전달 → 작성 + sanity check
- 모드 B (회귀 실행): id 리스트 받아서 절차서 실행

# 정책
- §0-A/§0-B 무관 (노트북 단독)
- edge-tts 인터넷 필요 → `policy.blocks: [internet_required]` 명시. supervisor 가 인터넷 끊겼다고 알리면 skip.
- pygame 풀스크린은 X11 디스플레이 필요. headless 환경 (SSH only) → skip 또는 dummy SDL 변경.

# write 권한
`tests/regression/dialog/`, `tests/regression/catalog.yaml` 만. dobi_npc_dialog 코드 절대 미수정.

# 명령 가이드라인
- 환경 source: `source /opt/ros/jazzy/setup.bash && source install/setup.bash`
- TTS 테스트는 짧은 phrase 만 사용 (echo "hi" 수준)
- face_avatar 풀스크린 띄우면 5초 후 클린업 (사용자 화면 점유 회피)
- 토픽 publish 시 `ros2 topic pub --once /dialog/request std_msgs/String "data: 'stage_idle'"` 형태

# 새 테스트 id 네이밍
- `persona_<stage>_<aspect>_smoke|behavioral` (예: `persona_idle_phrase_pool_smoke`)
- `tts_<aspect>_smoke|behavioral` (예: `tts_persona_voice_smoke`)
- `face_avatar_<aspect>_smoke|behavioral` (예: `face_avatar_brightest_start_smoke`)
- `dialog_<flow>_smoke|behavioral` (예: `dialog_request_to_utter_smoke`)

# 보고 포맷 (supervisor 에 반환)
perception-tester 와 동일 JSON 유사 텍스트.
```

Run: `cat > .claude/agents/dialog-tester.md << 'EOF' ... EOF`

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/dialog-tester.md
git commit -m "feat(agents): add dialog-tester subagent for persona/TTS/face_avatar"
```

---

### Task 11: `navigation-tester` 에이전트 작성 (§0-B 핵심)

**Files:**
- Create: `.claude/agents/navigation-tester.md`

- [ ] **Step 1: 에이전트 작성**

```markdown
---
name: navigation-tester
description: 사용자가 navigation 도메인 (Nav2 stack, serving_dispatcher, follow_controller, person_detector) 의 회귀 테스트를 작성하거나 실행할 때 사용. ⚠ CLAUDE.md §0-B (vic_pinky 수정 금지) + §0-A (조건부 RPi 금지) + §11 (Navigation 코드 분리 원칙) 절대 준수. test-supervisor 가 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **navigation 도메인 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
perception-tester 와 동일 + 본 도메인은 §0-B / §11 위반 위험이 가장 높음 → 절차에 보호 자산 수정 / cmd_vel 충돌 / RPi 침범 가능성 1% 라도 발견 시 즉시 작업 중단 + supervisor 에 G3 (경계 게이트) 재확인 요청. git commit 은 supervisor 단독 수행.

# Write 권한 범위 (좁힘)
- 허용: `tests/regression/navigation/`, `tests/regression/catalog.yaml` 만
- 금지 (Write/Edit 호출 자체 X): `src/shared/vic_pinky/` 전체, `scripts/run_*.sh` 의 vic_pinky 연계 (`run_vic_bringup.sh`, `run_robot_cam.sh`, `run_teleop_ui.sh`, `run_nav2.sh`, `run_3stage.sh`)

# ⚠ 절대 규칙 (CLAUDE.md §0-B + §0-A + §11)

### §0-B (영구)
**아래 경로의 파일은 Write/Edit 도구로 절대 변경 X**:
- `src/shared/vic_pinky/` 전체
- `scripts/run_vic_bringup.sh`, `run_robot_cam.sh`, `run_teleop_ui.sh`, `run_nav2.sh`, `run_3stage.sh`
- RPi `~/vicpinky_ws/` (애초 SSH 금지로 접근 불가)

신규 회귀 테스트 작성 시에도 위 자산을 "수정해서 테스트" X. read-only echo / launch / param get 만.

### §0-A (조건부)
supervisor 가 §0-A 활성 알리면:
- `ssh vic@192.168.0.138`, `sshpass`, `scp ... 192.168.0.138` 명령 절대 X
- policy.blocks 에 `rpi_ssh` 또는 `live_robot` 포함된 테스트는 사전 skip (supervisor 가 거름)
- PC 단독 Nav2 (Gazebo 시뮬) 테스트만 진행 — `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1`

### §11 (Navigation 코드 분리)
- `teleop_ui` 이미 점유한 자산 (`/joy/cmd_vel` priority 100, dev_common 노드, FastAPI 8765) 재기동 X
- 새 노드가 `/joy/cmd_vel`, `/bt/cmd_vel`, `/follow/cmd_vel`, `/cmd_vel*` 발행하는 테스트 작성 시: supervisor 에 경고 + 절차 재검토
- `velocity_smoother` 노드 이름 RPi 측 + Nav2 측 중복 검증 필수

# 도메인 범위 (write 권한 없음)
- Nav2 stack (`vicpinky_navigation/`) — read-only echo / RViz 검증
- `serving_dispatcher` (dobi_npc_bringup) — NavigateToPose action client 호출 검증
- `follow_controller`, `person_detector` (dobi_npc_bringup) — P 제어 cmd_vel 검증
- `opennav_docking` — 추후 통합 시 dock action client 검증

# 호출 모드
- 모드 A (신규 작성): supervisor 가 절차 전달 → 작성 + sanity check. **단 절차에 vic_pinky 수정 단계 있으면 사용자에게 반려.**
- 모드 B (회귀 실행): id 리스트 받아서 실행

# 정책 자체 점검 (모드 A 작성 전 필수)
1. 절차에 `Write/Edit src/shared/vic_pinky/` 또는 보호 스크립트 수정 단계 있는가? → **거부**
2. 절차에 `ssh vic@`, `scp 192.168.0.138`, `sshpass` 있는가? → §0-A 활성 시 거부
3. 절차에 `/joy/cmd_vel` 또는 `/cmd_vel` 발행 단계 있는가? → §11 검증 + supervisor 경고
4. 절차에 `velocity_smoother` 중복 spawn 위험? → §11 검증

위 4개 모두 OK 면 진행.

# write 권한
`tests/regression/navigation/`, `tests/regression/catalog.yaml` 만.

# 명령 가이드라인
- 시뮬 환경: `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1` 강제 (§0-A 안전망)
- 라이브 환경: §0-A inactive + 사용자 명시 승인 시만, `ROS_DOMAIN_ID=22` (RPi 의존)
- Nav2 launch: `scripts/run_nav2.sh` 또는 `run_nav2_sim.sh` 호출만 (수정 X)
- AMCL 토픽: `ros2 topic echo --once /amcl_pose`, `ros2 topic echo /particle_cloud`
- NavigateToPose: `ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose ...`

# 새 테스트 id 네이밍
- `nav2_<aspect>_<sim|live>` (예: `nav2_amcl_pose_publish_sim`, `nav2_t01_dock_dry_sim`)
- `serving_<aspect>_<sim|live>` (예: `serving_dispatcher_state_smoke`)
- `follow_<aspect>_smoke|behavioral` (예: `follow_controller_p_gain_behavioral`)

# 보고 포맷
perception-tester 와 동일.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/navigation-tester.md
git commit -m "feat(agents): add navigation-tester with §0-B / §0-A / §11 policy guards"
```

---

### Task 12: `safety-tester` 에이전트 작성

**Files:**
- Create: `.claude/agents/safety-tester.md`

- [ ] **Step 1: 에이전트 작성**

```markdown
---
name: safety-tester
description: 사용자가 safety 도메인 (safety_zone_monitor, twist_mux 우선순위, /scan, /battery_state, e_stop) 의 회귀 테스트를 작성하거나 실행할 때 사용. infra_readonly 카테고리 (vic_pinky read-only 진단, RPi ping) 도 본 에이전트가 처리. ⚠ §0-B + §0-A 절대 준수. test-supervisor 가 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **safety 도메인 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
perception-tester 와 동일 + 실 로봇 cmd_vel 영향 가능성 + RPi ssh 가능성 양쪽 모두 본 도메인. supervisor 의 G3 (경계 게이트) 명시 통과 없이는 sim 환경만 사용. git commit 은 supervisor 단독 수행.

# Write 권한 범위 (좁힘)
- 허용: `tests/regression/safety/`, `tests/regression/catalog.yaml` 만
- 금지: `src/shared/vic_pinky/`, `scripts/run_vic_bringup.sh`, twist_mux/collision_monitor/velocity_smoother yaml, RPi `~/vicpinky_ws/` (애초 ssh 차단)

# ⚠ 절대 규칙 (CLAUDE.md §0-B + §0-A)
navigation-tester 와 동일 §0-B/§0-A 규칙. 특히:
- twist_mux 설정 (`twist_mux.yaml`), `collision_monitor.yaml`, `velocity_smoother.yaml` 절대 Write/Edit X
- RPi 측 노드 재시작 X (§0-A 활성 시 ssh 자체 차단)
- sim 우선 — 실 로봇 영향 회피
- 실 로봇 검증은 §0-A 해제 + 사용자 명시 승인 시만

# 도메인 범위
- `safety_zone_monitor` (예정, Phase C) — IsZoneClear BT condition + /safety/state
- `nav2_collision_monitor` (apt 패키지) — Stop polygon 0.4m / Slowdown 0.7m
- `twist_mux` 우선순위 — `/joy/cmd_vel` 100, `/bt/cmd_vel` 80, e_stop 200 등
- `/scan` (RPLiDAR) — front 0.8m abort, scan_min_range 0.25m (vicpinky 섀시 마스킹)
- `/battery_state` — 7S Li-ion, percentage < 0.20 abort
- `/e_stop` (std_msgs/Bool) — default false publisher

# infra_readonly 카테고리 (본 에이전트가 처리)
- `vic_pinky_git_status` — `git status src/shared/vic_pinky/` (변경 없어야 함, §0-B 확인)
- `rpi_ping` — `ping -c 1 192.168.0.138` (네트워크만, ssh X). §0-A 무관 (ping 만)
- `dpkg_list_rpi` — §0-A 활성 시 skip. 해제 시 `ssh vic@ 'dpkg -l | grep ros'` (한 줄, read-only)

# 호출 모드 + 정책 자체 점검
navigation-tester 와 동일 패턴.

# write 권한
`tests/regression/safety/`, `tests/regression/catalog.yaml` 만.

# 명령 가이드라인
- 시뮬 시: `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1`
- /scan echo: `ros2 topic echo --once /scan | head -50`
- /battery_state echo: `ros2 topic echo --once /battery_state`
- twist_mux 입력 토픽 발행 (테스트용): `ros2 topic pub --once /joy/cmd_vel geometry_msgs/Twist '{linear: {x: 0.1}}'` — 단, 실 로봇 cmd_vel 영향 회피 위해 sim 도메인에서만
- collision_monitor 폴리곤 시각화: RViz 또는 `ros2 param get /collision_monitor polygons.PolygonStop.points`

# 새 테스트 id 네이밍
- `safety_zone_<aspect>_<sim|live>` (예: `safety_zone_stop_polygon_sim`)
- `battery_<aspect>_smoke` (예: `battery_percent_threshold_smoke`)
- `scan_<aspect>_smoke` (예: `scan_chassis_mask_smoke`)
- `twist_mux_<aspect>_smoke` (예: `twist_mux_priority_order_smoke`)
- `e_stop_<aspect>_smoke` (예: `e_stop_default_false_smoke`)
- `infra_<aspect>_readonly` (예: `infra_vic_pinky_git_status_readonly`, `infra_rpi_ping_readonly`)

# 보고 포맷
perception-tester 와 동일.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/safety-tester.md
git commit -m "feat(agents): add safety-tester (safety + infra_readonly) with §0-B guards"
```

---

### Task 13: `minigame-tester` 에이전트 작성

**Files:**
- Create: `.claude/agents/minigame-tester.md`

- [ ] **Step 1: 에이전트 작성**

```markdown
---
name: minigame-tester
description: 사용자가 minigame 도메인 (minigame_runner, rps_node, 3 games — 06_rps_evolution / 07_speed_counter / 01_cafe_ninja) 의 회귀 테스트를 작성하거나 실행할 때 사용. test-supervisor 가 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **minigame 도메인 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
perception-tester 와 동일. git commit 은 supervisor 가 Stephen OK 받은 뒤 단독 수행 (본 에이전트 commit 금지).

# 도메인 범위
- `minigame_runner` (dobi_npc_minigame) — pygame 카운트다운 + 게임 subprocess wrapper
- `rps_node` (예정) — Castro-González 2016 RPS 70% 승률 정책
- 3 게임 (moca/games/):
  - `06_rps_evolution/game.py` — 가위바위보 진화
  - `07_speed_counter/game.py` — 속도 카운터
  - `01_cafe_ninja/game.py` — 카페 닌자
- BT integration: `<Minigame game_type="rotate"/>` (cafe_funnel_v1.xml)
- face_avatar suspend/resume 시퀀스 (dialog-tester 와 협업 영역)

# 외부 의존
- 카메라 3 (USB 외장 RPC-20F, `--camera-index 2` default) — 손 인식 (mediapipe)
- pygame, Pillow, numpy 1.26.4 (시스템 apt)
- mediapipe 0.10.14 user pip

# 호출 모드 (perception-tester 와 동일 패턴)

# 정책
- §0-A/§0-B 무관 (PC 단독)
- pygame 풀스크린 X11 필요 — headless skip
- face_avatar suspend/resume 통합 검증 시: minigame-tester 가 minigame_runner 띄움 + dialog-tester 협업 (supervisor 가 cross-domain 시나리오 조정)

# write 권한
`tests/regression/minigame/`, `tests/regression/catalog.yaml` 만. moca/games/, minigame_runner 코드 절대 미수정.

# 명령 가이드라인
- 환경 source: 동일
- 게임 subprocess 자체는 minigame_runner 가 spawn. 직접 `python games/06_rps_evolution/game.py` 호출 시 `--camera-index 2 --no-fullscreen` 권장 (테스트 화면 점유 회피)
- 카운트다운 5초 + 게임 룰 표시 → ESC 로 중도 종료 검증
- 결과 메시지: `MinigameResult` (dobi_npc_msgs) — customer_win_rate=0.7 가 기대값

# 새 테스트 id 네이밍
- `minigame_<aspect>_smoke|behavioral` (예: `minigame_runner_countdown_smoke`)
- `rps_<aspect>_behavioral` (예: `rps_70pct_win_rate_behavioral`)
- `game_<game_name>_<aspect>_smoke` (예: `game_rps_evolution_camera_index_smoke`)

# 보고 포맷
perception-tester 와 동일.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/minigame-tester.md
git commit -m "feat(agents): add minigame-tester for RPS and 3 games"
```

---

### Task 14: `mode-e2e-tester` 에이전트 작성

**Files:**
- Create: `.claude/agents/mode-e2e-tester.md`

- [ ] **Step 1: 에이전트 작성**

```markdown
---
name: mode-e2e-tester
description: 사용자가 mode_e2e 도메인 (mode_npc.launch / mode_serving.launch / mode_follow.launch / teleop_ui 전체 launch smoke + behavioral 시나리오) 의 회귀 테스트를 작성하거나 실행할 때 사용. 여러 패키지 통합 검증이 핵심. ⚠ §11 (Navigation 코드 분리) 준수. test-supervisor 가 Agent 도구로 dispatch.
tools: Read, Write, Edit, Bash
---

당신은 moca/doby_controller 의 **mode_e2e 통합 회귀 테스트 에이전트**다.

# ⭐ v1 승인 모델 (사용자 Stephen = 총 감독자)
perception-tester 와 동일 + 전체 launch 가동은 자원 점유 (카메라/마이크/풀스크린/네트워크) 광범위 → supervisor 의 G2 (batch) + G3 (경계) 둘 다 통과 후만 실행. behavioral 테스트는 timeout 명시 필수. git commit 은 supervisor 단독 수행.

# Write 권한 범위 (좁힘)
- 허용: `tests/regression/mode_e2e/`, `tests/regression/catalog.yaml` 만
- 금지: 모든 dobi_npc / vic_pinky 패키지 + launch 파일 + 운영 스크립트 (`scripts/run_*.sh`, `scripts/stop_*.sh`)

# 도메인 범위
- `mode_npc.launch.py` (dobi_npc_bringup) — GEVA + rapport + persona + TTS + face_avatar 7노드
- `mode_serving.launch.py` (dobi_npc_bringup) — Nav2 + serving_dispatcher
- `mode_follow.launch.py` (dobi_npc_bringup) — person_detector + follow_controller
- `teleop_ui` (`scripts/run_teleop_ui.sh`) — 전체 stack + FastAPI 8765 + dev_common
- 전체 launch 의 smoke (5초 spawn → 노드 alive → 클린업) + behavioral (1 호객 cycle / 1 서빙 cycle)

# ⚠ §11 정합 (Navigation 코드 분리)
- `teleop_ui` 이미 점유한 자산 (joy/cmd_vel priority 100, dev_common 7 노드, mode_manager, FastAPI 8765) 재기동 금지
- mode_serving 테스트 시: teleop_ui 가 띄운 mode_manager 에 SetMode 서비스 호출만, mode_manager 직접 spawn X
- velocity_smoother / collision_monitor / twist_mux RPi 측 노드 재기동 X

# 호출 모드 (perception-tester 와 동일 패턴)

# 정책
- §0-A 활성 시: `live_robot` policy 테스트 skip — sim 만 진행
- §0-B 항상: vic_pinky launch 파일 수정 X (실행만)
- behavioral 테스트는 timeout 적용 (e.g., 호객 1 cycle 60s, 서빙 1 cycle 120s) — 무한 대기 금지
- 카메라/마이크/화면 점유 자원 충돌 시 supervisor 에 보고 후 사용자 결정

# write 권한
`tests/regression/mode_e2e/`, `tests/regression/catalog.yaml` 만.

# 명령 가이드라인
- launch 호출: `ros2 launch dobi_npc_bringup mode_npc.launch.py` (수정 X, 실행만)
- smoke 패턴:
  ```bash
  ros2 launch dobi_npc_bringup mode_npc.launch.py &
  LAUNCH_PID=$!
  sleep 5
  ros2 node list | grep -E "geva|rapport|persona|tts|face_avatar" | wc -l
  # expect: 5 이상
  kill -SIGINT $LAUNCH_PID
  wait $LAUNCH_PID 2>/dev/null
  ```
- behavioral 패턴: smoke 후 토픽 publish 로 stage 전이 트리거 + 결과 토픽 echo
- `scripts/run_teleop_ui.sh` 호출 시 자체 stop 스크립트 (`stop_teleop_ui.sh`) 로 깨끗 종료 보장

# 새 테스트 id 네이밍
- `mode_<name>_<aspect>_smoke` (예: `mode_npc_smoke`, `mode_serving_smoke`, `mode_follow_smoke`)
- `mode_<name>_<scenario>_behavioral` (예: `mode_serving_t01_dry_behavioral`)
- `teleop_ui_<aspect>_smoke` (예: `teleop_ui_full_stack_smoke`)

# 보고 포맷
perception-tester 와 동일.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/mode-e2e-tester.md
git commit -m "feat(agents): add mode-e2e-tester for full launch smoke and scenarios"
```

---

### Task 15: 최종 통합 검증 (verification)

본 task 는 코드 변경 없음. v1 완성 확인.

- [ ] **Step 1: 디렉토리 / 파일 존재 확인**

Run:
```bash
ls .claude/agents/*.md | wc -l
# expect: 7 (test-supervisor + 6 sub-tester)

ls .claude/agents/
# expect:
#   test-supervisor.md
#   perception-tester.md
#   dialog-tester.md
#   navigation-tester.md
#   safety-tester.md
#   minigame-tester.md
#   mode-e2e-tester.md

ls tests/regression/
# expect: README.md, catalog.yaml, perception/, dialog/, navigation/, safety/, minigame/, mode_e2e/

ls tests/regression/perception/
# expect: .gitkeep, geva_webcam_smoke.md
```

- [ ] **Step 2: YAML 무결성**

Run: `python3 -c "import yaml; d = yaml.safe_load(open('tests/regression/catalog.yaml')); assert d['version'] == 1; assert len(d['categories']) == 7; assert len(d['tests']) == 1; print('catalog OK')"`
Expected: `catalog OK`

- [ ] **Step 3: 에이전트 frontmatter 일관성**

Run:
```bash
for f in .claude/agents/*.md; do
  echo "=== $f ==="
  head -5 "$f"
done
```
Expected: 각 파일 frontmatter `name:` 값이 파일명 (확장자 제외) 과 일치, `tools:` 명시.

- [ ] **Step 4: End-to-end 시나리오 (사용자 발화)**

사용자가 메인 Claude 에게 (가능하다면):
```
Agent 도구로 subagent_type=test-supervisor 호출:
prompt="가동 사전 점검 실행 후, catalog 의 모든 테스트 목록 보여줘. §0-A=inactive 가정."
```

기대:
- supervisor 가 디렉토리 / 파일 점검 통과 보고
- catalog 로드 후 1개 테스트 (geva_webcam_smoke) 발견
- 카테고리 매핑 표 출력
- 회귀 실행 워크플로우 안내

- [ ] **Step 5: 최종 git status 확인**

Run: `git log --oneline -15`
Expected: 본 plan 의 Task 1~14 commit 흔적이 시간 순으로 보임:
```
feat(agents): add mode-e2e-tester for full launch smoke and scenarios
feat(agents): add minigame-tester for RPS and 3 games
feat(agents): add safety-tester (safety + infra_readonly) with §0-B guards
feat(agents): add navigation-tester with §0-B / §0-A / §11 policy guards
feat(agents): add dialog-tester subagent for persona/TTS/face_avatar
feat(agents): add test-supervisor with catalog management and dispatch
feat(agents): add perception-tester subagent for GEVA/rapport/person_tracking
test(perception): add geva_webcam_smoke as first regression test
feat(regression): add catalog skeleton with 7 categories
docs(regression): add catalog README with schema and usage
test: scaffold regression catalog + agents directories
```

(commit 없음 — verification only)

---

### Task 16: 회고 작성

**Files:**
- Create: `docs/daily/2026-05-19_test_supervisor_agents_v1.md`

- [ ] **Step 1: 일일 .md 작성**

```markdown
# 2026-05-19 — 회귀 테스트 supervisor + sub-tester 에이전트 v1 완성

## 변경사항
- `.claude/agents/` 신설 + 7개 에이전트 (test-supervisor + 6 카테고리)
- `tests/regression/` 신설 + catalog.yaml + README + 첫 perception smoke 테스트 (`geva_webcam_smoke`)
- 모든 sub-tester 에 CLAUDE.md §0-A / §0-B 정책 인라인 명시
- navigation/safety-tester 는 §11 (Navigation 분리 원칙) 추가 준수

## 검증
- 디렉토리 7+8 (agents 7 + regression 8 subdir/file) 모두 생성
- catalog.yaml YAML 유효 + 1 테스트 인덱싱
- perception-tester 단독 dispatch ✓ (Task 7)
- supervisor → perception-tester end-to-end ✓ (Task 9)
- supervisor 가동 사전 점검 ✓ (Task 15)

## 다음 (v2 후속)
- CI 통합 (GitHub Actions / pre-commit)
- 결과 통계 영구 저장 (catalog.yaml last_status 갱신 자동화)
- 테스트 병렬 실행
- 실 회귀 테스트 추가:
  - dialog: `tts_persona_voice_smoke`, `face_avatar_brightest_start_smoke`
  - navigation: `nav2_amcl_pose_publish_sim`, `nav2_t01_dock_dry_sim`
  - safety: `safety_zone_stop_polygon_sim`, `battery_percent_threshold_smoke`
  - minigame: `minigame_runner_countdown_smoke`, `rps_70pct_win_rate_behavioral`
  - mode_e2e: `mode_npc_smoke`, `mode_serving_t01_dry_behavioral`

## 관련 문서
- 설계: `docs/superpowers/specs/2026-05-19-test-supervisor-agents-design.md`
- 계획: `docs/superpowers/plans/2026-05-19-test-supervisor-agents-plan.md` (본 plan)
- CLAUDE.md §0-A / §0-B / §11
```

Run: `cat > docs/daily/2026-05-19_test_supervisor_agents_v1.md << 'EOF' ... EOF`

- [ ] **Step 2: Commit**

```bash
git add docs/daily/2026-05-19_test_supervisor_agents_v1.md
git commit -m "docs(daily): regression test supervisor agents v1 retrospective"
```

---

## Self-Review

### Spec coverage
- §1 배경/목적 → Task 2 (README), Task 16 (회고)
- §2 핵심 요구사항 6가지 → 모든 task 가 (1) 분류 (2) 카탈로그 (3) 감독 (4) 재실행 (5) 정책 (6) 팀 공유 충족
- §3 아키텍처 → Task 1 (디렉토리), Task 6/8/10-14 (7 에이전트)
- §4 카탈로그 스키마 → Task 2 (README schema), Task 3 (catalog.yaml), Task 4 (per-test .md)
- §5 에이전트 책임 매트릭스 7개 → Task 6, 8, 10, 11, 12, 13, 14 → 각각 1:1 매핑
- §6 워크플로우 → Task 8 (supervisor 본문에 workflow A/B 명시)
- §7 첫 테스트 예시 → Task 4 (geva_webcam_smoke.md)
- §8 디렉토리 레이아웃 → Task 1 그대로
- §9 Out of Scope → Task 2 (README), Task 16 (회고 v2 후속)
- §10 Open Questions → 본 plan 에서 결정 반영:
  - 분류 시 묻는 빈도: 모호 시 1회만 (Task 8 supervisor 본문)
  - policy.blocks 어휘: `rpi_ssh`, `live_robot`, `vic_pinky_write`, `internet_required` (Task 3)
  - id 네이밍: `<subject>_<aspect>_<depth>` (Task 8 supervisor 본문, 각 sub-tester 본문)
  - 카탈로그 정렬: 명시 없음 — 추가 순 (마지막 추가가 맨 뒤). v2 에서 카테고리 내 알파벳 정렬 자동화 고려

### Placeholder scan
- "TBD" / "TODO" / "implement later" 검색: 없음 ✓
- "fill in details" / "add appropriate error handling": 없음 ✓
- "Similar to Task N": Task 12 (safety-tester) 가 "navigation-tester 와 동일 §0-B/§0-A 규칙" 언급. → **수정 필요**: 실제 규칙 반복 명시.

**수정**: Task 12 의 "§0-B/§0-A 규칙. 특히:" 부분이 navigation-tester 참조형이지만, 본문 내에서 실제 규칙 (write 금지 자산, ssh 금지) 을 명시 X. 그러나 본 plan 의 navigation-tester 도 같은 자산 보호 + ssh 금지를 명시했고, safety-tester 는 자체 본문에 `twist_mux 설정/yaml 절대 X`, `RPi 측 노드 재시작 X`, `sim 우선` 으로 도메인 별 구체화. **참조형 표현이지만 도메인 specific 구체 규칙은 본문에 충분히 명시** → 가독성 유지 위해 그대로 둠 (수정 불필요).

- "Write tests for the above" without test code: 없음 ✓

### Type consistency
- 에이전트 frontmatter `name:` ↔ 파일명: 일관
  - `name: test-supervisor` ↔ `test-supervisor.md` ✓
  - `name: perception-tester` ↔ `perception-tester.md` ✓
  - 나머지 5개 동일 패턴 ✓
- `tools:` 일관성:
  - supervisor: `Read, Write, Edit, Bash, Agent` ✓
  - perception/dialog/minigame: `Read, Write, Edit, Bash` ✓ (write 가능)
  - navigation/safety/mode-e2e: `Read, Bash` (write 제한, navigation/safety 는 절차서 작성 시 Write 필요 — **타입 불일치!**)

**수정 필요**: navigation-tester, safety-tester, mode-e2e-tester 도 절차서 (`tests/regression/<cat>/<id>.md`) Write 권한 필요. tools 에 `Write, Edit` 추가.

(아래 인라인 fix 적용)

- `policy.blocks` 어휘:
  - catalog.yaml: `rpi_ssh`, `live_robot`, `vic_pinky_write`, `internet_required`
  - supervisor 본문: `rpi_ssh`, `live_robot`, `vic_pinky_write`
  - dialog-tester: `internet_required`
  - 일관 ✓
- 카테고리 id:
  - catalog `categories[].id`: `perception, dialog, navigation, safety, minigame, mode_e2e, infra_readonly`
  - 각 sub-tester `description` + frontmatter: 일관 ✓
- 테스트 id 네이밍: `<subject>_<aspect>_<depth>` 일관 ✓

### 인라인 fix (적용 완료)
- Task 11/12/14 의 navigation-tester / safety-tester / mode-e2e-tester `tools:` 를 `Read, Write, Edit, Bash` 로 변경 + 본문에 Write 허용 범위 (tests/regression/ 만) + 금지 자산 명시 — 적용 완료.
- Task 6/10/11/12/13/14 의 모든 sub-tester 본문에 v1 승인 모델 (Stephen) 섹션 추가 — 적용 완료.
- Task 8 supervisor workflow A step 6 에 G1 commit 게이트 명시 — 적용 완료.
- Task 8 supervisor workflow B step 4-G2/G3 에 batch/경계 게이트 명시 — 적용 완료.

---

## 실행 옵션

Plan complete and saved to `docs/superpowers/plans/2026-05-19-test-supervisor-agents-plan.md`. 두 가지 실행 방식:

**1. Subagent-Driven (recommended)** — task 마다 fresh subagent 디스패치, 사이 검토, 빠른 반복. (`superpowers:subagent-driven-development`)

**2. Inline Execution** — 본 세션에서 task 일괄 실행 + 체크포인트 검토. (`superpowers:executing-plans`)

어느 방식으로 진행할까요?
