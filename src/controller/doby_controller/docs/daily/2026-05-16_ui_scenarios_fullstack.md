# 2026-05-16 — 운영 UI 9 시나리오 자동 검증 풀스택 (M3 회고 §8.6 후속)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m3_dashboard_completion_ntp_stopmoca.md` §8.6 (운영 UI 자동 시나리오 러너 — 다음 단계)
> 본 회고: 그 다음 단계 (pytest 9 시나리오) 풀스택 검증 + 발견된 production 버그 2종 fix.

---

## 1. 목표

M3 회고 §8.6 의 미완료 항목 "운영 UI 자동 시나리오 러너 (pytest + httpx)" 완성:
- `tests/integration/test_ui_scenarios.py` (S1~S9) + `scripts/run_scenarios.sh` 본 구현은 22:35~22:41 분에 완료됨 (untracked, 미커밋).
- 본 세션 — `run_sim.sh` 풀스택 (Gazebo + Nav2 + UI) 띄워 9 시나리오 종합 검증 + 발견된 함정 fix + 회고/커밋.

## 2. 산출물 누적

### 2.1 신규 (3 untracked → 본 회고로 커밋 예정)

| 자산 | 책임 |
|---|---|
| `scripts/run_scenarios.sh` | opserver health 사전 검증 + `pytest tests/integration/test_ui_scenarios.py` exec 래퍼. 옵션 forward (`-k s5`, `-v`). |
| `tests/integration/conftest.py` | fixture (opserver_alive / http / fast_patrol / force_idle / ws_collect) + `_drain_until_clean` helper |
| `tests/integration/test_ui_scenarios.py` | S1~S9 (12 test 케이스, S6 4 sub-case 포함) |
| `tests/__init__.py` + `tests/integration/__init__.py` | 빈 패키지 마커 |

### 2.2 Production 버그 fix (2건)

본 검증에서 발견된 production 버그. 시뮬 외에 실 운영 (cafe) 에서도 동일 증상 — 라이브 영향 큼.

#### 버그 A — `mode_state.params` WS broadcast 타입 불일치

- **증상**: `/api/v1/status` 와 WS `mode_state` 의 `params` 필드가 **JSON string** 으로 전달됨 (M3 modes.html 의 `Object.keys(p)` + S2 테스트의 `params.get('waypoint')` 양쪽 모두 dict 가정).
- **Root cause**: `dobi_npc_msgs/msg/ModeState.msg` 의 `params` 가 `string` (JSON 직렬화) 인데, `opserver_node._on_mode_state` 가 그대로 WS 로 전달.
- **Fix**: `opserver_node._on_mode_state` 에서 JSON parse 후 dict 로 WS broadcast. snapshot (`self.mode_params`) 은 `operator.html` (legacy) 호환 위해 string 원본 보존.
- **수정 라인**: `src/moca_opserver/moca_opserver/opserver_node.py` (+11/-2)

#### 버그 B — pickup 큐 register 중복 → 동일 배달 재트리거

- **증상**: `POST /api/v1/pickup` → orchestrator 성공 시점에도 `_serving_queue` 에 entry 등록. serving 완료 후 mode→idle 진입 시 `_drain_serving_queue` 가 **같은 entry 로 serving 재트리거**. 운영상 → 동일 테이블로 중복 배달.
- **Root cause**: pickup 엔드포인트 (rest_api.py:299) 가 orchestrator 호출 **전에** queue.register. orchestrator 성공 = mode_manager 가 entry 추적 = queue 등록 불필요. drain 로직은 "pending (busy 라 못 받은) entry 만" 처리 의도.
- **Fix**: orchestrator 호출 성공 시 queue.register 생략. 실패 시 (BUSY 등) 만 등록 → 추후 idle 진입 시 drain 이 재시도. 의미론 정합 회복.
- **수정 라인**: `src/moca_opserver/moca_opserver/rest_api.py` (+5/-1)
- **부수 효과**: 본 fix 가 없으면 S1 (idle→patrol 자동 트리거) 가 영구 skip — S2 의 pickup entry 가 queue 에 영구 잔존하여 idle dwell 깨짐.

## 3. 시나리오 결과 (run_sim.sh 풀스택, DOMAIN=99)

`bash scripts/run_sim.sh --no-rviz` → Gazebo + Nav2 + UI 풀 가동 → `bash scripts/run_scenarios.sh -v`:

```
collected 12 items

S1 idle_patrol_auto       PASSED      8.7s
S2 patrol_pickup_preempt  PASSED      
S3 serving_complete_idle  SKIPPED     M4 자동화 후보 (Gazebo Nav2 도달 시간 의존)
S4 guide_to_guiding       PASSED      
S5 emergency_stop         PASSED      alarm_dwell 차단 검증
S6 invalid_mode           PASSED      INVALID_MODE 400
S6 battery_low            SKIPPED     wire-format 미지원 — 백엔드 mock 필요
S6 safety_alarm           SKIPPED     wire-format 미지원 — 백엔드 mock 필요
S6 busy                   SKIPPED     race 어려움
S7 event_log_accumulate   PASSED      
S8 config_broadcast       PASSED      
S9 utter_command          PASSED      

======================== 8 passed, 4 skipped in 33-21s =========================
```

