# 2026-05-19 — moca 워크스페이스 경로 이전 + CLAUDE.md 정합 작업

## 1. 배경

- 2026-05-19 본 세션 시작 시 사용자 명시: **moca 개발 루트가 `~/moca` → `~/physical-ai-repo-3/src/controller/doby_controller` 로 이동.**
- 직전 머지 (`6a44bd3 feat: add doby_controller from moca workspace`, `2aade7b Merge branch 'feat/doby-controller' into dev`) 로 신규 모노레포 `physical-ai-repo-3` 의 `src/controller/doby_controller/` 하위로 통합된 상태.
- CLAUDE.md 본문은 여전히 `~/moca/` 표기를 다수 보유 → 신규 경로와 의미상 동일하지만 표기 불일치.

## 2. 작업 결정 사항

### 2-1. `.bashrc` 수정 보류 — 별도 source 스크립트로 (사용자 선택)

CLAUDE.md §3 은 `moca_build` / `moca_activate` / `moca_clean` alias 를 ".bashrc 에 등록된" 것으로 명시했으나, `grep` 결과 `~/.bashrc` 에 0 건. Claude Code auto-mode classifier 가 `.bashrc` 직접 편집을 차단 → 사용자께 4 옵션 제시 → "**alias 대신 별도 스크립트로**" 선택.

### 2-2. 광의 일괄 치환 (사용자 명시)

후속으로 "일괄 치환해줘" 명시 → CLAUDE.md 전반의 `~/moca/` 표기를 신규 경로로 정정.

## 3. 변경 파일 (file-by-file, 세션 누적)

본 세션 누적 산출물: **저장소 내 4 수정 + 2 신규**, **저장소 외 메모리 2 신규**.

### 3-1. 신규 — `scripts/moca_env.sh`

source 시 현재 셸에 함수 + 환경변수 주입:

| 항목 | 정의 |
|---|---|
| `MOCA_WS_ROOT` | `SCRIPT_DIR/..` 자동 추정 (CLAUDE.md §7 상대경로 컨벤션 정합) |
| `moca_cd` | `cd $MOCA_WS_ROOT` |
| `moca_build` | `bash --noprofile --norc -c "..."` 격리 셸 콜콘 빌드 (§7 robot_arm 자동 source 영향 회피) |
| `moca_activate` | `source $MOCA_WS_ROOT/install/setup.bash` |
| `moca_clean` | `rm -rf build install log` |

사용법:
```bash
source ~/physical-ai-repo-3/src/controller/doby_controller/scripts/moca_env.sh
```

smoke-test 통과 — 4 함수 등록 + `MOCA_WS_ROOT` 자동 추정 OK.

### 3-2. 수정 — `CLAUDE.md`

| 위치 | 변경 종류 | 비고 |
|---|---|---|
| §3 빌드 명령어 (line 198-211 영역) | alias → source 스크립트 방식 명시 + 직접 호출 cd 경로 갱신 | `MOCA_WS_ROOT` 자동 추정 + §7 정합 한 줄 추가 |
| §0 cabot 금지 규칙 (line 95-97) | SoT 경로 표기 갱신 + 절대경로 하드코딩보다 §7 helper 권장 명시 | 역사적 사고 (2026-05-09 `WS="$HOME/cabot"`) 서술은 보존 |
| §3 워크스페이스 트리 top (line 164) | `~/moca/` → 신규 경로 + 역사적 주석 (`2026-05-19 이전 ~/moca/`) | 트리 alignment 무리하게 보존하지 않음 |
| §4.4 vic_pinky 로컬 변경사항 (line 311) | 경로 prefix 갱신 | — |
| §7 일일 .md 루틴 (line 436) | 경로 prefix 갱신 | — |
| §7 RPi scp 경로 규칙 (line 478) | 경로 prefix 갱신 | — |
| §7 상대경로 컨벤션 금지 패턴 (line 504-505) | 예시 경로 표기 갱신, deprecated 경로 (`$HOME/moca`, `$HOME/cabot`) 도 함께 금지로 명시 | 금지 의미 보존 |
| §8 외부 자산 표 (line 567) | vicpinky_emotion 자산 경로 갱신 | — |

검증: `grep -cE "~/moca|\$HOME/moca|/home/gjkong/moca"` → **2 건만 잔존** (line 164 역사적 주석, line 504 금지 패턴 예시 — 둘 다 의도적).

### 3-3. 수정 — `docs/cafe_npc_rpi_live_amcl_checklist.md`

