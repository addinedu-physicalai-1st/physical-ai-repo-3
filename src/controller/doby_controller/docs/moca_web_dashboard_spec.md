# MOCA Web Dashboard 사양서

> **문서 ID**: `moca_web_dashboard_spec.md`
> **버전**: v1.0 (2026-05-16)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §7
> **관련 문서**: `moca_opserver_api_spec.md` (백엔드 API)
> **구현 대상**: `src/moca_web/` (신규 패키지)

---

## 0. 본 문서의 범위

본 문서는 카페 점주가 사용할 **운영 웹 대시보드**의 UI/UX 사양과 프론트엔드 구현 방침을 정의한다.

### 0.1 본 문서가 다루는 것

1. 페이지 7종의 화면 구성, 데이터 바인딩, 상호작용
2. 디자인 시스템 (색상, 타이포그래피, 컴포넌트)
3. 반응형 레이아웃 (데스크톱/태블릿/모바일)
4. 프론트엔드 코드 구조 (vanilla JS, 빌드 도구 없음)
5. WebSocket 연동 및 상태 관리
6. 접근성 (a11y) 가이드라인

### 0.2 본 문서가 다루지 않는 것

- 백엔드 REST/WS 명세 (`moca_opserver_api_spec.md`)
- mode_manager FSM (`moca_5state_fsm_spec.md`)

---

## 1. 사용자와 환경

### 1.1 페르소나

**P1. 점주 (주 사용자)**
- 40대, IT 비전문가
- 카페 운영 + 직원 관리
- 태블릿(iPad) 또는 카운터 PC에서 접근
- 한국어 사용
- 한 화면에서 매장 상태 파악 필요

**P2. 직원 (보조 사용자)**
- 20-30대
- 스마트폰으로 가끔 확인 (배터리, 큐 상태)
- 빠른 상태 확인이 주 목적

**P3. 개발자 (Stephen 본인)**
- 디버그 페이지에서 raw 토픽/로그 확인
- 깊은 디버깅은 RViz/터미널 병행

### 1.2 디바이스/환경