**연속 3회 동일 결과** (33.73s → 21.72s → 23.65s). flake 0건.

회귀 — 기존 unit test 130/130 통과 (orchestrator + completion_timer + patrol_scheduler + table_occupancy + guiding_controller).

## 4. 디버그 trail

본 검증에서 거친 4 단계 root cause 추적:

### 4.1 S2 AttributeError — `'str' object has no attribute 'get'`

첫 풀스택 실행: S2 FAILED. `params.get('waypoint')` AttributeError. 원인 → §2.2 버그 A.

### 4.2 S1 영구 skip — IdlePatrolTimer 의 business_hours 가드

본 검증 시각 23:10+ → `business_hours='09:00-22:00'` 영업시간 외 → patrol 자동 트리거 영구 차단.
- **Fix**: `fast_patrol` fixture 에 `business_hours='24/7'` 임시 override (teardown 원복).
- 야간 회귀 가능. 주간 검증 시에도 일관 동작.

### 4.3 S1 시뮬 잔존 큐 → 무한 serving 재진입

S2 가 추가한 pickup entry 가 queue 에 잔존. mode→idle 진입마다 `_drain_serving_queue` 가 같은 entry 로 serving 재트리거. S1 의 idle dwell 자체가 깨짐.
- **수동 재현**: 22초 동안 WS 관찰 → `current=serving` 영원히 유지.
- **Fix**: §2.2 버그 B (pickup endpoint register 위치 조정). 본 fix 후 queue 의미론 회복.

### 4.4 S1 의 ws_collect 가 patrol broadcast 못 받음 (해결됨)

pytest 단독 실행은 PASS (9s) 인데 풀 suite 실행은 SKIP. 추적 결과 — S2 의 큐 잔재 (4.3) 가 S1 전에는 이미 영향 없으나 (정상 케이스), 사전 시뮬 잔재 (이전 세션) 가 누적되었던 경우. §2.2 버그 B fix 로 근본 해결.

## 5. 결정 / 정책

### 5.1 S3, S6 (battery/safety/busy) 의 skip 정책 유지

- **S3** — serving 완료 후 idle 자동 복귀. Gazebo Nav2 실 도달 시간 (~30-60s) 의존 + 시뮬 mocamap 상 T01-T05 도달 가능 검증 미완. M4 자동화 후보 — 시뮬 시간 가속 + waypoint shortcut.
- **S6 battery/safety** — wire-format 에 `battery_pct` / `safety_ok` 외부 induce 불가. 백엔드 mock (test-only endpoint `/api/v1/_test/inject_state`) 필요. M4 후보.
- **S6 busy** — orchestrator BUSY 상태는 mode 전환 진행 중 (~1.5s 윈도우). 동시 호출 race 로 induce 어려움. asyncio.gather 패턴 시도 가능하나 timing 불안정. 보류.

### 5.2 fast_patrol fixture 의 `business_hours='24/7'` override 영구

야간/주간 무관 일관 동작. 단순화 + 시간대 독립 검증. teardown 원복으로 운영 정책 영향 0.

### 5.3 `_drain_until_clean` helper — 향후 모든 fixture 가 사용

S1 fast_patrol 에만 적용. 향후 시나리오 (S10+) 가 추가될 때 동일 패턴 활용. 상태 확인 → 더러우면 idle 강제 → 2.5s settle → 재확인 (최대 8회).

### 5.4 `params` dict vs string 양립 — WS 만 dict, snapshot 은 string

- WS broadcast: dict (M3 modes.html + 시나리오 테스트 표준)
- `/api/v1/status` snapshot: string (operator.html legacy 호환)
- M4 에 operator.html 폐기 시점에서 snapshot 도 dict 로 통일 검토.

### 5.5 `--cleanup` 옵션의 run_sim.sh 동작 — 별 보고 (M4 보강 후보)

`bash scripts/run_sim.sh --cleanup` 으로 호출 시 Step 2 (dashboard) 의 cleanup 이 Step 1 (Gazebo+Nav2) 결과를 죽임. run_sim.sh 의 `--cleanup` 은 Step 1 **이전**에 실행되어야 함. 본 세션 회피책 — 그냥 `--no-rviz` 만 사용 (cleanup 별도 `stop_sim.sh` 로 사전 정리). 본 함정 메모.

## 6. 변경 통계

| 영역 | 파일 | 변경 |
|---|---|---|
| 신규 (Test) | `tests/__init__.py` | 신규 (빈) |
| 신규 (Test) | `tests/integration/__init__.py` | 신규 (빈) |
| 신규 (Test) | `tests/integration/conftest.py` | 신규 (126줄 → 142줄, `_drain_until_clean` + `business_hours` override 추가) |
| 신규 (Test) | `tests/integration/test_ui_scenarios.py` | 신규 (288줄, S1~S9 + 4 sub-case skip) |
| 신규 (Script) | `scripts/run_scenarios.sh` | 신규 (38줄, 사전 health check + pytest exec) |
| Production fix | `src/moca_opserver/moca_opserver/opserver_node.py` | +11/-2 (params JSON parse) |
| Production fix | `src/moca_opserver/moca_opserver/rest_api.py` | +5/-1 (pickup queue register 위치) |
| Docs | `docs/daily/2026-05-16_ui_scenarios_fullstack.md` | 본 문서 |