운영 SoT (다음 RPi 라이브 세션 진입 지침) — 옛 경로 표기 7 매치 전수 정정:

| 라인 | 컨텍스트 | 갱신 |
|---|---|---|
| 64 | `# launch 시 map:=/home/gjkong/moca/maps/...` (주석 예시) | 신규 절대경로 |
| 92 | `PC git sha: $(cd ~/moca && git rev-parse HEAD)` | 신규 경로 |
| 106 | `bash ~/moca/scripts/stop_sim.sh` | 신규 경로 |
| 168 | `cd ~/moca` (Nav2 stack 시동 디렉토리 이동) | 신규 경로 |
| 171 | `map:=/home/gjkong/moca/maps/mapv5_mocamap_live.yaml` (실 launch arg) | 신규 절대경로 |
| 279 | `bash ~/moca/scripts/stop_moca.sh` (PC 정지) | 신규 경로 |
| 313 | 영상 파일 위치 `~/moca/recordings/...` | 신규 경로 |

검증: 옛 경로 잔재 0 건.

### 3-4. 수정 — `docs/cafe_npc_system_architecture.md`

시스템 아키텍처 SoT — 옛 경로 표기 5 매치 + `.bashrc alias` 잘못된 클레임 1 블록 정정:

| 라인 | 컨텍스트 | 갱신 |
|---|---|---|
| 164 | 패키지 구성 트리 top `~/moca/` | 신규 경로 + 역사 주석 `(2026-05-19 이전 ~/moca/)` (CLAUDE.md line 164 와 동일 패턴) |
| 216 | `cd ~/moca` (빌드 디렉토리 이동) | 신규 경로 |
| 220-223 (블록) | `# 또는 .bashrc alias` 잘못된 클레임 | `scripts/moca_env.sh` source 방식으로 정정 (CLAUDE.md §3 와 동일 패턴, `.bashrc` 미수정 명시) |
| 230 | `source ~/moca/install/setup.bash` (시동) | 신규 경로 |
| 238 | `bash ~/moca/scripts/run_teleop_ui.sh` | 신규 경로 |
| 240 | `bash ~/moca/scripts/stop_teleop_ui.sh` | 신규 경로 |

검증: 옛 경로 잔재 1 건 (line 164 의 의도적 역사 주석만).

### 3-5. 수정 — `docs/daily/2026-05-19_follow_test_usb_cam_blocked.md`

같은 날 작성된 (먼저) 회고 — 역사 incident 의 원본 경로 보존 + 현재 경로 annotation 병기:

| 라인 | 변경 |
|---|---|
| 291 | `- **수정 대상**: \`/home/gjkong/moca/scripts/run_3stage.sh\` line 30` → 뒤에 `— *2026-05-19 워크스페이스 이전 후 현재 경로*: \`/home/gjkong/physical-ai-repo-3/src/controller/doby_controller/scripts/run_3stage.sh\`` 추가. 원본 경로 자체는 역사 기록으로 보존. |

### 3-6. 신규 — 본 회고 (`docs/daily/2026-05-19_workspace_path_relocation.md`)

본 세션 작업 일체의 SoT.

### 3-7. 메모리 (Claude 영구 메모리, 본 저장소 외부)

- `~/.claude/projects/-home-gjkong-physical-ai-repo-3/memory/project_moca_workspace_path.md` 신규
- `~/.claude/projects/-home-gjkong-physical-ai-repo-3/memory/MEMORY.md` 신규 (인덱스)

→ 향후 세션 진입 시 신규 경로가 자동 컨텍스트로 로드됨.

## 4. 정책 정합 확인

본 작업은 CLAUDE.md §0-B (vic_pinky 자산 보호) / §0-A (RPi 접근 제한) / §11 (navigation 코드 분리) 어느 정책에도 저촉되지 않음:

- vic_pinky 트리 자체는 미수정.
- RPi 접근 없음.
- `/joy/cmd_vel`, `/bt/cmd_vel` 등 cmd_vel 토픽 / mode_manager / Nav2 stack 무관.
- `~/.bashrc` 차단된 채로 유지 → shell 환경 보존.

## 5. 잔여 작업 / 후속

### 본 세션 내 미완

- (없음 — 사용자 명시 요청 범위 모두 처리. CLAUDE.md / cafe_npc_rpi_live_amcl_checklist / cafe_npc_system_architecture / follow_test annotation / 회고 §3-§5 정리까지 완료)

