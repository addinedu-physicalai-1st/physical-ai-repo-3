# 2026-05-16 — M3 Web Dashboard 완성 + NTP 통합 + stop_moca 보강

> 작업자: Stephen Kong (gjkong)
> 선행 회고: `docs/daily/2026-05-16_m3_dashboard_theme_iter.md` (M3 M2단계 + 테마 + 깜박임 해결)
> 다음 진행: 라이브 종합 검증 후 M4 (라이트 테마 토글 / i18n / 점주 사용자 테스트) 또는 reporter 기반 6대 NTP 통합

---

## 1. 오늘 (오후) 의 목표

본 세션 시작 시점 — M3 잔여 5 페이지 (modes / settings / events / analytics / debug)
+ stop_moca.sh 좀비 정리 보강. 진행 중 NTP 시간 동기화 안건 추가.

`moca_web_dashboard_spec.md` §13 의 M3 완성 항목 + 운영 안전 항목을 한 세션에 묶음.

## 2. 산출물 누적 (오늘 8번째 커밋 ffa86d7 이후)

### 2.1 M3w 잔여 5 페이지 본 구현

| 페이지 | 핵심 |
|---|---|
| **modes.html** | 현 모드 상태 카드 (강제 idle / 진입 1Hz / 파라미터 / 큐) + 서빙·순회·안내·모객 4 컨트롤 카드 + 수동 발화. WS set_mode/utter/skip_table/set_config + REST /command 'express' |
| **settings.html** | 운영/안전/알림/페르소나/시스템 5 섹션. 백엔드 wire-format (patrol_*/business_hours/battery_min) 활성 + alarm_dwell/텔레그램/페르소나 = M4 placeholder. **시스템 상태 카드 + NTP 영역 5행** |
| **events.html** | 카테고리 6 + 레벨 3 + 기간 3 필터 + CSV (BOM 한글) + [더 불러오기] 페이지네이션. `GET /api/v1/events` 백엔드 신설 (category/level/before/limit) |
| **analytics.html** | Chart.js 4.4.0 CDN. 4 KPI 카드 (서빙/순회/안내/모객 — `set_mode_result` WS 응답 기반 본 세션 카운트) + 도넛 (카테고리 비율) + 막대 (시간대별 0-23시) + 가로막대 (T01~T05) + 시스템 KPI dl |
| **debug.html** | dev_mode 토글 (LocalStorage) + 외부 서버 (port 8765) 2 버튼 + Raw 모드 요청 (POST /mode) + Raw WS 송신 (6 type 템플릿) + Status snapshot raw (3s 자동) + 큐 raw dump (serving/guiding/order) + Event raw stream (100건 ring) |

### 2.2 Backend 확장 (3 endpoint + 2 helper)

- **`get_status_snapshot()` 에 `uptime_sec` 1줄 추가** (settings 시스템 카드의 OpServer 가동 시간)
- **`get_events_snapshot()` 신규 helper + `GET /api/v1/events`** — in-memory deque 500 한도 안에서 category/level/before/limit 필터링
- **`GET /api/v1/ntp` 신규** — chrony 우선 (`chronyc tracking` 파싱), 미설치 시 systemd-timesyncd (`timedatectl show` + `show-timesync` 파싱). 5090 마스터 (192.168.0.133) ICMP ping reach + RTT. warnings 배열 (timesyncd 시 chrony 전환 권장 / 5090 unreachable 시 LAN 점검).

### 2.3 공통 자산

- **`js/toast.js` 신규** — 전역 `window.toast(msg, level)`. mode-buttons.js 의 _toast() 와 동일 동작이나 페이지 전역 호출 가능. modes/settings/events/analytics/debug 5개 페이지 재사용.
- **`css/components.css` 확장** — form / btn / modes-grid / settings-page + kv-list / events-page + filter-row + events-table + ev-tag + ev-cat-tag / analytics-page + kpi-grid + kpi-card + chart-grid + chart-card / debug-page + json-pre + json-grid 등 클래스 군. 기존 토큰/스타일 변경 0.

### 2.4 브랜드 / UX 변경

