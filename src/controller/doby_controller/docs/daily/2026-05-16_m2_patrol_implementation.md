# 2026-05-16 — M2 Patrol 본격 구현 (Phase M2 W1+W2 묶음)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m0_m1_5state_opserver_scaffold.md` (M0+M1),
>             `docs/daily/2026-05-16_relative_path_convention.md` (절대경로 제거)
> 선행 문서: `docs/moca_patrol_design.md` v1.0
> 다음 진행: M2 guiding (`moca_guiding_design.md` 수령 후) 또는 OpServer
>           CompletionWatcher + PatrolScheduler 5분 타이머

---

## 1. 오늘의 목표

`moca_patrol_design.md` 의 §15 권장 작업 순서대로 patrol 모드를 본격 구현.
M1 단계의 `mode_stack_stub` placeholder 를 실 노드로 교체. 디자인 문서 §6 의
M2 W1 (scheduler skeleton) + W2 (detector 실 구현) 를 하루에 묶어 진행.

## 2. 산출물

### 2.1 신규 서비스 (`dobi_npc_msgs/srv/ScanTable.srv`)

`patrol_scheduler ↔ table_occupancy_detector` 통신용 서비스.
디자인 §3.3 명세 그대로:
```
string table_id
---
bool success
string occupancy             # "empty" | "occupied" | "finished" | "unknown"
uint8 person_count
bool dishes_detected
float32 confidence
string error
```

**중요 발견**: M0 단계에서 누락된 신규 srv. 마스터 계획서 §4.2/§4.3 의 5 msg + 2 srv
목록에 없었지만 patrol 구현에 필수. 디자인 §3.3 의 "M0 작업 시 함께 추가" 주의 누락 케이스.

CMakeLists.txt 등록 + 빌드 통과 (15.8s). `ros2 interface show` 정상.

### 2.2 patrol_scheduler_node.py (신규)

위치: `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/patrol_scheduler_node.py`

**핵심 책임** — mobility orchestration:
- tables.yaml 로드 (home_pose + tables) — `_dict_to_pose` 헬퍼는 dispatcher 패턴 차용
- 9-state FSM: `INIT → NEXT ⇄ (MOVING → DWELL → SCAN → REPORT) → RETURNING → DONE`
- ABORTED 경로 (rapport abort_trigger)
- Nav2 NavigateToPose action client + ScanTable.srv client
- `/patrol/state` 1Hz publish + `/patrol/table_report` 이벤트 publish
- approach_dist 후방 offset 계산 (`x - approach * cos(yaw)`)

**FSM 구현 디테일**:
- `_transition(new_state)` 가 prev != new 인 경우만 entry action 호출 (자기 자신 무시)
- INIT 의 entry 는 `__init__` 안 `_load_tables()` 직후 NEXT 전이 (디자인 §2.3)
- DWELL 은 entry action 없음 — `_tick` (20Hz) 가 elapsed 체크
- SCAN 는 `cli_scan.call_async` + done_callback → REPORT 전이
- MOVING 의 `arrival_timeout` (default 30s) 만료 시 unknown report + NEXT skip
- SCAN service hang (5s 미응답) fallback → REPORT unknown

**DONE/ABORTED 의 self-terminate X** — 디자인 §8 P1 (b) 채택:
- `/patrol/state` 계속 publish 하면서 OpServer CompletionWatcher 가
  관찰 후 `SetMode('idle')` → mode_manager SIGTERM
- 다른 활동 모드 (serving/guiding/engaging) 와 일관된 책임 분리

**Nav2 callback 체인**:
```
send_goal_async → _on_nav_accepted (goal_handle.accepted 체크)
                ↓ get_result_async
                _on_nav_result (status: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED)
                ↓
                MOVING→DWELL / RETURNING→DONE / 실패→_handle_nav_failure
```

### 2.3 table_occupancy_detector_node.py (신규)

위치: `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/table_occupancy_detector_node.py`

