# Approach Nav2 통합 사전 — cmd_vel watcher + dummy goal race 발견 + 안전 패치

**작성일**: 2026-05-04 (오후 트랙)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 체크리스트**: `docs/rpi_integration_checklist.md` §4.2 + §5 위험
**상태**: cmd_vel safety watcher + Approach `allow_dummy_goal` 안전 가드 + race condition 라이브 재현. **이동 테스트는 vic_pinky 충전 종료까지 보류** (사용자 명시).

---

## 0. 시작 컨텍스트

오전 트랙(`2026-05-04_rpi_first_contact.md`)에서:
- vic_pinky RPi 5(192.168.0.138) ↔ 노트북(192.168.0.154) 도메인 22 통신 확립
- `run_vic_bringup.sh` / `stop_vic_bringup.sh` 스크립트 + SafetyCheck `/battery_state` 라이브 검증 완료

오후 트랙 목표: **체크리스트 §4.2 Approach Nav2 통합 사전 안전망** — Test 2(이동 가능 환경 + Nav2 stack live)에 진입하기 전에 모든 안전 장치 준비.

도중 사용자 지시: **"절대 이동 테스트 금지 — vic_pinky 충전 중"** → Test 2는 보류, 사전 검증 + 안전 패치까지 완료.

---

## 1. 작업 흐름

### Step 1: cmd_vel safety watcher (`scripts/cmd_vel_watch.py`)

표준 ROS2 Python 노드 패턴:
- `/cmd_vel` (Twist) 구독 (RELIABLE QoS, depth 10)
- 임계값 (linear|angular) 초과 시 **TRIP** 로그 + `--kill-on-trip` 옵션으로 RPi bringup SSH KILL
- 5초 주기 요약: total/zero/nonzero/peak
- 종료 시 FINAL 통계

**자체 검증** (합성 publish):
- zero twist 5회 → `total=5 zero=5 TRIPPED=False`
- non-zero 0.20m/s → `TRIP: linear=0.200m/s (>=0.05)` 발동
- peak tracking + final summary

`--kill-on-trip` 끈 모드로 라이브 검증 시 백그라운드 모니터, 켠 모드로 본격 Nav2 통합 시 비상 정지.

### Step 2: Test 1A — 첫 시도, race 발견

**환경**: RPi `vicpinky_bringup` 종료 + dev_all + fake_customer_publisher (1Hz, 3.0m).

**결과**:
```
[Approach] /customer_pose 미수신 + goal_pose 미연결 → 더미 (1.0, 0.0)
[Approach] Nav2 'navigate_to_pose' 서버 미발견 (1.0s). BT 단독 fallback
```

→ Approach가 `/customer_pose` 미수신으로 봐서 **dummy goal 경로** 진입.

**원인**: ROS2 publisher 기본 QoS가 `VOLATILE` — 늦게 join한 subscriber는 과거 메시지 못 받음. fake_customer 1Hz publish + dev_all 1.5s warmup의 timing race로 첫 BT 사이클 Approach `onStart`에 메시지 안 도달.

### Step 3: Test 1B — fake_customer 10Hz + 충분한 warmup

**환경**: fake_customer rate를 10Hz(period=0.1)로, dev_all 시작 4초 전부터 publish.

**결과** (두 BT 사이클 모두 캡처):
```
Cycle 1 (T+0.1s after BT load, race 패배):
  [Approach] /customer_pose 미수신 + goal_pose 미연결 → 더미 (1.0, 0.0)
  [Approach] Nav2 ... 서버 미발견 → fallback

Cycle 2 (T+15s, fake_customer 정상 도달):
  [Approach] Proxemic goal: customer(3.00,0.00) dist=3.00m → goal(1.50,0.00) social=1.50m
  [Approach] Nav2 ... 서버 미발견 → fallback
```

**검증된 항목**:
- BT 등록 9 user + 41 builtin
- Proxemic 수식: `cx + (-cx/dist)*social = 3 + (-1)*1.5 = 1.5` 정확
- Nav2 fallback 1초 timeout
- watcher: `/cmd_vel total=0` (이동 신호 0건)

