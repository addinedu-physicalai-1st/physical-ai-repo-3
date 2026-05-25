# 2026-05-16 — M3 Dashboard M2 단계 + 테마 반복 + 좀비 정리

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m3_web_dashboard_skeleton.md` (M1 골격)
> 다음 진행: T01 위치 사용자 추가 이미지 받은 후 좌표 미세 조정, modes/events/analytics/settings 페이지 (M3 완성)

---

## 1. 오늘의 목표

M3 dashboard M1 골격 완성 (사이드바/헤더/WS 연동) 후 본 회고에서:
- M2 단계 — 평면도 SVG / 빠른 모드 / 이벤트 피드 / 테이블 카드 본 구성
- 테마 디자인 반복 — `mocanewdesign.png` (골드/브론즈) → light mode → **`pinklabthema.png`** (다크 마젠타 + 네온 핫핑크) 최종
- 이모지 일괄 제거 (CSS 색 dot / 텍스트 라벨로 대체)
- 매장 평면도 PNG 교체 (`halltop.png` → **`maptopview.png`** 1171×741)
- 글자 가독성 (밝게)
- 깜박임 버그 해결 — DOM 부분 갱신 + 좀비 50+ 정리

## 2. 산출물 누적 (오늘 7번째 커밋 1f2f35b 이후)

### 2.1 M3w M2 단계 (평면도 + 빠른모드 + 이벤트피드 + 테이블카드)

- **`assets/maptopview.png`** (1171×741) — mapv5_mocamap PGM 의 3× 업스케일, 매장 외곽 + 가구 placeholder
- **`assets/floorplan.svg`** — viewBox `0 0 391 250` (PGM native) + image stretch + 마커 오버레이
- **`components/floorplan-view.js`** — fetch SVG inline + `store.robot_pose` → transform 갱신 + `store.tables` → table-{T0X} 클래스 갱신
- **`components/mode-buttons.js`** — 5 빠른 모드 + STOP + Confirm/TableSelect/PersonaModal (M1 prompt 임시) + Toast
- **`components/event-feed.js`** — `store.events` ring buffer 200 → 최근 12 표시
- **`components/table-card.js`** — 단일 테이블 occupancy 카드 (5개 grid)
- **`pages/dashboard.html`** 본 구성 — 3 상태 카드 + 평면도+빠른모드 그리드 + 이벤트 피드
- **`pages/tables.html`** 완성 — 5 `<table-card>` 그리드

### 2.2 테마 디자인 반복 (3 단계)

| 단계 | 베이스 | 액센트 | 결과 |
|---|---|---|---|
| 1차 | 다크 브론즈 (#16100a) | 골드 (#d4af37) | `mocanewdesign.png` 정합 |
| 2차 | 라이트 크림 (#faf6ec) | 골드 darken (#b8860b) | `data-theme="dark"` 토글 옵션 |
| **3차 최종** | **다크 마젠타 (#0a0612)** | **네온 핫핑크 (#ff007a)** | **`pinklabthema.png`** 정합 |

3차 (PinkLAB) 추가 효과:
- body 라디얼 글로우 (핑크 + 시안 코너)
- 카드 반투명 (`bg-glass` rgba(40,20,60,0.55) + `backdrop-filter: blur(12px)`)
- 사이드바/헤더 blur(20px)
- mode-badge: idle 라벤더 / serving 민트 / patrol 시안 / guiding 오렌지 / **engaging 핫핑크** / offline 코랄
- 사이드바 brand "MoCa" — 핑크 그라데이션 + drop-shadow glow
- 글자 가독성: `--text-primary` `#ffffff` (순백), 모든 텍스트 한 단계씩 밝게

### 2.3 이모지 일괄 제거 (27곳)

| 위치 | 이전 | 이후 |
|---|---|---|
| 사이드바 brand | `🤖 MOCA + Dobi Barista` | `MoCa` (serif 핑크 그라데이션) + `Mobile Catering Snack Bar` |
| 사이드바 nav 7 | `🏠/🎮/🪑/📋/📊/⚙️/🛠` | 텍스트만 + CSS 좌측 dot 마커 |
| 사이드바 footer | `🔋` | `BATT` 라벨 |
| battery-gauge | `🔋` | `BATT` 라벨 |
| safety-indicator | `✅/⚠` | CSS color dot (currentColor + glow) |
| table-card | `⚪🔴🟡❓` | CSS color dot (occ-{empty/occupied/finished/unknown}) |
| mode-buttons | `🏠/🍽/🔄/🚶/🎯/🛑` | 텍스트 ("대기/서빙/순회/안내/모객/STOP") |
| event-feed | `ℹ/⚠/❌` | `INFO/WARN/ERR` mono 텍스트 |
| dashboard 헤딩 | `📍/🚀/📺` | 일반 텍스트 |