빌드 회귀 — moca_opserver 빌드 2.12s + 1.98s OK. 기존 unit test 130/130 통과. 시나리오 8/12 PASS + 4 의도 SKIP 연속 3회 동일.

## 7. 다음 단계

### 7.1 즉시

- 본 세션 결과 일괄 커밋 (untracked 5 + modified 2 + 회고 1)
- M3 회고 (§8.6) cross-reference 갱신 (optional)

### 7.2 M4 후보 (시나리오 보강)

- **S3 자동화** — Gazebo sim_time 가속 + 짧은 waypoint shortcut (`tables_short.yaml`) 로 ~5-10s 도달 가능하게 + completion_watcher 자동 idle 복귀 검증
- **S6 battery/safety** — `POST /api/v1/_test/inject_state` (테스트 전용 endpoint) — `{"battery_pct": 0.1, "safety_ok": false}` 등 직접 주입. 운영 모드에서는 비활성화 (env var 또는 build flag).
- **S6 busy** — pytest-asyncio 도입 + `asyncio.gather` 로 동시 set_mode 시뮬. race 윈도우 정확히 잡기.
- **S10+** — engaging mode (모객 BT) 자동 시나리오. cafe_funnel_v1.xml 의 5-stage 진행 + abort trigger.
- **run_sim.sh `--cleanup` 위치 fix** — Step 1 전에 cleanup 호출하도록 옵션 처리 순서 조정.

### 7.3 메모리 갱신 후보

- **`mode_state.params` WS broadcast dict 표준** — operator.html legacy 폐기 시점에서 snapshot 도 통일
- **pickup endpoint queue 의미론** — orchestrator 성공 시 register 안 함 + drain 은 pending 만 처리 (본 fix 후 정착)
- **business_hours 야간 검증** — 모든 시간대-의존 fixture 는 24/7 override 권장

## 8. 메모리/문서 정합 확인

- [[feedback_dont_touch_working_code]] ✅ — Production 버그 2종 fix 는 최소 변경 (+16줄, -3줄). 기존 동작 정합 보존 (operator.html string 호환).
- [[feedback_relative_path_convention]] ✅ — 모든 신규 자산 SCRIPT_DIR + 환경변수 helper.
- [[feedback_starlette_symlink_install]] 무관 (정적 자산 변경 0).
- [[project_navigation_code_separation]] ✅ — Nav2 / mode 분리 정책 유지 (테스트는 REST/WS 만 호출, 직접 cmd_vel publish 0).
- [[feedback_no_rpi_when_team_working]] ✅ — DOMAIN=99 시뮬 격리 (LOCALHOST_ONLY=1).
- [[project_m3_dashboard_complete]] ✅ — M3 회고 §8.6 후속 완료. 본 문서가 trail.

---

*다음 갱신 — M4 시작 시점 (KPI 영구 DB / S3 자동화 / 운영자 테스트)*

---

## 9. 후속 trail — `--cleanup` fix + S6 wire-format mock (commit 4ebd746 + 9-trail)

본 §1-8 의 8/12 PASS 이후 즉시 진행된 보강 2 트랙.

### 9.1 `run_sim.sh --cleanup` 위치 fix (commit 4ebd746)

§5.5 의 함정 — `--cleanup` 이 Step 2 (dashboard) 에 forward 되어 Step 1 (Gazebo+Nav2) 까지 같이 죽이는 문제. Step 0 (사전 정리) 으로 분리. `stop_sim.sh` 위임 (Gazebo + UI 풀스택 일괄). `run_dashboard.sh` 의 `--cleanup` forward 차단.

검증: `bash scripts/run_sim.sh --no-rviz --cleanup` 후 `/amcl /controller_server /map_server /nav2_container /planner_server /moca_opserver /mode_manager` 7 노드 모두 alive 확인.

### 9.2 S1 race + IdlePatrolTimer cooldown fix (commit 4ebd746)

§3 의 3회 연속 PASS 가 §8 후속 검증 시 1회 + 2회 SKIP 으로 flaky 화. 2 root cause:

1. **S1 의 `_ensure_idle` race** — `_ensure_idle` 의 POST /mode 가 직전 IdlePatrolTimer 가 fire 한 patrol (0.5s 윈도우) 을 즉시 kill. mode_manager 1Hz publish 가 0.5s 윈도우 못 잡으면 patrol broadcast 안 됨. fast_patrol 의 `_drain_until_clean` 이 이미 idle 보장하므로 `_ensure_idle` 호출 제거.
2. **IdlePatrolTimer cooldown 30s 하드코딩** — 연속 테스트 실행 시 두 번째부터 cooldown 으로 patrol 트리거 차단. `patrol_retrigger_cooldown_sec` config 노출. fast_patrol 이 0 으로 override (teardown 원복). 운영 default 30s 유지.

