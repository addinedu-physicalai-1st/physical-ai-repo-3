# 2026-05-21 — promo_viewer PoC: 모객 모드 매장 홍보 kiosk

> branch: `feat/engaging-analytics-migration`
> 작업자: Stephen + Claude Opus 4.7
> 시간 목표: 1시간 내 완료 (실측 ~45 분)

## 1. 한 줄 요약

모객(engaging) 모드 IDLE/APPROACH 단계에서 표시할 매장 홍보 + 미니게임 소개
6 프레임 standalone HTML + ROS 노드 kiosk viewer 신규 패키지로 PoC 완료.
**어제까지의 기존 코드 0 변경 + dashboard 무영향** 정합.

## 2. 산출물 (모두 신규)

### 2.1 자산
- `assets/promo/promo.html` — 단일 파일 standalone, 6 프레임 24초 1 사이클 무한 loop, file:// 직접 동작
  - F1 매장 환영 + 메뉴 7종 (MOCA 토스트/피자 SET + 5 음료)
  - F2 오픈 이벤트 (첫 방문 SET 시 아메리카노 공짜, 로봇 따라가기 SET 20% 할인)
  - F3 미니게임 도전 유도 (게임 승리 시 음료 10% 할인)
  - F4 가위바위보 ✌️
  - F5 스피드 카운터 🖐️
  - F6 카페 닌자 🥷
  - CSS keyframes 만 사용 (JS 0, 외부 의존 0)
  - PinkLAB 디자인 토큰 인라인 (dashboard tokens.css 미참조 = 비연동)

### 2.2 신규 패키지 `dobi_npc_promo`
```
src/dobi_npc/dobi_npc_promo/
├── package.xml        (ASCII description — CLAUDE.md §7 함정 회피)
├── setup.py
├── setup.cfg
├── resource/dobi_npc_promo
├── dobi_npc_promo/
│   ├── __init__.py
│   └── promo_viewer_node.py
└── launch/
    └── mode_engaging_promo.launch.py
```

### 2.3 promo_viewer_node 사양
- ROS 노드 + `google-chrome --kiosk --app=file://.../promo.html` subprocess wrapper
- 자가 spawn — 노드 시작 시 자동 풀스크린 표시
- 4 토픽 구독:
  - `/promo/suspend` (Empty) — 외부 suspend
  - `/promo/resume` (Empty) — 외부 resume
  - `/minigame/start` (String) — minigame 시작 자동 suspend (chrome kill)
  - `/minigame/result` (MinigameResult) — minigame 종료 자동 resume (chrome respawn)
- workspace root 자동 추정 (CLAUDE.md §7 SCRIPT_DIR 패턴)
- 파라미터: `browser_cmd`, `promo_html_path`, `kiosk`, `respawn_delay_sec`

## 3. 검증

### 3.1 빌드
- `colcon build --packages-select dobi_npc_promo --symlink-install` ✓
- import smoke ✓
- `ros2 pkg list | grep dobi_npc_promo` ✓
- `ros2 pkg executables dobi_npc_promo` → `promo_viewer` ✓

### 3.2 라이브 mock 검증 (DOMAIN=99 sim 격리)
browser_cmd=/bin/true (noop, 사용자 화면 비방해), kiosk=false 로 spawn:

| step | publish | 기대 | 실측 | 결과 |
|---|---|---|---|---|
| 0 | node spawn | promo spawn pid 출력 | pid=7544 | PASS |
| 1 | `/minigame/start "rps"` | suspended | "suspended (minigame start: rps)" | PASS |
| 2 | `/minigame/result {game_id: rps}` | resumed + new pid | new pid=7606 | PASS |
| 3 | `/promo/suspend {}` | suspended (외부) | "suspended (외부 트리거)" | PASS |
| 4 | `/promo/resume {}` | resumed (외부) + new pid | new pid=7639 | PASS |
| 5 | SIGTERM | cleanup | node terminated | PASS |

