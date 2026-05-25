# 2026-05-19 — sim UI → 로봇 통신 1단계 검증 + 게임 즉사 디버깅 (6 patches)

> 작성: 2026-05-19 (doby)
> 본 회고는 같은 날 5번째 — 직전: `2026-05-19_fsm_spec_code_drift_6state.md`
> 세션 시간: ~21:00 ~ 23:00 (약 2h)

---

## 1. 세션 컨텍스트

사용자 명시: **"기존 5개 기능 검증 부터 먼저야"** — Phase 1 BT 신규 작업이나 라이브 follow 테스트보다 5-state 모드 (idle/serving/patrol/guiding/engaging) 검증 우선.

진입 시점 상태:
- 워크스페이스 이전 (`~/moca` → `physical-ai-repo-3/...`) 직후 빌드 산출물 미존재
- test-supervisor v1 시스템 (이전 세션) 첫 검증 단계
- UI 코드 (operator/dashboard/modes.html) + 백엔드 (opserver_node + mode_manager) 가동 상태로 UI → 로봇 통신 chain 검증 필요

사용자 결정 4건:
1. 진행 방식 — "단계적 (sim 먼저 → live)"
2. sim 1단계 진행 방식 — "doby 가 대신 가동 + 사용자는 버튼 클릭"
3. UI → 로봇 통신 다이어그램 형식 — sequence diagram (UML IS) + 통신 프로토콜 명시 + 5 modes (follow 제외)
4. 게임 rotate 문제 해결 — "cafe_funnel_v1.xml 에서 rotate → random"

---

## 2. 작업 단계 (timeline)

### 2-1. 사전 점검 (~21:00)

| 점검 | 결과 |
|---|---|
| install/ 빌드 산출물 | ❌ 비어있음 → `moca_build` 필요 |
| 5 mode launch 파일 | ✅ 6 launch 존재 (`mode_npc/serving/patrol/guiding/engaging/follow.launch.py`). `mode_npc` 는 deprecated wrapper |
| 회귀 카탈로그 mode_e2e | ❌ 0 tests |
| mode-e2e-tester 에이전트 | ✅ 새 세션이라 자동 디스커버리 활성 |
| commit 정책 | 회귀 시스템 = commit X 유지 |

### 2-2. moca_gazebo/models 복원 (워크스페이스 이전 회귀, 첫 발견)

`moca_build` 실패 → `moca_gazebo` 의 `models/` 디렉토리 누락 → install DIRECTORY 항목으로 빌드 abort. 이전 시 누락된 자산.

- `~/moca/src/moca_gazebo/models/` 에 10 디렉토리 (banner, cafe_table, kiosk, mapv5 등), 3.9M 존재
- `/home/gjkong/physical-ai-repo-3/.gitignore` (root) + `doby_controller/.gitignore` 둘 다 본 경로 ignore 안 함 (트랙 가능) — `~/moca` 시절 다른 정책에서 막혔던 자산
- 복원: `cp -a ~/moca/src/moca_gazebo/models src/moca_gazebo/`
- 재빌드 → 12 packages OK (36.5s)

### 2-3. 5 mode smoke 절차서 작성 + 회귀 1차 (~21:15)

`tests/regression/mode_e2e/` 에 5 smoke .md 작성 + `catalog.yaml` 인덱싱.

각 절차서 — DOMAIN=99 + LOCALHOST_ONLY=1 격리, ros2 launch 직접 호출, node alive + 토픽 등록 검증.

test-supervisor 에 dispatch → mode-e2e-tester 가 5 smoke 실행:

| Mode | 결과 | 시간 | 비고 |
|---|---|---|---|
| idle | ✅ PASS | 8s | current_mode='idle', battery_ok |
| serving | ✅ PASS | 11s | /serving/state state=idle |
| patrol | ✅ PASS | 17s | detector+scheduler alive |
| guiding | ❌ FAIL | 19s | efficientdet_lite0.tflite 누락 |
| engaging | ✅ PASS | 13s | bt_executor+minigame_runner alive |

**4/5 PASS**. fail 은 `bash scripts/download_models.sh` 미실행 (워크스페이스 이전 후 모델 자산 미다운로드). 다운로드 (3 모델: efficientdet_lite0 7.2M + face_landmarker 3.7M + gesture_recognizer 8.3M) + `colcon build --packages-select dobi_npc_emotion dobi_npc_minigame` 후 재실행 → **5/5 PASS**.

### 2-4. UI 통신 플로우 다이어그램 (~21:40)

사용자 요청: "UI 에서 로봇까지 통신 절차가 어떻게 되는지 궁금해" + 후속 "IS 로 그려줘 / 실제 통신 프로토콜이 뭔지 / 5개 모드 전체 / follow 추후".