**핵심 책임** — perception 서비스 서버:
- `/camera/image_raw` 구독 → `_last_frame` cache + `_last_frame_ts`
- `/table_occupancy/scan` 서비스 응답 (호출 시점 1프레임 grab → YOLO → 분류)
- YOLO 분류 룰 (디자인 §3.2 그대로):
  - `person >= 1` → occupied
  - `person == 0 ∧ dishes` → finished (M3)
  - `person == 0` → empty
  - 프레임/모델 없음 → unknown

**Degrade gracefully 패턴**:
- `try: from ultralytics import YOLO; YOLO_AVAILABLE = True` 가드
- 미설치 환경에서도 노드 정상 기동 + 모든 응답 unknown + error=no_model 로 명확히 표시
- weights 파일 없음 / 로드 실패도 같은 경로
- `frame_stale_sec=2.0` — cache 가 너무 오래되면 unknown + error=stale_frame
- inference 예외 → success=False + error=inference_error:<type>

**YOLO weights 경로 — workspace_root 추정 + env**:
- `_find_workspace_root()` 패턴 ([[feedback_relative_path_convention]] 정합)
- `MOCA_YOLO_WEIGHTS` env var override 지원
- 기본 fallback `<ws>/models/yolo/yolov8n.pt`

### 2.4 mode_patrol.launch.py (M1 stub → M2 실 노드 교체)

- detector 먼저 spawn (서비스 ready 보장)
- scheduler 가 detector wait_for_service 시점에 이미 떠있음
- launch args: `params_json`, `image_topic`, `dwell_per_table_sec`, `arrival_timeout_sec`

### 2.5 setup.py entry_points 추가

```python
'patrol_scheduler = dobi_npc_bringup.patrol_scheduler_node:main',
'table_occupancy_detector = dobi_npc_bringup.table_occupancy_detector_node:main',
```

### 2.6 단위 테스트 (`test_patrol_scheduler.py` + `test_table_occupancy_detector.py`)

**26 tests / 0 failures** (pytest 10.46s).

scheduler 16건:
- tables.yaml 로드 + sweep_order filter (yaml 에 없는 ID 제거)
- approach_pose 후방 offset 계산
- FSM 전이 (INIT→NEXT→MOVING, sweep 소진 → RETURNING, RETURNING SUCCEEDED→DONE)
- Nav2 callback (SUCCEEDED → DWELL, ABORTED → unknown + NEXT)
- scan_done with result / exception
- rapport abort_trigger → ABORTED (DONE/ABORTED/INIT 에서는 무시)
- home_pose 없음 → 즉시 DONE
- State enum value 정합 (디자인 §2.2)

detector 10건:
- 프레임 없음 / 모델 없음 / frame stale → unknown + 명시적 error
- mock YOLO 1 person → occupied + conf
- mock YOLO 3 persons → occupied + max conf
- 0 persons → empty + default 0.9 conf
- inference exception → success=False + error=inference_error
- 빈 results list → empty (None handling)
- frame_age helper

**테스트 전략**: ROS Node 실 인스턴스 + 외부 의존(Nav2/Image) MagicMock.
`_send_nav_goal` 의 `wait_for_server(2.0)` 가 blocking + 즉시 실패 → 다음 state 로
빠지는 함정 발견 → fixture 에서 `act_nav` MagicMock 으로 교체 + send_goal_async 가
idle future 반환 → state 가 MOVING/RETURNING 에서 callback 대기.

### 2.7 통합 스모크 결과

Nav2 부재 환경 (시뮬 도메인 99 + LOCALHOST_ONLY=1):
- 5 테이블 sweep 완주: `init → next → moving → next → ... → returning → done`
- 각 테이블 `TableReport(occupancy='unknown', reason='nav_server_unavailable')` 발행
- `/patrol/state` 1Hz 정상
- detector ultralytics 미설치 → `unknown` 응답 + log: "ultralytics 미설치 — pip install --user ultralytics"
- 사이클 완료 후 self-terminate X, "OpServer SetMode("idle") 대기" 로그 (디자인 §6.1)

