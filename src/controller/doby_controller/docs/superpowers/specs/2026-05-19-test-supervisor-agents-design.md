# 회귀 테스트 Supervisor + 카테고리 Sub-Tester 에이전트 설계서

**작성일**: 2026-05-19
**작성자**: 공국진 (Stephen) + Claude (Opus 4.7)
**상태**: design (사용자 검토 대기)
**관련**: CLAUDE.md §0-A / §0-B / §11

---

## 1. 배경 & 목적

moca/doby_controller 프로젝트는 Phase 0-B 완료 + 노트북 단독 트랙 완성 + Phase 3 미니게임 통합 완료 상태에서, dobi_npc 7개 패키지 + 30+ 운영 스크립트 + 다중 launch 모드 (`mode_npc`, `mode_serving`, `mode_follow`, `teleop_ui`) 를 수동으로 검증하고 있다. 검증 절차가 회고 `.md` 안에 흩어져 있어 다음과 같은 문제가 있다.

- 같은 테스트를 N번째 수행할 때 절차를 매번 재구성해야 함 (히스토리 셸 기억 + 회고 검색)
- 코드 변경 후 어떤 테스트가 영향받는지 일관 추적 불가
- 팀원 합류 시 (송민규/류재상 등) 동일 기준으로 검증하기 어려움
- 회귀 (regression) 의 의미가 모호: "라이브 직전 한 번 돌려본다" 수준

본 설계는 **수동 테스트를 유형 분류 → 표준 `.md` 절차서로 카탈로그화 → 후일 동일 절차 재실행 (regression)** 을 자동화하는 **Claude Code 서브에이전트** 시스템을 정의한다.

---

## 2. 핵심 요구사항

1. **유형화**: 사용자가 방금 수행한 테스트를 듣고 적절한 카테고리로 분류
2. **카탈로그**: 표준 스키마로 git-committed 절차서 작성, 인덱스 유지
3. **감독**: 절차 실행 시 precondition / 단계 / 기대값을 supervisor 가 검증
4. **재실행**: 카테고리/태그/id 단위로 회귀 실행 + 종합 리포트
5. **정책 정합**: §0-A (조건부 RPi 금지) + §0-B (vic_pinky 수정 금지) 위반 가능 명령을 에이전트 레벨에서 차단
6. **팀 공유**: 카탈로그 + 에이전트 정의 모두 git committed → 팀원 onboarding 즉시 가능

---

## 3. 아키텍처

```
사용자 입력
    │
    ▼
┌──────────────────────────────┐
│  test-supervisor             │  Top-level agent
│  - 카탈로그 read/write       │
│  - 카테고리 분류              │
│  - sub-tester 디스패치       │
│  - §0-A/§0-B 정책 검증       │
│  - 종합 리포트                │
└──────┬───────────────────────┘
       │ Agent 도구로 호출
       │
   ┌───┼───────┬──────────┬────────┬─────────┬─────────┐
   ▼   ▼       ▼          ▼        ▼         ▼         ▼
perception  dialog   navigation  safety   minigame  mode-e2e
-tester    -tester   -tester    -tester  -tester   -tester
                     ⚠ §0-B    ⚠ §0-B
                     준수      준수
   │
   ▼ (모든 sub-tester 공통)
tests/regression/
├── catalog.yaml
├── perception/<id>.md
├── dialog/<id>.md
├── navigation/<id>.md
├── safety/<id>.md
├── minigame/<id>.md
└── mode_e2e/<id>.md
```

**호출 패턴**:

- **저장**: `사용자 → supervisor → (분류 결정) → 해당 카테고리 sub-tester → .md 작성 + catalog 갱신`
- **실행**: `사용자 → supervisor → (catalog 필터) → 1+ sub-tester 디스패치 → 각자 결과 반환 → supervisor 종합 리포트`

**컨텍스트 격리 이유**: sub-tester 가 별도 Agent 호출로 spawn 되면 자기 도메인 프롬프트만 로드 → §0-B 위반 회피, 도구 스코핑 가능, 컨텍스트 윈도우 절약.

---

## 4. 카탈로그 스키마

### 4.1 `tests/regression/catalog.yaml` (인덱스)