산출물: `docs/ui_to_robot_comm_flow.html` (mermaid sequence diagrams)
- 0. 통신 프로토콜 레퍼런스 (10 row 표): WebSocket / HTTP / Python in-process / ROS2 Service (RTPS/DDS) / POSIX subprocess + signals / ROS2 Action / ROS2 Topic / Modbus RTU
- 1-5. 5 modes 각자 sequence diagram (lifelines + 메시지 + 프로토콜 라벨)
- 6. 피드백 채널 (역방향 RTPS → opserver → WS broadcast → UI)
- 7. 가동 의존 (RPi bringup / Nav2 / opserver + dev_common / perception)

### 2-5. 1단계 sim — UI 버튼 클릭 검증 (대화형, ~22:00 ~ 22:30)

doby 가 mode_manager + opserver_node 백그라운드 가동 (DOMAIN=99 + LOCALHOST_ONLY=1), 사용자가 브라우저 (`http://localhost:8800/static/pages/modes.html`) 에서 버튼 클릭, doby 가 ros2 topic echo + log 로 검증.

| Mode | Click | spawn | dispatcher 노드 | 자동 idle | 통신 chain |
|---|---|---|---|---|---|
| idle (init) | — | — | (none) | — | ✅ |
| serving (T01, via_pickup) | ✅ | ✅ pgid 41163 | serving_dispatcher | 수동 idle | ✅ |
| patrol | ✅ | ✅ pgid 41371 | scheduler+detector | ✅ CompletionWatcher 1s dwell | ✅ |
| guiding (T02, C-...) | ✅ | ✅ pgid 41463 | guiding_ctrl+person_detector | ✅ CompletionWatcher 5s aborted | ✅ |
| engaging (friendly_child) | ✅ | ✅ pgid 41592 | bt_executor+minigame_runner | 수동 필요 | ✅ |

**5/5 통신 chain PASS**. UI button → WS frame → opserver_node → ModeOrchestrator → priority gating → SetMode service → mode_manager → subprocess.Popen → mode launch → dispatcher 노드 alive 까지 전체 chain 실 사용자 클릭으로 검증됨.

부산물 검증:
- IdlePatrolTimer 자동 트리거 (300s idle → patrol) — opserver_node 의 운영 자동화 feature
- CompletionWatcher dwell→idle 자동 사이클 (patrol 1s, guiding 5s) — done/aborted 신호 받으면 자동 idle 복귀
- priority gating reject — 사용자 클릭 + IdlePatrolTimer race 시 mode_manager 가 `reject [patrol] → transition_in_progress` 로 정상 거부

### 2-6. 게임 즉사 디버깅 (~22:30 ~ 23:00)

engaging 모드 진입 → BT funnel 진행 → MINIGAME stage 도달 시 게임 subprocess 가 즉사. 사용자 보고 시간순:
1. "게임 실행하다 바로 죽는데 정상인가?"
2. "카페 닌자는 플레이가 가능했음." (라이브에선)
3. "가위 바위 보 게임은 카운트가 끝난 후 바로 죽음."
4. "카운트 게임도 바로 죽음."

연쇄 root cause 6건 확정 + 6 patches 적용 (시간순):

| # | 진단 | Root cause | Patch |
|---|---|---|---|
| 1 | games/ 디렉토리 자체 부재 | 워크스페이스 이전 시 누락 (moca_gazebo/models 와 동일 패턴) | `cp -a ~/moca/games games` (24M, 4 게임) |
| 2 | game_camera_index=2 (`/dev/video2`) sim 미연결 | game.py 의 `cv2.VideoCapture(2)` 즉시 fail → setup() False → main() 즉시 return (exit 0 silent) | `mode_engaging.launch.py` 의 `game_camera_index` default 에 `EnvironmentVariable('MOCA_GAME_CAMERA_INDEX', default='2')` fallback 추가. sim 진입 시 env=0 override |
| 3 | mode_manager 가 옛 env 로 가동됨 | 재기동 필요 | `MOCA_GAME_CAMERA_INDEX=0` env 로 mode_manager 재기동 → spawn 하는 자식 ros2 launch 가 env 상속 |
| 4 | 게임 3개 등록했는데 1개 (rps) 만 등장 | `cafe_funnel_v1.xml` 의 `<Minigame game_type="rotate"/>` 의 rotate counter 가 **bt_executor 프로세스-단위 static atomic** → engaging 재진입 시 counter=0 reset → 매번 pool[0]="rps" | `rotate` → `random` (cafe_funnel_v1.xml line 63). 매 호출 무작위, process reset 영향 없음 |
| 5 | cafe_ninja 가 윈도우 모드로 뜸 | argparse 자체 부재 → minigame_runner 가 보낸 `--fullscreen` 무시 → `is_fullscreen=False` (default) | `games/01_cafe_ninja/src/game.py` main() 에 argparse 추가 (rps 패턴) + `args.fullscreen` → `_game_instance.is_fullscreen=True` + setup() 의 namedWindow 직후 `cv2.setWindowProperty FULLSCREEN` 자동 호출 |
| 6 | speed_counter 가 stretch (가로 늘어남) + 우측 시간 표시 잘림 | `cv2.namedWindow(name, WINDOW_NORMAL)` 기본 = `WINDOW_FREERATIO` → fullscreen 시 cv2 가 frame 을 윈도우 size 에 stretch | `games/07_speed_counter/src/game.py` 의 namedWindow flag 에 `WINDOW_KEEPRATIO` 추가. cv2 native aspect 유지 + letterbox 자동 (시도: 1차 단순 resize → 2차 수동 numpy letterbox → 3차 KEEPRATIO 채택) |

