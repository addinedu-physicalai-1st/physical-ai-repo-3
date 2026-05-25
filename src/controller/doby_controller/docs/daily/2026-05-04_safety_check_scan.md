# SafetyCheck — /scan 가드 통합 + vicpinky 섀시 self-noise 캘리브레이션

**작성일**: 2026-05-04 (B 단계 LaunchSupervisor 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "SafetyCheck /scan 통합: 1.0m 이내 인간 감지 alarm"
**상태**: `safety_check.hpp`에 `/scan` (sensor_msgs/LaserScan) 가드 추가, BT XML 노출, RPi 라이브 환경에서 1차 동작 확인. 단 vicpinky 섀시 자체반사 0.18~0.21m 확인 → `scan_min_range=0.25` 기본값으로 마스킹.

---

## 0. 시작 컨텍스트

전 단계까지 SafetyCheck는 `/battery_state.percentage < 0.20` 만 평가. CLAUDE.md TODO에 "1.0m 이내 인간 감지 alarm — /scan 통합" 항목 미해결로 남아 있었음. RPi 실 LiDAR 가용한 시점에서 가장 단순한 거리 임계 가드를 우선 추가.

설계 결정 — Phase 5 미래에 사람/벽 구분, 클러스터링, dwell 등으로 진화하더라도 **1차 cut은 거리 임계만**. Marzinotto 2014 priority safety의 1차 가드는 단순할수록 신뢰성↑.

---

## 1. 구현 — `safety_check.hpp`

기존 단일 입력 (battery)에서 **OR 조합 가드**로 확장.

### 1.1 입력 포트 (3개 신규)

```cpp
BT::InputPort<double>("scan_min_dist", 1.0,        // 임계 거리
  "scan 임계 거리 (m). 이 거리 내 obstacle 발견 시 alarm SUCCESS"),
BT::InputPort<double>("scan_min_range", 0.05,      // self-noise 컷
  "LiDAR self-noise 무시 거리 (m). 이보다 가까운 측정값은 무시"),
BT::InputPort<std::string>("scan_alarm_enabled", "true",
  "/scan 가드 활성 여부. 비활성 시 배터리만 평가"),
```

— `scan_min_range` 분리 이유: LiDAR 하드웨어 자체 최소(0.05m, RPLiDAR A1 spec)와 **로봇 섀시 마스킹 거리**가 다름. C++ default는 하드웨어 spec(0.05), XML default는 로봇 통합값(vicpinky=0.25).

### 1.2 구독자 + 콜백

```cpp
sub_scan_ = node_->create_subscription<sensor_msgs::msg::LaserScan>(
  "/scan", rclcpp::QoS(5).best_effort(),     // Nav2 LiDAR QoS 일치
  [this](sensor_msgs::msg::LaserScan::SharedPtr msg) {
    on_scan(msg);
  });

// on_scan: 가장 가까운 유효 obstacle 거리 산출
//   - !std::isfinite(r) skip      (NaN/inf)
//   - r < scan_min_range skip     (self-noise)
//   - r > range_max skip          (LiDAR 측정 한계 초과)
```

— `nearest = std::numeric_limits<float>::infinity()` 초기화 후 min reduction. mutex 보호.

### 1.3 tick() 가드 조합

```cpp
// 미수신 정책: 안전 측 OK (FAILURE = 정상 진행)
//   /battery_state 미수신 → battery_pct_ < 0 → battery_alarm = false
//   /scan 미수신          → scan_received_ = false → scan_alarm = false

if (battery_alarm || scan_alarm) {
  return BT::NodeStatus::SUCCESS;   // funnel 차단
}
return BT::NodeStatus::FAILURE;     // funnel 진행
```

— 두 가드 모두 **로그 1회만 발생** (`last_warned_low_`, `last_warned_scan_` flag). 매 tick(10Hz) 스팸 방지. 정상 복귀 시 `→ normal` INFO 1회.

### 1.4 BT XML 노출 — `cafe_funnel_v1.xml`

```xml
<SafetyCheck name="safety_alarm"
             battery_min="0.20"
             scan_min_dist="1.0"
             scan_min_range="0.25"
             scan_alarm_enabled="true"/>
```

— 운영자가 의식적으로 보고 조절할 값(`battery_min`, `scan_min_dist`, `scan_alarm_enabled`)은 명시. `scan_min_range`는 본래 LiDAR self-noise 보정용(기본 0.05)이지만 vicpinky 섀시 마스킹을 위해 0.25로 override.

---

## 2. 라이브 검증 — RPi /scan 연결 상태에서 첫 시동

```bash
moca_activate
ros2 run dobi_npc_bt bt_executor
```

### 2.1 1차 시동 (scan_min_range=0.05, 기본 LiDAR spec)

```
[WARN] [SafetyCheck] obstacle within 0.18m < 1.00m → alarm
[bt] safety_alarm: IDLE -> SUCCESS
[bt] root_alarm_fallback: RUNNING -> SUCCESS
```

— 0.18m에서 즉시 alarm. 100ms tick마다 동일 패턴. funnel 진입 차단.

### 2.2 진단 — 0.18m가 진짜 obstacle인가?

```bash
ros2 topic echo /scan --once --field ranges \
  | tr "," "\n" | grep -oE "[0-9]+\.[0-9]+" | sort -n | uniq -c | head
```

```
  2 0.18050
  2 0.18125
  1 0.18350
  2 0.18675
  1 0.19075
  2 0.19125
  4 0.19300
  4 0.19350
  ...
```

— **0.18~0.21m 구간에 다수 샘플 클러스터**. 단발성이면 노이즈, 다수면 구조반사. 2개+ 샘플이 동일 거리에 일관되게 잡히는 패턴은 **vicpinky 섀시 자체**(LiDAR 마운트 주변의 본체/케이블/모터 하우징 가능성).

`/scan` topic 메타:
- `frame_id: laser_link`
- `range_min: 0.05`, `range_max: 16.0`
- `angle_min/max: ±π` (360도 RPLiDAR)

LiDAR 하드웨어 최소(0.05m)는 통과하지만 vicpinky의 LiDAR 마운트 위치상 섀시 일부가 시야에 들어와 0.18~0.21m로 반사하는 것으로 추정.

### 2.3 2차 시동 (scan_min_range=0.25, 섀시 마스킹)

```
[WARN] [SafetyCheck] obstacle within 0.31m < 1.00m → alarm
```

— 0.18~0.21m 클러스터는 사라짐. 0.31m에서 다시 alarm. 이 시점에서는 **섀시 너머 실제 환경 반사**(현재 로봇이 책상/벽 근처에 있을 가능성) 또는 **2차 구조반사** 둘 중 하나. 라이브 테스트 시 로봇을 빈 공간에 두고 재확인 필요.

### 2.4 1차 cut 결론

- C++ default `scan_min_range=0.05` = LiDAR spec, 코드 측 정합성
- XML default `scan_min_range=0.25` = vicpinky 통합값, 섀시 1차 마스킹
- 0.25m 이상 alarm 발생 시 **실제 obstacle로 간주** (보수적 안전 측)
- 라이브 테스트에서 로봇을 사방 1m+ 빈 공간에 두고 alarm 안 떠야 정상

---

## 3. 발견 / 함정

### 3.1 ReactiveFallback 재평가 패턴 정합

기존 EmotionMonitor와 동일한 alarm 시맨틱(SUCCESS=위험, FAILURE=정상). ReactiveFallback이 매 tick 자식을 재평가하는 구조 덕에 별도 latch 없이도 즉시 abort 작동.

### 3.2 `/scan` QoS

`rclcpp::QoS(5).best_effort()` — RPLiDAR 표준 발행 QoS와 일치(BEST_EFFORT, KEEP_LAST 5). RELIABLE로 두면 매칭 실패해 콜백 미도착. Nav2도 동일 패턴이라 일관됨.

### 3.3 `range_max` 필터

`r > msg->range_max` 컷이 없으면 LiDAR가 측정 불가 시점에 발행하는 경계값(예: 16.0001 같은 spec out 값)이 잡힐 수 있음. nearest 산출에서 제외.

### 3.4 mutex — `scan_min_obs_dist_` 공유

콜백(다른 executor 스레드)과 tick(BT 스레드)이 동시 접근. battery는 `std::atomic<float>` 으로 충분했지만 scan은 "수신 여부" + "최근 거리" 두 값을 일관되게 읽어야 해서 `std::mutex` 필요.

### 3.5 self-noise 컷이 LiDAR spec에 종속

vicpinky가 로봇별로 다르므로 `scan_min_range`는 **로봇 통합 시점의 캘리브레이션 값**. CLAUDE.md / hardware-specific 문서에 박는 게 옳음. 본 회고가 그 1차 기록.

---

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/safety_check.hpp` | `/scan` 구독 + on_scan + 가드 OR 조합 + 3 입력 포트 (총 +90 줄) |
| `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` | SafetyCheck에 scan 포트 3종 노출, 캘리브레이션 코멘트 |

---

## 5. 다음 / TODO 갱신

### 즉시 (라이브 테스트 시)
- [ ] vicpinky를 사방 1m+ 빈 공간(혹은 카페 한가운데)에 두고 BT 시동 → alarm 안 떠야 통과
- [ ] 사람이 1.0m 안으로 들어왔을 때 alarm 즉시 발동 + 떠나면 1회 normal log + funnel 재진입 확인
- [ ] `scan_min_range` 0.25 → 실측 결과 따라 0.20~0.30 범위로 미세 튜닝

### Phase 후속 (관련성 가까움)
- [ ] **사람/벽 구분**: 360도 LiDAR raw로는 사람-벽 구분 불가. RPi USB 캠 + GEFA(자세) 도입 시 보강.
- [ ] **클러스터링**: 단일 ray 임계 → ray cluster 임계로 진화 (point noise robustness)
- [ ] **dwell 통합**: SafetyCheck도 abort 후 일정 시간 funnel 재진입 차단 (face_avatar dwell 패턴 재사용)

### CLAUDE.md TODO 변경
- `[ ] SafetyCheck /scan 통합` → **`[x] SafetyCheck /scan 통합 (2026-05-04, scan_min_range vicpinky=0.25)`**
- 새 항목: `[ ] /scan 캘리브레이션 라이브 검증 — scan_min_range 미세 튜닝`

---

## 6. 한 줄 요약

> SafetyCheck에 `/scan` 거리 임계 가드 1.0m 추가. vicpinky 섀시 자기반사 0.18~0.21m 확인 → `scan_min_range=0.25` 기본값으로 마스킹. 라이브 테스트에서 실측 미세 튜닝 + 사람 침입 trigger 확인 예정.