```yaml
version: 1
generated: 2026-05-19
tests:
  - id: geva_webcam_smoke
    category: perception
    file: perception/geva_webcam_smoke.md
    depth: smoke              # smoke | behavioral
    tags: [geva, webcam, phase2]
    duration_estimate_sec: 15
    requires:
      - device: camera_1       # 노트북 웹캠
      - package: dobi_npc_emotion
    policy:
      blocks: []               # ["rpi_ssh", "vic_pinky_write"] 등
    added: 2026-05-19
    last_passed: null

  - id: nav2_t01_dock_dry
    category: navigation
    file: navigation/nav2_t01_dock_dry.md
    depth: behavioral
    tags: [nav2, serving, sim-only]
    duration_estimate_sec: 90
    requires:
      - package: dobi_npc_bringup
      - sim: gazebo
    policy:
      blocks: [rpi_ssh, vic_pinky_write]  # 시뮬만 허용
    added: 2026-05-19
    last_passed: null
```

**필드 의미**:
- `id` — kebab-case 고유 식별자
- `category` — 7개 sub-tester 도메인 중 1개 (`perception`, `dialog`, `navigation`, `safety`, `minigame`, `mode_e2e`, `infra_readonly`)
- `depth` — `smoke` (10-30초, spawn + 토픽 존재) / `behavioral` (분 단위, 시나리오)
- `requires` — 디바이스/패키지/외부 자원 (precondition gate)
- `policy.blocks` — 본 테스트가 본질적으로 정책 위반 (e.g., RPi ssh 필요) 시 차단 표시. supervisor 가 §0-A 활성 상태에서 자동 skip
- `last_passed` — 회귀 통과 시 갱신 (선택)

### 4.2 per-test `.md` 스키마

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
  - moca_build 성공
  - source install/setup.bash 완료
policy_notes:
  - "§0-A 무관 (노트북 단독)"
  - "§0-B 무관 (vic_pinky 자산 미참조)"
---

# 목적
GEVA 노드가 노트북 웹캠을 열고 `/emotion/state` 토픽을 발행하는지 확인.

# 셋업
```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run dobi_npc_emotion geva_node &
GEVA_PID=$!
sleep 3
```

# 단계
1. `ros2 topic list | grep -q /emotion/state` — expect: 토픽 존재 (exit 0)
2. `timeout 5 ros2 topic echo --once /emotion/state` — expect: `source: "face"`, `confidence > 0`
3. `kill -0 $GEVA_PID` — expect: 노드 alive (exit 0)

# 기대 결과
- `/emotion/state` 발행 주기 ≥ 1Hz
- `valence`, `arousal` 범위 [-1, 1]
- `source = "face"`

# 클린업
```bash
kill $GEVA_PID 2>/dev/null
wait $GEVA_PID 2>/dev/null
```

# 알려진 이슈
- mediapipe `0.10.14` user pip 필수 (CLAUDE.md §7 외부 의존성)
- 웹캠 미연결 시 본 테스트 skip (precondition 미달)
```

---

## 5. 에이전트 책임 매트릭스

### 5.1 test-supervisor (top)

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/test-supervisor.md` |
| 도구 | `Read`, `Write`, `Edit`, `Bash`, `Agent` |
| 책임 | 카탈로그 CRUD / 카테고리 분류 / sub-tester 디스패치 / 종합 리포트 |
| 정책 인지 | §0-A 활성 여부 판정 (사용자에게 묻거나 RPi ping 으로 추정), §0-B blocks 자동 skip |
| 호출 트리거 | "테스트 저장", "회귀 돌려", "perception 만 돌려", "tagged smoke 만" |

### 5.2 perception-tester

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/perception-tester.md` |
| 도구 | `Read`, `Write`, `Edit`, `Bash` |
| 도메인 | `geva_node`, `rapport_tracker`, `decision_rule_node` (예정), `person_tracking_pkg` |
| 입력 자원 | 카메라 1 (노트북 웹캠), 카메라 2 (RPi USB — read-only), 카메라 3 (USB 외장) |
| 정책 | §0-A/§0-B 무관 (PC 단독 노드) |
| 대표 테스트 | `geva_webcam_smoke`, `rapport_event_threshold`, `person_tracking_msg_shape` |

### 5.3 dialog-tester

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/dialog-tester.md` |
| 도구 | `Read`, `Write`, `Edit`, `Bash` |
| 도메인 | `persona_manager`, `tts_node`, `face_avatar_node`, `/dialog/request|utter` 토픽 |
| 외부 의존 | edge-tts `7.2.7` (인터넷 필요), pygame, gif assets |
| 정책 | §0-A/§0-B 무관 |
| 대표 테스트 | `tts_persona_voice_smoke`, `face_avatar_brightest_start`, `dialog_request_to_utter` |