전체 회귀 (orchestrator 41 + patrol 26) = **67/67 PASS** (9.18s).

## 3. 발견 / 결정

### 3.1 P1 (scheduler self-terminate 시점) → (b) DONE 유지 채택

디자인 §8 미해결 이슈 P1 의 두 옵션:
- (a) DONE 진입 5초 후 자동 self-terminate
- (b) OpServer 가 SetMode('idle') 호출까지 대기

(b) 채택. **이유**: serving/guiding/engaging 도 같은 패턴 (활동 모드가 자기 종료 안 함,
OpServer CompletionWatcher 가 외부 조율). 일관된 책임 분리. `/patrol/state="done"`
계속 publish 하면 OpServer 가 1초 dwell 후 `SetMode('idle')` 호출 → mode_manager
SIGTERM → scheduler/detector 정상 종료.

이 결정은 OpServer M2 작업의 CompletionWatcher 구현 시점에 라이브 검증 필요.

### 3.2 ScanTable.srv 누락 — M0 의 미발견

마스터 계획서 §4.2 는 5 msg + 2 srv (GetTableStatus, SetPatrolSchedule) 만 정의.
ScanTable.srv 는 patrol_design 문서 §3.3 안에 정의됐지만 마스터/M0 체크리스트에
누락. **교훈**: 다음 mode design 문서 (guiding) 도 신규 srv/msg 정의가 본문 안에
있을 가능성 — 진입 시 grep 으로 사전 점검 권장.

### 3.3 ultralytics 미설치 환경 — degrade gracefully 패턴 검증

CLAUDE.md §7 외부 의존성 정책에 ultralytics 미언급. 시스템에 미설치. 본 작업에서
`try/except ImportError + YOLO_AVAILABLE` 가드로 처리 → detector 노드는 정상 기동
+ 모든 응답 unknown + 명시적 error="no_model". 사용자가 결정 시점에
`pip install --user ultralytics` 하면 자동 활성화. M3 진입 또는 실 라이브 검증 시점.

본 패턴은 다른 perception 노드 (guiding 의 person tracker 등) 에도 재사용 가능.

### 3.4 install 트리 stale (재빌드 필요한 경우)

새 console_scripts entry_point 추가 + 새 파이썬 파일 추가 후 colcon build 1회로는
install/<pkg>/lib/<pkg>/ 의 entry script 가 미반영되는 경우 발견. 해결:
`rm -rf build/<pkg> install/<pkg>` 후 clean rebuild → symlink-install 정상.

`install/<pkg>/lib/python3.12/site-packages/dobi-npc-bringup.egg-link` 가 `build/<pkg>`
를 가리키는 develop 모드. build 디렉토리의 모듈 = src 의 hard link (inode 동일).
src 변경 → 즉시 반영이지만 새 파일 추가 시는 한 번 rebuild 필요.

### 3.5 [[feedback_dont_touch_working_code]] 정합

- 기존 `serving_dispatcher_node.py` 의 `_dict_to_pose` 헬퍼 패턴 차용 (재구현, 직접 호출 X)
- `mode_stack_stub` 도 보존 (다른 모드 stub 가능성 위해)
- `tables.yaml` 무수정
- 기존 launch 5종 (mode_engaging/guiding/serving/npc/follow) 무수정

### 3.6 [[feedback_relative_path_convention]] 정합

- detector 의 `_find_workspace_root()` + `MOCA_YOLO_WEIGHTS` env — face_avatar/minigame_runner
  와 동일 패턴
- mode_patrol.launch.py 의 `tables_yaml` 은 `FindPackageShare('dobi_npc_bringup')` 사용
- 절대경로 0건

## 4. 빌드 / 테스트 명령