### 2.4 컴포넌트 DOM 부분 갱신 (깜박임 해결)

- **mode-badge**: `_build()` 한 번 + textContent/className 부분 갱신 + dedup (같은 `current` + `entered_at` 이면 skip) + 1Hz 자체 timer 로 시간만 별도 갱신
- **battery-gauge**: 같은 패턴 (level + text 분리 갱신, 같은 값이면 skip)
- **safety-indicator**: 같은 패턴 (state key `cls:label` dedup)

### 2.5 매장 평면도 PNG 교체 + 마커 좌표 매핑

좌표 변환 — ROS map → PGM pixel:
```
px = (x + 51.320) * 20.0
py = 250.0 - (y + 6.624) * 20.0
yaw_svg = -yaw * 180 / π
```

테이블 마커 cx/cy (`maptopview.png` 측정 후 추정):
- T02-T05: 이미지 안 4 가구 사각형 위치에 fit
- **T01: 추정** (이미지에 T01 명시 X — 사용자 추가 이미지 받은 후 미세 조정 예정)

### 2.6 캐시 무효화 (총 5 단계)
`?v=20260516` → `b` → `c` → `d` → **`e`** (HTML 14곳 + floorplan.svg fetch 1곳)

## 3. 깜박임 버그 해결 ★

### 3.1 사용자 보고
"현재 모드 PATROL + 시간 배지가 깜박이는 현상이 아직 해결이 안되었어."

### 3.2 진짜 원인 발견
`ros2 topic info -v /mode/state` 검사:
- **Publisher count: 11** (정상 = 1)
- 5초 동안 mode: idle 5건 + **patrol 22건** (race)
- publish rate **9.5Hz** (정상 = 1Hz)

`ps -eo pid,cmd | grep moca` — 좀비 50+ 발견:
- mode_manager 9+, patrol_scheduler 12, mode_patrol.launch 7+, guiding_controller 2, person_detector 2, table_occupancy_detector 1

오늘 여러 차례 통합 스모크 + `ros2 run` + `ros2 launch` 가 자식 process 를 부모 종료 후에도 살려둠. 각자 mode_state publish + CompletionWatcher 트리거 → 매 0.2s mode 변경 → mode-badge 깜박.

### 3.3 정리 + 영구 대책
- 50+ PID 일괄 SIGKILL → publisher 1개로 복귀
- mode/idle 단독 안정 publish 1Hz
- ros2 daemon stop/start 로 stale 캐시 cleanup
- 영구 대책 (후속) — `stop_moca.sh` 보강: 모든 자식 process group 까지 SIGKILL

### 3.4 DOM 부분 갱신 (조합)
좀비 race 해결과 별개로 mode-badge / battery-gauge / safety-indicator 가 broadcast 마다 `innerHTML` 재생성하던 패턴을 **부분 갱신 + dedup** 으로 교체. 향후 1Hz mode_state publish 환경에서도 visible flicker 없음.

## 4. 발견 / 결정

### 4.1 디자인 반복 — 사용자 의도 추적

`mocanewdesign.png` (메탈릭 골드) → light mode 요청 → 어두워 보임 (캐시 + 인식 차이) → **`pinklabthema.png`** PinkLAB 다크 마젠타 + 핑크 (최종)

본 회고 시점에 PinkLAB 테마 적용. PinkLAB 브랜드 정합 + 사이버펑크/futuristic 톤. 사용자 만족 신호 (깜박임 해결 확인 + 테이블 위치 조정 진행).

### 4.2 ROS process 좀비 — 운영 위험

오늘 작업 중 누적된 50+ 좀비가 단순 UI 깜박임 너머 — **race condition 으로 인한 잘못된 자동 모드 전이** 위험. 점주 환경에서 동일 사태 발생하면 로봇이 의도 외 행동 가능.