### 5.4 navigation-tester ⚠ §0-B 핵심

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/navigation-tester.md` |
| 도구 | `Read`, `Bash` (write 금지 vic_pinky 경로) |
| 도메인 | Nav2 stack, `serving_dispatcher`, `follow_controller`, `person_detector` |
| **금지** | vic_pinky tree (`src/shared/vic_pinky/`) Edit/Write, RPi scp/ssh (§0-A 활성 시) |
| **허용** | PC 측 Nav2 launch, AMCL 토픽 echo (read-only), NavigateToPose action client, RViz spawn |
| 정책 | §0-A 활성 시 RPi 의존 테스트 skip, §0-B 항상 준수 |
| 대표 테스트 | `nav2_amcl_pose_publish`, `nav2_t01_dock_dry` (sim), `follow_controller_p_gain` |

### 5.5 safety-tester ⚠ §0-B 핵심

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/safety-tester.md` |
| 도구 | `Read`, `Bash` (read-only ros2 cli 위주) |
| 도메인 | `safety_zone_monitor`, twist_mux 우선순위, `/scan`, `/battery_state` |
| **금지** | twist_mux 설정 Edit, collision_monitor 폴리곤 변경, RPi 측 노드 재시작 |
| **허용** | sim 측 polygon 검증, BT IsZoneClear condition 단위 테스트, /scan echo |
| 정책 | sim 우선 (실 로봇 영향 회피), 실 로봇 검증은 §0-A 해제 + 사용자 명시 |
| 대표 테스트 | `safety_zone_stop_polygon_sim`, `battery_percent_threshold`, `e_stop_default_false` |

### 5.6 minigame-tester

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/minigame-tester.md` |
| 도구 | `Read`, `Write`, `Edit`, `Bash` |
| 도메인 | `minigame_runner`, `rps_node`, 3 games (`06_rps_evolution`, `07_speed_counter`, `01_cafe_ninja`) |
| 외부 의존 | 카메라 3 (USB 외장 RPC-20F) — 손 인식 |
| 정책 | §0-A/§0-B 무관, 단 face_avatar suspend/resume 시퀀스 통합 검증 시 dialog-tester 와 협업 |
| 대표 테스트 | `minigame_runner_countdown`, `rps_70pct_win_rate`, `face_avatar_suspend_resume` |

### 5.7 mode-e2e-tester

| 속성 | 값 |
|---|---|
| 파일 | `.claude/agents/mode-e2e-tester.md` |
| 도구 | `Read`, `Bash` |
| 도메인 | `mode_npc.launch.py`, `mode_serving.launch.py`, `mode_follow.launch.py`, `teleop_ui` 전체 |
| 책임 | smoke (launch 5초 spawn + 노드 alive + 클린업), behavioral (1 호객 cycle, 1 서빙 cycle) |
| 정책 | §11 navigation 코드 분리 원칙 준수 (teleop_ui 가 점유한 자원 재기동 금지) |
| 대표 테스트 | `mode_npc_smoke`, `mode_serving_t01_dry`, `mode_follow_p_control` |

### 5.8 infra_readonly (safety-tester 내부)

별도 에이전트 X. safety-tester 가 카테고리 = `infra_readonly` 인 read-only 진단 테스트 (RPi ssh ping, vic_pinky git status, dpkg list) 도 함께 처리. §0-A 활성 시 skip.

---

## 6. 워크플로우

### 6.1 저장 워크플로우

```
1. 사용자가 수동 테스트 수행
   $ ros2 run dobi_npc_emotion geva_node
   $ ros2 topic echo --once /emotion/state
   (확인 후 종료)

2. 사용자: "test-supervisor 에이전트로 방금 한 GEVA 웹캠 테스트 저장해줘"

3. supervisor 가 사용자에게 짧게 확인:
   - 어떤 명령을 돌렸는지
   - 기대 결과는 무엇이었는지
   - depth = smoke 인지 behavioral 인지
   - (이미 git diff / 셸 history 로 추정)