state transition 4/4 정확. 토픽 등록 4/4 정확.

### 3.3 진짜 chrome 풀스크린 라이브 검증
사용자 직접 진행 권고 (doby 작업 중 chrome kiosk 띄우면 화면 점유). 명령:
```bash
# 터미널 1 — engaging stack (이미 동작 중인 환경)
ros2 launch dobi_npc_bringup mode_engaging.launch.py
# 터미널 2 — promo viewer
ros2 launch dobi_npc_promo mode_engaging_promo.launch.py
# 터미널 3 — 동작 토글 확인
ros2 topic pub --once /minigame/start std_msgs/String "{data: rps}"
ros2 topic pub --once /minigame/result dobi_npc_msgs/MinigameResult "{...}"
```

## 4. 기존 코드 0 변경 정합

| 영역 | 변경 |
|---|---|
| `src/moca_opserver/*` (dashboard) | **0** |
| `static/*` (대시보드 페이지/JS/CSS) | **0** |
| `src/dobi_npc/dobi_npc_dialog/*` (face_avatar 포함) | **0** |
| `src/dobi_npc/dobi_npc_minigame/*` (minigame_runner) | **0** |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_engaging.launch.py` | **0** |
| `src/shared/vic_pinky/*` (§0-B) | **0** |
| 신규 `src/dobi_npc/dobi_npc_promo/*` | 신규 패키지 |
| 신규 `assets/promo/promo.html` | 신규 자산 |
| 신규 본 회고 | 신규 docs |

`git status --short` 기준 본 PoC 가 만든 신규 파일만 추가됨. modified 0.

## 5. 통합 (사용자 직접 실행)

```bash
# 한 번만
moca_build  # 또는 colcon build --packages-select dobi_npc_promo --symlink-install
moca_activate

# 모객 모드 진입 시
ros2 launch dobi_npc_bringup mode_engaging.launch.py &
ros2 launch dobi_npc_promo mode_engaging_promo.launch.py &
```

자동 동작:
- engaging 모드 진입 즉시 → chrome kiosk 풀스크린 promo
- BT funnel 이 MINIGAME 단계 진입 → `/minigame/start` 발행 → chrome kill (face_avatar / minigame_runner 풀스크린 노출)
- minigame 종료 → `/minigame/result` 발행 → chrome 다시 spawn → promo 복귀
- 이 사이클이 모객 모드 동안 반복

## 6. 한계 / 후속

### 6.1 PoC 범위 내
- ICEBREAK / OFFER / LEAD-IN 단계에서도 promo 가 계속 표시됨 (사용자 D3 정합 — IDLE/APPROACH + MINIGAME 만 명시, 나머지 추후 세분화)
- chrome spawn/kill 시 1-2 초 로딩 깜빡임 (kiosk 패턴 한계, 사용자 D6 정합)

### 6.2 추후 트리거 세분화 (사용자 명시 후속)
- `/dialog/request` (stage_id="icebreak") 받으면 promo suspend → face_avatar 노출
- LEAD-IN 끝 + IDLE 복귀 시 promo resume
- 또는 새 `/bt/stage_id` 토픽 신설 + BT XML 에서 stage 직접 발행

### 6.3 회귀 카탈로그 (보류)
- v1 회귀 supervisor 변경 commit 금지 정책 ([[feedback_test_supervisor_v1_no_commit]]) 정합으로
  catalog.yaml 추가는 v1 검증 해제 후 진행

## 7. 다음 step 후보

- promo HTML 톤/카피 사용자 확인 (file:// 또는 mode_engaging_promo.launch 직접)
- 사용자 OK 시 본 PoC 의 mode_engaging.launch 통합 (어제까지 코드 변경 제약 해제 시점에)
- ICEBREAK 트리거 세분화 (Track D 후보)
- 한 cycle 의 길이 / 프레임 timing 조정 (현 4초 hold + 0.6초 fade)
