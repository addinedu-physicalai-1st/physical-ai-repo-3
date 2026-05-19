# 2026-05-16 — M3 Web Dashboard M1 골격 (사이드바/헤더 + WS 연동)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m2_opserver_completion_watcher.md`
> 선행 문서: `docs/moca_web_dashboard_spec.md` v1.0
> 다음 진행: M2-단계 (평면도 SVG + 빠른 모드 + 이벤트 피드)

---

## 1. 오늘의 목표

`moca_web_dashboard_spec.md` 의 **M1 골격 범위**:
- 디렉토리 구조 + 정적 자산 placeholder
- 사이드바 + 헤더 (공통 컴포넌트)
- dashboard.html (모드 뱃지 + 배터리만, WS 연동 검증)
- ws.js + store.js 핵심 모듈
- FastAPI static mount

사용자 결정: **`moca_opserver` 안에 static 디렉토리 통합** (별 `moca_web` 패키지 만들지 않음).

## 2. 산출물

### 2.1 디렉토리 구조 (`src/moca_opserver/static/`)

```
static/
├── index.html                       # /static/pages/dashboard.html 로 redirect
├── pages/
│   ├── dashboard.html               # 메인 대시보드 (M1 골격)
│   ├── modes.html                   # placeholder (M3)
│   ├── tables.html                  # placeholder (M2)
│   ├── events.html                  # placeholder (M3)
│   ├── analytics.html               # placeholder (M3)
│   ├── settings.html                # placeholder (M3)
│   └── debug.html                   # placeholder (M3)
├── components/
│   ├── mode-badge.js                # 모드 뱃지 web component
│   ├── battery-gauge.js             # 배터리 게이지 web component
│   ├── safety-indicator.js          # 안전/온라인 표시
│   └── header-clock.js              # 1Hz 시계
├── js/
│   ├── utils.js                     # formatTime / formatRelative / clamp
│   ├── ws.js                        # WSClient (auto-reconnect 지수 백오프 1→30s)
│   ├── store.js                     # vanilla pub-sub 상태 관리
│   └── api.js                       # REST fetch wrapper
├── css/
│   ├── tokens.css                   # 디자인 토큰 (다크 + PinkLAB 컬러)
│   ├── reset.css                    # 최소 리셋
│   ├── layout.css                   # 사이드바 + 헤더 + grid 반응형
│   └── components.css               # 공통 컴포넌트 스타일
└── assets/
    └── icons/                       # M2/M3 SVG 아이콘
```

### 2.2 FastAPI 정적 mount (rest_api.py 확장)

```python
app.mount(
    '/static',
    StaticFiles(directory=static_dir, html=True, follow_symlink=True),
    name='static')

@app.get('/')
def root_redirect():
    return RedirectResponse(url='/static/pages/dashboard.html', status_code=307)
```

**경로 prefix**: `/static/*` — API 라우터 `/api/v1/*` 와 WebSocket `/ws/dashboard` 와 공존.

**static_dir resolve 3단** (`_resolve_static_dir`):
1. 환경변수 `MOCA_WEB_STATIC_DIR`
2. `ament_index_python.packages.get_package_share_directory('moca_opserver') + '/static'`
3. fallback: 본 파일 위치 → `../static` (symlink-install dev)

### 2.3 setup.py data_files 확장

```python
(os.path.join('share', package_name, 'static'), glob('static/*.html')),
(os.path.join('share', package_name, 'static', 'pages'), glob('static/pages/*.html')),
(os.path.join('share', package_name, 'static', 'components'), glob('static/components/*.js')),
(os.path.join('share', package_name, 'static', 'js'), glob('static/js/*.js')),
(os.path.join('share', package_name, 'static', 'css'), glob('static/css/*.css')),
# ... assets, icons
```

colcon `--symlink-install` 환경에서 chain symlink: `install/.../file.html → build/.../file.html → src/.../file.html`.

### 2.4 디자인 시스템 — `tokens.css`

다크 테마 기본 + PinkLAB 브랜드:
- `--pink-primary: #ff6b9d` / `--pink-soft: #ffb3cf` / `--coral: #ff8c7a`
- 모드 뱃지: idle 회색 / serving 초록 / patrol 파랑 / guiding 노랑 / engaging 핑크 / offline 빨강
- 폰트: Pretendard + Noto Sans KR (한글 가독성) + JetBrains Mono (숫자)
- `--space-{1-8}` + `--radius-{sm,md,lg}` + `--shadow-{sm,md}` + `--fs-{xs-2xl}`
- 라이트 테마 토글: `[data-theme="light"]` (M4)

### 2.5 JS 인프라