4. supervisor 가 카테고리 = perception 으로 분류 → perception-tester 호출

5. perception-tester:
   - tests/regression/perception/geva_webcam_smoke.md 작성 (스키마 준수)
   - tests/regression/catalog.yaml 에 새 entry 추가
   - 작성된 절차로 실행해보고 통과 확인 (sanity check, **통과 강제 X — 실패해도 .md 보존 + last_status="fail" 기록**, 사용자가 디버그 가능하게)
   - 결과 supervisor 에게 반환

6. supervisor 가 사용자에게:
   - 작성된 파일 경로 + 절차서 미리보기
   - sanity check 결과
   - "이대로 commit 할까요?" 확인

7. 사용자 OK → git add + commit
```

### 6.2 실행 (회귀) 워크플로우

```
1. 사용자: "test-supervisor, perception 회귀 돌려"
   (또는 "all smoke", "tag:nav2", "id:geva_webcam_smoke")

2. supervisor:
   - catalog.yaml 필터 (category=perception)
   - §0-A 활성 여부 확인 → 활성이면 policy.blocks 에 rpi_ssh/vic_pinky_write 있는 테스트 skip
   - precondition gate (디바이스/패키지 가용성) 사전 점검

3. supervisor → perception-tester Agent 도구로 호출
   파라미터: 실행할 test id 리스트, depth filter

4. perception-tester:
   - 각 .md 순차 실행
   - 단계별 expect 비교
   - pass / fail / skip + 첫 실패 step + 셸 출력 발췌 반환

5. supervisor 종합 리포트:

   회귀 결과 (perception 카테고리, 2026-05-19 21:34)
   ────────────────────────────────────────────────
    PASS  geva_webcam_smoke           (12s)
    PASS  rapport_event_threshold     (28s)
    FAIL  person_tracking_msg_shape   (8s)
          └─ Step 2 실패: 토픽 /tracked_persons 미발행 (timeout 5s)
    SKIP  rpi_usb_cam_geva_fusion     (§0-A 활성 — RPi 차단)
   ────────────────────────────────────────────────
   2 pass / 1 fail / 1 skip   총 48s
```

### 6.3 supervisor 의 §0-A 판정

- 명시 신호: 사용자가 "RPi 사용 중", "팀이 RPi 쓰고있어" 발화 → §0-A 활성
- 명시 해제: 사용자가 "RPi 사용 OK" 발화 → §0-A 해제
- 묵시 추정 금지 (§0-A 규칙). 불확실 시 사용자에게 1 회 짧게 확인.

---

## 7. 첫 번째 테스트 예시 — `geva_webcam_smoke`

§4.2 스키마 그대로 사용. perception 카테고리의 가장 단순한 smoke 로, supervisor + perception-tester 통합 동작 검증의 first contact 로 기능.

---

## 8. 디렉토리 레이아웃

```
~/physical-ai-repo-3/src/controller/doby_controller/
├── .claude/
│   └── agents/
│       ├── test-supervisor.md
│       ├── perception-tester.md
│       ├── dialog-tester.md
│       ├── navigation-tester.md
│       ├── safety-tester.md
│       ├── minigame-tester.md
│       └── mode-e2e-tester.md
├── tests/
│   └── regression/
│       ├── catalog.yaml
│       ├── perception/
│       │   └── geva_webcam_smoke.md
│       ├── dialog/
│       ├── navigation/
│       ├── safety/
│       ├── minigame/
│       └── mode_e2e/
└── docs/superpowers/
    ├── specs/2026-05-19-test-supervisor-agents-design.md   ← 본 문서
    └── plans/2026-05-19-test-supervisor-agents-plan.md     ← 후속 구현 계획서
