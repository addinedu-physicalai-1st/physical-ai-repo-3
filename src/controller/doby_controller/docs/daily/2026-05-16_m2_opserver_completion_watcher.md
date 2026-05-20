# 2026-05-16 — M2 OpServer 자동 사이클 (CompletionWatcher + IdlePatrolTimer)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m2_guiding_implementation.md`
> 선행 문서: `docs/moca_opserver_api_spec.md` §5.2 + §5.4
> 다음 진행: 라이브 통합 검증 또는 M3 (Web Dashboard)

---

## 1. 오늘의 목표

M2 패트롤/가이딩 완료 후 마지막 미해결 — **활동 모드 종료 후 자동 idle 복귀**
파이프라인 + **5분 idle dwell 자동 patrol 트리거** 구현.

본 회고들에서 결정한 "활동 모드 DONE 자체 self-terminate X" 패턴은 OpServer 가
`SetMode('idle')` 을 호출해야 완결. 두 모듈 신규:
- `CompletionWatcher` (API §5.4)
- `IdlePatrolTimer` (API §5.2 — 이름은 모드 노드 `patrol_scheduler` 와 차별)

그리고 guiding_design §10 G3 운영 정책 (guiding 중 serving 큐잉) 도 함께 구현.

## 2. 산출물

### 2.1 `moca_opserver/completion_watcher.py` (신규)

**책임**: 4 활동 모드 (serving/patrol/guiding/engaging) 의 state 토픽 관찰 → dwell 후
자동 `SetMode('idle')`. 활동 모드 dispatcher 가 self-terminate 하지 않는다는
디자인 결정의 외부 조율자.

**종료 시그널 집합**:
```python
_DONE_SIGNALS = {
    'serving':  {'idle'},                # /serving/state JSON.state
    'patrol':   {'done', 'aborted'},     # PatrolState.current_state
    'guiding':  {'done', 'aborted'},     # GuidingState.current_state
    'engaging': {'done', 'completed'},   # /bt/result (M2 placeholder)
}
```

**핵심 메커니즘**:
- `on_X_state(state_value)`: 종료 시그널이면 `_dwell_start[mode] = now`, 활동 재개
  신호면 `_dwell_start[mode] = None` (리셋)
- `tick()` (1Hz): elapsed >= dwell + node.current_mode == 본 모드 → SetMode('idle',
  override_priority=True)
- 트리거 후 `_retrigger_cooldown_sec=2.0` 동안 재트리거 차단 (idempotent)
- 현재 모드가 본 모드 아니면 dwell invalidate (stale 신호 무시)

**override_priority=True**: 활동 모드 → idle 은 우선순위 무관 통과 (FSM spec §3.4
강제 idle 패턴과 정합).

### 2.2 `moca_opserver/idle_patrol_timer.py` (신규)

**책임**: `/mode/state.current_mode == 'idle'` 5분 누적 + 가드 만족 시 patrol 자동 트리거.

**★ 명명 차별**: 본 모듈은 `moca_opserver.idle_patrol_timer.IdlePatrolTimer`.
모드 노드 `dobi_npc_bringup.patrol_scheduler_node.PatrolScheduler` 와 혼동 회피.
마스터 트리는 `patrol_scheduler.py` 명명이지만 본 구현은 명명 차별 (책임이 완전히 다름).

**가드 4중**:
1. `config.patrol_enabled == True`
2. 영업시간 (`config.business_hours`) — `_in_business_hours("09:00-22:00")`
3. 배터리 (`battery_pct >= battery_min` 또는 미수신)
4. `_retrigger_cooldown_sec=30.0` (같은 idle 사이클 중복 차단)

**business_hours 파싱**: `"HH:MM-HH:MM"` 형식 + 빈 문자열/`"24h"`/`"24/7"`/`"always"`
= 24시간 활성. 잘못된 형식은 (None, None) → 24시간 활성 fallback (안전 측).

**트리거 후 `_last_idle_entered_at = None`** — 사이클 끝나서 idle 다시 들어와야
다음 5분 dwell 시작.

### 2.3 opserver_node 통합 (★ G3 정책 포함)

**1Hz timer 추가**: `_tick_completion_and_patrol` — CompletionWatcher.tick() +
`_drain_serving_queue()` + IdlePatrolTimer.tick()

**콜백 wiring**:
- `_on_mode_state` → `self.idle_patrol_timer.on_mode_state(msg.current_mode)`
- `_on_serving_state` → `self.completion_watcher.on_serving_state(state_val)`
- `_on_patrol_state` → `self.completion_watcher.on_patrol_state(msg.current_state)`
- `_on_guiding_state` → `self.completion_watcher.on_guiding_state(msg.current_state)`

**G3 정책 (`/pickup` 핸들러)**:
```python
# guiding_design §10 G3 정책 — guiding 진행 중 serving 선점 금지 (큐잉만)
if current == 'guiding':
    opserver.serving_queue_register(req.model_dump())
    return _ok({..., 'queue_position': N, 'preempted': False,
                'outcome': 'queued:guiding_in_progress'})
```

