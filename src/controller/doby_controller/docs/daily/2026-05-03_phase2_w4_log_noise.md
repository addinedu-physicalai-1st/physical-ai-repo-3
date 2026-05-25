# Phase 2 W4 회고 — BT 로그 노이즈 정리 (FilteredCoutLogger)

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: 직전 회고 §2 학습 사항 (ReactiveFallback 로그 폭발) 해결
**상태**: BT::StdCoutLogger → 자체 FilteredCoutLogger 교체. IDLE 관련 toggle 노이즈 완전 제거. 검증/디버깅 부담 크게 감소.

---

## 0. 발견 → 해결

### 발견 (직전 트랙들의 누적 부담)
- 라이브 검증 시 한 발화 3초 동안 BT 로그가 60+ 라인의 `safety_alarm IDLE → FAILURE`, `emotion_alarm FAILURE → IDLE` toggle로 폭발
- abort/utter_done/stage 전이 같은 핵심 라인이 노이즈에 묻힘
- 검증 시마다 `grep -vE "..."`로 manual 필터링 필요

### 해결
**자체 logger 작성 — IDLE 관련 전이 자동 skip**.
- BT 4.x `StatusChangeLogger.enableTransitionToIdle(false)` 활용 → X → IDLE cleanup 자동 skip
- 추가로 `IDLE → FAILURE` (Condition tick의 정상 fail) 필터 → 매 tick 반복 노이즈 제거

---

## 1. 작업 흐름

### Step 1: BT 4.x StatusChangeLogger API 조사

`/opt/ros/jazzy/include/behaviortree_cpp/loggers/abstract_logger.h`:
- 베이스 클래스 `BT::StatusChangeLogger(TreeNode* root_node)`
- `virtual void callback(Duration, const TreeNode&, NodeStatus prev, NodeStatus status) = 0`
- **`enableTransitionToIdle(bool)` 메서드가 이미 존재** (기본 true)
- `setEnabled(bool)`, `setTimestampType(TimestampType)` 등 부가 기능

`bt_cout_logger.h`: StdCoutLogger가 같은 베이스 상속한 단순 구현.

### Step 2: FilteredCoutLogger 헤더 작성

`dobi_npc_bt/include/dobi_npc_bt/filtered_cout_logger.hpp`:

```cpp
class FilteredCoutLogger : public BT::StatusChangeLogger {
public:
  explicit FilteredCoutLogger(BT::TreeNode* root_node)
  : BT::StatusChangeLogger(root_node) {
    this->enableTransitionToIdle(false);  // X → IDLE 자동 skip
  }

  void callback(BT::Duration timestamp, const BT::TreeNode& node,
                BT::NodeStatus prev_status, BT::NodeStatus status) override {
    // ConditionNode의 "tick → 정상 FAILURE" 반복 noise 제거
    if (prev_status == BT::NodeStatus::IDLE &&
        status == BT::NodeStatus::FAILURE) {
      return;
    }
    // SUCCESS(alarm 발동)는 prev_status==IDLE이어도 출력
    auto sec = std::chrono::duration_cast<std::chrono::milliseconds>(
                 timestamp).count() / 1000.0;
    std::cout << "[bt " << std::fixed << std::setprecision(3) << sec << "] "
              << node.name() << ": "
              << BT::toStr(prev_status, true) << " -> "
              << BT::toStr(status, true) << std::endl;
  }

  void flush() override { std::cout << std::flush; }
};
```

핵심:
- `enableTransitionToIdle(false)` → FAILURE/SUCCESS → IDLE cleanup callback 자체가 호출 안 됨
- `prev==IDLE && status==FAILURE` → 추가 필터 (Condition tick fail 노이즈)
- `prev==IDLE && status==SUCCESS` → **출력 (alarm 발동!)** ← 핵심 보존 케이스

### Step 3: bt_executor 교체

```cpp
// 이전
#include "behaviortree_cpp/loggers/bt_cout_logger.h"
...
BT::StdCoutLogger cout_logger(tree);

// 변경 후
#include "dobi_npc_bt/filtered_cout_logger.hpp"
...
dobi_npc_bt::FilteredCoutLogger cout_logger(tree.rootNode());
```

CMakeLists.txt 변경 0건 (헤더만 추가).

### Step 4: 자체 검증 (bt_executor 단독 5초)

**비교 결과**:

| 항목 | 이전 (StdCoutLogger) | 현재 (FilteredCoutLogger) |
|---|---|---|
| `safety_alarm IDLE/FAILURE noise` | 100ms마다 4 라인 | **0** |
| 한 사이클(3초) 라인 수 | 60+ | ~10 |
| stage 전이 보존 | ✓ | ✓ |
| alarm 발동 (IDLE → SUCCESS) | ✓ | ✓ |
| RUNNING → SUCCESS/FAILURE | ✓ | ✓ |

**현재 출력 샘플**:
```
[bt ...] root_alarm_fallback: IDLE -> RUNNING
[bt ...] cafe_funnel: IDLE -> RUNNING
[bt ...] stage1_idle_scan: IDLE -> SUCCESS
[bt ...] stage2_approach: IDLE -> RUNNING
[bt ...] stage2_approach: RUNNING -> SUCCESS
[bt ...] stage3_ice_break: IDLE -> RUNNING
[WARN] [stage3_ice_break] timeout 10.1s → SUCCESS (forced)
[bt ...] stage3_ice_break: RUNNING -> SUCCESS
...
```

`safety_alarm`/`emotion_alarm` toggle 노이즈 완전 제거. timeout/abort 같은 핵심은 그대로 보임.

---

## 2. 핵심 학습

### BT 4.x `StatusChangeLogger`의 빌트인 필터링

베이스 클래스에 이미 `enableTransitionToIdle(bool)` 있음. StdCoutLogger는 기본 true(노이즈 포함). 우리가 false로 끄면 cleanup 전이 자동 skip — **자체 callback에서 분기 불필요**.

이 사실을 빨리 알아냈으면 자체 logger 작성도 더 짧게. `enableTransitionToIdle(false)` 한 줄로 절반 해결, 나머지(IDLE→FAILURE)만 callback에서 필터.

문서/헤더 먼저 읽기의 가치.

### 정상 상태 = noise, 비정상 상태 = signal

ConditionNode(SafetyCheck/EmotionMonitor)의 alarm 패턴:
- 정상: tick → IDLE → FAILURE → IDLE (반복)
- 비정상: tick → IDLE → SUCCESS (alarm 발동!)

즉 **정상 상태가 noise**, 비정상이 signal. 일반적인 logger 룰("모든 전이 출력")이 alarm 패턴엔 부적합 — alarm은 본질적으로 sparse event.

추상화: 정상 동작이 반복 패턴이면 그 패턴 자체가 noise. 비정상(예외, 알람, 변화)이 출력 가치. logger는 도메인 지식 반영해야.

### `enableTransitionToIdle(false)` vs callback 내 필터의 차이

- `enableTransitionToIdle(false)`: callback 호출 자체가 안 됨 (베이스 클래스에서 차단). CPU/IO 절약.
- callback 내 필터: callback은 호출되지만 출력만 skip. 약간의 오버헤드.

성능 차이는 미미하나 **의도 표현이 다름**. enableTransitionToIdle은 logger 정책, callback 내 분기는 코드 logic. 두 layer 분리.

### tree.rootNode() vs tree

`BT::StdCoutLogger(BT::Tree& tree)` 생성자는 내부에서 `tree.rootNode()`를 사용. 우리 자체 logger는 베이스가 `TreeNode*`를 받으므로 `tree.rootNode()`를 직접 전달.

만약 logger가 모든 노드에 callback 부착하려면 root에서 traverse — 베이스 클래스가 알아서 처리.

### timeout 10초 정상 작동 확인

검증 중 tts_node 안 띄움 → utter_done 안 옴 → IceBreak/Offer/LeadIn이 10초 후 timeout SUCCESS로 진행 (이전 utter_done 트랙 효과). 로그도 정확:
```
[WARN] [stage3_ice_break] timeout 10.1s → SUCCESS (forced)
```

이전 트랙들이 통합되어 작동함을 부수적으로 확인.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **노이즈 60+ 라인 → 10 라인** (한 사이클당). 검증/디버깅 부담 크게 감소.
- **timestamp 형식 통일**: `[bt 1777787173.191]` — bt 표시 + epoch 초 (소수점 3자리). 다른 노드 로그(`[INFO] [...]`)와 시각적 구분.
- **stderr 출력 보존**: 본 logger는 stdout. ROS RCLCPP_INFO/WARN 등은 stderr (또는 ROS log). 두 채널 분리되어 grep/redirect 정책 유연.

### 위험 요소

