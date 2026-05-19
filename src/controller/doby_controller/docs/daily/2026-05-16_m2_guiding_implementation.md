# 2026-05-16 — M2 Guiding 본격 구현 (Phase M2 W3+W4 묶음)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m2_patrol_implementation.md`
> 선행 문서: `docs/moca_guiding_design.md` v1.0
> 다음 진행: OpServer CompletionWatcher + PatrolScheduler 5분 타이머 (M2 마무리)

---

## 1. 오늘의 목표

M2 guiding 본격 구현. M1 단계의 `mode_guiding.launch.py` 가 임시로 follow stack
(person_detector + follow_controller) 재사용 중이었음. 디자인 §1 의 "코드 재사용
< 30%" 원칙대로 신규 `guiding_controller_node.py` 작성 + launch 교체.

디자인 §8 의 M2 W3 (controller skeleton) + W4 (customer 추적) 를 하루에 묶어 진행.

## 2. 산출물

### 2.1 GuidingState.msg 확장 (M0 부족분 보완)

**M0 단계 (5월 16일 오전)**: 6 필드 — current_state, target_table, customer_id,
distance_to_target, distance_to_customer, customer_in_sight.

**M2 확장 (본 회고)**: 11 필드 — 5 신규 + state value 통일:
- `customer_lag_m`: 로봇 진행방향 기준 뒤처짐 (양수=뒤, 음수=앞)
- `customer_last_seen`: 마지막 bbox 감지 Time
- `progress`: 0.0~1.0 (M3 정밀화)
- `started_at`: 진입 Time
- `last_utter_text`: 마지막 발화 (debug)
- `current_state` 값: `init/lock_on/moving/waiting/arrived/done/aborted` (7 state)

**M0 누락 사유**: M0 단계에서 정의한 GuidingState 는 마스터 계획서 §4.2 의
필드만 따랐고 guiding_design 문서를 그 시점에 읽지 않았음. 디자인 §2.2.1 의 풀
스펙은 M2 진입 시점에서 발견. 동일 함정이 ScanTable.srv (M2-patrol) 에서도 발견됨.

**교훈**: mode design 문서 (patrol/guiding/web) 는 본문 안에 신규 msg/srv 정의
가 들어가는 경우가 있다. 마스터 계획서의 msg/srv 목록과 별개로 design 진입 시
grep 으로 사전 점검 필요.

### 2.2 guiding_controller_node.py (신규 553줄)

위치: `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/guiding_controller_node.py`

**핵심 책임** — supervised navigation:
- target_table + customer_id JSON params 파싱 + tables.yaml 검증
- 7-state FSM: `INIT → LOCK_ON → MOVING ⇄ WAITING → ARRIVED → DONE (+ ABORTED)`
- 카운터 앞 customer person bbox lock-on (10s timeout)
- Nav2 NavigateToPose 로 target_table 진행
- 카메라로 customer 추적 + lag 계산 (1.5m 초과 → WAITING, 1.0m 미만 복귀 → MOVING)
- customer_lost > 8s → ABORTED ("어디 가셨어요" 발화)
- 도착 후 5s dwell → DONE (OpServer SetMode('idle') 대기, patrol/serving 과 일관)

**follow_controller 와 알고리즘 정반대**:
- follow = 손님이 앞장, 로봇이 reactive 추적 (P-제어 + /cmd_vel 직접)
- guiding = 로봇이 앞장, 손님 supervised 추적 (Nav2 + lag 모니터)
- 코드 재사용: bbox 처리 휴리스틱 (가장 큰 bbox = 최근접 사람) 만 동일 패턴

**핵심 알고리즘 3종**:
1. lag 계산 — `lag = -dot(customer - robot, (target - robot).normalized())`.
   양수=뒤처짐, 음수=앞섬.
2. Customer lock-on — 가장 큰 bbox 가 customer. M3에서 BYTE-track ID 추적으로 정밀화.
3. Ground projection — M2 휴리스틱 (로봇 뒤 1m). 디자인 §7.1 의 한계 명시 — M3에서
   TF + camera_info + bbox 하단 ray projection 으로 정밀화.

