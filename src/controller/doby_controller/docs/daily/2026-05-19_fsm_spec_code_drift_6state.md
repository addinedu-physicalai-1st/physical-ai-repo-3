# 2026-05-19 — Mode FSM spec-code drift 정정 (5-state v1.0 → 6-state v1.1)

## 1. 배경

2026-05-19 teammember 머지 (`docs/daily/2026-05-19_teammember_merge.md`) 시 사용자 결정 — *"mode_follow + mode_guiding 분리 운용 (둘 다 살림) — VALID_MODES 6-state"* — 으로 `follow` 가 정식 6번째 상태로 승격됐으나, **spec 문서 `docs/moca_5state_fsm_spec.md` 는 v1.0 (5-state) 그대로 미갱신**.

drift 발견 경위: 사용자 질문 *"우리 5개 상태 모드는 모드 ROS통신 맞지?"* 답변 준비 중 `VALID_MODES` 점검에서 noticed.

drift 항목 (정정 전):
| 위치 | spec (v1.0) | 코드 (현재) | 정합? |
|---|---|---|---|
| `mode_manager_node.py:67` `VALID_MODES` | — | 6-state | (코드가 SoT) |
| `moca_5state_fsm_spec.md` §1.1 `VALID_MODES` | 5-state | — | ✗ drift |
| `moca_5state_fsm_spec.md` §6.3 `LEGACY_MODE_ALIAS` | `{'npc': 'engaging', 'follow': 'guiding'}` | `{'npc': 'engaging'}` | ✗ drift |
| `dobi_npc_msgs/msg/ModeState.msg` 코멘트 | "5-state FSM" | — | ✗ drift |
| `dobi_npc_msgs/srv/SetMode.srv` 코멘트 | "5상태 FSM" | — | ✗ drift |
| `mode_manager_node.py` 헤더 docstring | — | 6-state | ✓ (머지 시점 갱신됨) |

## 2. 정정 방향 결정 — 사용자 결정 정합 (5 → 6 spec 확장)

후보:
- **A. spec 을 6-state 로 확장** ← 사용자 결정 (teammember 머지 §2) 정합. 채택.
- B. 코드를 5-state 로 revert ← 머지 결정 거스름. 기각.

부수 컨텍스트 (사용자 명시 2026-05-19 본 세션 중):
> *"ui 에서 서빙로봇의 상태 모드는 이번 병합하면서 6개 상태로 확장이 된 것이 맞아. follow 추종 모드가 추가 되었지. 하지만 UI에서는 아직 5개 상태 모드에 대해서만 구현이 되어서 추가 수정 개발을 앞두고 있어."*

→ spec 은 6-state SoT 로 갱신하되, **UI (운영자 UI / 웹 대시보드) 는 5-state 구현이 그대로**라는 caveat 을 spec 에 명시. 향후 UI 추격 트랙이 별도 존재함을 후속 개발자에게 전달.

## 3. 변경 파일 (file-by-file)

### 3-1. 수정 — `docs/moca_5state_fsm_spec.md` (v1.0 → v1.1)

main spec. 717 → 757 라인.

