# 2026-05-20 — operator.html → M3 dashboard 마이그레이션 (engaging-analytics)

> 작성: 2026-05-20 21:40 (doby) | 작업 중단 — 다음 세션 이어서
> branch: `feat/engaging-analytics-migration` (base = feat/bt-engagement)
> 이어 시작 위치: 본 문서 §6 "작업 단계" Task 2 부터

---

## 1. 한 줄 정의

기존 `localhost:8765/operator` (legacy `web/static/operator.html`) 의 모객 모드 한정
분석 콘텐츠 (V/A circumplex + funnel 진행 + rapport 타임라인 + 미니게임 결과 + 강제 발화 + 로그)
를 `localhost:8800` (M3 dashboard, `src/moca_opserver/`) 로 마이그레이션. 마이그 후
operator.html 삭제 예정.

## 2. 사용자 확정 결정

| # | 결정 | 채택 |
|---|---|---|
| D1 | 콘텐츠 위치 | **옵션 E** — modes.html 의 engaging 컨텍스트 expand 섹션 (engaging 모드 활성 시 자동 show) |
| D2 | 글로벌 nav 변경 | **0** (기존 7 페이지 유지: 대시보드/모드 제어/테이블/이벤트/통계/설정/디버그) |
| D3 | operator.html 운명 | **삭제 예정** — 본 trake 후속 |
| D4 | 백엔드 endpoint | moca_opserver 신규 — REST `/api/v1/...` + WS `/ws/v1/engaging` |
| D5 | base 브랜치 | feat/bt-engagement (모객 BT 변경 + 분석 패널 같은 PR 흐름) |

## 3. 자산 인벤토리 (operator.html 619 lines, 7 섹션)

| # | operator 섹션 | line | 백엔드 | M3 분배 |
|---|---|---|---|---|
| 1 | 현재 상태 (모드 뱃지) | 198 | GET /api/mode/state | **기존 헤더 mode-badge 활용** — 신규 X |
| 2 | V/A circumplex SVG | 223-270 | WS /ws/telemetry | modes.html engaging 컨텍스트 |
| 3 | 라포 이벤트 list | 274 | WS /ws/telemetry | 같음 |
| 4 | 미니게임 결과 | 299 | WS /ws/telemetry | 같음 |
| 5 | 모드 전환 버튼 | 306 | POST /api/mode/request | **기존 modes.html mode-buttons 활용** — 신규 X |
| 6 | 강제 발화 form | 322 | POST /api/dialog/utter | modes.html engaging 컨텍스트 |
| 7 | 로그 console | 351 | local | debug.html 통합 |

## 4. 백엔드 신규 endpoint (moca_opserver)

| 위치 | 신규 | 출처 | 비고 |
|---|---|---|---|
| `opserver_node.py` | ROS sub: `/emotion/state` (EmotionState) | teleop_server.py:1066-1067 패턴 | state cache |
| `opserver_node.py` | ROS sub: `/rapport/event` (RapportEvent) | teleop_server.py:1068-1069 | 최근 N 이벤트 deque |
| `opserver_node.py` | ROS sub: `/minigame/result` (MinigameResult) | (신규 — operator.html 표시용) | 최신 결과 1 개 |
| `ws_hub.py` | WS `/ws/v1/engaging` (5Hz throttle) | operator.html `/ws/telemetry` 패턴 | emotion + rapport + minigame state 통합 broadcast |
| `rest_api.py` | POST `/api/v1/dialog/utter` | teleop_server.py:1623 | body {text: str, persona?: str} → /dialog/router_in 발행 |

## 5. 프론트엔드 신규 자산

| 파일 | 내용 |
|---|---|
| `static/js/engaging-analytics.js` | V/A circumplex 렌더링 (SVG 동적) + rapport 타임라인 list + minigame card. WS 구독 |
| `static/css/components.css` 확장 | `.circumplex`, `.abort-zone`, `.traj-pt`, `.cur-pt`, `.rapport-list` 등 |
| `static/pages/modes.html` 확장 | 하단 `<section id="engaging-analytics" hidden>` — V/A SVG + rapport + minigame + 강제 발화 form |
| `static/pages/debug.html` 확장 | console log 영역 추가 (또는 신규 `<console-log>` 컴포넌트) |

