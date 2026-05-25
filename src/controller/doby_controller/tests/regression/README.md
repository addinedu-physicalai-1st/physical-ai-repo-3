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