### 2.3 UtterRequest 통합 (★ 디자인과 실측 정합)

디자인 §5.1 의 priority 7/8/9 (높을수록 우선) 가정은 **실 UtterRequest 와 반대**.
실 메시지는 `0=safety / 10=operator / 20=serving / 30=npc / 255=lowest` (낮을수록
우선) 정책.

**본 구현 채택**:
- `GUIDING_UTTER_PRIORITY_NORMAL = 25` (operator < guiding < serving)
- `GUIDING_UTTER_PRIORITY_URGENT = 15` (ABORTED "어디 가셨어요" — operator 와 비슷한 긴급도)
- `source='guiding'`, `preempt=False`

**face_expression 동기** — UtterRequest 의 `face_expression` 필드에 직접 채워서
tts_node 가 face/utter 동기 처리. 별도 `/face_avatar/expression` 발행 X
(디자인 §2.1.3 의 `/set_emotion` + EmotionState.expression 가정은 잘못된 가정).

### 2.4 8 어휘 face_expression 매핑

디자인 §5.3 의 `neutral/happy/sad/confused` → CLAUDE.md §4.2 의 실 자산 8 어휘
(`basic/hello/happy/fun/interest/bored/sad/angry`) 로 매핑:

```python
FACE_BY_STATE = {
    State.LOCK_ON: 'basic',
    State.MOVING:  'happy',
    State.WAITING: 'interest',   # confused → interest (호기심/주의 환기)
    State.ARRIVED: 'happy',
    State.ABORTED: 'sad',
}
```