## 6. 작업 단계 (10 task — 다음 세션 이어 시작 Task 2 부터)

- [x] **Task 1**: `feat/engaging-analytics-migration` 브랜치 cut from `feat/bt-engagement` ✓
- [ ] **Task 2**: `opserver_node.py` — `/emotion/state` `/rapport/event` `/minigame/result` ROS subscriber 추가 + state cache (3 멤버: `_emotion_state`, `_rapport_events_deque(maxlen=20)`, `_last_minigame_result`)
- [ ] **Task 3**: `ws_hub.py` — `/ws/v1/engaging` WebSocket 추가 + 5Hz throttle + state 통합 JSON broadcast
- [ ] **Task 4**: `rest_api.py` — `POST /api/v1/dialog/utter` (text + persona → /dialog/router_in publish)
- [ ] **Task 5**: `static/js/engaging-analytics.js` 컴포넌트 작성 (operator.html line 471-598 의 V/A SVG + rapport renderer + minigame card JS 포팅)
- [ ] **Task 6**: `static/css/components.css` 에 `.circumplex` `.abort-zone` `.traj-pt` `.cur-pt` `.rapport-list` 추가 (operator.html line 104-194)
- [ ] **Task 7**: `static/pages/modes.html` 하단에 `<section id="engaging-analytics" hidden>` 추가 — V/A SVG + rapport list + minigame card + 강제 발화 form. JS: `/mode/state` 가 engaging 일 때만 show + WS 연결
- [ ] **Task 8**: `static/pages/debug.html` 에 console log 영역 추가 (operator.html line 351 의 로그 패턴)
- [ ] **Task 9**: 통합 빌드 + 라이브 검증 — localhost:8800/modes 진입 → engaging 모드 트리거 → 분석 패널 표시 + 데이터 정상
- [ ] **Task 10**: 회고 .md + integration commit + 사용자 push 위임. operator.html 삭제는 별 commit (다음 trake)

## 7. 검증 절차 (Task 9)

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select moca_opserver
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging &
ros2 launch moca_opserver opserver.launch.py &
'
# 브라우저 localhost:8800/static/pages/modes.html
# - engaging 모드 활성 시 분석 패널 자동 show
# - V/A circumplex 의 현재 점이 라이브 emotion 따라 움직임
# - rapport 타임라인이 /rapport/event 따라 추가
# - 미니게임 결과 카드가 /minigame/result 수신 시 갱신
# - 강제 발화 form 의 text 입력 + send → TTS 발화
# - localhost:8800/static/pages/debug.html 의 console log 가 라이브 log 표시
```

## 8. §0-B / §0-A 영향

본 trake 의 변경 대상 = `src/moca_opserver/` + `static/` 트리. `src/shared/vic_pinky/` +
`scripts/run_*.sh` + RPi `~/vicpinky_ws/` 모두 **touch 0**. WebSocket + REST 추가만,
ROS topic publish 도 `/dialog/router_in` 외 신규 X.

## 9. 다음 세션 이어 시작 가이드

```bash
cd ~/physical-ai-repo-3
git checkout feat/engaging-analytics-migration
git log --oneline -3  # 본 design.md commit 확인
# 본 문서 §6 Task 2 부터 진행
```

본 문서가 spec + plan 통합 SoT. Task 별 코드 작성 가이드는 operator.html 의 원본 line 참조 (§3 / §5).

## 10. 시간 기록

- 21:39 작업 중단 (10분 잔여)
- 21:40 본 design.md 작성
- 21:45 commit + 사용자 push 위임 예정
- 다음 세션: Task 2 부터 (백엔드 ROS subscriber 시작)