### Step 4: 안전 패치 — `approach.hpp` `allow_dummy_goal`

**문제 정의**: Test 1B의 Cycle 1에서 발생한 dummy goal 경로가 **Nav2 stack 살아있을 때**:
- Approach가 (1.0, 0.0)을 NavigateToPose action으로 송신
- Nav2 plan + drive → vic_pinky 1m 무계획 이동
- 체크리스트 §5 위험 시나리오 그대로

**패치 설계**:
```cpp
BT::InputPort<std::string>(
    "allow_dummy_goal", "false",
    "/customer_pose 미수신 + goal_pose 미연결 시 더미 (1.0, 0.0) Nav2 송신 허용. ...")
```

`onStart()` 내 dummy 분기 진입 직전 가드:
```cpp
if (!goal_valid) {
  std::string allow_dummy_str = "false";
  getInput("allow_dummy_goal", allow_dummy_str);
  const bool allow_dummy =
      (allow_dummy_str == "true" || allow_dummy_str == "1" || ...);
  if (!allow_dummy) {
    RCLCPP_WARN(...);
    no_nav2_fallback_ = true;
    return BT::NodeStatus::RUNNING;
  }
  // ... 기존 dummy 송신 경로 (allow_dummy=true 시에만) ...
}
```

**왜 string port인가**: BT.CPP의 `InputPort<bool>("port", "false", ...)` 기본값 파싱 버그 우회. 실측 `"false"` 문자열이 `true`로 인식됨 (Test 1C 1차 시도에서 발견). string port + 수동 변환으로 명시적 처리.

### Step 5: Test 1C — 패치 검증

**환경**: dev_all (fake_customer 없음 → goal_valid=false 강제, BT XML도 allow_dummy_goal 미지정 → 기본 false 적용 기대).

**결과**:
```
[Approach] goal_valid=false (customer_pose/goal_pose 미연결).
  allow_dummy_goal='false' (false) → Nav2 송신 스킵, fallback SUCCESS.
```

- WARN 1회만 (Reactive Fallback 사이클이 다시 올 때마다 동일 메시지)
- watcher: `/cmd_vel total=0`
- BT funnel은 Approach SUCCESS 후 다음 단계(IceBreak 등)로 정상 진행

→ **dummy goal Nav2 송신이 영구 차단됨**. allow_dummy_goal=true로 BT XML 수정 시에만 dummy 송신 허용 (dev/시뮬용).

---

## 2. 핵심 학습

### Race condition을 라이브 재현 — W2 회고가 옳았다

W2 회고 §3에서 경고된 시나리오 ("Approach가 /customer_pose 미수신 시 dummy 좌표 사용 → vic_pinky가 랜덤 방향으로 1m 이동")가 본 트랙에서 **첫 BT 사이클**에 라이브 재현됨. ROS2 default QoS의 알려진 특성:

| QoS 속성 | 영향 |
|---|---|
| reliability=RELIABLE | publisher가 모든 subscriber에게 도달 보장 |
| durability=VOLATILE (기본) | **늦게 join한 subscriber는 과거 메시지 못 받음** |
| history=KEEP_LAST(10) | 큐 크기 |

`/customer_pose` publisher가 default QoS면 늦게 시작한 Approach subscriber는 첫 publish를 놓침 → has_customer_pose_=false → dummy goal 경로.

**해결책 (영구)**: 안전 패치 (allow_dummy_goal=false 기본)
**해결책 (보너스)**: fake_customer를 transient_local QoS로 변경 — Phase 2 GEFA 교체 시 함께 정리

### BT.CPP `InputPort<bool>` 기본값 파싱 버그 우회

`BT::InputPort<bool>("name", "false", "desc")` — default string `"false"`가 BT.CPP의 `convertFromString<bool>`을 통과할 때 `true`로 파싱됨 (실측). 정확한 BT.CPP 버전 동작은 미확인이지만, 본 워크스페이스의 `ros-jazzy-behaviortree-cpp 4.8.3-1noble`에서 재현됨.