| 위치 | 변경 종류 | 비고 |
|---|---|---|
| 헤더 (line 1-9) | 타이틀 "MOCA Mode FSM 사양서" 로 변경, 파일명 보존 사유 명시, 버전 v1.0 → v1.1, 워크스페이스 경로 신규 경로 + 역사 주석 | 파일명 (`moca_5state_fsm_spec.md`) 유지 — 27+ 파일에서 cross-reference |
| §0.2 신설 | v1.1 변경 사항 changelog: 배경 + 5→6 확장 사유 + spec-code 정합 상태 표 + ⚠ UI 5-state 잔존 caveat + legacy alias 정리 | 후속 개발자 진입 시 v1.0 → v1.1 컨텍스트 즉시 파악 |
| §1.1 상태 집합 S | 5-tuple → 6-tuple, `VALID_MODES` 갱신, `^^^^^^ v1.1 추가` 마커 | — |
| §2.6 신설 | S_follow 정식 명세 (속성 10종 + 의도 시나리오 + guiding 과의 차이 재확인) | follow 의 priority=4 (mode_manager docstring 의 기존 명시값 채택) |
| §2.5 S_engaging | 선점 정책 행에 `follow` 추가 (engaging 은 follow 에게 선점됨) | — |
| §3.1 전이 매트릭스 | 5×5 → 6×6 확장 (follow 행/열 신규 추가) + 우선순위 정렬 한 줄 추가 | T-IF, T-FI, T-FS, T-FG, T-FP, T-EF 신규 셀 |
| §3.2 전이 상세 | T-IF (idle→follow), T-EF (engaging→follow 선점), T-FP/T-FG (follow→patrol/guiding 선점) 신규 명세 + 기존 T-SI...T-EI 헤더에 T-FI 합류 + T-PS...T-ES 헤더에 T-FS 합류 | — |
| §3.3 거부 표 | T-busy 케이스 4 행 추가: serving/guiding/patrol→follow (priority 낮음), follow→engaging | — |
| §6.3 후방 호환 | `LEGACY_MODE_ALIAS` 에서 `'follow': 'guiding'` 제거 + v1.0 → v1.1 마이그레이션 주의 | — |
| §7.1 상태 다이어그램 | ASCII 다이어그램 6번째 상태 박스 (S_follow prio 4) 추가 + T-IF/T-FS/T-FG/T-FP/T-FI/T-EF 전이 화살표 + e_complete 미정의 주석 | Mermaid 호환 표기 보존 |
| §8.1 mode_manager 변경 | 6 항목 모두 [x] 완료 표기 (이미 머지로 적용됨) + 1 잔여 (M1 stretch) | — |
| §8.2 신규 launch | mode_follow.launch.py 상태를 "deprecation wrapper" → "정식 stack" 으로 정정 + v1.2 후보 추가 | — |
| §8.3 단위 테스트 | `test_mode_manager_5state.py` → `test_mode_manager_6state.py` 리네이밍 권장 + follow 시나리오 추가 | — |
| §8.4 통합 테스트 | "5종" → "6종" spawn/kill cycle + UI 6-state 통합 검증 v1.2 후보 추가 | — |

### 3-2. 수정 — `src/dobi_npc/dobi_npc_msgs/msg/ModeState.msg`

`current_mode` 필드 enum + 헤더 코멘트 6-state 정합:
- 5-state FSM → 6-state FSM (2026-05-19 v1.1)
- 상태 enum 6 entries 모두 priority 값 동봉
- legacy alias `'follow' -> 'guiding'` 제거 (npc → engaging 만 잔존)
- ⚠ UI 5-state 잔존 caveat 추가 (subscribers 가 follow 모드 표시 부재를 의도된 상태로 인식하도록)
- `current_mode` 필드 인라인 코멘트에 `"follow"` 추가

### 3-3. 수정 — `src/dobi_npc/dobi_npc_msgs/srv/SetMode.srv`

`requested_mode` 필드 enum + 헤더 코멘트 6-state 정합:
- "5상태 FSM" → "6상태 FSM (2026-05-19 v1.1 확장)"
- `params` 페이로드 표에 follow 케이스 추가 (`{"target":"<id>"}`, 현 구현 미사용 주석)
- legacy alias `"follow" -> guiding` 제거
- ⚠ UI 5-state 잔존 + follow 진입은 ros2 service CLI / OpServer 자동 트리거로만 가능 caveat 추가

### 3-4. 미변경 (의도적 보존)

- **`mode_manager_node.py` 헤더 docstring** (line 1-50) — 2026-05-19 머지 시점에 이미 6-state 로 갱신됨. drift 없음.
- **`CLAUDE.md` footer line 757** — `(... mode_manager 6-state)` 이미 명시. drift 없음.
- **`docs/moca_mode_and_opserver_plan.md`** (5-state 언급 다수) — 옛 마이그레이션 plan 의 역사 기록. retroactive rewrite 시 planning history 왜곡 — 보존.
- **`docs/moca_5state_fsm_spec.md` 파일명 자체** — 27+ 파일에서 cross-reference 됨. rename 시 scatter change. 파일명 보존 + 헤더에 사유 한 줄 명시.

## 4. UI 통합 — work-in-progress 가 별도 트랙 (참고)

본 작업 범위 외이지만 후속 개발자 컨텍스트로 명시:

- **현재 UI 상태**: `web/static/*.html` + `teleop_server.py` 의 모드 표시 / 모드 전환 버튼은 5-state 구현 그대로
- **follow 모드 임시 진입 경로**: `ros2 service call /mode/request dobi_npc_msgs/srv/SetMode "{requested_mode: 'follow', params: ''}"` 또는 OpServer 자동 트리거 (`moca_opserver/opserver_node.py` 의 mode_orchestrator)
- **UI 갱신 시 변경 범위 추정** (별도 트랙):
  - `web/static/operator.html` 의 mode chip / button 그룹에 `follow` 항목 추가
  - `web/static/dashboard.html` 의 mode 표시/KPI 카드 갱신
  - `teleop_server.py` 의 mode 전환 endpoint route 에 follow 처리 분기
  - `docs/moca_web_dashboard_spec.md` 6-state 동기화