검증:
- 사용자 보고: "게임 2번째 정상적으로 플레이 후 완료 되었어" (#1-3 patch 후)
- "카페 닌자 전체 화면 잘 적용 되었어" (#5 patch 후)
- "3 게임 모두 전체 화면 정상 출력" (#6 patch 후)

---

## 3. 산출물 + commit 정책

### 3-1. 회귀 시스템 (v1 = commit X 유지, [[feedback_test_supervisor_v1_no_commit]])

- `tests/regression/mode_e2e/mode_idle_smoke.md` (신규)
- `tests/regression/mode_e2e/mode_serving_smoke.md` (신규)
- `tests/regression/mode_e2e/mode_patrol_smoke.md` (신규)
- `tests/regression/mode_e2e/mode_guiding_smoke.md` (신규)
- `tests/regression/mode_e2e/mode_engaging_smoke.md` (신규)
- `tests/regression/catalog.yaml` (5 entry 인덱싱 + last_status/last_run 갱신)

→ Stephen 명시 "v1 검증 OK" 또는 "회귀 시스템 커밋 재개" 까지 working tree 보존.

### 3-2. 워크스페이스 이전 회귀 복원 (gitignore 정책 결정 필요)

- `src/moca_gazebo/models/` (3.9M, 10 디렉토리 — banner/cafe_table/kiosk/mapv5/etc.)
- `games/` (24M, 4 게임 — 01_cafe_ninja/06_rps_evolution/07_speed_counter/08_zombie_dodge)

둘 다 워크스페이스 이전 시 누락된 자산. 현 `.gitignore` 는 ignore 안 함. **다른 머신 / clone 시 동일 누락 재발 방지 위해 commit 권장** — 단 사이즈 (총 27.9M) + 게임 자산 정책 (LFS vs 직접) 결정 필요.

### 3-3. 운영 코드 patch (사용자 결정 필요)

- `src/dobi_npc/dobi_npc_bringup/launch/mode_engaging.launch.py` — `EnvironmentVariable` fallback 추가 (sim 환경 보조). 라이브 default 동작 변화 X.
- `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` — `rotate` → `random` (1줄). 운영 정책 변경.
- `games/01_cafe_ninja/src/game.py` — argparse + fullscreen 적용. minigame_runner integration 완성도 향상.
- `games/07_speed_counter/src/game.py` — `WINDOW_KEEPRATIO` flag + numpy import (사용 안 함, 제거 가능).

### 3-4. 문서 (사용자 결정 필요)

- `docs/ui_to_robot_comm_flow.html` — mermaid sequence diagrams (5 modes + 통신 프로토콜 표)
- 본 회고 — `docs/daily/2026-05-19_sim_ui_5mode_verification_game_fixes.md`

---

## 4. 핵심 발견 + 함정 (후속 개발자용)

### 4-1. rotate counter 의 process-단위 reset

`bt_executor` 가 매 engaging 진입 시 새 프로세스로 spawn 되어 `static std::atomic<size_t> counter{0}` 가 0 으로 reset. process 안에서 minigame stage 가 2회 이상 발생하지 않는 한 rotate 는 항상 첫 게임만 선택. **3 게임 cycle 의도라면 `random` 또는 persistent counter** 사용.

같은 함정 — 다른 BT 의 process-단위 static counter 가 의도와 다르게 동작 가능. 검사 필요.

### 4-2. game.py 의 fail-silent 패턴

`cv2.VideoCapture(N)` fail 시 setup() False 반환 → main() 즉시 return → `exit code 0`. minigame_runner 입장에선 "정상 종료" 로 인식. **MinigameResult 가 빈 채로 publish 되거나 retry 없음**. 후속: game.py 의 setup() fail 시 `sys.exit(2)` 등 non-zero 종료 + minigame_runner 가 returncode 분기.

### 4-3. cv2 fullscreen windowed stretch 기본 동작

`cv2.namedWindow(name, WINDOW_NORMAL)` 만 쓰면 `setWindowProperty FULLSCREEN` 후 imshow 시 frame 을 윈도우 size 에 **stretch** (default WINDOW_FREERATIO). aspect 보존 위해 `cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO` 명시 필수.

### 4-4. 워크스페이스 이전 (`~/moca → physical-ai-repo-3`) 시 자산 누락 패턴

본 세션에서 2건 발견 (moca_gazebo/models, games/). `.gitignore` 정책이 `~/moca` 시절과 다를 가능성. 다른 큰 자산 (maps/, datasets/, web/, models/) 도 점검 권장. CLAUDE.md `.gitignore` 섹션:
```
build/, install/, log/, maps/, datasets/, web/, models/
```
이 중 어느 것이 실 누락 위험인지 추가 검사.

### 4-5. 옛 test-supervisor 세션의 lingering processes

이전 test-supervisor 세션이 띄운 mode launch 자식 프로세스 (PID 38XXX 대) 가 mode_manager 종료 후에도 좀비로 잔존. 본 세션 cleanup 필수. `pkill -9 -f` + `ros2 daemon stop` 정리.

---

## 5. 정책 정합

본 작업은 CLAUDE.md §0-A / §0-B / §11 어느 정책에도 저촉되지 않음:
- vic_pinky 트리 자체는 미수정 (§0-B OK)
- RPi 접근 없음 (§0-A inactive 유지)
- cmd_vel 토픽 / Nav2 stack 무관 (§11 OK)
- DOMAIN=99 + LOCALHOST_ONLY=1 격리 — 라이브 RPi 영향 0

회귀 시스템 변경은 [[feedback_test_supervisor_v1_no_commit]] 유지.

---

## 6. 1단계 vs 2단계 라이브 — 분리 명시

| 게이트 | sim 1단계 (본 세션) | live 2단계 (별 세션) |
|---|---|---|
| DOMAIN | 99 + LOCALHOST_ONLY=1 | 22 + LAN broadcast |
| §0-A | inactive 가정 (안전) | 사용자 명시 해제 필요 |
| RPi bringup | 미접근 | run_vic_bringup.sh 가동 |
| Nav2 | 미가동 (action wait timeout 으로 graceful abort 검증) | run_nav2.sh 가동 + AMCL 안정 |
| 실 휠 동작 | X (cmd_vel pipeline 안 거침) | ✅ (twist_mux → smoother → monitor → zlac → 모터) |
| 카메라 3 | 미연결 (env=0 우회) | RPC-20F 외장 연결 (default index 2) |
| 게임 시연 | sim 카메라 0 으로 검증됨 | 카메라 3 으로 정상 동작 |

**1단계 = UI → SetMode → spawn 통신 chain 검증** (본 세션 5/5 PASS).
**2단계 = UI → 휠 동작 end-to-end + 카페 환경 영상 촬영** (라이브, §0-A 해제 후).

---

## 7. 후속 트랙

### 즉시 (별 트랙)
- workspace 이전 누락 자산 전수 검사 (.gitignore 비교 + 큰 자산 별 디렉토리)
- minigame_runner integration 완성 (game.py 의 fail-silent → exit code 분기)
- rps + cafe_ninja 도 WINDOW_KEEPRATIO 적용 (사용자 호소 없으나 잠재 이슈)

### v1 검증 후속
- Stephen 명시 "v1 OK" → 회귀 시스템 commit 재개 + 본 세션 5 smoke + 갱신 catalog commit
- v2 팀 확산 (별 결정)

### 라이브 2단계 진입 조건 (별 세션)
1. 사용자 명시 §0-A 해제
2. 백업 (CLAUDE.md §7 일일 백업 루틴)
3. RPi bringup + Nav2 가동
4. 카메라 3 연결
5. 5 modes UI 클릭 → 실 휠 동작 + 영상 촬영

---

**작업자**: gjkong (Claude Opus 4.7 보조)
**세션 시간**: ~2h
**Patches**: 6건 (적용 전부 working tree, commit 정책 사용자 결정 대기)
**검증 PASS**: 5/5 modes 통신 chain + 3/3 게임 fullscreen
**다음 작업**: 사용자 명시 — workspace 누락 자산 commit 정책 결정 / live 2단계 / v1 회귀 commit 재개 / Phase 1 BT 신규 등