**결과**: 3회 연속 8/12 PASS 안정. 실행 시간 33s → 13-16s 단축.

### 9.3 S6 wire-format mock endpoint (commit 본 trail)

**목표**: §3 의 `S6 battery_low_skip` + `S6 safety_alarm_skip` 활성 → 시나리오 커버리지 8 → 10.

**설계 — 운영 안전 + 테스트 활성 양립**:
- `POST /api/v1/_test/inject_state` endpoint — env `MOCA_TEST_MODE=1` 일 때만 FastAPI 라우터에 등록. 운영 모드에서는 404.
- 허용 페이로드: `{battery_pct, safety_ok, clear}`.
- `safety_ok` 주입 시 `_test_safety_locked=True` → `_on_mode_state` 콜백이 safety_ok 덮어쓰기 차단 (mode_manager 1Hz publish 가 inject 값 무효화하던 race 해결).
- `clear: true` → lock 해제 (teardown).
- `battery_pct` — sim 에 `/battery_state` publisher 없어 inject 후 영구 (teardown 시 1.0 명시).

**기동 옵션** — `bash scripts/run_dashboard.sh --test-mode` 또는 `bash scripts/run_sim.sh --test-mode` (TODO: run_sim.sh 도 forward 옵션 추가 시점).

**검증**:
- 운영 모드: `curl POST /api/v1/_test/inject_state` → 404 ✓
- 테스트 모드: 200 + `battery_pct=0.05` 주입 → `POST /mode patrol` → 503 BATTERY_LOW (`battery 0.05 < min 0.20`) ✓
- 3회 연속 10/12 PASS, 15-17초. unit test 130/130 회귀 0.

**S6 busy 만 skip 유지** — orchestrator BUSY state 의 race window (~1.5s spawn) 동시 호출로 induce 어려움. pytest-asyncio + asyncio.gather 패턴 별도 검토 필요.

### 9.4 갱신된 결과 표

| ID | 결과 | 비고 |
|---|---|---|
| S1 | PASS | fast_patrol drain + cooldown=0 override |
| S2 | PASS | params dict (§2.2 버그 A fix) |
| S3 | SKIP | M4 자동화 후보 (Gazebo 도달 시간) |
| S4 | PASS | |
| S5 | PASS | alarm_dwell 차단 |
| S6 invalid_mode | PASS | INVALID_MODE 400 |
| **S6 battery_low** | **PASS** | inject_state endpoint (`battery_pct=0.05`) |
| **S6 safety_alarm** | **PASS** | inject_state endpoint (`safety_ok=false`) |
| S6 busy | SKIP | race induce 어려움 |
| S7 | PASS | events deque 누적 |
| S8 | PASS | config_updated broadcast |
| S9 | PASS | utter command |

**합계: 10 PASS / 2 SKIP** (이전 8/4 → 10/2).

---

*다음 갱신 — M4 시작 시점 (KPI 영구 DB / S3 Gazebo 자동화 / S10+ engaging / 운영자 테스트)*

---

## 10. S3 completion 주입 — pipeline 검증 (commit 본 trail)

### 10.1 실 Nav2 cycle 측정 (S3 skip 해제 전 baseline)

T01 (closest, ~2.35m from home) 시나리오 실측:
- **첫 pickup (cold AMCL)**: 100s+ stuck — robot 미동작. AMCL initial pose race + Nav2 미준비.
  - `/serving/state`: `state=navigating, current_table=null` 영원히 유지
  - 수동 NavigateToPose 직접 호출 → ~30s 도달 (Nav2 자체는 작동)
- **두 번째 pickup (warm AMCL)**: 75s 완주
  - 0-4s: nav to T01 / 4-9s: dwell 5s / 9-69s: 복귀 ~60s / 69-72s: svc=idle / 75s: mode→idle

**결론**: 실 Nav2 cycle 의 신뢰성 + 시간 부담 — 자동 시나리오로 부적합 (100-150s 변동 + AMCL race 불안정).

### 10.2 inject_completion='serving' pipeline 검증 채택

S3 의 진짜 의도 — `completion_watcher → orchestrator → SetMode(idle)` pipeline. Nav2 도달 시간 제외하고 pipeline 만 빠르게 검증.

**설계 확장 (commit 본 trail)**:
- `POST /api/v1/_test/inject_state` 에 `inject_completion: 'serving'|'patrol'|'guiding'|'engaging'` 키 추가
- serving 의 경우 `_test_completion_locked=True` 설정 → `_on_serving_state` 콜백의 dispatcher publish 가 dwell reset 하던 race 차단
- `clear:true` 로 lock 해제 (teardown)
- completion_watcher.on_serving_state('idle') 직접 호출 → dwell 시작 → 3s 후 SetMode(idle)

**테스트 본 구현**: `test_s3_serving_complete_to_idle` 8초 완주 (pickup 1.9s + inject + dwell 3s + setmode + mode_state).

