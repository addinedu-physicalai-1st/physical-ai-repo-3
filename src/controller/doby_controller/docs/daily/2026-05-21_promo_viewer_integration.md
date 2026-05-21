# 2026-05-21 — promo_viewer 통합: face_avatar ↔ promo ↔ minigame 사이클

> branch: `feat/engaging-analytics-migration`
> 작업자: Stephen + Claude Opus 4.7
> 선행: `2026-05-21_promo_viewer_poc.md` (PoC + mock 검증)

## 1. 한 줄 요약

promo_viewer 를 engaging 모드 통합 — BT funnel stage 에 따라 단일 디스플레이를
promo(chrome kiosk) ↔ face_avatar ↔ minigame 시간 분할. DOMAIN=22 라이브에서
한 사이클 화면 검증 완료.

## 2. 통합 단계 (S1-S4)

- **S1** promo_viewer 점검 + watchdog 버전 재작성 + DOMAIN=99 mock 검증 (6 콜백)
- **S2** bt_executor 부재 진단 → **stale build** 확인 → `dobi_npc_bt` 재빌드
- **S3** face_avatar 단독 기동
- **S4** DOMAIN=22 라이브 — promo→face→minigame→face→promo 사이클 화면 검증

## 3. 발견 + 수정

### 3.1 bt_executor stale build (S2)
`cafe_funnel_v1.xml` IdleScan 의 `stable_frames` 포트가 빌드에 미반영 →
`Failed to create tree`. install 빌드(05-19) < src 수정(05-20). **재빌드로 해결**
(코드 0 변경 — 컴파일만, "어제 코드 수정 금지" 정합).

### 3.2 Approach lost timeout — funnel 자동 진행 막힘
IdleScan SUCCESS 후 Approach 가 `lost timeout 2.0s` FAILURE 반복.
BoT-SORT track_id 가 끊겼다 재할당(`customer_id 1→2`)되는데 Approach BT 노드는
고정 track_id 추적이라 track 을 잃음. **기존 코드(Approach↔person_tracking) 통합
이슈 — doby 수정 금지 영역.** funnel 자동 진행 대신 stage 토픽 수동 publish 로
promo_viewer 검증.

### 3.3 promo_viewer_node.py 수정 (신규 패키지 코드 — 수정 허용)
- **`--kiosk` 전체화면**: `--app=URL` 은 앱 윈도우(작은 창)라 `--kiosk` 와 충돌.
  `--kiosk --start-fullscreen` + positional URL 로 교체.
- **`_kill` 잔재 정리**: chrome 멀티프로세스 — 메인이 SIGTERM 에 죽어도
  renderer/gpu 자식이 남음. `killpg SIGKILL` + `pkill -9 -f user-data-dir=...`
  추가로 확실히 정리.
- **face_avatar suspend/resume 통합**: promo_viewer 가 promo chrome 만 제어하면
  face_avatar 와 z-order 조율 안 됨. `/face_avatar/suspend|resume` (minigame_runner
  와 동일 인터페이스, resume 시 wmctrl raise) 를 promo_viewer 가 발행.
  `_enter_promo` → face suspend / `_enter_dialog` → face resume.
- **`/dialog/request` 구독 + watchdog**: IdleScan/Approach 는 토픽 미발행이라
  '무활동' 으로 간접 감지. `idle_resume_sec` 무활동 시 promo 복귀.

### 3.4 pkill 자기 명령 라인 매치 (exit 144)
`pkill -f 'dobi_npc_promo'` 가 자기 Bash 명령 라인(패턴 문자열 포함)을 매치해
부모 셸을 죽임 → exit 144. 패턴 첫 글자를 `[d]obi_npc_promo` 로 감싸 회피.
`rm -rf /tmp/moca_promo_chrome` 처럼 경로에 raw 문자열이 있으면 같은 명령의
pkill 이 그것도 매치 → pkill 과 rm 명령 분리. [[feedback_pkill_bre_substring_trap]]
의 다른 측면 — alternation 뿐 아니라 self-match 함정.

### 3.5 watchdog 타이밍
`idle_resume_sec=8` (기본) 은 실제 BT funnel stage 간격엔 맞지만, 수동 publish
검증에선 단계 사이 시간이 길어 watchdog 가 중간에 promo 복귀. 수동 검증 시
`idle_resume_sec=99999` 로 사실상 비활성.

