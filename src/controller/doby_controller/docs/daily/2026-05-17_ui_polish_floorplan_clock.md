# 2026-05-17 — UI 정리 (floorplan 교체/반응형 + header-clock 날짜 + dashboard 카드 텍스트)

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_ui_scenarios_fullstack.md` (전날 시작 — pytest 시나리오 작업)
> 본 회고: 2026-05-17 자정 직후~새벽 UI 마감 작업 (커밋 e361a19 ~ dcf18e6, 7건)

---

## 1. 본 세션 범위

전날 (2026-05-16) 시작한 pytest 시나리오 작업이 자정 넘어 17일 새벽까지 이어짐 (commit 8dadfea ~ 497a827 → §2026-05-16 회고 §1-15 누적). 그 후 UI 마감 작업으로 전환 — Dashboard 텍스트/평면도/시계.

총 7 commit (e361a19 ~ dcf18e6).

## 2. 산출물

### 2.1 Dashboard 빠른 모드 + /modes 카드 텍스트 (commit e361a19)

`mode-buttons.js` 의 모드별 desc 라벨 + `modes.html` 의 카드 설명 갱신:

| 위치 | 이전 | 이후 |
|---|---|---|
| 순회 desc (양쪽) | `5 테이블 1회 sweep` | `5 테이블 1회 patrol` |
| 모객 desc (mode-buttons 작은 카드) | `한산 시 호객` | `빈 테이블 50% 이상 시,<br>모객 시작` (줄바꿈 — 작은 카드) |
| 모객 desc (modes.html 큰 카드) | `한산 시 페르소나로 모객 발화` | `빈 테이블 50% 이상 시, 모객 시작` (한 줄) |

메모리 정합:
- `[[feedback_terminology_mogaek]]` — 호객→모객 잔재 제거
- `[[feedback_cache_busting_global_bump]]` — 7 페이지 `?v=20260516f → 20260517a` 일괄

### 2.2 매장 평면도 floorplan.svg → tview.png 교체 (commit edd28be + bcd9993)

`docs/assets/tview.png` (1251×788, home + T01~T05 위치 라벨 포함 top-view) 로 교체.

**손실**: 이전 floorplan.svg 의 동적 마커 (robot tracking + 테이블 occupancy 색상) 제거. tview.png 가 정적 이미지라 store 바인딩 불가.

**복구 경로** (필요 시 후속):
- tview.png 위에 SVG/Canvas overlay 추가
- `tables.yaml` world 좌표 → tview.png 픽셀 좌표 매핑 (1251×788, projection 미확정)
- 이전 store 바인딩 (`store.on('robot_pose')`, `store.on('tables')`) 복원

**보존**: `static/assets/floorplan.svg` 자체는 삭제 안 함 (M4 정리 후보, 동적 마커 복구 시 참고).

### 2.3 floorplan 반응형 + 깨짐 fix (commits db46b44 + 5f68a4c)

**첫 시도 (db46b44)**: `aspect-ratio: 1251/788` + `width:100%` + `max-height:70vh` + `padding` 조합. 사용자 라이브 검증 시 **깨짐** 보고.

**실패 원인**: aspect-ratio + max-height + padding 의 box 계산 충돌. 브라우저별 다른 layout 결과.

**Fix (5f68a4c)**: aspect-ratio 제거, img 자체 비율 유지 방식으로 단순화:
```css
floorplan-view img {
  width: 100%;
  height: auto;        /* 폭 기준 비율 자동 */
  max-height: 70vh;
  object-fit: contain;
}
```

같은 commit 에서 **404 함정 해결**: src/ 에만 카피된 신규 tview.png 가 `install/share/moca_opserver/static/assets/` 에 symlink 미생성 → 404. `colcon build --packages-select moca_opserver --symlink-install` 으로 신규 자산 symlink 자동 생성.

→ 메모리 [[feedback_new_static_asset_needs_rebuild]] 신설.

### 2.4 header-clock 날짜 prefix (commit 47bcdaa)

기존 `HH:MM:SS` → `YYYY-MM-DD HH:MM:SS` (시스템 시계 기반 동적 — 자정 후 자동 갱신). 1Hz setInterval 유지.

CSS 너비 제약 없음 (font-mono + var(--fs-base)) — overflow 우려 없음.

### 2.5 tview.png 재갱신 (commit dcf18e6)

사용자가 docs/assets/tview.png 재업로드 (1485791 bytes, 이전 1484123). symlink chain (install → build → src) 살아있어 src/ 만 카피하면 즉시 반영 (rebuild 불필요 — 새 파일 아니라 기존 파일 갱신).

`docs/assets/tview (Copy).png` (이전 버전 백업) 도 같이 add — 사용자 결정으로 유지.

## 3. 발견 / 결정

### 3.1 ⚠ 신규 정적 자산 추가 시 colcon build 필수

기존 `[[feedback_starlette_symlink_install]]` 은 follow_symlink=True 가 필요한 chain symlink 보안 거부 문제. 본 세션 발견은 **다른 문제**:
- `--symlink-install` 은 빌드 시점의 파일만 install/ 에 symlink. 신규 파일은 rebuild 안 하면 install/ 에 등록 X → 404.
- 기존 파일 텍스트 편집은 즉시 반영 (symlink 통과). 신규 추가만 함정.

→ 메모리 [[feedback_new_static_asset_needs_rebuild]] 신설.

### 3.2 aspect-ratio + img 의 단순화 원칙

`aspect-ratio` CSS 속성은 width/height/padding/max-* 조합 시 브라우저별 layout 차이. 이미지 컨테이너는 **img 자체 비율 유지 (width:100% + height:auto + object-fit:contain)** 가 가장 robust. 부모는 padding 만, aspect-ratio 부여 X.

### 3.3 동적 마커 복구는 M4 후보

tview.png 정적 교체로 robot tracking + 테이블 점유 색상 손실. 운영 우선순위 낮으므로 M4 후보. 복구 시 픽셀 매핑 + SVG overlay 패턴 필요.

### 3.4 시간 표시 — 시스템 시계 기반 동적

`Date()` 호출이 클라이언트 브라우저 시계 기준. 다중 PC 운영 시 NTP 동기화 중요 (이미 메모리 [[project_ntp_topology_5090_master]] 정합).

## 4. 변경 통계 (본 세션 7 commit)

| 커밋 | 영역 | 파일 | 변경 |
|---|---|---|---|
| e361a19 | UI 텍스트 | mode-buttons.js + modes.html + 7 페이지 cache | +95/-95 |
| edd28be | 평면도 자산 | tview.png 카피 + floorplan-view.js + CSS + 7 페이지 cache | +106/-172 |
| bcd9993 | 평면도 주석 | floorplan-view.js alt 라벨 + 7 페이지 cache | +93/-93 |
| db46b44 | 평면도 반응형 (1차, 깨짐) | floorplan CSS + 7 페이지 cache | +97/-94 |
| 5f68a4c | 평면도 404+깨짐 fix | floorplan CSS + 7 페이지 cache | +99/-99 |
| 47bcdaa | header-clock | header-clock.js + 7 페이지 cache | +96/-93 |
| dcf18e6 | tview.png 재갱신 | tview.png + (Copy).png + 7 페이지 cache | +92/-92 |

빌드: colcon `--packages-select moca_opserver --symlink-install` 1회 (신규 tview.png 등록). unit 회귀 없음 (UI 작업 ROS 모듈 영향 X).

## 5. 메모리 갱신

- **신설**: `[[feedback_new_static_asset_needs_rebuild]]` (신규 정적 자산 → colcon build)
- **정합 확인**: `[[feedback_starlette_symlink_install]]`, `[[feedback_cache_busting_global_bump]]`, `[[feedback_terminology_mogaek]]`, `[[feedback_dont_touch_working_code]]`

MEMORY.md index 1행 추가.

## 6. 다음 단계 (M4 후보)

- **floorplan 동적 마커 복구** — tview.png 위 SVG overlay + 픽셀 매핑 + store 바인딩 복원
- **floorplan.svg 정리** — 더 이상 사용 X, 삭제 검토
- **alarm_dwell teardown 최적화** — 시나리오 _ensure_idle 의 7s safety 대기 누적 단축 (test-only `clear_alarm` endpoint)
- **cache busting 자동화** — Makefile 또는 build hook (현 7 페이지 일괄 sed 수동)
- **NTP 6대 통합** — chrony 5090 master + 클라이언트 5대 적용 (RPi §0-A 해제 시점)

## 7. 본 일자 (2026-05-17) 누적 — 작업 통계

전날 23:50+ ~ 본 일자 02:20 (~약 2.5시간)
- pytest 시나리오 마감 작업: 9 commits (8dadfea ~ 497a827) — 2026-05-16 회고 §1-15 정합
- UI 마감 작업: 7 commits (e361a19 ~ dcf18e6) — 본 회고

**시나리오 PASS 비율 67% → 100%** (의도 skip 0, flake 0). M3 운영 UI 자동 시나리오 러너 완성.
**UI 마감**: 평면도 교체 + 반응형 + 시계 + 카드 텍스트 정리.

---

*다음 갱신 — M4 시작 시점 또는 위 후보 진행 시*