### 본 세션에서 발견·확인된 의도적 보존 (역사 기록 — 갱신 X)

- `docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md:1259` — 실행 완료된 plan 의 expected output (`/home/gjkong/moca/yolov8n.pt`). 작성/실행 시점 SoT 보존.
- `docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md` 전체 `~/moca` 표기 ~100+ 건 — 같은 이유로 보존.
- `docs/daily/2026-05-19_follow_test_usb_cam_blocked.md:291` 의 원본 경로 — annotation 으로 신규 경로 병기됐으나 원본 경로 자체는 역사 기록으로 보존.
- 본 회고 §3-2 / §3-3 의 grep regex 예시 안에 포함된 옛 경로 표기 — 검증 명령 자체를 기록하는 용도.
- `CLAUDE.md` line 164 의 `(2026-05-19 이전 ~/moca/)` 주석, line 504 의 금지 패턴 예시 (`$HOME/moca`, `$HOME/cabot` 을 함께 deprecated 로 명시).
- `cafe_npc_system_architecture.md` line 164 의 동일 형태 역사 주석.

### 후속 점검 권장 (별도 요청 시)

- **다른 docs 미점검 트리**: `docs/rpi_integration_checklist.md`, `docs/moca_db_schema.md`, `docs/superpowers/specs/*.md`, `docs/daily/*.md` (2026-05-19 외) 등은 본 세션에서 grep 안 함. 일괄 grep 후 정정 검토.
- **scripts/ + src/ 코드 내부 하드코딩**: `run_*.sh`, `*.py`, launch xml 에 `$HOME/moca` 또는 `os.path.expanduser('~/moca')` 잔재 가능. 본 세션 grep 결과 `scripts/`/`src/` 코드 파일에 **`/home/gjkong/moca` 절대경로는 0 건**. `~/moca` 상대경로 / `$HOME/moca` 는 별도 점검 필요. §7 상대경로 컨벤션 (SCRIPT_DIR / env / `_find_workspace_root()` helper) 위반 발견 시 즉시 교체.
- **`moca.repos` / `package.xml` description**: 신규 경로 영향 없음 (URL/ASCII description) — 점검만.
- **운영 alias 정규화 검토**: 매 셸 세션마다 `source moca_env.sh` 가 번거롭다고 판단되면 `.bashrc` 1줄 추가 (`source $HOME/.../moca_env.sh`) 또는 Claude Code 권한 설정 변경 후 자동화. 본 세션에서는 사용자 선택대로 `.bashrc` 미수정 유지.

## 6. 메모리 / 인덱스 갱신

- `[[project_moca_workspace_path]]` — 본 회고와 동기화 (workspace path SoT).
- `[[feedback_no_vic_pinky_modification]]` — 본 작업이 정책 저촉 없음 검증됨.
- `[[project_navigation_code_separation]]` — 본 작업과 무관, 갱신 필요 X.

---

**작업자**: gjkong (Claude Opus 4.7 보조)
**소요 시간**: ~35 분 (초기 CLAUDE.md + `scripts/moca_env.sh` ~15 분 + 후속 운영 SoT `cafe_npc_rpi_live_amcl_checklist` + `follow_test` annotation + `cafe_npc_system_architecture` ~15 분 + 회고 §3/§5/푸터 정리 ~5 분)
**git 상태 (본 회고 최종 정리 후)**:
```
M CLAUDE.md
M docs/cafe_npc_rpi_live_amcl_checklist.md
M docs/cafe_npc_system_architecture.md
M docs/daily/2026-05-19_follow_test_usb_cam_blocked.md
?? scripts/moca_env.sh
?? docs/daily/2026-05-19_workspace_path_relocation.md
```
**저장소 외 산출물**: `~/.claude/projects/-home-gjkong-physical-ai-repo-3/memory/{project_moca_workspace_path.md, MEMORY.md}`
**다음 작업 (예상)**:
1. 별도 요청 시 — `docs/rpi_integration_checklist.md` / `docs/moca_db_schema.md` / `docs/superpowers/specs/*.md` / 2026-05-19 외 daily 들의 옛 경로 잔재 점검
2. 별도 요청 시 — `scripts/` + `src/` 코드 내부 `~/moca`, `$HOME/moca` 하드코딩 점검 (§7 상대경로 컨벤션 위반 검출)
3. 또는 다른 트랙 (RPi 라이브 AMCL 검증, Phase 1 BT 노드 골격, 등) 진행