### 3.6 promo 단계 음성 (tts_node 발화)
사용자 결정 — promo 음성도 tts_node 로 (face_avatar 와 동일 엔진). promo_viewer
가 `_enter_promo` 시 `/dialog/utter` (UtterRequest) 직접 발행 → tts_node 발화.
1회 요약 멘트 (`promo_utter_text` 파라미터, 기본 128자), promo 단계 진입 시 1회.
겹침 방지 — tts_node 는 새 utter 수신 시 interrupt(현 재생 즉시 중단)하므로
IceBreak 의 face 멘트가 promo 멘트를 자동 중단. dialog_router 는 즉시중단
미구현(코드 주석)이라 dialog_router 우회해 `/dialog/utter` 직접 발행. tts_node 의
빈 텍스트는 skip 되므로 빈 텍스트 중단은 불가 — face 멘트 interrupt 에 의존.
face_avatar 단계 음성은 기존 tts 체인(persona_manager → dialog_router →
tts_node) 그대로 — 통합 기동 시 함께 spawn 필요.

## 4. 검증

### 4.1 S1 mock (DOMAIN=99, browser=/bin/true)
6 콜백 — dialog/minigame start/minigame result/watchdog/promo suspend/resume 전수 PASS.

### 4.2 S4 라이브 (DOMAIN=22, 수동 publish, idle_resume_sec=99999)
| 단계 | 트리거 | 결과 | 화면 확인 |
|---|---|---|---|
| 1 | `/dialog/request icebreak` | promo kill, face_avatar resumed | "보여" ✓ |
| 2 | `/minigame/start rps` | minigame 단계, minigame_runner 게임 | "게임 잘 넘어갔어" ✓ |
| 3 | `/minigame/result` | minigame 종료 → face_avatar | (자동) ✓ |
| 4 | `/promo/resume` | promo spawn, face_avatar suspended | "promo 잘 떴어" ✓ |

face_avatar 로그의 `display suspended`/`display resumed` 쌍이 z-order 조율 증거.

### 4.3 한계
- funnel 자동 진행은 §3.2 (Approach track_id) 로 막힘 — stage 토픽 수동 publish 로 검증
- minigame 게임은 게임 카메라(`/dev/video2`) 부재로 ~9초 후 종료 — promo_viewer
  전환은 정상
- `ros2 topic pub --once` DDS discovery 불안정 — `-t 3` 다회 publish 로 보강

### 4.4 음성 라이브 검증 (환경 재구축 후, DOMAIN=22)
전체 스택 재구축 — dashboard + 인지(geva/v4l2/rapport) + 음성 체인
(persona_manager/dialog_router/tts_node) + face_avatar + engaging stack +
promo_viewer. tts_node 로그 기준:
- **promo 음성**: `speak [promo/promo/ko-KR-SunHiNeural]` — promo_viewer →
  `/dialog/utter` → tts 발화 (약 25초 멘트) ✓
- **face_avatar 음성**: `speak [casual_browser/icebreak/.../face=hello]` —
  persona_manager → dialog_router → tts 발화 + face 표정 ✓
- **겹침 방지**: promo 멘트 `speak` 후 `utter_done` 없이 face 멘트 `speak` —
  tts_node interrupt 가 promo 멘트를 중단 ✓
4항목 모두 사용자 청취/화면 확인 완료.

### 4.5 데모 영상 녹화

`ffmpeg x11grab` + `@DEFAULT_MONITOR@` 음성 캡처. 듀얼 모니터 — eDP(노트북,
primary) 1920x1080 @0,0 + HDMI 확장 @1920,0. ffmpeg 캡처 = eDP.

**(a) Dashboard UI 데모** — dashboard 모객 분석(카메라 앞 V/A 라이브) →
face_avatar → 카페닌자 → face_avatar → promo. 69초, H.264/AAC.
터미널 노출 차단: 검은 배경 chrome z-order 하단 + dashboard chrome `wmctrl`
minimize/복원. 사용자가 영구 위치로 이동 완료.

**(b) 카페닌자 게임 플레이** — game.py 단독 풀스크린(eDP 0,0 1920x1080).
앞 13초(카운트다운+game.py 로딩) 트림 → 19초. `/tmp/moca_ninja_demo_trim.mp4`.
터미널 노출 차단: 터미널을 HDMI 확장 모니터로 이동.

**영상 촬영 교훈**:
- chrome kiosk 는 강한 최상위 — 검은 배경용 chrome kiosk 가 오히려 pygame
  콘텐츠(face_avatar/게임)를 덮음. 터미널을 캡처 영역 밖으로 옮기는 방식이 안전.
- 듀얼 모니터 — ffmpeg 캡처 영역과 콘텐츠 풀스크린 모니터가 일치해야 하고,
  터미널 등 불필요 창은 캡처 영역(eDP) 밖(HDMI)으로 이동.
- `pkill -f` 패턴이 명령 자신의 문자열(echo 메시지·rm 경로의 raw 단어)을
  매치하면 부모 셸을 죽임(exit 144/1). `[첫글자]` 묶기 또는 pkill/rm 명령
  분리로 회피.