CLAUDE.md §4.2 의 vicpinky_emotion/emotion/*.gif 8 어휘 자산 우선 (기존 face_avatar
인프라 그대로 재사용).

### 2.5 mode_guiding.launch.py (M1 임시 → M2 실 노드 교체)

M1 단계: person_detector + follow_controller (임시 stub) 2 노드.
M2 단계: person_detector + **guiding_controller (신규)** 2 노드.

- follow_controller 제거 — guiding 은 cmd_vel 직접 발행 안 함 (Nav2 책임)
- person_detector 는 그대로 (Detection2DArray on /robot_cam/persons)
- launch args: params_json, persons_topic, image_topic

### 2.6 setup.py entry_point 추가

```python
'guiding_controller = dobi_npc_bringup.guiding_controller_node:main',
```

### 2.7 단위 테스트 (`test_guiding_controller.py`)

**25 tests / 0 failures** (pytest 16.32s).

커버리지:
- 입력 검증 3: tables.yaml load, invalid target_table → ABORTED, approach pose backward offset
- FSM transition 6: lock_on timeout, lock_on→moving, moving→aborted(lost), moving→waiting(lag), waiting→moving(lag recover), arrived→done
- Nav2 callback 3: SUCCEEDED→ARRIVED, ABORTED→ABORTED, CANCELED→state 유지(WAITING 진입)
- lag 계산 3: 양수(뒤처짐), 음수(앞섬), 데이터 없음=0
- rapport 3: abort_trigger→ABORTED, 기타 이벤트 무시, DONE/ABORTED/INIT 무시
- utter 3: face_expression 동기, cooldown 차단, FACE_BY_STATE 매핑 정합
- 거리 헬퍼 3: distance_to_customer, unknown, distance_to_target
- State enum sanity 1

**테스트 전략**: rclpy.init + 실 Node + act_nav MagicMock + Parameter override.
patrol 테스트와 동일 패턴.

### 2.8 통합 스모크 결과

Nav2 부재 환경 (ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1):

| 시나리오 | 결과 |
|---|---|
| invalid table_id (T99) → 즉시 ABORTED | ✅ `init→aborted`, utter [sad] prio=15 |
| valid T01 + LOCK_ON 10s timeout → ABORTED | ✅ `init→lock_on (basic prio=25) → aborted (sad prio=15)` |
| `/guiding/state` 1Hz 발행 (11 필드) | ✅ |

**ros2 CLI parameter 함정**: JSON 을 `ros2 run --ros-args -p params_json:='{...}'`
로 전달 시 YAML parser 가 `Couldn't parse parameter override rule` 에러. 해법:
**`ros2 launch ... params_json:='{...}'`** 사용 (ParameterValue 로 string 처리).

### 2.9 전체 회귀

**92/92 PASS** (24.68s) — orchestrator 41 + patrol_scheduler 16 + table_occupancy_detector
10 + **guiding_controller 25 (신규)**.

## 3. 발견 / 결정

### 3.1 디자인 vs 실측 정합 5가지

| 디자인 가정 | 실제 |
|---|---|
| `/person_detector/persons` (가정) | `/robot_cam/persons` (Detection2DArray, follow_controller 와 동일) |
| `/set_emotion` + EmotionState.expression | `/face_avatar/expression` (std_msgs/String) — 단 UtterRequest 의 face_expression 필드로 동기 발행 |
| utter priority 7/8/9 (높을수록 우선) | UtterRequest.priority 0=safety/10=op/20=serving/30=npc/255=lowest (낮을수록 우선) |
| 8 어휘 neutral/happy/sad/confused | CLAUDE.md basic/hello/happy/fun/interest/bored/sad/angry |
| GuidingState 6 필드 | 11 필드 (디자인 §2.2.1, M0 부족분) |

**교훈**: 디자인 문서가 실 코드보다 앞서 작성된 경우 (또는 따로 만든 경우) 인터페이스
가정이 실측과 어긋날 수 있다. 디자인 §15 권장 순서대로 "사전 정합성 확인" 단계를
넣어서 grep 으로 follow_controller 의 토픽/메시지 패턴을 먼저 확인하는 게 정석.

### 3.2 디자인 §10 미해결 이슈 결정

| # | 이슈 | 결정 | 시점 |
|---|---|---|---|
| G1 | customer ground projection 정확도 | (a) M2 휴리스틱 (로봇 뒤 1m) | 본 회고 |
| G2 | customer ID tracking | M3 (BYTE-track) | 본 회고 |
| G3 | guiding 중 serving 선점? | OpServer 책임 (controller 무관) | 본 회고. 본격 M2 마무리에서 다시 |
| G4 | customer_lost 후 처리 | (a) 5s dwell + OpServer idle (다른 모드와 일관) | 본 회고 |
| G5 | 안내 중 손님 변경 | (a) 첫 lock 유지 (M2: 매 프레임 최근접 갱신, M3 ID tracking) | 본 회고 |
| G6 | 다인 일행 | (a) M2 무시, 1명만 | 본 회고 |
| G7 | 손님 다른 방향 | (a) 무시 (Nav2 진행) + lost timeout 폴백 | 본 회고 |

### 3.3 ros2 CLI vs launch parameter 함정

본 작업에서 발견:
- `ros2 run <pkg> <node> --ros-args -p params_json:='{"k":"v"}'` → YAML parse 에러
- `ros2 launch <pkg> <launch.py> params_json:='{"k":"v"}'` → 정상 (ParameterValue str 캐스팅)

다음 회고 또는 메모리 추가 후보. 대형 JSON params 는 항상 launch 경유.

### 3.4 [[feedback_dont_touch_working_code]] 정합

- follow_controller_node.py 무수정 — guiding 은 별 노드로 작성
- mode_follow.launch.py 의 deprecation wrapper 그대로 유지 (이미 M1)
- person_detector 노드 (dobi_npc_emotion) 무수정 — guiding 가 그대로 구독
- tables.yaml 무수정

### 3.5 [[feedback_relative_path_convention]] 정합

- guiding_controller 가 tables_yaml 을 launch 의 FindPackageShare 로 받음
- 코드 안 절대경로 0건

## 4. 빌드 / 테스트 명령

```bash
# 빌드
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  colcon build --packages-select dobi_npc_msgs dobi_npc_bringup --symlink-install
'

# 단위 테스트
source install/setup.bash
python3 -m pytest src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py -v

# 전체 회귀
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py

# 통합 스모크 (Nav2 부재, lock_on timeout 검증)
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup mode_guiding.launch.py \
  params_json:='{"target_table":"T01","customer_id":"C-test"}'
# 10초 후 ABORTED 전이 + utter "어디 가셨어요"
```

## 5. 다음 단계

### 5.1 즉시 (M2 마무리 — OpServer)

본 회고들에서 결정한 "활동 모드 DONE 후 self-terminate X" 패턴은 OpServer 가
`SetMode('idle')` 을 호출해야 완결. 두 모듈 본격 구현:

- **CompletionWatcher** (API spec §5.4):
  - 4 활동 모드 (`serving/patrol/guiding/engaging`) 의 state 토픽 관찰
  - "done"/"arrived"/"aborted" 시그널 dwell (3/1/5/2s) 후 자동 `SetMode('idle')`
  - 현 opserver_node.py 의 `on_serving_state` / `on_patrol_state` 등 콜백 안에서
    호출하는 형태. 기존 patrol/guiding 의 DONE 유지 동작과 정합.

- **PatrolScheduler 5분 타이머** (API spec §5.2):
  - `/mode/state.current_mode == 'idle'` 5분 누적 + 영업시간 + 배터리 OK
  - 자동 `SetMode('patrol', {"sweep_mode":"all"})` 트리거
  - opserver_node 의 1Hz timer 에 추가. config_yaml 의 `patrol_interval_minutes`
    동적 갱신 가능.

### 5.2 M2 guiding 보강 (G3 결정 반영 — OpServer mode_orchestrator 분기)

디자인 §10 G3: guiding 중 serving 선점은 *큐잉만* (실 운영 정책상 안내 중 끊김
부적절). 현 orchestrator 는 priority 기반 선점 허용 — guiding(2) ← serving(1)
선점 가능. G3 결정 반영 시 분기 추가:

```python
if current_mode == 'guiding' and target_mode == 'serving':
    return queue_only()   # serving_queue 에만 추가, SetMode 호출 X
```

본 결정은 OpServer M2 마무리 작업과 함께.

### 5.3 라이브 통합 검증

- ultralytics 설치 결정 시 patrol detector 실 YOLO + Gazebo 5 테이블 사이클 실시간 확인
- Gazebo + nav2 + AMCL + person 시뮬레이터로 guiding G1~G5 시나리오 (디자인 §9.2)
- person_detector 가 실 화면에서 bbox 발행 → guiding_controller customer_xy 추정 정확도 평가

### 5.4 M3 진입 전 보류

- TF + ray projection ground projection (G1 정밀화)
- BYTE-track customer ID tracking (G2)
- 멀티 손님 (G6)
- 음성 인식 (디자인 §8.4)

## 6. 메모리 갱신 사항 (제안)

다음 메모리 추가 후보 — 별도 결정 필요:
- `[[feedback_ros2_launch_json_param]]` — JSON params 는 `ros2 launch` 경유 필수 (`ros2 run --ros-args -p ...:='{}'` YAML parse 에러)
- `[[feedback_design_spec_field_check]]` — design 문서 진입 시 신규 msg/srv 정의 사전 grep (M0 에서 ScanTable, GuidingState 5필드 누락 사고 2회)

기존 메모리 정합:
- `[[feedback_dont_touch_working_code]]` ✅
- `[[feedback_relative_path_convention]]` ✅
- `[[project_navigation_code_separation]]` ✅ (guiding 이 /cmd_vel* 발행 안 함, Nav2 NavigateToPose 만)
- `[[feedback_terminology_mogaek]]` — 본 회고는 "동행 안내" / "guiding" (모객 무관)

---

*다음 갱신: OpServer CompletionWatcher + PatrolScheduler 5분 타이머 구현 후*