```bash
# 빌드 (clean 권장 — 새 entry_points 적용)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  rm -rf build/dobi_npc_bringup install/dobi_npc_bringup
  colcon build --packages-select dobi_npc_bringup --symlink-install
'

# 단위 테스트 (orchestrator + patrol 합계)
source install/setup.bash
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  -v

# 통합 스모크 (Nav2 부재 환경 — sweep 완주 검증)
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_patrol.launch.py &
sleep 30
ros2 topic echo /patrol/state --once
ros2 topic echo /patrol/table_report  # 5 unknown report 확인

# 단일 SetMode 진입 (mode_manager 와 함께)
ros2 run dobi_npc_bringup mode_manager &
sleep 3
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
  "{requested_mode: patrol, params: ''}"
```

## 5. 디자인 §8 미해결 이슈 결정 사항

| # | 이슈 | 결정 | 시점 |
|---|---|---|---|
| P1 | scheduler self-terminate | (b) DONE 유지 + OpServer 조율 | 본 회고에서 결정 |
| P2 | dwell 중 skip_table | (a) M2 무시 | M3 OperatorCommand 통합 |
| P3 | YOLO weights 위치 | `models/yolo/yolov8n.pt` (workspace 추정) | 본 작업에서 결정 |
| P4 | LiDAR TF (M3) | 보류 | M3 |
| P5 | confidence 재시도 | (a) 그대로 보고 | 본 작업에서 결정 |
| P6 | 'finished' 임계 | dishes conf > 0.6 + 최근 1분 person=0 | M3 |
| P7 | priority_only sweep | params_json sweep_order override | 본 작업에서 구현 |

## 6. 다음 단계

### 6.1 즉시 (M2 마무리)

- **OpServer CompletionWatcher 구현**: `/patrol/state` 관찰 → "done" 1초 dwell →
  `SetMode('idle')` 호출. 다른 모드(serving/guiding/engaging) 도 같은 패턴.
  API spec §5.4 의 `DWELL_SEC = {'patrol': 1.0, ...}`.
- **OpServer PatrolScheduler 5분 타이머**: idle 5분 dwell + 영업시간 + 배터리 OK
  → 자동 patrol 트리거. API spec §5.2 `PatrolScheduler.tick()`.

### 6.2 M2 guiding (별 design 문서 수령 후)

- `guiding_controller_node` 신규 (follow 와 알고리즘 정반대 — 로봇 앞장 + customer
  카메라 추적). FSM spec §2.4 50% 신규 코드.
- `mode_guiding.launch.py` 의 임시 follow stack 교체.

### 6.3 라이브 통합 검증 (Nav2 + Gazebo)

- 현 통합 스모크는 Nav2 부재 → 모든 TableReport unknown.
- 실 검증: Gazebo + nav2 + AMCL 후 patrol 진입 → 5 테이블 도착 + dwell + detector
  scan → occupancy 결과 확인. 이를 위해 ultralytics 설치 결정 필요.

### 6.4 M3 진입 전 보류

- priority_only sweep_mode 실 구현 (OpServer table_registry 가 정렬 후 sweep_order params 로 넘김)
- 식기 (dishes) custom YOLO weights
- LiDAR cluster ROI 보조
- skip_table operator command
- 실기 1주 운영 데이터 + sweep 평균 시간 < 90s 검증

## 7. 메모리 갱신 사항

본 작업으로 추가할 메모리 없음 (모두 디자인 문서대로 진행, 신규 함정 발견 없음).

기존 메모리 정합:
- `[[feedback_dont_touch_working_code]]` ✅
- `[[feedback_relative_path_convention]]` ✅ (detector workspace_root + env)
- `[[project_navigation_code_separation]]` ✅ (patrol_scheduler 가 `/cmd_vel*` 발행 안 함, Nav2 NavigateToPose action 만 사용)
- `[[feedback_freeze_gazebo_world_20260515]]` ✅ (무수정)
- `[[feedback_terminology_mogaek]]` — 본 회고 "모객" 무관 (patrol=순회, engaging=모객)

---

*다음 갱신: OpServer CompletionWatcher + PatrolScheduler 5분 타이머 구현 후,
또는 M2 guiding 진입 후*