- **사이드바 h1 "MoCa" → "MOCA"** (7 페이지 sed 일괄, `<h1>MoCa</h1>` → `<h1>MOCA</h1>`)
- **사이드바 h1 그라데이션 단일 핑크 → 3-color PinkLAB** (`pinklabcolor.png` 참고). `135deg, #e565a8 (핑크 0%) → #6e4eb4 (보라 55%) → #3a2a5e (다크 플럼 100%)`. drop-shadow glow 도 핑크 → 보라 톤 `rgba(110, 78, 180, 0.45)`.
- **dashboard.html + tables.html cache 버전 `?v=20260516e` → `?v=20260516f`** 통일 (그라데이션 적용 누락 해결 — 두 페이지만 옛 버전 유지하여 캐시된 옛 layout.css 사용 중이었음)
- **debug.html "외부 서버 연동" 2 버튼**: `http://localhost:8765` + `http://localhost:8765/operator` (operator.html 전용 → 양쪽 진입점)

### 2.5 NTP 시간 동기화 통합

토폴로지 — 5090 서버 (192.168.0.133) 단일 master + 5 client (노트북 3 + 로봇 2):

```
[Internet NTP] (옵션)
       │
       ▼
┌─────────────────────────┐
│ 5090 서버 192.168.0.133 │  ← chrony master (allow + local stratum 8)
└────────┬────────────────┘
         │
   ┌─────┼─────┬─────┬─────┬─────┐
 노트북1  노트북2  노트북3  로봇1  로봇2
 (운영)              (192.168.0.138 Vic Pinky + 추가 1대)
```

- **`scripts/chrony/server_5090.conf`** — master 설정 (pool kr.pool.ntp.org + local stratum 8 + allow 192.168.0.0/24 + makestep 1.0 3 + rtcsync)
- **`scripts/chrony/client.conf`** — client 5대 (server 192.168.0.133 prefer + backup pool)
- **`scripts/chrony/README.md`** — 토폴로지 다이어그램 + 6대 IP 표 (확정/미정) + apply 절차 (5090 → 노트북 5대 → RPi 별도, §0-A 정책 명기) + 함정 4종 (timesyncd+chrony 동시 실행 금지 / RPi RTC 배터리 / 인터넷 단절 대비 / UDP 123 방화벽) + 향후 reporter 기반 6대 통합 표시 안내

**현 상태**: 운영 노트북 chrony 미설치 — systemd-timesyncd 사용 중. NTP 서버 `ntp.ubuntu.com (91.189.91.157)`. `/api/v1/ntp` endpoint 가 dual-path 지원하므로 chrony 전환 시점에 자동 우선 사용.

### 2.6 stop_moca.sh 좀비 정리 보강

회고 §4.2 의 50+ 좀비 사고 (mode_state publisher 11개 race) 영구 대책:

- **패턴 13 확장**: `moca/install/`, `ros2 launch`, `ros2 run dobi_npc`, `mode_manager`, `patrol_scheduler`, `guiding_controller`, `table_occupancy_detector`, `completion_watcher`, `idle_patrol_timer`, `serving_dispatcher`, `person_detector`, `follow_controller`, `minigame_runner` + opserver 3종 (`ros2 run moca_opserver`, `opserver_node`, `moca_opserver`)
- **신규 옵션**: `--with-opserver` (기본 on), `--no-opserver`, `--no-daemon`, `--dry-run` + 기존 `--with-ui`, `--quiet`
- **ros2 daemon stop/start** 자동 (stale topic/node cache cleanup)
- **검증 step 자동**:
  - `ros2 node list` 의 moca/mode_manager/opserver/patrol/guiding/serving_dispatcher/completion_watcher/idle_patrol 잔재 매칭
  - `/mode/state` Publisher count ≤ 1 자동 검증 (회고의 11개 race 실시간 감지)