### 4.6 game.py 카메라 인덱스 버그 (영상 촬영 중 발견)
카페닌자 `game.py` 가 `--camera-index` 를 파싱(line 654)만 하고 실제로는
`cv2.VideoCapture(0)` (line 182) 으로 video0 고정. minigame_runner 가
`--camera-index 2` 를 줘도 무시 → geva 입력용 v4l2_camera(video0)와 충돌 →
busy → 게임 crash('카운트만 하고 끝남'). 본 세션은 게임 영상 촬영을 위해
v4l2_camera 를 잠시 종료(video0 해제)해 우회. `game.py` 는 어제까지 코드라
미수정 — §6 후속.

## 5. 기존 코드 0 변경 정합

| 영역 | 변경 |
|---|---|
| `dobi_npc_promo/*` (promo_viewer) | 신규 패키지 (수정 허용) |
| `assets/promo/promo.html` | 신규 자산 + 텍스트 수정 (brand, Doby 표기) |
| `dobi_npc_bt` 재빌드 | 컴파일만 — 코드 0 변경 |
| dashboard / moca_opserver / static | **0** |
| face_avatar / minigame_runner / cafe_funnel XML | **0** |
| vic_pinky | **0** |

## 6. 후속

- **funnel 자동 진행** — Approach BT 노드 ↔ person_tracking track_id 연속성
  (track 재할당 시 Approach 가 새 track_id 재바인딩). 기존 코드 영역, 팀 협의.
- **promo_viewer ↔ mode_engaging.launch 통합** — 현재 별 launch 수동 spawn.
  "어제 코드 수정 금지" 해제 시 mode_engaging.launch.py 에 include.
- **watchdog → /dialog/utter_done 정밀화** — utter_done(Empty, stage 정보 없음)
  + stage 자체 추적으로 LeadIn 완료 정확 감지.
- **face_avatar suspend 초기 유실** — promo_viewer 시작 시 _face_suspend 가 DDS
  discovery 전이라 유실 가능. latched QoS 또는 지연 재발행 검토.
- **game.py 카메라 인덱스 버그** (§4.6) — `cv2.VideoCapture(0)` 하드코딩 →
  `--camera-index` 인자 반영하도록 수정 필요. 수정 시 게임(외장 카메라)과
  geva(내장 카메라) 동시 사용 가능 — 현재는 v4l2_camera 종료 우회.
- **게임 데모 영상 보관** — `/tmp/moca_ninja_demo_trim.mp4` (19초) 영구 위치로
  이동 필요 (임시 경로). dashboard 데모는 사용자가 이동 완료.

## 7. 세션 종료 시점 상태

- **라이브 스택** (DOMAIN=22): dashboard(mode_manager+opserver, 8800 health OK)
  + 인지(geva/rapport/person_tracking) + 음성 체인(persona_manager/dialog_router/
  tts_node) + face_avatar + engaging stack(bt_executor/minigame_runner) +
  promo_viewer — 11 노드 기동 중. 게임 영상 촬영 위해 v4l2_camera 는 종료된
  상태 → geva 입력 끊김. 라이브 검증 시 v4l2_camera 재기동 필요.
- **dashboard 영향**: moca_opserver / static 코드 0 변경 — 무영향 확인.
- **미커밋 산출물** (git): 신규 `src/dobi_npc/dobi_npc_promo/`, `assets/promo/`,
  `docs/daily/2026-05-21_promo_viewer_poc.md`,
  `docs/daily/2026-05-21_promo_viewer_integration.md`.
  기존 파일 modified 0 (modified 11개는 모두 이전 세션 미커밋).
- **데모 영상**: dashboard 데모(69초) — 사용자 영구 위치로 이동 완료 /
  카페닌자 게임 데모 `/tmp/moca_ninja_demo_trim.mp4`(19초) — 보관 위치 미정.
- **커밋**: 미실행 — 사용자 명시 대기.

### 7.1 라이브 검증 재구축 가이드
재구축 순서 (DOMAIN=22, ROS_LOCALHOST_ONLY=0):
1. dashboard — `mode_manager` + `opserver_node`(port 8800)
2. 인지 — `v4l2_camera`(video0→/webcam/image_raw) + `geva_node` +
   `rapport_tracker` + `person_tracking_node`
3. 음성 — `persona_manager` + `dialog_router` + `tts_node`
4. 표현 — `face_avatar`(fullscreen)
5. engaging — SetMode engaging → `bt_executor` + `minigame_runner` 자동 spawn
6. promo — `ros2 launch dobi_npc_promo mode_engaging_promo.launch.py`
주의: approach_controller/group_approach 는 cmd_vel 발행 — §0-A 정합 위해 제외.
게임(minigame) 검증 시에만 v4l2_camera 종료(video0 해제) 후 실행 (§4.6 버그).