**`ws.js`** — WSClient 클래스:
- WebSocket auto-reconnect (지수 백오프 1→30s)
- `on(type, callback)` / `send(obj)` 패턴
- `*` wildcard handler 지원
- `ws:open` / `ws:close` 이벤트

**`store.js`** — Store 클래스 (pub-sub):
- `state`: mode / battery / robot_pose / online / serving / patrol / guiding / tables / events / welcome / alarm
- `set(key, val)` → 구독자 콜백 일괄 호출
- `on(key, cb)` 구독 시 현 값 즉시 callback
- WS 이벤트 → store 자동 갱신 (wsClient.on 등록)
- events ring buffer 200 limit

**`api.js`** — fetch wrapper (`api.get(path)`, `api.post(path, body)`)

**`utils.js`** — formatTime / formatRelative / clamp

### 2.6 Web Components 4종

모두 `customElements.define()` 패턴. `store.on(key, cb)` 자동 구독.

| 컴포넌트 | 책임 | 데이터 소스 |
|---|---|---|
| `<mode-badge>` | 현재 모드 색상 + 시각 표시 (idle/serving/patrol/guiding/engaging/offline) | `store.mode` + `store.online` |
| `<battery-gauge>` | % 게이지 + 색상 (ok ≥ 30% / low / critical < 20% / unknown) | `store.battery` |
| `<safety-indicator>` | 안전/알람/오프라인 표시 | `store.mode.safety_ok` + `store.online` |
| `<header-clock>` | 1Hz 갱신 시계 (`setInterval`) | (자체 timer) |

### 2.7 페이지 7종

| 페이지 | 단계 | 내용 |
|---|---|---|
| `dashboard.html` | **M1 구현** | 헤더 + 사이드바 + placeholder main (모드 뱃지/배터리 WS 검증) |
| 6 다른 페이지 | placeholder | 사이드바 + 헤더만 (active 표시) — 네비 작동 검증 |
| `index.html` | redirect | `<meta http-equiv="refresh" content="0; url=/static/pages/dashboard.html">` |

### 2.8 사이드바 + 헤더 (공통)

**사이드바** (220px 데스크톱 / 60px 태블릿 / 모바일 햄버거 stretch):
- 🤖 MOCA 로고 + Dobi Barista 서브 텍스트
- 7 네비 (대시보드/모드제어/테이블/이벤트/통계/설정/디버그)
- footer 상태 (● 로봇 온라인/끊김 + 🔋 배터리%)

**헤더**:
- `<mode-badge>` + `<battery-gauge>` + `<safety-indicator>` + `<header-clock>`
- 오프라인 시 빨간 배경

## 3. 발견 / 결정

### 3.1 ★ `app.mount("/", ...)` Starlette 함정

처음 spec §11.3 의 `app.mount("/", StaticFiles(directory=..., html=True))` 패턴 따랐으나 **404**.

**원인**: Starlette 의 `app.mount('/', ...)` 가 내부적으로 `path=''` 로 등록.
빈 prefix 의 sub-path 매칭이 실패 (empty prefix 의 Mount.matches 동작 불일치).

**해결**: `/static` 명시 prefix 로 변경.
```python
app.mount('/static', StaticFiles(directory=...), name='static')
```

영향: 모든 HTML 안의 자산 URL 일괄 sed 치환 (`href="/css/"` → `href="/static/css/"` 등).

### 3.2 ★ `StaticFiles` symlink 보안 거부 → `follow_symlink=True` 필수

mount 자체는 성공했지만 모든 GET 가 404. routes 검사로 Mount 등록 확인 + install 트리에 파일 존재 확인. 그러나 404.

**원인**: Starlette `StaticFiles` 가 보안상 symlink 의 외부 target 거부 (`os.path.commonpath` 검사). colcon symlink-install 환경에서 chain symlink (`install/... → build/... → src/...`) 의 실 target 이 mount directory 밖.

**해결**: Starlette 1.0+ 의 `follow_symlink=True` 인자.
```python
StaticFiles(directory=..., html=True, follow_symlink=True)
```

본 함정은 **`feedback_starlette_symlink_install`** 메모리 후보. ROS2 ament_python symlink-install + StaticFiles 조합에서 일관되게 발생.

### 3.3 디버그 print 보존

`build_fastapi_app` 안의 `print(f'[moca_opserver] static mounted ...', flush=True)` 를 ros2 노드 logger 대신 print 로 유지. 이유: uvicorn 의 별 thread 에서 `log = logging.getLogger(__name__)` 가 ros2 stdout 으로 routing 안 됨. print + flush 가 가장 신뢰성 있음.