- **기존 보존** ([[feedback_dont_touch_working_code]]): 카메라 점유 (`/dev/video0`, `/dev/video2`) + audio sink mute (`wpctl`) 점검
- **dry-run 라이브 검증 — 회고 §4.2 패턴 실시간 재현 발견**:
  - `mode_manager` 2쌍 (ros2 run 부모 + 자식, 4 process)
  - `opserver_node` 2쌍 (4 process)
  - `table_occupancy_detector` 1, `patrol_scheduler` 1
  - 총 10 process — 기존 패턴 (`moca/install/` + `ros2 launch dobi_npc`)으로는 `ros2 run` 부모 미매칭이었음. 보강 효과 확인됨.

## 3. 발견 / 결정

### 3.1 백엔드 wire-format vs UI placeholder 정책

`alarm_dwell_sec`, 텔레그램 토큰, 야간 자동 순회 차단, 모객 자동 종료, 기본 페르소나, 기본 voice 등은 현 ConfigRequest / WsSetConfig schema 에 미포함. settings.html 에 UI 만 두고 disabled + "M4 placeholder" 텍스트 명기. 추후 backend wire-format 확장 시 ID/이름만 활성화 — UI 재작업 없음.

원칙 — wire-format에 있는 키만 활성, 나머지는 시각 placeholder. [[feedback_dont_touch_working_code]] 정합.

### 3.2 analytics — in-session vs 영구 KPI

Chart.js KPI 4 카드 (서빙/순회/안내/모객 횟수)는 본 세션 `set_mode_result` WS 응답 카운트. 페이지 reload 시 0 으로 초기화. 일/주/월 KPI 는 영구 DB 필요 — M4. 본 회고 시점에 메모리 deque 500 한도 + client 집계 first cut 으로 시각화 가치 일부 확보.

`analytics.html` 상단 배너에 "in-session 집계 — 영구 KPI / 일·주·월 차트 / 날짜 선택은 M4 (DB + KPI endpoint)" 명기.

### 3.3 events 백엔드 endpoint — `GET /api/v1/events`

기존 백엔드는 `_events: deque(maxlen=500)` 메모리 누적 + `event_log` WS broadcast 만. 페이지네이션 endpoint 부재로 events.html 의 [더 불러오기] 불가. `get_events_snapshot()` helper + 라우터 1개 신설 (~30 줄). category/level/before/limit 4 쿼리 파라미터 + 정렬 후 limit.

deque 500 한도 안에서만 — 더 과거는 영구 DB 필요 (M4).

### 3.4 NTP 토폴로지 결정 — 5090 master 단일

5090 (192.168.0.133, NVIDIA RTX 5090 서버) 을 LAN 마스터로 두는 단순 토폴로지 채택. 이유:
- 가장 강력한 하드웨어 + 항상 켜질 가능성 + 고정 IP
- 카페 인터넷 단절 대비 — `local stratum 8` 로 LAN 내 master 역할 유지
- 클라이언트 5대는 `server 192.168.0.133 prefer` + backup pool

**대안 검토**: mesh peer / 노트북 1대 마스터 / 인터넷 stratum 1 직접 — 모두 단점 (복잡 / 안정성 / 의존성). 5090 master 단일이 가장 단순/안정.

### 3.5 `?v=20260516f` cache busting 발견 — 미스 누락 사고

modes/settings/events/analytics/debug 5 페이지는 작업 중 `?v=20260516f` 로 갱신했으나 dashboard.html + tables.html 은 `?v=20260516e` 그대로. 사용자가 tables 진입 시 캐시된 옛 layout.css 사용 → 새 3-color 그라데이션 미적용. sed 일괄 갱신으로 해결.

**교훈**: 글로벌 css 변경 시 모든 페이지의 ?v= 일괄 갱신 필요. 페이지별 patch 만 작업하다 보면 미터치 페이지 누락 가능. 다음 세션에서 cache busting 자동화 검토 (Makefile 또는 build hook).

### 3.6 systemd-timesyncd 한계 — chrony 전환 필요

현 운영 노트북: systemd-timesyncd 사용. 인터넷 NTP 의존. offset 측정 불가 (timesyncd 는 단순 sync 만 표시). LAN 내 다른 호스트와 직접 동기 불가능. 카페 인터넷 단절 시 fallback 없음.