- **SoT**: 본 회고 §4 + spec `moca_5state_fsm_spec.md` §0.2 ⚠ UI caveat + §2.6 ⚠ UI 통합 상태 행

## 5. 정책 정합

본 작업은 CLAUDE.md §0-A / §0-B / §11 어느 정책에도 저촉되지 않음:
- vic_pinky 트리 자체는 미수정.
- RPi 접근 없음.
- cmd_vel 토픽 / Nav2 stack 무관.
- 코드 (msg/srv) 변경은 코멘트만 — 메시지 IDL 자체는 미변경 (필드 추가/삭제 X) → ABI 안정, 재빌드 정상.

⚠ 단 `dobi_npc_msgs` 패키지 빌드는 필요할 수 있음 (.msg / .srv 코멘트 변경이 generated header 영향 0 이지만 install/share/ 의 .msg 원본 파일은 갱신됨). 다음 `colcon build --packages-select dobi_npc_msgs` 또는 전체 빌드 시 자동 반영.

## 6. 검증 결과

| 항목 | 검증 | 결과 |
|---|---|---|
| spec `VALID_MODES` ↔ code `VALID_MODES` | `grep` 양쪽 비교 | ✅ 정확 일치 |
| 잔존 "5-state" 표기 | spec 내 grep | 모두 의도적 메타-주석 (역사 컨텍스트 + UI caveat + 파일명 보존 사유 + v1.0 cross-ref) |
| msg/srv 코멘트 | head -15 / head -12 | 6-state 정합 ✅ |
| LEGACY_MODE_ALIAS | spec §6.3 ↔ code:71 | 둘 다 `{'npc': 'engaging'}` ✅ |

## 7. 후속 권장

- **본 세션 후 즉시** (선택): `colcon build --packages-select dobi_npc_msgs` 로 install/share/ 의 .msg / .srv 원본 갱신 반영. 동작에는 영향 0 — install 의 코멘트가 최신화될 뿐.
- **UI 추격 트랙 (별도 세션)**: §4 의 변경 범위 추정대로 web/static/* + teleop_server.py + moca_web_dashboard_spec.md 6-state 통합. spec §8.4 v1.2 후보 (UI 6-state 통합 e2e 시나리오) 으로 등록.
- **다른 design docs grep** (선택): `moca_serving_design.md` / `moca_idle_design.md` / `moca_patrol_design.md` / `moca_guiding_design.md` / `moca_engagement_design.md` / `moca_opserver_api_spec.md` / `moca_web_dashboard_spec.md` 에 5-state 직접 단언 발견 시 정정. 본 세션 grep 결과 — VALID_MODES 언급은 있으나 명시적 "5-state" 단언은 거의 없음. 안전.
- **테스트 코드 갱신** (별도 세션): `test_mode_manager_5state.py` → `test_mode_manager_6state.py` 리네이밍 + follow 시나리오 추가 (spec §8.3).

## 8. 메모리 / 인덱스 갱신

- 본 작업은 메모리 영구화 필요 없음 — 모두 spec/code 자체로 SoT 보존. (전형적 patch-and-record 작업)
- `[[project_moca_workspace_path]]` 와 무관.
- `[[feedback_no_vic_pinky_modification]]` — 본 작업 정책 저촉 없음 검증됨 (§5).

---

**작업자**: gjkong (Claude Opus 4.7 보조)
**소요 시간**: ~25 분 (spec doc §0/§1/§2/§3/§6/§7/§8 7섹션 갱신 + msg/srv 2 파일 + 회고)
**git 상태 (본 회고 작성 직후)**:
```
M CLAUDE.md
M docs/cafe_npc_rpi_live_amcl_checklist.md
M docs/cafe_npc_system_architecture.md
M docs/daily/2026-05-19_follow_test_usb_cam_blocked.md
M docs/moca_5state_fsm_spec.md
M src/dobi_npc/dobi_npc_msgs/msg/ModeState.msg
M src/dobi_npc/dobi_npc_msgs/srv/SetMode.srv
?? scripts/moca_env.sh
?? docs/daily/2026-05-19_workspace_path_relocation.md
?? docs/daily/2026-05-19_fsm_spec_code_drift_6state.md
```
**다음 작업 (예상)**:
1. UI 추격 트랙 — operator.html / dashboard.html / teleop_server.py / moca_web_dashboard_spec.md 6-state 통합 (별도 세션)
2. test_mode_manager 6-state 리네이밍 + follow 시나리오 (별도 세션)
3. 또는 다른 트랙 진행