| 디바이스 | 화면 폭 | 우선순위 | 사용 빈도 |
|---|---|---|---|
| 데스크톱 (카운터 PC) | ≥1280px | 1 | 항상 켜둠 |
| 태블릿 (iPad 11") | 1024px | 1 | 점주 휴대 |
| 스마트폰 (iPhone) | 375-430px | 2 | 가끔 확인 |

**브라우저 지원**:
- Chrome/Edge 120+ (주력)
- Safari 17+ (iPad)
- Firefox 120+ (개발 환경)
- IE 미지원

**네트워크**: 매장 내 Wi-Fi (저지연, 안정). 외부망 접속은 M3+ 검토.

---

## 2. 디자인 시스템

### 2.1 컬러 팔레트 (다크 테마 기본)

기존 `web/static/operator.html`의 톤을 계승하되 PinkLAB 브랜드 컬러를 점진적으로 도입한다.

```css
:root {
  /* Base */
  --bg-primary: #1a1a1d;
  --bg-secondary: #25252b;
  --bg-tertiary: #2f2f37;
  --border: #3a3a42;

  /* Text */
  --text-primary: #e5e5e7;
  --text-secondary: #94949c;
  --text-muted: #6c6c75;

  /* Brand (PinkLAB) */
  --pink-primary: #ff6b9d;       /* Vic Pinky 표면 색 */
  --pink-soft: #ffb3cf;          /* 호흡 효과 */
  --coral: #ff8c7a;              /* Dobi Barista fabric */

  /* Semantic */
  --accent: #4a9eff;              /* 기본 액션 */
  --success: #4ade80;
  --warning: #fbbf24;
  --danger: #f87171;
  --info: #60a5fa;

  /* Mode badges */
  --mode-idle: #6c6c75;
  --mode-serving: #4ade80;
  --mode-patrol: #60a5fa;
  --mode-guiding: #fbbf24;
  --mode-engaging: #ff6b9d;

  /* Sizing */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.5);
}

/* Light theme (선택, 토글 가능) */
[data-theme="light"] {
  --bg-primary: #f8f9fa;
  --bg-secondary: #ffffff;
  --bg-tertiary: #f1f3f5;
  --border: #dee2e6;
  --text-primary: #212529;
  --text-secondary: #495057;
  --text-muted: #868e96;
  /* ... */
}
```

### 2.2 타이포그래피

```css
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI",
               "Noto Sans KR", "Pretendard Variable", "Pretendard",
               sans-serif;
  --font-mono: "JetBrains Mono", "D2Coding", monospace;

  --fs-xs: 11px;
  --fs-sm: 13px;
  --fs-base: 15px;
  --fs-md: 17px;
  --fs-lg: 20px;
  --fs-xl: 28px;
  --fs-2xl: 36px;
}
```

- 한글 가독성 우선: Pretendard 우선 fallback, Noto Sans KR 보조
- 숫자(배터리%, 시간 카운터)는 mono 폰트로 흔들림 방지

### 2.3 간격 시스템

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-8: 48px;
}
```

### 2.4 컴포넌트 라이브러리 (vanilla JS)

별도 프레임워크 도입 없이 web components 또는 단순 클래스 기반 작성. 다음 컴포넌트를 `static/components/`에 정의:

| 컴포넌트 | 파일 | 용도 |
|---|---|---|
| ModeBadge | `mode-badge.js` | 현재 모드 표시 |
| BatteryGauge | `battery-gauge.js` | 배터리 % 게이지 |
| TableCard | `table-card.js` | 테이블 카드 (occupancy 색상) |
| EventFeed | `event-feed.js` | 실시간 이벤트 피드 |
| Floorplan | `floorplan.js` | SVG 평면도 + 로봇 마커 |
| AlarmBanner | `alarm-banner.js` | 상단 빨간/노란 배너 |
| Toast | `toast.js` | 우상단 알림 |
| Modal | `modal.js` | 확인 모달 |
| Chart | `chart-wrap.js` | Chart.js 래퍼 |

각 컴포넌트는 `data-*` 속성 또는 JS API로 갱신. React 미사용 (점주용 단순 UI에 과한 의존성).

---

## 3. 페이지 구조

### 3.1 사이드바 (모든 페이지 공통)

```
┌──────────────────┐
│  🤖 MOCA         │  ← 로고/타이틀
│  Dobi Barista    │
├──────────────────┤
│ 🏠 대시보드      │  ← 활성 표시
│ 🎮 모드 제어     │
│ 🪑 테이블        │
│ 📋 이벤트        │
│ 📊 통계          │
│ ⚙️  설정         │
│ 🛠 디버그        │
├──────────────────┤
│ ● 로봇 온라인    │  ← 하단 상태 표시
│ 🔋 78%           │
│ 12:34:56         │
└──────────────────┘
```

**반응형 처리**:
- 데스크톱: 폭 220px 고정 표시
- 태블릿: 폭 60px (아이콘만), 호버/탭으로 펼침
- 모바일: 햄버거 메뉴, 풀스크린 오버레이로 열림

### 3.2 헤더 (모든 페이지 공통)

```
┌──────────────────────────────────────────────────────────────┐
│  [현재 모드 뱃지]  [배터리]  [안전]  [Wi-Fi]      [현재 시각] │
│   SERVING          78%       ✅      -52dBm        12:34:56  │
└──────────────────────────────────────────────────────────────┘
```

- 항상 1Hz로 mode_state 갱신
- robot_offline 시 모드 뱃지를 회색 "OFFLINE"으로 변경, 헤더 전체 빨간 배경

### 3.3 페이지별 라우팅

```
/                       → /dashboard 리다이렉트
/dashboard              → 대시보드
/modes                  → 모드 제어
/tables                 → 테이블 모니터링
/events                 → 이벤트 로그
/analytics              → 통계
/settings               → 설정
/debug                  → 디버그
```

라우팅 방식: 단순 정적 html (`static/pages/dashboard.html` 등). hash 라우팅도 검토했으나 5페이지 정도라 multi-page가 단순.

---

## 4. 페이지 상세 — 대시보드 (`/dashboard.html`)

### 4.1 레이아웃 (1280px 데스크톱)

```
┌───────┬──────────────────────────────────────────────────────┐
│       │  [헤더: 모드 뱃지 + 배터리 + 안전 + 시간]            │
│ Side  ├──────────────────────────────────────────────────────┤
│ bar   │                                                      │
│       │  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│       │  │ 현재 모드  │  │ 진행 큐    │  │ 다음 순회  │      │
│       │  │ SERVING    │  │ 서빙 2건   │  │ 03:22 후   │      │
│       │  │ 12:34 진입 │  │ 안내 0건   │  │            │      │
│       │  └────────────┘  └────────────┘  └────────────┘      │
│       │                                                      │
│       │  ┌────────────────────────┐  ┌──────────────────┐    │
│       │  │   📍 매장 평면도        │  │  🚀 빠른 모드    │    │
│       │  │                         │  │                  │    │
│       │  │   ┌─────────────────┐  │  │  [🏠 대기   ]    │    │
│       │  │   │ [픽업] [Home🤖] │  │  │  [🍽 서빙   ]    │    │
│       │  │   │   [T01]         │  │  │  [🔄 순회   ]    │    │
│       │  │   │   [T02] [T04]   │  │  │  [🚶 안내   ]    │    │
│       │  │   │   [T03] [T05]   │  │  │  [🎯 모객   ]    │    │
│       │  │   └─────────────────┘  │  │                  │    │
│       │  │                         │  │  🛑 [  STOP  ]   │    │
│       │  └────────────────────────┘  └──────────────────┘    │
│       │                                                      │
│       │  ┌──────────────────────────────────────────────┐    │
│       │  │  📺 실시간 이벤트                  [더보기 →]│    │
│       │  │  12:34:58  pickup_ready → serving(T03) ✅   │    │
│       │  │  12:33:12  patrol completed                 │    │
│       │  │  12:28:01  patrol started (timer)           │    │
│       │  └──────────────────────────────────────────────┘    │
└───────┴──────────────────────────────────────────────────────┘
```

### 4.2 컴포넌트별 데이터 바인딩

| 영역 | 데이터 소스 | 갱신 |
|---|---|---|
| 헤더 모드 뱃지 | WS `mode_state` | 1Hz |
| 헤더 배터리 | WS `battery` | 1Hz |
| 헤더 안전 | WS `mode_state.safety_ok` | 1Hz |
| 카드 "현재 모드" | WS `mode_state` | 변화 시 |
| 카드 "진행 큐" | WS `serving_progress` + `guiding_progress` | 변화 시 |
| 카드 "다음 순회" | 클라이언트 계산 (idle 진입 시각 + interval) | 1Hz 클라이언트 타이머 |
| 평면도 로봇 마커 | WS `robot_pose` | 1Hz |
| 평면도 테이블 색상 | WS `table_update` | 변화 시 |
| 모드 버튼 | (액션) WS `set_mode` 송신 | 클릭 |
| STOP 버튼 | (액션) WS `emergency_stop` | 클릭 |
| 이벤트 피드 | WS `event_log` | 변화 시 |

### 4.3 평면도 SVG 구조

`static/assets/floorplan.svg` — 매장 평면도 정적 SVG. 좌표는 `tables.yaml`의 map frame과 매핑.

```html
<svg viewBox="-52 -7 28 16" preserveAspectRatio="xMidYMid meet">
  <!-- 매장 벽 -->
  <path class="wall" d="M-51,-6 L-51,7 L-30,7 L-30,-6 Z" />

  <!-- 카운터 영역 -->
  <rect class="counter" x="-37" y="2" width="3" height="2" />

  <!-- 가구 (cafe_layout.yaml 기반) -->
  <g class="furniture">
    <circle id="prep_station" cx="-36.07" cy="2.793" r="0.3" />
    <circle id="open_arm" cx="-36.42" cy="3.276" r="0.4" />
    <rect id="kiosk" x="-35.7" y="3.3" width="0.4" height="0.2" />
  </g>

  <!-- 테이블 (id로 occupancy 색상 동적) -->
  <g class="tables">
    <circle id="table-T01" data-table="T01" cx="-36.337" cy="0.526" r="0.5"
            class="table-empty" />
    <circle id="table-T02" data-table="T02" cx="-41.037" cy="0.243" r="0.5"
            class="table-empty" />
    <!-- ... T03~T05 -->
  </g>

  <!-- 로봇 마커 (JS로 좌표 갱신) -->
  <g id="robot-marker" transform="translate(-36.887, 2.809) rotate(-90)">
    <circle r="0.3" fill="var(--pink-primary)" />
    <path d="M0,-0.3 L0.15,0.15 L-0.15,0.15 Z" fill="white" />  <!-- 방향 화살표 -->
  </g>