→ 6대 모두 chrony 전환 권장 — `scripts/chrony/README.md` 절차대로 5090 master + 5 client 적용. RPi 측은 §0-A 정책 (팀 작업 중 SSH 차단) 해제 시점 적용.

### 3.7 stop_moca.sh 검증 자동화 — Publisher count

회고 §4.2 의 핵심 사고 패턴 (`/mode/state` Publisher count 11) 을 검증 step 으로 자동 감지. 정상은 0 또는 1. 2 이상이면 좀비 race — 사용자가 즉시 인지.

## 4. 빌드 / 테스트 명령

```bash
# 빌드 (clean — 신규 자산 등록 시)
cd ~/moca
bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  rm -rf build/moca_opserver install/moca_opserver
  colcon build --packages-select moca_opserver --symlink-install
'

# 전체 회귀 (UI/NTP/snapshot 작업이 ROS 모듈 영향 X 확인)
source install/setup.bash
python3 -m pytest \
  src/moca_opserver/test/test_orchestrator.py \
  src/moca_opserver/test/test_completion_and_timer.py \
  src/dobi_npc/dobi_npc_bringup/test/test_patrol_scheduler.py \
  src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py \
  src/dobi_npc/dobi_npc_bringup/test/test_guiding_controller.py
# Expected: 130 passed (본 세션 전 구간 동일)

# 브라우저 라이브 검증 (좀비 정리 후)
bash scripts/stop_moca.sh --dry-run     # 매칭 확인
bash scripts/stop_moca.sh               # 실제 정리 + 검증 자동 출력
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
ros2 run dobi_npc_bringup mode_manager &
ros2 run moca_opserver opserver_node &
sleep 5
# 브라우저: http://localhost:8800/
#   - 7 페이지 사이드바 MOCA 3-color 그라데이션
#   - modes / settings / events / analytics / debug 본 구현 동작
#   - settings → 시스템 상태 카드 → NTP 5행 (도구 / 동기 / 서버 / offset / 5090 reach)
```

## 5. 다음 단계

### 5.1 즉시
- 종합 라이브 검증 (좀비 cleanup 후 7페이지 회귀 확인)
- chrony 설치 + 5090 master 적용 + 5 client 적용 (사용자 직접 — RPi 는 §0-A 해제 시점)

### 5.2 M4 (다음 마일스톤 후보)
- 라이트 테마 토글 (data-theme="light" 이미 토큰 정의됨)
- i18n ko/en 분리
- 영구 KPI (DB + `/api/v1/kpi/*` endpoint) → analytics 일/주/월 차트
- 알림/페르소나/alarm_dwell wire-format 확장 → settings placeholder 활성
- 6대 NTP 통합 표시 (reporter or 5090 web endpoint)
- 점주 사용자 테스트 (N=3, 사용성 + 모바일 반응형)
- cache busting 자동화 (Makefile 또는 build hook)

### 5.3 운영 트랙
- 5090 서버 chrony 설정 적용 + LAN 마스터 검증 (`chronyc clients` 로 5 client 누적 확인)
- RPi 노트북 IP 확정 (현재 모두 "추후 확인")
- chronyc 출력 파싱 → `/api/v1/ntp` 결과 변화 확인

## 6. 메모리 갱신 후보

본 회고에서 새로 발견된 함정/정책 :
- **`?v=YYYYMMDDx` cache busting 누락 사고** — 5 페이지 갱신 + 2 페이지 누락 → tables.html 만 옛 css. 글로벌 css 변경 시 모든 페이지 ?v= 일괄 갱신 필요. (signal 약함 — Makefile 도입 후 메모리화)
- **`/api/v1/ntp` endpoint** — chrony / timesyncd dual-path. 운영 노트북에서 자기 자신 상태 + 5090 ping. 6대 통합은 reporter 필요.
- **stop_moca 패턴 확장 (13)** — `ros2 run` 부모 패턴이 핵심 누락. mode_manager 2쌍 같은 좀비 race 자동 검증.