**우회**:
```cpp
BT::InputPort<std::string>("name", "false", "desc")  // string으로 받고
std::string s = "false"; getInput("name", s);
const bool b = (s == "true" || s == "1" || ...);     // 수동 변환
```

장점:
- BT.CPP 버전 의존성 제거
- 명시적 — "허용 값" 목록을 코드에서 직접 보임
- BT XML의 `allow_dummy_goal="..."` 표기가 string으로 직관적

단점: 다른 bool 포트도 같은 패턴 적용 검토 (현재 다른 곳엔 없음)

향후 다른 bool 포트 추가 시: 같은 string + 수동 변환 패턴 사용 권장. CLAUDE.md §5 표준 코드 패턴에 추가 검토.

### 안전 가드의 명시성 — log message에 raw 값 노출

WARN/INFO 메시지에 `allow_dummy_goal='%s'` 형태로 **실제 받은 string 값**을 포함. 이로써:
- 운영자가 BT XML 설정 실수 즉시 파악 (예: `"True"` vs `"true"`)
- 의도하지 않은 default fallback 디버깅 쉬움

이전 Phase 2 W4 hysteresis 트랙에서도 같은 원칙 — **현재 상태를 로그에 raw로 노출**.

### 이중 안전 — 코드 가드 + 외부 모니터

| 안전 층위 | 메커니즘 |
|---|---|
| L1: 코드 (Approach) | allow_dummy_goal=false → dummy goal Nav2 송신 차단 |
| L2: 코드 (Approach) | `/customer_pose` 거리 < 1.0m abort (W2 Step D) |
| L3: 외부 (cmd_vel_watch) | /cmd_vel 임계 초과 → `--kill-on-trip`으로 RPi bringup KILL |
| L4: 물리 | 사용자 비상 정지 / 충전 중엔 모터 단절 |

L1+L2는 **소스에서 차단** — 의도하지 않은 cmd_vel 자체가 발생 안 함. L3는 **하류에서 차단** — 어떤 경로로든 cmd_vel이 나오면 즉각 중단. L4는 최후 보루.

본 패치 후 vic_pinky가 충전 종료된 상태에서 §4.2 Test 2 진입할 때 L1+L3 동시 가동 권장.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **첫 BT 사이클 race가 실재**: 의심되던 시나리오 라이브 재현. 향후 Approach 안전 가드의 정당성 입증.
- **Proxemic 수식 정확**: customer (3, 0) + social 1.5 → goal (1.5, 0). `cx + (-cx/dist)*social` 공식 검증.
- **BT.CPP `InputPort<bool>` 기본값 파싱 의심 동작**: `"false"` → `true`. 워크어라운드 적용. (본 워크스페이스 BT.CPP 4.8.3 환경 한정 검증)
- **vic_pinky 충전 시 RPi 네트워크 끊김**: ping 100% loss. 충전 도크와 RPi 주 전원 분리 가능성. 운영 정책 검토 필요.
- **Watcher의 RELIABLE QoS**: vic_pinky bringup이 `/cmd_vel` reliable subscriber면 충돌 없음. Nav2의 velocity_smoother도 통상 reliable. 본 환경에선 안전.

### 위험 요소

- **Test 2 (Nav2 stack live) 미수행**: 충전 종료까지 보류. 충전 끝나면:
  1. RPi 네트워크 복구 확인
  2. `bash scripts/run_vic_bringup.sh`
  3. **사용자 명시 OK** (이동 가능 환경)
  4. cmd_vel_watch `--kill-on-trip` 백그라운드
  5. RPi에서 `vicpinky_navigation` Nav2 stack 시동
  6. dev_all + fake_customer (10Hz, 3.0m)
  7. `[Approach] goal accepted` + watcher CLEAN 또는 TRIP 시 즉시 KILL