```

---

## 9. Out of Scope (본 설계에서 제외)

- **CI 통합** — GitHub Actions / pre-commit 자동 회귀는 v2 로 보류 (v1 은 사용자 명시 호출만)
- **결과 영구 저장소** — `last_passed`, 실패 통계 DB 화는 v2 (v1 은 catalog.yaml inline + 사용자 reporting)
- **테스트 병렬화** — sub-tester 다중 spawn 은 v2 (v1 은 순차)
- **flaky 테스트 재시도 정책** — v2
- **테스트 코드 (Python pytest 등)** — 본 시스템은 `.md` 절차서 + `Bash` 실행. 코드성 단위 테스트는 별 트랙

---

## 10. Open Questions (사용자 검토 시 결정)

1. **supervisor 가 분류 시 사용자에게 묻는 빈도** — 매번 vs 자신 있으면 silent. (제안: 신규 카테고리/모호 시만 묻기)
2. **`policy.blocks` 키워드 집합** — `rpi_ssh`, `vic_pinky_write`, `live_robot`, `internet_required` 정도면 충분? 추가 필요한가?
3. **테스트 id 네이밍 컨벤션** — `<subject>_<aspect>_<depth>` 패턴? (e.g., `geva_webcam_smoke`, `nav2_t01_dock_dry`)
4. **카탈로그 정렬** — id 알파벳 vs 추가일자? (제안: 카테고리 내 알파벳)

---

## 11. 승인 모델 + 롤아웃 (2단계)

### 11.1 v1 — Stephen 단독 검증 단계 (현재)

- **총 감독자 + 최고 승인자**: 공국진 (Stephen, gjkong / skong097)
- **승인 필수 게이트**:
  - (G1) 신규 테스트 카탈로그 commit — sub-tester 가 작성 후 Stephen 명시 OK 받기 전 git commit X
  - (G2) 회귀 일괄 실행 (category 단위, all smoke, all 등) — 1 차례 Stephen 의 명시 시작 명령 필요
  - (G3) §0-A/§0-B 경계 테스트 실행 — supervisor 가 정책 위반 가능성 1% 라도 있으면 Stephen 확인
  - (G4) `catalog.yaml` 의 `categories` / `policy_blocks_vocabulary` 같은 메타 스키마 수정 — Stephen 직접 또는 명시 위임
- **권한 위임 형식**: Stephen 이 단일 명령으로 "geva_webcam_smoke 만 돌려" 처럼 단일 테스트 실행 명시 — 그 범위 안에서는 supervisor 가 G2 재확인 없이 진행 가능
- **에이전트 프롬프트 명시 사항**: 모든 sub-tester 본문에 "Stephen (사용자) 의 명시 승인 없이 다음 행위 금지" 인라인 표기 — commit, batch run, policy boundary, schema mutation

### 11.2 v2 — 팀 전체 확산 단계 (후속)

- **트리거**: Stephen 의 검증 OK → "팀 확산 OK" 발화 시
- **확산 대상 (CLAUDE.md SoT)**: 송민규, 류재상, 김진우, 김덕현, 안순혁
- **확산 방식**:
  - `.claude/agents/` 는 git committed → `git pull` 만으로 팀원 onboarding
  - `tests/regression/README.md` 가 신규 팀원 진입 문서
  - 팀원이 자기 도메인 sub-tester 의 정책/명령 가이드라인을 수정할 수 있도록 PR 컨벤션 정립 (v2 작업)
- **권한 모델 (v2)**: 도메인별 owner 지정 — 각자 자기 도메인 sub-tester + 카탈로그 일부 영역 수정 PR 가능. 카테고리 추가/제거 + 정책 스키마 수정은 여전히 Stephen 승인 유지.
- **CI 통합 검토 (v2)**: pre-commit 또는 GitHub Actions 로 smoke 회귀 자동화 — Stephen + 팀 협의

---

## 12. 다음 단계

- [ ] 본 설계 사용자 (Stephen) 검토 + 승인
- [ ] `superpowers:writing-plans` 스킬 호출 → `docs/superpowers/plans/2026-05-19-test-supervisor-agents-plan.md` 작성
- [ ] 구현 계획 따라 `.claude/agents/` 7개 + `tests/regression/` 초기 구조 + `geva_webcam_smoke` 첫 테스트 까지 v1 완성
- [ ] **v1 Stephen 단독 검증 기간** (기간 미정, 자체 사용 만족 시점까지)
- [ ] v1 검증 완료 후 — v2 팀 확산 RFC 작성 (sub-tester PR 컨벤션, 도메인 owner 지정, CI 통합 여부)

---

*본 문서는 `superpowers:brainstorming` 스킬 흐름을 따라 작성. 검토 후 변경 사항 있으면 인라인 갱신 + spec self-review 재실행 → writing-plans 진입.*
*v1 = Stephen 단독, v2 = 팀 확산. v1 단계에서는 Stephen 이 모든 commit / batch run / policy boundary 의 최종 승인자.*