- **컬러 코드 ANSI escape**: `BT::toStr(status, true)`가 컬러 ANSI 출력. tee/grep 시 컬러 코드가 일반 텍스트로 남아 grep 패턴 작성 시 주의 필요. 운영/CI 환경에선 컬러 끄는 옵션 검토 (`BT::toStr(status, false)`).
- **bt 라인이 launch prefix(`[bt_executor-3]`)와 결합**: `ros2 launch` 사용 시 모든 노드 stdout이 `[node-N]` 접두로 출력됨. 우리 `[bt ...]` 접두와 결합되어 `[bt_executor-3] [bt 1777...] ...`처럼 두 번 표시. 가독성 약간 떨어지나 무시 가능.
- **alarm SUCCESS 케이스 한 번만 출력**: ReactiveFallback이 alarm 후 root SUCCESS 처리 → 다음 tick에서 root IDLE → RUNNING 새 사이클. 새 사이클 첫 tick에서 alarm이 다시 SUCCESS면 출력됨. 즉 abort 지속 동안 매 사이클(약 100ms 간격)마다 1번씩 출력. 적절한 빈도.
- **다른 logger와 호환**: BT::FileLogger, BT::Groot2Publisher 등은 별도 동작. 우리 logger는 stdout 전용.

### 갭

- **timestamp 형식이 launch prefix와 중복**: launch prefix `[bt_executor-3]`도 timestamp 포함됨 (ROS log). 우리 `[bt 1777...]`는 BT 자체 timestamp(boot 이후 시간). 의미 다르나 형식 비슷해 혼동 가능. 후속에서 `[bt+0.123s]` 같은 relative 형식 검토.
- **filtering 정책의 운영 토글 부재**: 디버그 시 풀 verbose가 필요할 수도. 환경변수 또는 ROS 파라미터로 toggle 검토 (예: `verbose_bt=true`로 StdCoutLogger 사용).

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **face_avatar 애니메이션 v2**: 정적 1프레임 → Pillow 모든 프레임 + 30fps
- **abort dwell time**: abort 후 일정 시간 face publish 무시
- **min_confidence 임계**: rapport_tracker에 conf 게이팅
- **logger verbose toggle**: 위 갭 §2
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase

### Phase 후속

- W2.5 (RPi): GEFA, decision_rule fusion
- Phase 3: RPS 미니게임

---

## 5. 산출물 위치

### 신규 파일
- `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/filtered_cout_logger.hpp` (FilteredCoutLogger, ~50줄)
- `docs/daily/2026-05-03_phase2_w4_log_noise.md` (본 회고)

### 수정 파일
- `src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp` (#include 변경 + 한 줄 logger 교체)

### 변경 없음
- 다른 BT 노드, persona_manager, tts_node, face_avatar — 모두 그대로
- 메시지/토픽 인터페이스 — 변경 없음
- BT XML cafe_funnel_v1.xml — 변경 없음

### 다음 커밋
- W4 log noise 정리 + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_bt --symlink-install
'
```

### 자체 검증 (bt_executor 단독 5초)
```bash
pkill -KILL -f "bt_executor" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_bt bt_executor > /tmp/bt.log 2>&1 &
PID=$!
sleep 5
kill -INT $PID; wait

# 노이즈 카운트 (이전 트랙이라면 60+, 현재는 0)
grep -cE "safety_alarm.*(IDLE -> FAILURE|FAILURE -> IDLE)|emotion_alarm.*(IDLE -> FAILURE|FAILURE -> IDLE)" /tmp/bt.log
# 출력: 0

# 핵심 라인 (보존)
grep -E "stage[0-9]|cafe_funnel|root_alarm|EmotionMonitor|abort|^\\[bt" /tmp/bt.log
```

### 라이브 통합 검증 (dev_all.launch + abort 발동)
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log

# 별도 터미널 — abort 발동 (hysteresis 5회 충족 위해 rate=20)
ros2 topic pub --rate 20 /emotion/state dobi_npc_msgs/msg/EmotionState \
  "{valence: -0.7, arousal: 0.6, confidence: 0.9, source: 'face', flags: []}"
# 1초 후 Ctrl+C

# launch 콘솔에서 깔끔한 alarm 발동 라인 관찰:
#   [bt ...] emotion_alarm: IDLE -> SUCCESS
#   [bt ...] root_alarm_fallback: RUNNING -> SUCCESS
#   (이전엔 이 라인이 IDLE/FAILURE 100여 라인 사이에 묻혔음)
```

---

**상태**: BT 로그 노이즈 정리 완료. 검증/디버깅 부담 크게 감소. 다음은 애니메이션 v2 / dwell time / min_confidence / 자투리 또는 휴식.