**timing race fix — `_wait_for_mode` helper**:
- pickup 후 mode='serving' 도달 ~1.9-2.5s (1Hz publish + transition 1.5s)
- 기존 `time.sleep(2.0)` 경계 시 inject 시 mode 가 여전히 idle → `_observe` silent reject
- `_wait_for_mode(http, 'serving', timeout=5.0)` 100ms polling 으로 race 제거

### 10.3 실 Nav2 cycle 은 opt-in 으로 분리

`test_s3_real_nav2_cycle` 신규 — `@pytest.mark.skip(reason='opt-in')` 로 default skip. 180s timeout. 향후 자동 회귀에 필요 시 mark 제거 + 별 marker 도입 검토 (예: `@pytest.mark.slow`).

### 10.4 갱신된 결과 표 (11/13)

| ID | 결과 | 시간 | 비고 |
|---|---|---|---|
| S1 | PASS | ~1s | fast_patrol drain + cooldown=0 |
| S2 | PASS | ~3s | params dict (§2.2 버그 A) |
| **S3 serving_complete_to_idle** | **PASS** | **~8s** | **inject_completion (pipeline 검증)** |
| **S3 real_nav2_cycle** | **SKIP (opt-in)** | — | 실 Gazebo Nav2 ~75-150s, mark 제거 시 실행 |
| S4 | PASS | ~3s | |
| S5 | PASS | ~3s | alarm_dwell 차단 |
| S6 invalid_mode | PASS | ~0.5s | |
| S6 battery_low | PASS | ~1s | inject_state |
| S6 safety_alarm | PASS | ~1s | inject_state |
| S6 busy | SKIP | — | race induce 어려움 |
| S7 | PASS | ~2s | |
| S8 | PASS | ~1s | |
| S9 | PASS | ~1s | |

**합계: 11 PASS / 2 SKIP** (이전 10/2 → 11/2, S3 split 으로 total 13). 3회 연속 24s 안정.

### 10.5 다음 후보 (M4)

- **S3 real_nav2_cycle 안정화** — AMCL initial pose 자동화 (run_nav2_sim.sh 의 WARN 해결), Nav2 복귀 path 단축 (home_pose 위치 조정 또는 return_home_after_dwell 옵션 노출)
- **S6 busy** — pytest-asyncio + asyncio.gather 동시 set_mode race 도전
- **S10+ engaging mode** — cafe_funnel_v1.xml BT abort_trigger + emotion event 검증
- **CompletionWatcher `_retrigger_cooldown_sec` config 노출** — 패턴 일관성 (patrol_retrigger_cooldown_sec 와 동일 정합)

---

*다음 갱신 — M4 시작 시점*

---

## 11. S10/S11/S12 engaging mode 시나리오 (commit 본 trail)

### 11.1 신규 3 시나리오

| ID | 시나리오 | 검증 |
|---|---|---|
| **S10 engaging_entry** | `POST /mode engaging` → ws_collect `mode_state.current='engaging'` | mode_manager 의 engaging stack 진입 검증 |
| **S11 engaging_complete_to_idle** | engaging → `inject_completion='engaging'` → completion_dwell 2s → idle | completion_watcher.on_engaging_done() pipeline 검증 |
| **S12 engaging_rapport_abort** | engaging → `inject_rapport_abort=true` → mode_manager 강제 idle | cafe_funnel BT 의 abort 경로 (Russell V<-0.5 / A>0.4) 시뮬 |

### 11.2 인프라 확장

**opserver_node.py — /rapport/event publisher 추가**:
- 기존엔 subscribe 만 (감정 노드가 발행자). 테스트 inject + 향후 운영자 강제 abort UI 위해 publisher 추가.
- 운영 모드에서 OpServer 가 abort 자체 발행 X (감정 노드 책임 — geva_node + rapport_tracker).

**rest_api.py — inject_state 확장**:
- `inject_rapport_abort: bool` 키 추가 → RapportEvent(event_type='abort_trigger', weight=0.9, reason='test_inject') 발행
- mode_manager._on_rapport 가 인지 → `_safety_alarm_until_ns = now + 5s` + `_do_transition(prev, 'idle', ...)` thread spawn → 강제 idle

**run_sim.sh — `--test-mode` forward 옵션**:
- `bash scripts/run_sim.sh --test-mode` → run_dashboard.sh --test-mode → MOCA_TEST_MODE=1
- 시뮬 풀스택 + 테스트 endpoint 한 줄 기동

### 11.3 발견: S5/S12 의 alarm_dwell 5s 가 후속 테스트 차단

S5 emergency_stop + S12 rapport_abort 가 mode_manager 측 `_safety_alarm_until_ns = now + 5s` 설정 → opserver.safety_ok 가 5s 동안 false → 후속 non-idle setmode 가 503 SAFETY_ALARM 거부.

**증상**: S10 (engaging_entry) 가 isolated PASS, 풀 suite 에서 FAIL.
`AssertionError: engaging 거부: {"code":"SAFETY_ALARM","message":"alarm dwell active"}`