### 3.4 무프레임워크 (vanilla JS + Web Components)

spec §11.1 결정 그대로. React/Vue 미사용. Web Component 의 `customElements.define()` + `store.on()` 패턴이 점주용 단순 UI 에 충분. 빌드 도구 없음 — 정적 파일 직접 serving.

### 3.5 캐시 무효화: `?v=YYYYMMDD`

각 HTML 의 CSS/JS link 에 `?v=20260516` query string. 수동 갱신 (M3+ 자동화).

### 3.6 [[feedback_dont_touch_working_code]] / [[feedback_relative_path_convention]] 정합

- 기존 opserver_node.py / mode_orchestrator / 등 무수정 — rest_api.py 의 build_fastapi_app 끝부분만 추가
- 절대경로 0건 — `_resolve_static_dir()` 가 ament_index → workspace 추정 → env 우선
- 단위 테스트 회귀 — 130/130 PASS (UI 작업이 기존 모듈 영향 0)

## 4. 빌드 / 테스트 명령

```bash
# 빌드 (clean 권장 — 새 data_files 등록 시점)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  rm -rf build/moca_opserver install/moca_opserver
  colcon build --packages-select moca_opserver --symlink-install
'

# 전체 회귀
source install/setup.bash
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/moca_opserver/test/test_completion_and_timer.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py

# 브라우저 스모크
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 run dobi_npc_bringup mode_manager &
ros2 run moca_opserver opserver_node &
sleep 5
# 브라우저: http://localhost:8800/
#   - 자동 리다이렉트 → /static/pages/dashboard.html
#   - 헤더에 모드 뱃지/배터리/안전/시계 실시간 표시
#   - 사이드바 네비 → 6 placeholder 페이지
```

## 5. spec §13 로드맵 진행

### M1 (본 회고에서 완료) ✅
- [x] 디렉토리 구조 생성, 정적 파일 placeholder
- [x] 사이드바 + 헤더 컴포넌트
- [x] dashboard.html: 모드 뱃지 + 배터리만 (WS 연동 검증)
- [x] ws.js, store.js 핵심 모듈
- [x] FastAPI static mount

### M2 (다음)
- [ ] 평면도 SVG (`static/assets/floorplan.svg`) + 로봇 마커 (`/odom` → SVG transform)
- [ ] 테이블 카드 (5개) + occupancy 색상 (table-card.js)
- [ ] dashboard 이벤트 피드 (event-feed.js)
- [ ] tables.html 완성 (그리드 카드 + occupancy 통계)
- [ ] 빠른 모드 5 버튼 (확인 모달 + WS send_mode)

### M3 (완성)
- [ ] modes.html (5 카드 컨트롤 + 발화 입력)
- [ ] events.html + CSV 내보내기
- [ ] analytics.html (Chart.js)
- [ ] settings.html (config API)
- [ ] debug.html (기존 operator.html 흡수)
- [ ] 모바일 반응형 검수

## 6. 다음 단계

### 6.1 즉시

- 회고 + 백업 + 커밋 (오늘 7번째 마무리)

### 6.2 M3 W M2 단계 진입 (다음 세션 또는 이어서)

- floorplan.svg 디자인 (tables.yaml 좌표 매핑) — viewBox 28×16 m
- robot_pose → SVG transform 1Hz 갱신
- TableCard web component + occupancy 색상 매핑 (empty/occupied/finished/unknown)
- EventFeed web component (최근 200건 store.events ring buffer)
- 빠른 모드 5 버튼 + ConfirmModal + PersonaModal + TableSelectModal

### 6.3 W1 미해결 — React/Vue 도입?

(a) 무프레임워크 (M1 채택) ✅. M3 까지 유지. 점주용 UI 복잡도가 낮아 충분.

## 7. 메모리 갱신 제안

- `[[feedback_starlette_symlink_install]]` 신규 — colcon `--symlink-install` 환경에서
  Starlette `StaticFiles` 사용 시 `follow_symlink=True` 필수. chain symlink 의 외부
  target 보안 거부.
- `[[feedback_starlette_mount_root]]` 신규 — `app.mount('/', ...)` 패턴은 `path=''` 로
  등록되어 sub-path 매칭 실패. `/static` 같은 명시 prefix 사용.

기존 메모리 정합:
- `[[feedback_dont_touch_working_code]]` ✅
- `[[feedback_relative_path_convention]]` ✅ (`_resolve_static_dir` env > ament > workspace 추정)
- `[[project_navigation_code_separation]]` 무관 (UI 작업)

---

*다음 갱신: M3 dashboard M2 단계 (평면도 + 빠른 모드 + 이벤트 피드) 진입 후*