기존 메모리 정합:
- `[[feedback_dont_touch_working_code]]` ✅ (백엔드 변경 최소 — uptime_sec 1줄, get_events_snapshot helper, /ntp endpoint 추가만)
- `[[feedback_relative_path_convention]]` ✅ (절대경로 0건, chrony scripts/는 상대경로)
- `[[feedback_starlette_symlink_install]]` ✅ (모든 정적 자산 chain symlink 유지)
- `[[project_navigation_code_separation]]` 무관 (UI/Backend 작업)
- `[[feedback_no_rpi_when_team_working]]` ✅ (chrony RPi 적용은 §0-A 해제 시점 명기)

## 7. 변경 통계

| 영역 | 파일 | 변경 |
|---|---|---|
| Frontend HTML | `static/pages/*.html` × 7 | 5 본 구현 (modes/settings/events/analytics/debug) + 2 cache bump (dashboard/tables) + 7 brand "MOCA" |
| Frontend CSS | `static/css/components.css` | +250줄 (form/btn/modes/settings/events/analytics/debug 클래스 군) |
| Frontend CSS | `static/css/layout.css` | sidebar__brand h1 3-color 그라데이션 |
| Frontend JS | `static/js/toast.js` | 신규 |
| Backend | `rest_api.py` | +130줄 (GET /events + GET /ntp) |
| Backend | `opserver_node.py` | +2줄 (uptime_sec + get_events_snapshot helper) |
| Scripts | `scripts/chrony/` | 신규 (server_5090.conf + client.conf + README.md) |
| Scripts | `scripts/stop_moca.sh` | 통째 rewrite (117→195줄, 패턴 13 + 4 신옵션 + daemon reset + 검증 step) |
| Docs | `docs/daily/2026-05-16_*.md` | 회고 4건 누적 (M0M1, M2 3건, M3 M1, M3 M2테마, 본 문서) |

회귀 0 (130/130 × 7회 빌드 / 각 endpoint 작업 후) · Node JS syntax OK × 5 페이지 · bash syntax OK + dry-run smoke OK (좀비 10개 실 매칭).

## 8. 라이브 검증 trail + 후속 patch (저녁 21:30~)

본 커밋 ed44425 이후 라이브 검증 중 발견된 함정 + 사용성 보강 3건. 4 Track 커밋 (5c2707f / 3ab5b6f / 920b1a2 / 605fd97) 으로 다른 트랙도 일괄 정리.

### 8.1 run_dashboard.sh / stop_dashboard.sh 신규 (한 줄 기동)

사용자가 라이브 검증을 위해 매번 `export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1 + source + ros2 run x2 + sleep 5 + 브라우저` 5 단계 수동 입력하던 흐름 → 한 줄 스크립트로 통합.

**`scripts/run_dashboard.sh`** 핵심:
- SCRIPT_DIR 기반 워크스페이스 자동 추정 (CLAUDE.md §7 상대경로 컨벤션)
- 환경 격리: `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1` (§0-A 정합)
- `setsid` 분리 spawn → 부모 셸 닫혀도 노드 유지 + stop_moca 패턴 매칭
- 로그: `<ws>/log/dashboard_<TS>/{mode_manager.log, opserver_node.log}`
- health check: `curl /api/v1/health` 5초 후
- 브라우저 chain fallback: xdg-open → sensible-browser → google-chrome → chromium → firefox
- 옵션: `--cleanup` / `--no-browser` / `--verbose` / `--port=N`

**`scripts/stop_dashboard.sh`** — `stop_moca.sh` thin wrapper (`exec bash stop_moca.sh "$@"`). 옵션 그대로 forward. run_dashboard ↔ stop_dashboard 짝.

### 8.2 set -u + ROS source 충돌 fix

라이브 실행 시 에러:
```
/opt/ros/jazzy/setup.bash: line 8: AMENT_TRACE_SETUP_FILES: unbound variable
```

**원인**: `set -u` (strict unbound var) 가 ROS setup.bash 의 `${AMENT_TRACE_SETUP_FILES}` 같은 default 없는 var 참조와 충돌.