**Fix**: `_ensure_idle` 에 `safety_ok=true` polling (최대 7s) 추가. alarm dwell 자동 해제 대기. 일부 테스트 (S10/S11/S12 가 S5/S12 후속) 가 +5-7s 추가 되어 풀 suite 24s → 42s. 수용 가능.

### 11.4 갱신된 결과 표 (14/16)

| ID | 결과 | 비고 |
|---|---|---|
| S1 ~ S9 | PASS / 의도 SKIP | 11 의 기존 + S6 busy 1 skip |
| **S10 engaging_entry** | **PASS** | POST /mode engaging |
| **S11 engaging_complete** | **PASS** | inject_completion='engaging' + dwell 2s |
| **S12 rapport_abort** | **PASS** | inject_rapport_abort → mode_manager 강제 idle |
| S3 real_nav2_cycle | SKIP | opt-in |
| S6 busy | SKIP | race induce 어려움 |

**합계: 14 PASS / 2 SKIP** (이전 11/2 → 14/2, total 16). 3회 연속 42s 안정.

### 11.5 다음 후보 (M4)

- **S13/S14 priority preemption** — engaging 중 pickup (priority 1) → serving 선점 / engaging 중 guide (priority 2) → guiding 선점
- **S6 busy** — pytest-asyncio + asyncio.gather race
- **AMCL 안정화** — run_nav2_sim.sh 의 initial pose 신뢰성 + S3 real_nav2_cycle 활성
- **alarm_dwell teardown 최적화** — S5/S12 후속 테스트 시간 단축 (현재 +5-7s 매 ensure_idle)

---

*다음 갱신 — M4 시작 시점*

---

## 12. S13/S14 priority preemption (commit 본 trail)

### 12.1 신규 2 시나리오 — engaging 선점 검증

`PRIORITY = {serving: 1, guiding: 2, patrol: 3, engaging: 5, idle: 99}`. 숫자 작을수록 우선순위 높음. orchestrator unit test 는 priority gating 검증하지만 (test_orchestrator.py 의 test_priority_gating[serving-engaging-True-None] 등) — **실 모드 stack 의 spawn + transition** 까지 검증하는 통합 테스트는 부재.

| ID | 시나리오 | 검증 |
|---|---|---|
| **S13 engaging_pickup_preempt_serving** | engaging → POST /pickup → serving 자동 선점 (override_priority=False) | priority 1 vs 5 — mode_manager 가 engaging stack kill + serving stack spawn |
| **S14 engaging_guide_preempt_guiding** | engaging → POST /guide → guiding 자동 선점 (override_priority=False) | priority 2 vs 5 — guide endpoint 의 orchestrator 호출 + 실 transition |

### 12.2 결과

- isolated: 2 PASS in 10.4s
- 풀 suite: 3회 연속 **16 passed / 2 skipped** in 62s

본 추가로 시간 42s → 62s (S13/S14 각 ~10s — engaging spawn + safety_ok 대기 + preempt + ws_collect).

### 12.3 갱신된 결과 표 (16/18)

| ID | 결과 | 비고 |
|---|---|---|
| S1 ~ S12 | PASS / 의도 SKIP | 14 PASS + S3_real/S6_busy 2 SKIP |
| **S13 pickup_preempt_serving** | **PASS** | engaging (5) → serving (1) 선점 |
| **S14 guide_preempt_guiding** | **PASS** | engaging (5) → guiding (2) 선점 |

**합계: 16 PASS / 2 SKIP** (이전 14/2 → 16/2, total 18).

### 12.4 남은 후보 (M4)

- **S6 busy** — pytest-asyncio + asyncio.gather 동시 set_mode race induce (이전부터 미해결)
- **S3 real_nav2_cycle** — AMCL initial pose 안정화 + 실 Gazebo cycle 자동화
- **S15+** — patrol/guiding 중 우선순위 inversion (현재 priority gating 검증, BUSY 거부 검증)
  - guiding (2) 중 patrol (3) → BUSY 거부
  - guiding (2) 중 engaging (5) → BUSY 거부
  - 이미 orchestrator unit 에서 검증됨 — 통합은 redundant 가능
- **alarm_dwell teardown 최적화** — 각 ensure_idle 의 7s safety 대기 누적

---

*다음 갱신 — M4 시작 시점*

---

## 13. S6 busy priority gating (commit 본 trail)

### 13.1 접근 — race 대신 deterministic priority gating

기존 `test_s6_busy_skip` 의 skip 사유: "동시 set_mode race 로 induce 어려움". 하지만 orchestrator.request_mode_change 의 BUSY 본 경로는 **priority gating** (`PRIORITY[target] >= PRIORITY[current]`, override=False) 으로 deterministic 하게 induce 가능.

mode_orchestrator.py:118-124 — non-idle current + non-idle target + lower-priority target + override=False → `{code: 'BUSY', message: f'lower_priority_during_{current}'}`. orchestrator unit (test_priority_gating) 이 게이팅 로직 검증, 본 통합 시나리오는 **REST 423 응답 + error code 매핑** 검증.