priority 만 보면 serving(1) < guiding(2) 으로 선점 가능하지만 운영 정책 우선.

**G3 큐 drain (`_drain_serving_queue`)**:
- idle 진입 + serving_queue 비어있지 않으면 첫 entry 로 SetMode('serving') 자동
- guiding 완료 → CompletionWatcher idle → drain → serving 자동 시작 의 완결성
- G3 정책 + 자동 큐 drain = "선점 X 큐잉 → 안내 끝나면 자동 처리" 완결

### 2.4 단위 테스트 (`test_completion_and_timer.py`)

**38 tests / 0 failures** (pytest 0.06s).

커버리지:
- business_hours 파싱 9건 (valid 2 / open 4 / invalid 3)
- in_business_hours 3건 (24h / within / outside)
- IdlePatrolTimer 9건:
  - idle 진입 dwell 시작
  - 비-idle 모드 진입 시 dwell 리셋
  - interval 미만 elapsed → 트리거 안 함
  - interval 만료 → SetMode('patrol') 호출 + 트리거 후 리셋
  - patrol_enabled=False → 차단
  - 영업시간 밖 → 차단
  - battery_low → 차단
  - battery 미수신 → 안전 측 허용
  - idle_elapsed_sec 헬퍼
- CompletionWatcher 20건:
  - 시그널 분류 10 (mode × state → done? parametrize)
  - 외 모드 진행 중 신호 무시 1
  - 활동 재개 신호 → dwell 리셋 1
  - dwell 만료 → SetMode('idle', override=True) 1
  - dwell 미만 → 트리거 안 함 1
  - retrigger_cooldown → 중복 차단 1
  - tick 시점 모드 변경 → invalidate 1
  - config completion_dwell_X 정합 + default fallback 1
  - 기타 보조 3

**전략**: ROS Node 없이 FakeNode + MagicMock orchestrator. config 는 dataclass-like
일반 클래스. 매우 빠름 (38 tests / 0.06s).

### 2.5 통합 스모크 결과

mode_manager + opserver 동시 기동 + `patrol_interval_minutes=0.167` (10초 단축):

| 시점 | 동작 |
|---|---|
| 0s | idle → IdlePatrolTimer dwell 시작 |
| 10.7s | IdlePatrolTimer 만료 → SetMode('patrol') |
| 11s | mode_manager spawn patrol stack |
| ~12s | patrol_scheduler init → next → moving (Nav2 부재 → unknown skip) → ... → returning → done |
| 12s | CompletionWatcher[patrol]: 'done' signal → dwell 시작 (1.0s) |
| 13s | CompletionWatcher dwell 만료 → SetMode('idle', override=True) |
| 13s | mode_manager: patrol → idle, SIGTERM patrol stack |
| 13s | IdlePatrolTimer 재시작 (다음 dwell) |
| 23s | **cycle 2 자동 patrol 재트리거** ✅ |

본 사이클은 운영 환경의 정상 흐름:
- 영업 시간 + idle 상태에서 5분마다 자동 순회 (테이블 점유 상태 업데이트)
- 순회 완료 후 자동 idle 복귀
- 동행 안내 / 서빙 요청 들어오면 즉시 선점 또는 큐잉

### 2.6 전체 회귀 — **130/130 PASS** (132s)

| 모듈 | tests |
|---|---|
| orchestrator (M1) | 41 |
| completion+timer (M2op 신규) | 38 |
| patrol_scheduler (M2-patrol) | 16 |
| table_occupancy_detector (M2-patrol) | 10 |
| guiding_controller (M2-guiding) | 25 |
| **합계** | **130** |

## 3. 발견 / 결정

### 3.1 G3 운영 정책 채택 (guiding_design §10 결정)

guiding 중 serving 선점은 **큐잉만**. 디자인 §10 G3 의 (b) 채택.
이유: 실 매장에서 손님 안내 중 끊김 부적절. priority 룰은 자동 선점이 기본이지만
운영 정책이 우선.

**구현 위치**:
- `rest_api.py /pickup` 핸들러: `current == 'guiding'` 분기 추가
- `opserver_node._drain_serving_queue()`: idle 진입 + 큐 비어있지 않으면 자동 drain
- mode_orchestrator 자체에는 분기 추가 안 함 (운영자 수동 override_priority=True 는 여전히 허용)

### 3.2 IdlePatrolTimer 명명 차별 (충돌 회피)

마스터 계획서 §5.2 트리는 `moca_opserver/patrol_scheduler.py` 명시지만, 모드 노드
`dobi_npc_bringup.patrol_scheduler_node` 와 동일한 클래스명 `PatrolScheduler` 가
들어가면 import / debug 시 혼란 가능. 본 구현은 명명 차별:
- 파일: `moca_opserver/idle_patrol_timer.py`
- 클래스: `IdlePatrolTimer`

기능은 마스터 디자인과 동일 (idle 5분 dwell → patrol 트리거).

### 3.3 CompletionWatcher 의 `current_mode` 검증