</svg>
```

```css
.table-empty    { fill: var(--text-muted); }
.table-occupied { fill: var(--mode-engaging); }   /* 핑크 */
.table-finished { fill: var(--warning); }          /* 노랑 */
.table-unknown  { fill: var(--border); }
```

좌표 변환: WS `robot_pose.x/y/yaw`를 SVG `transform="translate(x,y) rotate(yaw_deg)"`로.

### 4.4 모드 전환 버튼 동작

```javascript
// 클릭 → 확인 모달 (필요 시) → WS 송신
function onModeButtonClick(targetMode) {
  if (targetMode === 'engaging') {
    // engaging은 페르소나 선택 모달
    showPersonaModal((persona) => {
      ws.send({type: 'set_mode', mode: 'engaging', params: {persona}});
    });
  } else if (targetMode === 'serving' || targetMode === 'guiding') {
    // 활동 모드는 운영자가 직접 누른 경우 override_priority=true (점주 의도 우선)
    showTableSelectModal(targetMode, (tableId) => {
      ws.send({type: 'set_mode', mode: targetMode,
               params: {target_table: tableId},
               override_priority: true});
    });
  } else {
    // idle, patrol은 즉시
    ws.send({type: 'set_mode', mode: targetMode, override_priority: true});
  }
}
```

비상정지(STOP):
```javascript
function onEmergencyStop() {
  showConfirmModal('비상정지하시겠습니까?\n로봇이 즉시 멈춥니다.', () => {
    ws.send({type: 'emergency_stop'});
    showToast('비상정지 명령 전송됨', 'warning');
  });
}
```

### 4.5 반응형 변경 (≤768px 모바일)

- 3 카드(현재 모드 / 진행 큐 / 다음 순회) → 세로 스택 1열
- 평면도와 빠른 모드 → 세로 스택
- 빠른 모드 버튼 → 2×3 그리드 (가독성)
- 이벤트 피드 → 접힘, 탭으로 펼침

---

## 5. 페이지 상세 — 모드 제어 (`/modes.html`)

### 5.1 레이아웃

상단 현 모드 상태 카드 + 모드별 상세 컨트롤 카드 5종.

```
┌──────────────────────────────────────────────────────────────┐
│  현재 모드: SERVING                          [강제 idle →]   │
│  진입: 12:34:00 (3분 12초 진행 중)                            │
│  파라미터: {"waypoint":"T03","via_pickup":true}              │
│  큐: [D-0043→T01]                                            │
└──────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  🍽 서빙 모드                                  │
│                                                │
│  강제 시작:                                    │
│  ┌──────────┐ ┌──────────────┐ ┌──────────┐    │
│  │테이블:T03▼│ │ ☑ via_pickup │ │  [실행]  │    │
│  └──────────┘ └──────────────┘ └──────────┘    │
│                                                │
│  큐 관리:                                      │
│  - D-0043 → T01     [건너뛰기] [취소]          │
│  [전체 큐 초기화]                              │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  🔄 순회 모드                                  │
│                                                │
│  강제 시작: [전체 ▼] [실행]                    │
│                                                │
│  자동 주기: ☑ 활성                             │
│   주기: [5] 분  [저장]                         │
│   영업시간: [09:00] - [22:00]  [저장]          │
│                                                │
│  순회 순서: T01 → T02 → T03 → T04 → T05        │
│   [▲▼로 재정렬]                                │
│                                                │
│  지금까지 순회 횟수 (오늘): 23회               │
│  최근 순회: 12:33:12 (87초 소요)                │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  🚶 동행 안내                                  │
│                                                │
│  강제 시작:                                    │
│  ┌──────────┐ ┌──────────────────────┐         │
│  │테이블:T02▼│ │고객ID: [자동생성] ☑ │         │
│  └──────────┘ └──────────────────────┘         │
│  [실행]                                        │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  🎯 모객 모드                                  │
│                                                │
│  페르소나: [casual_browser ▼]                  │
│   ○ casual_browser  ○ friendly_child           │
│   ○ professional_adult                         │
│                                                │
│  [시작] [중단]                                 │
│                                                │
│  자동 종료 조건: ☑ 5분 경과 시                 │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  💬 수동 발화                                  │
│                                                │
│  ┌────────────────────────────────┐            │
│  │ 안녕하세요!                    │ [말하기]   │
│  └────────────────────────────────┘            │
│  표정: [happy ▼]  [표정 적용]                  │
└────────────────────────────────────────────────┘
```

### 5.2 동작 명세

각 카드의 [실행] 버튼은 confirm 후 WS `set_mode` 송신. 결과는 1초 내 헤더 모드 뱃지 변경으로 확인.

설정값 저장 ([저장] 버튼): WS `set_config` 송신 → 성공 토스트.

---

## 6. 페이지 상세 — 테이블 (`/tables.html`)

### 6.1 그리드 카드

```
┌────────────────────────────────────────────────────────┐
│  마지막 순회: 12:33:12 (87초 소요)  [지금 순회 시작 →] │
├────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │ T01              │  │ T02              │            │
│  │ ⚪ 빈            │  │ 🔴 점유 (2명)    │            │
│  │ 신뢰도: 92%      │  │ 신뢰도: 88%      │            │
│  │ 갱신: 12:33:12   │  │ 갱신: 12:33:15   │            │
│  │                  │  │                  │            │
│  │ 오늘 서빙: 12회  │  │ 오늘 서빙: 8회   │            │
│  │ 평균 점유: 25분  │  │ 평균 점유: 32분  │            │
│  │                  │  │                  │            │
│  │ [테스트 서빙 →]  │  │ [점유 확인 →]    │            │
│  └──────────────────┘  └──────────────────┘            │
│                                                        │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │ T03              │  │ T04              │            │
│  │ 🟡 식사완료      │  │ ⚪ 빈            │            │
│  │ 신뢰도: 78%      │  │ 신뢰도: 95%      │            │
│  │ ⚠ 청소 필요      │  │                  │            │
│  │ ...              │  │ ...              │            │
│  └──────────────────┘  └──────────────────┘            │
│                                                        │
│  ┌──────────────────┐                                  │
│  │ T05              │                                  │
│  │ ❓ 미지          │                                  │
│  └──────────────────┘                                  │
└────────────────────────────────────────────────────────┘
```

### 6.2 occupancy 상태 색상

| 상태 | 색상 | 의미 |
|---|---|---|
| `empty` | 회색 ⚪ | 비어있음 |
| `occupied` | 빨강 🔴 | 사람 있음 |
| `finished` | 노랑 🟡 | 식사 종료, 청소 필요 |
| `unknown` | 어두운 회색 ❓ | 마지막 순회 정보 없음 |

### 6.3 동작

- [지금 순회 시작 →]: WS `set_mode`로 patrol 즉시 진입
- [테스트 서빙 →]: 카운터에서 픽업 → 해당 테이블로 가는 시뮬 (개발용 — debug 페이지로 옮김 검토)
- [점유 확인 →]: 해당 테이블만 우선 순회 (`sweep_mode:"priority_only"`)

---

## 7. 페이지 상세 — 이벤트 로그 (`/events.html`)

### 7.1 레이아웃

```
┌──────────────────────────────────────────────────────────────┐
│  📋 이벤트 로그                                              │
│                                                              │
│  필터: ☑ pickup ☑ guide ☑ mode_change ☑ alarm ☐ debug       │
│        시간: [오늘 ▼]    [내보내기 CSV →]                    │
├──────────────────────────────────────────────────────────────┤
│  12:34:58  ℹ  pickup_ready  drink=D-0042  table=T03         │
│                → serving started                             │
│  12:34:58  ℹ  mode_change   idle → serving                  │
│  12:33:12  ℹ  mode_change   patrol → idle (cycle done)      │
│  12:33:12  ℹ  patrol_report all 5 scanned (1 occ, 4 empty)  │
│  12:30:01  ℹ  table_report  T02 → empty                     │
│  ...                                                         │
│  12:18:33  ⚠  alarm         battery_low (0.18 < 0.20)       │
│  12:18:33  ℹ  mode_change   patrol → idle (forced)          │
│  ...                                                         │
│                                       [더 불러오기 ↓]        │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 데이터 소스