**해결** — source 부분만 set -u 일시 해제:
```bash
set +u
source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash"
set -u
```

**부가 흐름 재정렬** — source 가 cleanup 이전 (기존엔 cleanup → source 순). stop_moca.sh 의 `command -v ros2` 검사 통과 → ros2 daemon stale cache reset + 검증 step 작동.

**향후 관련 스크립트** (run_teleop_ui.sh 등) 도 같은 패턴 적용 검토 (필요 시).

### 8.3 tables.html 🪑 이모지 잔재 제거

회고 §2.3 (`2026-05-16_m3_dashboard_theme_iter.md`) 의 이모지 27곳 일괄 제거 작업에서 누락된 마지막 1건. `tables.html:40` 의 `<h3>🪑 테이블 점유 현황</h3>` → `<h3>테이블 점유 현황</h3>`.

grep 검색 결과 다른 페이지/컴포넌트의 이모지 잔재 0건 확인.

### 8.4 라이브 검증 결과 (사용자 보고 기준)

- 사이드바 3-color 그라데이션 — tables 페이지만 미적용 → cache 버전 `?v=e → f` 통일 patch (dashboard.html + tables.html 양쪽)
- run_dashboard.sh `--cleanup` 실행 시 set -u 에러 → §8.2 fix
- tables 페이지 🪑 이모지 잔재 → §8.3 제거
- 그 외 7 페이지 (modes/settings/events/analytics/debug + dashboard/tables) 회귀 0 — 사용자 라이브 종합 검증 완료

### 8.5 4 Track 커밋 분리 (Track별)

`ed44425` (M3 + NTP + stop_moca 본 커밋) 외 본 세션 작업물 4 Track:

| Track | SHA | 제목 | 파일 |
|---|---|---|---|
| C | `5c2707f` | Nav2 sim 보조 — params + run/stop + mapv5_mocamap.pgm | 4 |
| B | `3ab5b6f` | Serving 모드 dispatcher + M0/M1/M2 OpServer 회고 | 4 |
| A | `920b1a2` | Gazebo 카페 레이아웃 — kiosk + floor_grid + 가구 6종 + walls_high | 38 |
| D | `605fd97` | 디자인 reference PNG — PinkLAB 팔레트 + 맵 top view | 8 |

**Track B 메시지 정정** (amend 금지 정책으로 message 그대로 유지) — "회고 4건" 명시했으나 실제 stat 4 파일 (Serving 본문만). 회고들은 이전 커밋 `72ccbf0` ("5-state FSM 확장 + moca_opserver scaffold + 단위 테스트") 에 이미 들어가 있어서 본 add 시점 already tracked + no diff. 본 회고가 trail.

본 §8 trail + run/stop_dashboard.sh + 이모지 patch 는 다음 세션 정리 시 별 커밋 권장.

### 8.6 ROS_DOMAIN_ID UI 표시 + 시뮬/실물 wrapper (단계 1+2)

운영 웹 UI 에서 ROS_DOMAIN_ID 상태 가시화 + Gazebo 시뮬 vs 실물 로봇 전환 wrapper.
ROS_DOMAIN_ID 는 DDS participant ID 라 런타임 UI 변경 불가 — 노드 재기동 필수.

**Backend** (`opserver_node.py`):
- `import os` 추가
- `get_status_snapshot()` 에 `environment` block 추가 — `ros_domain_id` / `localhost_only` / `hint` (MOCA_DOMAIN_HINT env var)

**Frontend** (`settings.html` 시스템 상태 카드):
- ROS_DOMAIN_ID 행 + 색 코딩 (99 시뮬 = 초록 / 22 실물 = 주황 / 미설정 = 빨강)
- ROS_LOCALHOST_ONLY 행 + 색 코딩 (1 loopback = 초록, 0 LAN broadcast = 일반)

**run_dashboard.sh `--domain=N` 옵션**:
- `--domain=99` (default) — LOCALHOST_ONLY=1 + MOCA_DOMAIN_HINT="시뮬"
- `--domain=22` — LOCALHOST_ONLY=0 + MOCA_DOMAIN_HINT="실물" + §0-A 경고 메시지