**M3 진입 전 점검 필요**:
- mode_manager 의 `LaunchSupervisor.kill()` 이 SIGTERM → SIGKILL fallback 정상 작동? (기존 코드 확인됨)
- ros2 daemon 캐시 정합성
- `scripts/stop_moca.sh` 의 패턴이 본 좀비 잡는지 검증 (CLAUDE.md §10 자주 쓰는 명령)
- launch process group 추적 (`setsid` 활용 이미 patrol_scheduler 등 사용)

### 4.3 SVG fetch 캐시 — 별도 ?v= 필요

`floorplan-view.js` 가 `fetch('/static/assets/floorplan.svg')` 호출 — HTML 의 ?v= 와 무관. JS 내부에서 `?v=20260516e` 직접 추가.

추후 컴포넌트가 fetch 하는 다른 자산도 같은 패턴 필요 (애니메이션 등).

### 4.4 mapv5_mocamap PGM 좌표 매핑 (재확인)

`maps/mapv5_mocamap.yaml`:
- resolution: 0.050 m/px
- origin: [-51.320, -6.624, 0]
- PGM: 391×250 px

PNG (maptopview.png) = PGM × 3 (1171×741). viewBox 는 PGM native 유지 (preserveAspectRatio=none stretch).

T02-T05 의 가구 사각형은 ROS map 좌표와 잘 정합. **T01 은 이미지 안에 별도 표시 없어 추정** — 사용자 추가 이미지 받은 후 정확 조정.

## 5. 빌드 / 테스트 명령

```bash
# 빌드 (clean 권장 — 신규 PNG/SVG 자산 등록 시)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  rm -rf build/moca_opserver install/moca_opserver
  colcon build --packages-select moca_opserver --symlink-install
'

# 전체 회귀 (UI 작업이 기존 모듈 영향 X 확인)
source install/setup.bash
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/moca_opserver/test/test_completion_and_timer.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py
# Expected: 130 passed

# 브라우저 라이브 검증
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
# (좀비 cleanup)
ps -eo pid,cmd | grep -E "moca_opserver|dobi_npc|ros2 run dobi|ros2 launch dobi" \
  | grep -v "grep\|claude" | awk '{print $1}' | xargs -r kill -9
ros2 daemon stop && ros2 daemon start

ros2 run dobi_npc_bringup mode_manager &
ros2 run moca_opserver opserver_node &
sleep 5
# 브라우저: http://localhost:8800/ → /static/pages/dashboard.html
#   - PinkLAB 다크 마젠타 베이스 + 네온 핑크 액센트
#   - mode-badge 깜박 없음 (1Hz mode_state, 단일 publisher)
#   - 평면도 maptopview.png + 테이블 마커 (T01 추정)
```

## 6. 다음 단계

### 6.1 즉시
- 사용자 추가 이미지 (T01-T05 라벨 명시된 평면도) 받으면 cx/cy 미세 조정
- ★ `stop_moca.sh` 의 좀비 잡기 패턴 검증/보강 (운영 안전)

### 6.2 M3 완성 (spec §13 잔여)
- modes.html (5 카드 컨트롤 + 발화 입력)
- events.html + CSS 필터 + CSV 내보내기
- analytics.html (Chart.js KPI)
- settings.html (영업시간/주기/배터리 config API)
- debug.html (기존 operator.html 흡수)
- 모바일 반응형 검수 (iPad/iPhone 실기)

### 6.3 M4
- 라이트 테마 토글 (data-theme="light" 이미 토큰 정의됨)
- i18n ko/en
- 점주 사용자 테스트

## 7. 메모리 갱신 후보

본 회고에서 새로 발견된 함정:
- **좀비 ros2 process 누적** — 개발 중 50+ 좀비 가능. `pkill -f` 의 패턴이 `python3 .../mode_manager` (entry script 경로) 라 매칭 어려움. PID 직접 kill 또는 명시 패턴 필요.
- **SVG fetch 별도 ?v=** — HTML 안 link/script 의 ?v= 와 분리됨

기존 메모리 정합:
- `[[feedback_starlette_symlink_install]]` ✅ (follow_symlink=True 사용 중)
- `[[feedback_starlette_mount_root]]` ✅ (/static 명시 prefix)
- `[[feedback_dont_touch_working_code]]` ✅ (UI 작업이 ROS 모듈 회귀 0)

---

*다음 갱신: T01 좌표 미세 조정 + M3 modes/events/analytics 본 구현 후*