- 최근 200건은 WS `event_log` 누적 + 로컬 ring buffer
- 더 과거: `GET /api/v1/events?before=...&limit=100` 페이지네이션
- CSV: 필터 적용 후 `GET /api/v1/events?...&format=csv` (M3)

### 7.3 필터링

체크박스 토글 → 클라이언트 측 즉시 필터 (DOM hide/show). 시간 필터(`오늘/최근 1시간/직접 입력`)는 API 재호출.

### 7.4 레벨 아이콘

```
ℹ  info    (회색)
⚠  warn    (노랑)
❌ error   (빨강)
```

---

## 8. 페이지 상세 — 통계 (`/analytics.html`)

### 8.1 레이아웃

```
┌──────────────────────────────────────────────────────────────┐
│  📊 통계                                                     │
│  기간: [일간 | 주간 | 월간]  날짜: [2026-05-16 ▼]            │
├──────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │  서빙    │ │  순회    │ │  안내    │ │  모객    │         │
│  │   47회   │ │   23회   │ │   12회   │ │    3회   │         │
│  │ 평균 87s │ │ 평균 92s │ │ 평균 41s │ │ 평균 4분 │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 모드별 시간 점유율                                   │    │
│  │   [도넛 차트: idle 60%, serving 20%, patrol 10%,    │    │
│  │    guiding 7%, engaging 3%]                          │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 시간대별 서빙 횟수                                   │    │
│  │   [막대 차트: 09시~22시 시간대별]                   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 테이블별 사용도 (오늘 서빙 횟수)                     │    │
│  │   T01: ▓▓▓▓▓▓▓▓▓▓▓▓ 12                              │    │
│  │   T02: ▓▓▓▓▓▓▓▓ 8                                   │    │
│  │   T03: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 14                            │    │
│  │   T04: ▓▓▓▓▓ 5                                       │    │
│  │   T05: ▓▓▓▓▓▓▓▓ 8                                   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 시스템 KPI                                           │    │
│  │  배터리 사이클: 1.2회   비상정지: 0회               │    │
│  │  순회 점유 발견율: 24%  안내 미아: 0회              │    │
│  │  spawn 실패: 1회        모객 전환률: 33%            │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 라이브러리

- Chart.js (CDN load)
- 데이터: `GET /api/v1/kpi/daily?date=...` 또는 `GET /api/v1/kpi/range?from=...&to=...`

---

## 9. 페이지 상세 — 설정 (`/settings.html`)

### 9.1 섹션

```
┌──────────────────────────────────────────────────────────────┐
│  ⚙️ 설정                                                    │
├──────────────────────────────────────────────────────────────┤
│  [ 운영 설정 ]                                               │
│   영업 시간:  [09:00] ~ [22:00]              [저장]          │
│   자동 순회:  ☑ 활성   주기: [5] 분         [저장]          │
│   배터리 임계: [20] %                       [저장]          │
│                                                              │
│  [ 안전 설정 ]                                               │
│   alarm dwell: [5] 초                       [저장]          │
│   야간 자동 순회 차단: ☑ 활성                                │
│   모객 자동 종료 (분): [5]                                   │
│                                                              │
│  [ 알림 설정 ]                                               │
│   배터리 < 30% 시 알림: ☐                                    │
│   비상정지 발생 시 알림: ☑                                   │
│   텔레그램 봇 토큰: [    ]                  [테스트 전송]    │
│                                                              │
│  [ 페르소나 / 발화 ]                                         │
│   기본 페르소나: [casual_browser ▼]                          │
│   기본 voice: [ko-KR-SunHiNeural ▼]                          │
│                                                              │
│  [ 시스템 ]                                                  │
│   워크스페이스: ✅ OK                                        │
│   ROS DOMAIN ID: 22                                          │
│   OpServer 버전: 0.3.0                                       │
│   mode_manager 상태: ✅ 정상                                 │
│   카메라: ✅ 작동                                            │
│   LiDAR: ✅ 작동                                             │
│                                                              │
│   [로그 다운로드] [설정 백업] [재기동]                       │
└──────────────────────────────────────────────────────────────┘
```

### 9.2 저장 방식

각 [저장] 버튼은 해당 섹션의 값을 WS `set_config` 또는 `POST /api/v1/config`로 송신. 성공 시 토스트.

---

## 10. 페이지 상세 — 디버그 (`/debug.html`)

Stephen 개인용. 기존 `web/static/operator.html`의 raw 컨트롤을 그대로 흡수 + 추가:

- 모든 ROS 토픽 echo (선택 가능 list)
- `/mode/request` 직접 호출 폼 (raw JSON params)
- BT tick rate 실시간 그래프
- 카메라 라이브 뷰 (`/image_raw/compressed` MJPEG)
- emotion 차원 모델 라이브 (v/a 산점도)
- rapport 이벤트 raw 로그
- 큐 raw dump (serving / guiding)
- 강제 토픽 publish (`/operator/command` 등)

이 페이지는 점주에게 보이지 않도록 사이드바에서 dev 모드 토글로 가림 (LocalStorage `dev_mode=true`).

---

## 11. 프론트엔드 코드 구조

### 11.1 디렉토리

```
moca_web/
├── package.xml
├── setup.py
├── launch/
│   └── moca_web.launch.py        # 단독 실행용 (FastAPI static serve)
├── moca_web/
│   ├── __init__.py
│   └── web_server.py             # FastAPI 정적 파일 서버 (또는 opserver 통합)
└── static/
    ├── index.html                # /dashboard 리다이렉트
    ├── pages/
    │   ├── dashboard.html
    │   ├── modes.html
    │   ├── tables.html
    │   ├── events.html
    │   ├── analytics.html
    │   ├── settings.html
    │   └── debug.html
    ├── components/
    │   ├── mode-badge.js
    │   ├── battery-gauge.js
    │   ├── table-card.js
    │   ├── event-feed.js
    │   ├── floorplan.js
    │   ├── alarm-banner.js
    │   ├── toast.js
    │   ├── modal.js
    │   └── chart-wrap.js
    ├── js/
    │   ├── api.js                # REST 클라이언트 (fetch wrapper)
    │   ├── ws.js                 # WebSocket 클라이언트 (auto-reconnect)
    │   ├── store.js              # 상태 관리 (vanilla pub-sub)
    │   ├── router.js             # (선택) 페이지 네비
    │   ├── i18n.js               # ko/en 토글 (M3)
    │   └── app.js                # 부트스트랩
    ├── css/
    │   ├── reset.css
    │   ├── tokens.css            # 디자인 토큰 변수
    │   ├── layout.css            # 사이드바/헤더
    │   ├── components.css        # 공통 컴포넌트 스타일
    │   ├── pages.css             # 페이지별
    │   └── theme-light.css       # 라이트 테마 (선택)
    └── assets/
        ├── logo.svg
        ├── floorplan.svg
        └── icons/
            ├── mode-idle.svg
            ├── mode-serving.svg
            ├── mode-patrol.svg
            ├── mode-guiding.svg
            └── mode-engaging.svg