각 시그널 수신 시 `node.current_mode == mode` 인지 확인. stale 신호 (이미 다른 모드
진행 중인데 이전 패트롤의 늦은 done 발행 등) 무시. 단순하지만 안전.

또한 tick 시점에서도 한번 더 검증 — 트리거 직전 mode 가 바뀌었으면 invalidate.

### 3.4 retrigger_cooldown 필요성

dwell 만료 → SetMode('idle') 호출 직후 mode_manager 가 비동기 처리 중. 그 사이
1초 안 다음 tick 에서 dwell_start 가 None 됐지만 새 시그널이 다시 들어올 수 있다.
`_retrigger_cooldown_sec=2.0` 가 그 race 차단.

### 3.5 ros2 parameter snapshot의 알려진 한계

`GET /status` 의 `config.patrol_interval_minutes` 가 ROS parameter override 값이
아닌 dataclass default 표시. 실 동작 (IdlePatrolTimer.tick) 은 정상 — config
인스턴스의 갱신된 값 사용. UI snapshot 만 stale.

**M3 디버그**: `OpServerNode.__init__` 에서 parameter 를 config dataclass 에
주입하는 시점이 declare_parameter 이후라 정상 갱신되는 것 맞지만, 어딘가 snapshot
복사가 default 만 가져오는 듯. 본 작업 범위 밖 — 추후 디버깅.

### 3.6 [[feedback_dont_touch_working_code]] / [[feedback_relative_path_convention]] 정합

- 기존 OpServerNode `_on_X_state` 콜백에 한 줄 추가만 (기존 동작 유지)
- `_drain_serving_queue` 는 신규 메서드 — 기존 serving_queue 관리 그대로 사용
- mode_orchestrator 수정 없음
- 절대경로 / cabot 잔재 0건

## 4. 빌드 / 테스트 명령

```bash
# 빌드 (moca_opserver 만)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  colcon build --packages-select moca_opserver --symlink-install
'

# 단위 테스트 (38건)
source install/setup.bash
python3 -m pytest src/moca_opserver/test/test_completion_and_timer.py -v

# 전체 회귀 (130건)
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/moca_opserver/test/test_completion_and_timer.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py

# 자동 사이클 통합 스모크 (Nav2 부재, ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1)
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 run dobi_npc_bringup mode_manager &
ros2 run moca_opserver opserver_node --ros-args -p patrol_interval_minutes:=0.167 &
# 10초 후 자동 patrol → 1초 후 done → 1초 dwell → idle → 10초 후 cycle 2
```

## 5. 디자인 §10 미해결 이슈 결정 사항

| # | 이슈 | 결정 | 본 회고에서 |
|---|---|---|---|
| G3 | guiding 중 serving 선점 | (b) 큐잉만 (운영 정책 우선) + idle 진입 시 자동 drain | ✅ 구현 |

API spec §9:

| # | 이슈 | 결정 | 본 회고에서 |
|---|---|---|---|
| O1 | FastAPI + rclpy executor | (a) 별 thread (기존) | 변경 없음 |
| O2 | SetMode async timeout | (a) 2s 후 INTERNAL_ERROR (기존) | 변경 없음 |

## 6. 다음 단계

### 6.1 즉시

- 회고 + 백업 + 커밋 (오늘 6번째 마무리 사이클)
- engaging completion 시그널 wiring (M3) — `/bt/result` 또는 별 토픽

### 6.2 라이브 통합 검증

- ultralytics 설치 결정 시 patrol detector 실 YOLO + Gazebo 5 테이블 사이클
- mode_manager + opserver + nav2 + Gazebo 전체 stack 자동 사이클 검증
  (현 통합 스모크는 Nav2 부재 환경 — Nav2 정상 동작 시 5 테이블 sweep 시간 ~90s
  예상)
- POS/OpenARM stub 으로 `/pickup`, `/guide` REST 시나리오 검증

### 6.3 M3 진입

- Web Dashboard (`moca_web_dashboard_spec.md` 수령 후) — 6 페이지 (dashboard / modes
  / tables / events / analytics / settings) + 11종 WS broadcast 시각화
- API spec §9 미해결 O3-O5 (KPI sqlite, event_log 영속화, 권한 차등)
- patrol priority_only sweep_mode 실 구현 (OpServer table_registry 가 정렬해서
  params_json 으로 patrol_scheduler 에게 전달)
- guiding G1-G2 (TF projection + ID tracking)
- engaging completion 시그널 (BT 측 publisher 추가 또는 mode_manager 가 launch
  child process exit 감지)

## 7. 메모리 갱신

본 작업으로 추가할 메모리 없음 — 모두 디자인 문서 따름 + 새 함정 발견 없음.

기존 메모리 정합:
- `[[feedback_dont_touch_working_code]]` ✅
- `[[feedback_relative_path_convention]]` ✅
- `[[project_navigation_code_separation]]` ✅ (opserver 가 직접 cmd_vel 발행 X)

---

*다음 갱신: 라이브 통합 검증 또는 M3 Web Dashboard 진입 후*