**4 wrapper 신규**:
- `scripts/run_sim.sh` — `run_nav2_sim.sh` (Gazebo + Nav2 + RViz) + `run_dashboard.sh --domain=99` 통합. 옵션: `--no-rviz` / `--no-nav2` (UI 단독 검증) / `--cleanup`
- `scripts/run_real.sh` — §0-A 정책 prompt (Vic Pinky 단독 사용 / RPi 사용 OK / collision_monitor 준비 3건) → `run_dashboard.sh --domain=22`. `--force` 로 prompt 건너뛰기 가능.
- `scripts/stop_sim.sh` — `stop_moca.sh` + `run_nav2_sim.sh --stop`
- `stop_real.sh` — `stop_moca.sh` thin wrapper

**시뮬 검증 가치**: 운영 UI 의 모든 5-state 전환 (idle/serving/patrol/guiding/engaging)을 Gazebo 만으로 실 로봇 없이 종합 검증 가능. 계획서 §10.1 자동 시나리오 + §10.2 점주 시나리오의 1차 검증 환경. 다음 단계 (별 task) — 운영 UI 자동 시나리오 러너 (pytest + httpx 또는 debug.html 시나리오 버튼).

빌드 1.71s · 회귀 130/130 · bash syntax 5/5 · snapshot environment block smoke OK.

### 8.7 브랜드 가로폭 visual 매칭 trail

사이드바 brand 영역 (h1 + p) 의 가로폭/대소문자 / 가로폭 매칭 3 단계 patch.

**Step 1 — `MOCA` → `MoCa` 롤백** (7 페이지 sed 일괄):
- 이전 sed 일괄로 `MoCa` → `MOCA` 변경했으나 사용자가 mixed-case 선호 → 롤백.
- `<title>` 의 `MOCA Dashboard` / `설정 — MOCA` 등은 의도 보존 (브라우저 탭, 검색엔진 용).

**Step 2 — sub-text 대문자화 제거**:
- 사용자 보고: "Mobile Catering Snack Bar 가 화면에 전부 대문자" — CSS `.sidebar__brand p { text-transform: uppercase }` 가 적용되어 시각상 `MOBILE CATERING SNACK BAR` 로 보임.
- `text-transform` 제거 + `letter-spacing` 0.08em → 0.04em (mixed-case 자연 자간).

**Step 3 — 가로폭 visual 매칭** (`docs/assets/mocanewdesign.png` 정합):
- 사용자 참조 이미지: `MoCa` (큰 serif) 가로폭 = `Mobile Catering Snack Bar` (작은 sans) 가로폭. 좌우 경계 정렬.
- CSS 변경:
  | 속성 | 이전 | 이후 |
  |---|---|---|
  | `.sidebar__brand` text-align | (없음) | center |
  | h1 font-size | `var(--fs-brand)` 32px | **42px** |
  | h1 letter-spacing | 0.04em | **0.14em** (sub-text 폭 매칭) |
  | h1 line-height | (기본) | 1.0 |
  | p margin-top | 4px | 2px |
  | p font-size | 11px | 11px (명시) |
  | p letter-spacing | 0.04em | 0.02em |
  | p white-space | (없음) | nowrap |

사용자 라이브 확인 — 정합 OK.

### 8.8 mapv5_mocamap.pgm archival copy 위치 정리

Track C 커밋 (5c2707f) 에서 `mapv5_mocamap.pgm` 을 repo root 에 add 했으나
디자인 자산 정리 (PNG 8건 `docs/assets/` 이동) 과 일관성 위해
`docs/assets/mapv5_mocamap.pgm` 로 이동. 실 SoT 는 `maps/mapv5_mocamap.pgm`
(Nav2 / `place_furniture_picker.py` / `run_nav2_sim.sh` 참조). `maps/` 가 .gitignore
대상이라 git tracked 본은 docs/assets/ 안 archival copy 만 남김.

---

*다음 갱신 — chrony 5090 적용 후 + 노트북/추가 로봇 IP 확정 후*