```

### 11.2 핵심 모듈

#### js/ws.js — WebSocket 클라이언트

```javascript
class WSClient {
  constructor(url) {
    this.url = url;
    this.handlers = new Map();    // type → [callback, ...]
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => { this.reconnectDelay = 1000; emit('ws:open'); };
    this.ws.onmessage = (e) => this.handleMessage(JSON.parse(e.data));
    this.ws.onclose = () => this.reconnect();
    this.ws.onerror = (e) => console.error('WS error', e);
  }

  reconnect() {
    emit('ws:close');
    setTimeout(() => this.connect(), this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  handleMessage(msg) {
    const handlers = this.handlers.get(msg.type) || [];
    handlers.forEach(h => h(msg));
  }

  on(type, callback) {
    if (!this.handlers.has(type)) this.handlers.set(type, []);
    this.handlers.get(type).push(callback);
  }

  send(obj) {
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    } else {
      console.warn('WS not open, dropped:', obj);
    }
  }
}

window.wsClient = new WSClient(`ws://${location.host}/ws/dashboard`);
```

#### js/store.js — 상태 관리 (pub-sub)

```javascript
class Store {
  constructor() {
    this.state = {
      mode: null,
      battery: null,
      tables: {},
      serving: null,
      patrol: null,
      guiding: null,
      events: [],
      online: false,
    };
    this.subscribers = new Map();
  }