### 13.2 시나리오 본 구현 — `test_s6_busy_priority_gating`

1. `_ensure_idle`
2. POST /mode serving (priority 1, override=True)
3. `_wait_for_mode('serving')`
4. POST /mode engaging (priority 5, override=False) → **423 BUSY** 검증
5. 메시지에 `'serving'` (current_mode) 포함 검증
6. finally: idle 강제 복귀

isolated 3.55s. 풀 suite 안정 — 3회 연속 60-66s.

### 13.3 갱신된 결과 표 (17/18) — single skip

| ID | 결과 | 비고 |
|---|---|---|
| S1 ~ S14 | PASS / 의도 SKIP | 16 PASS + S3_real_nav2_cycle skip |
| **S6 busy_priority_gating** | **PASS** | serving + engaging override=False → 423 BUSY |

**합계: 17 PASS / 1 SKIP** (이전 16/2 → 17/1, total 18).

남은 단일 skip: `test_s3_real_nav2_cycle` — 의도된 opt-in (실 Gazebo Nav2 cycle ~75-150s, AMCL race 의존).

### 13.4 본 세션 누적 진행

| 커밋 | 시나리오 커버리지 | 시간 |
|---|---|---|
| 8dadfea | 8/12 (초기) | 33s |
| 4ebd746 | 8/12 (안정) | 13-16s |
| b0a6fbc | 10/12 (S6 mock) | 15-17s |
| f0c26e3 | 11/13 (S3 split) | 24s |
| cf5cd55 | 14/16 (S10-S12) | 42s |
| b75cff8 | 16/18 (S13/S14) | 62s |
| **본** | **17/18 (S6 busy)** | **60-66s** |

**시나리오 PASS 비율: 67% → 94%** (8/12 → 17/18). 의도 skip 만 1건 남음.

### 13.5 남은 후보 (M4 또는 별 트랙)

- **S3 real_nav2_cycle 활성** — `run_nav2_sim.sh` 의 AMCL initial pose 안정화 + Nav2 복귀 시간 단축 (home_pose 조정)
- **alarm_dwell teardown 최적화** — _ensure_idle 의 7s safety_ok 대기 누적 (현재 풀 suite 60s+의 약 절반 비중)
- **S15+ 추가 시나리오** — guiding/patrol/engaging 중간의 다양한 priority/BUSY 케이스 (orchestrator unit 와 중복 가능성 검토)
- **TestCase fixture 정리** — engaging 진입 + safety_ok 대기 등 공통 패턴 fixture 화

---

*다음 갱신 — M4 시작 시점 또는 위 후보 진행 시*

---

## 14. S3 real_nav2_cycle 활성화 (commit 본 trail)

### 14.1 run_nav2_sim.sh — AMCL initial pose 신뢰성 + warmup nav

**문제 1**: `ros2 topic pub --once /initialpose` 가 AMCL subscription 타이밍 race 로 손실. AMCL 이 아직 lifecycle active 안 됐거나 subscription 등록 전이면 메시지 drop. 결과 — `/amcl_pose` 미발행 → TF map→base_link 미확립 → Nav2 planner hang.

**Fix**: 최대 15회 반복 publish (1s 간격), `/amcl_pose` 수신 즉시 break. AMCL ready 시점이 언제든 catch.

**문제 2**: 첫 dispatcher nav 시 cold AMCL race 로 `state=navigating, current_table=null` 영원히 stuck.

**Fix**: run_nav2_sim.sh Step 3.5 — 현 위치로 단발 NavigateToPose warmup. Nav2 stack 전체 (BT navigator, costmaps, planner, controller) 활성화. dispatcher 의 첫 실 nav 가 warm Nav2 에 진입.

검증: warmup.log → `Goal finished with status: SUCCEEDED` 확인.

### 14.2 S3 real_nav2_cycle 본 구현

**skip mark 제거** + race fix:
- 기존 false-positive: `_ensure_idle` 후 ws_collect 가 즉시 initial idle mode_state 매칭 → 1.5s 안 PASS (실 cycle 미검증).
- Fix: `_wait_for_mode('serving', 5s)` 로 pickup 후 serving 진입 확인 → 그 후 ws_collect (current=='idle') 매칭. False positive 회피.
- timeout 150s (warmup 후 typical 75-100s + buffer).

**실측**: isolated 95.5s — pickup → serving spawn ~1.5s → Nav2 to T01 ~10-15s → dwell 5s → return 60s → completion dwell 3s.

### 14.3 풀 suite 3회 결과

| run | 결과 | 시간 | 비고 |
|---|---|---|---|
| 1 | **18/18 PASS** | 116s | 첫 실행 — warmup 직후 clean state |
| 2 | **18/18 PASS** | 126s | 안정 |
| 3 | 17/18 (S3 real SKIP) | 219s | robot 위치 누적 + Nav2 state drift → S3 real 150s timeout |