- **첫 사이클 race는 안전 패치로 차단됐지만, 합성 시나리오는 여전히 가능**: 누군가 BT XML에서 `allow_dummy_goal="true"`로 명시 설정하면 위험 부활. `cafe_funnel_v1.xml`엔 의도적으로 미지정 (default false 활용).
- **fake_customer transient_local 미적용**: 첫 사이클 race를 Approach 코드에서 가드했지만 fake_customer 자체는 그대로. 다른 노드(예: 향후 GEFA gate)도 같은 race 가능. fake_customer가 임시 노드라 우선순위 낮지만 회수 작업 후보.

### 갭

- **체크리스트 §4.2 Test 2 미완**: 충전 종료 + 사용자 OK 후 진행. 현 트랙은 사전 안전망까지.
- **watcher 기능 확장**: `/odom` velocity 모니터 추가 가능 (cmd_vel은 명령, odom은 실 동작). 이중 모니터로 명령-동작 불일치 감지.
- **단위 테스트 부재**: Approach onStart 분기들의 단위 테스트 없음. BT.CPP의 dummy ROS context로 테스트 가능. CLAUDE.md TODO §3에 이미 등록됨 (BT 단위 테스트 골격).
- **persona별 allow_dummy_goal 정책**: 현재 글로벌 BT XML 한 줄. 페르소나별 customer pose 임계 다르면 페르소나 YAML로 분리 검토 (현재 우선순위 낮음).

---

## 4. 다음 일정

### 충전 종료 후 (사용자 OK 시)

1. **§4.2 Test 2**: Nav2 stack live + watcher `--kill-on-trip` + 안전 패치 적용 상태에서 cafe_funnel 1 사이클 통합. Approach `goal accepted` 로그 + 정상 Proxemic 경로 도달 후 cmd_vel 거동 모니터.
2. **§4.3 cafe_funnel 1 사이클**: 15~20초 funnel 정상 진행 측정 (utter_done 박자 + face/utter sync 라이브 재확인).
3. **§4.4 abort 카메라**: hysteresis 5프레임 ON/OFF 실 표정으로 검증.

### 즉시 가능 (충전 무관)

- **YAML 스키마 jsonschema** (CLAUDE.md TODO)
- **BT 단위 테스트 골격** (CLAUDE.md TODO)
- **fake_customer transient_local QoS** 보너스 (선택)
- **watcher /odom velocity 모니터 확장**

---

## 5. 산출물 위치

### 신규 파일
- `scripts/cmd_vel_watch.py` (실행권한, 6167 bytes)
- `docs/daily/2026-05-04_approach_safety_patch.md` (본 회고)

### 수정 파일
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/approach.hpp` (allow_dummy_goal 안전 가드 + 헤더 주석 갱신)

### 변경 없음
- `bt_xml/cafe_funnel_v1.xml` — Approach 노드 새 포트 미지정 → default `"false"` 활용 (안전 by default)
- 다른 BT 노드, 메시지, persona YAML, dobi_npc 코드

### 검증 명령어 (재현용)

```bash
# Watcher 자체 검증
python3 ~/moca/scripts/cmd_vel_watch.py --linear-thresh 0.05 --angular-thresh 0.05 &
WPID=$!
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.20, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
sleep 1
# 기대: TRIP linear=0.200
kill -INT $WPID

# 안전 패치 검증 (RPi 미연결 + fake_customer 없음)
ros2 launch dobi_npc_bringup dev_all.launch.py fullscreen:=false &
sleep 18
# 기대 라인: [Approach] goal_valid=false ... allow_dummy_goal='false' (false) → Nav2 송신 스킵
pkill -INT -f "ros2 launch dobi_npc_bringup"

# Proxemic 검증 (fake_customer 10Hz)
ros2 run dobi_npc_bringup fake_customer_publisher \
  --ros-args -p customer_x:=3.0 -p publish_period_sec:=0.1 &
sleep 4
ros2 launch dobi_npc_bringup dev_all.launch.py fullscreen:=false &
sleep 25
# 기대 라인: [Approach] Proxemic goal: customer(3.00,0.00) dist=3.00m → goal(1.50,0.00)
```

---

**상태**: §4.2 사전 안전망 완료. Test 2는 충전 종료 + 사용자 OK 후 즉시 진행 가능 — 모든 가드(L1 코드 / L3 watcher) 준비됨.