  set(key, value) {
    this.state[key] = value;
    (this.subscribers.get(key) || []).forEach(cb => cb(value));
  }

  get(key) { return this.state[key]; }

  on(key, callback) {
    if (!this.subscribers.has(key)) this.subscribers.set(key, []);
    this.subscribers.get(key).push(callback);
    if (this.state[key] !== null) callback(this.state[key]);
  }
}

window.store = new Store();

// WS 이벤트 → store 갱신
wsClient.on('mode_state', (msg) => store.set('mode', msg.data));
wsClient.on('battery', (msg) => store.set('battery', msg.data));
wsClient.on('table_update', (msg) => {
  const tables = store.get('tables');
  tables[msg.data.table_id] = msg.data;
  store.set('tables', tables);
});
wsClient.on('event_log', (msg) => {
  const events = store.get('events');
  events.unshift(msg.data);
  if (events.length > 200) events.pop();
  store.set('events', events);
});
// ...
```

#### components/mode-badge.js — Web Component

```javascript
class ModeBadge extends HTMLElement {
  connectedCallback() {
    this.render({current: 'idle'});
    store.on('mode', (mode) => this.render(mode));
  }

  render(mode) {
    const color = `var(--mode-${mode.current})`;
    this.innerHTML = `
      <div class="badge" style="background:${color}">
        <span class="label">${mode.current.toUpperCase()}</span>
        <span class="time">${formatTime(mode.entered_at)}</span>
      </div>
    `;
  }
}
customElements.define('mode-badge', ModeBadge);
```

HTML 사용:
```html
<mode-badge></mode-badge>
```

### 11.3 빌드/배포

- 빌드 도구 없음. 정적 파일 그대로.
- FastAPI(opserver 또는 별도 web_server)가 static 디렉토리 mount:
  ```python
  app.mount("/", StaticFiles(directory=".../moca_web/static", html=True), name="static")
  ```
- 캐시 무효화: html 파일에 `?v=YYYYMMDD` 쿼리 string (수동 갱신, M3+ 자동화)

---

## 12. 접근성 (a11y)

### 12.1 키보드 네비게이션

- 모든 인터랙티브 요소에 tabindex
- 모드 전환 버튼: Enter/Space로 활성화
- 모달: Escape로 닫기, Tab trap

### 12.2 ARIA

- 모드 뱃지: `role="status"`, `aria-live="polite"`
- 알람 배너: `role="alert"`
- 평면도 로봇 마커: `aria-label="로봇 위치: SERVING 모드"`

### 12.3 색상 대비

- 다크 테마 텍스트 대비 WCAG AA 충족 (4.5:1 이상)
- 색상만으로 정보 전달 금지 (occupancy는 색 + 아이콘 + 텍스트)

---

## 13. 단계별 구현 로드맵

### M1 — 골격 (마스터 계획서 §9.2)

- [ ] 디렉토리 구조 생성, 정적 파일 placeholder
- [ ] 사이드바 + 헤더 컴포넌트
- [ ] dashboard.html: 모드 뱃지 + 배터리만 (WS 연동 검증)
- [ ] ws.js, store.js 핵심 모듈
- [ ] FastAPI static mount

### M2 — patrol/guiding 연계

- [ ] 평면도 SVG + 로봇 마커
- [ ] 테이블 카드 (5개) + occupancy 색상
- [ ] dashboard 이벤트 피드
- [ ] tables.html 완성

### M3 — 완성

- [ ] modes.html (5 카드 컨트롤)
- [ ] events.html + CSV 내보내기
- [ ] analytics.html + Chart.js 차트
- [ ] settings.html + config API
- [ ] debug.html (기존 operator.html 흡수)
- [ ] 모바일 반응형 검수 (iPad/iPhone 실기)

### M4 — 다듬기

- [ ] 라이트 테마 토글
- [ ] i18n ko/en
- [ ] 점주 사용자 테스트 + 개선

---

## 14. 점검 시나리오

### 14.1 점주 시나리오 (M3 종료 조건)

1. **아침 출근**: 태블릿 켜고 대시보드 진입 → 현재 idle / 배터리 87% 확인 → 따로 동작 없음 → 5분 후 patrol 자동 시작 보임.
2. **점심 러시**: 평면도에서 로봇이 서빙 중인 거 시각화 + 큐 카드에 "서빙 2건" 표시. 빠른 모드 버튼은 모두 비활성 (priority).
3. **고객 동행 요청 자동**: POS에서 결제 → "T02로 안내 중" 토스트 + 평면도 로봇이 카운터→T02 이동.
4. **모객 시도**: 한산 시간, 모드 제어 페이지 → 모객 카드 → 페르소나 선택 → 시작. → 헤더 뱃지 ENGAGING. → 1분 후 손님 들어와서 자동 종료.
5. **저녁 마감**: 설정 페이지에서 영업시간 확인, 22시 자동 순회 정지 확인.

각 단계에서 사용자가 헤매는 부분이 없으면 통과.

### 14.2 직원 시나리오 (스마트폰)

1. 스마트폰으로 접속 → 사이드바 햄버거 → 대시보드 → 헤더에서 배터리/모드 한눈 확인.
2. 비상정지 버튼 잘 보이는지 확인.

### 14.3 안전 시나리오

1. 배터리 < 20% 강제 → 헤더 빨간 배너 표시 + 모드 버튼 비활성.
2. 비상정지 클릭 → 모달 확인 → 토스트 + 5초간 다른 모드 버튼 비활성.

---

## 15. 미해결 이슈

| # | 이슈 | 후보 |
|---|---|---|
| W1 | React/Vue 도입? | (a) 무프레임워크 (현 설계) (b) Vue 3 무빌드 |
| W2 | 모바일에서 평면도 인터랙션 (탭/줌) | (a) 단순 표시만 (b) 핀치줌 + 테이블 탭 |
| W3 | 알림(Telegram)을 OpServer가 직접? web push? | (a) OpServer가 텔레그램 봇 호출 (b) Web push API |
| W4 | KPI 차트 데이터 갱신 주기 | (a) 새로고침 시만 (b) 1분 폴링 |
| W5 | 다국어 i18n 도입 시점 | M4 이후 |
| W6 | 라이트 테마 우선순위 | M4 (M1-3은 다크만) |

---

**End of Document**