**flakiness 분석**: 각 run 의 S2 (patrol→pickup) + S3 real_nav2 (실 cycle) + S3 inject (mode 강제 idle) 누적으로 robot 의 실 위치가 home 에서 멀어짐. 3회째에 멀리서 시작 + Nav2 복귀 path 길어짐 → 150s 부족.

### 14.4 갱신된 결과 표 (18/18, run 1 기준)

| ID | 결과 | 시간 |
|---|---|---|
| S1 ~ S14 + S6 busy | 17 PASS | ~62-66s |
| **S3 real_nav2_cycle** | **PASS (run 1-2) / SKIP (run 3)** | **~95s** |

**합계: 17-18 PASS / 0-1 SKIP** (이전 17/1 → 17-18/0-1, total 18). PASS 비율 **94% → 94-100%**.

### 14.5 향후 안정화 (M4 후보)

- **시나리오 간 robot pose reset** — 각 테스트 전 `/initialpose` 재발행 (또는 Gazebo set_entity_pose 서비스)
- **S3 real_nav2_cycle 별 marker** — `@pytest.mark.slow` 등으로 분리, default suite 제외 (CI 빠른 회귀 + 별 nightly 회귀)
- **AMCL drift 모니터링** — robot 가 home 에서 ±2m 이상 멀어지면 경고 log

### 14.6 본 세션 최종 요약 (9 커밋)

| 커밋 | 시나리오 | PASS 비율 |
|---|---|---|
| 8dadfea | 8/12 | 67% |
| 4ebd746 | 8/12 (S1 race fix) | 67% |
| b0a6fbc | 10/12 (S6 mock) | 83% |
| f0c26e3 | 11/13 (S3 split) | 85% |
| cf5cd55 | 14/16 (S10-S12) | 88% |
| b75cff8 | 16/18 (S13/S14) | 89% |
| 60a168e | 17/18 (S6 busy) | 94% |
| **본** | **18/18 (run 1-2) / 17/18 (run 3)** | **94-100%** |

**시나리오 PASS 비율 67% → 94-100%** (의도된 skip 0건, robot 위치 누적 의존 flake 1건).

---

*다음 갱신 — M4 또는 다른 트랙 시작 시점*

---

## 15. S3 real flakiness 해소 — pose reset fixture (commit 본 trail)

### 15.1 문제 — robot 위치 누적 drift

§14.3 의 run 3 (17/18) 분석: S2/S3_real 등 실 Nav2 cycle 후 robot 가 home 에서 벗어남. 누적되며 S3_real 의 nav 거리 길어짐 → 150s timeout.

### 15.2 Gazebo `set_pose` 서비스 활용

Gazebo Garden/Harmonic 의 `/world/mapv5_moca/set_pose` 서비스로 robot 직접 teleport. 검증:
```
gz service -s /world/mapv5_moca/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
  --timeout 2000 --req 'name: "vicpinky", position: {x: -36.887, y: 2.809, z: 0.0}, ...'
→ data: true
→ /amcl_pose 즉시 (-36.92, 2.65) 갱신
```

### 15.3 신규 endpoint `POST /api/v1/_test/reset_robot_pose`

- MOCA_TEST_MODE gate (운영 모드 미등록)
- subprocess.run(['gz', 'service', ...]) 으로 set_pose 호출
- payload 옵션: {world, model, x, y, yaw} (기본 tables.yaml home_pose)
- Gazebo CLI 미설치 또는 timeout → 503 (test 가 graceful skip 가능)

### 15.4 test_s3_real_nav2_cycle 통합

매 실행 전 reset_robot_pose 호출 → home_pose teleport → 1s 안정화 대기 → pickup. 누적 drift 영구 회피.

### 15.5 3회 연속 결과 — 18/18 PASS

| run | 결과 | 시간 |
|---|---|---|
| 1 | **18/18 PASS** | 116s |
| 2 | **18/18 PASS** | 191s — S3 real ~130s (path planning 변동) |
| 3 | **18/18 PASS** | 149s |

**flake 해소 확인**: 이전 run 3 의 17/18 (S3 real SKIP) 재현 X. 시간 변동 (S3 real cycle 자체 75-130s) 은 남아있으나 PASS 결정성 회복.

### 15.6 본 세션 최종 (10 커밋)

| 커밋 | 시나리오 | PASS 비율 |
|---|---|---|
| 8dadfea | 8/12 | 67% |
| 4ebd746 | 8/12 (S1 race fix) | 67% |
| b0a6fbc | 10/12 (S6 mock) | 83% |
| f0c26e3 | 11/13 (S3 split) | 85% |
| cf5cd55 | 14/16 (S10-S12) | 88% |
| b75cff8 | 16/18 (S13/S14) | 89% |
| 60a168e | 17/18 (S6 busy) | 94% |
| 035c257 | 18/18 (S3 real, flake 가능) | 94-100% |
| **본** | **18/18 (S3 real flake fix)** | **100%** |

**시나리오 PASS 비율 67% → 100%. 모든 시나리오 결정성 확보.**

---

*다음 갱신 — M4 시작 시점 (KPI DB / 다른 영역 / 새 시나리오 등)*
