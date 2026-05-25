# 미니게임 3종 통합 + minigame_runner 일반화 + 5초 카운트다운 + face_avatar X11 raise fix

**작성일**: 2026-05-05
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md Phase 3 RPS 미니게임 + Polite phrase + OMX 가위바위보 (Phase 3 W7-9)
**커밋**: `3d59bab` (RPS 사전 작업) + `15dd274` (3종 통합 + face_avatar fix)
**상태**: cafe_funnel BT 의 Minigame phase 가 stub → 실 게임. PlayWait 06/07/01 세 게임을 moca/games 카피 후 subprocess wrapper 로 일반화. minigame_runner 가 game_id rotate, 5초 카운트다운 + 룰 표시, 게임 종료 후 face_avatar 정상 복귀까지 라이브 검증.

---

## 0. 시작 컨텍스트

전 세션까지:
- 노트북 단독 호객 BT (GEVA → EmotionMonitor → TTS → face_avatar) 라이브 검증 통과
- Phase 1 5-stage funnel + Phase 2 W4 emotion alarm 통합 완료
- Phase 3 미니게임은 stub 노드 + persona YAML 의 minigame_invite stage 가 placeholder

본 세션 목표: vicpinky 없는 노트북 단독 시나리오에서 **게임 유도 → 실 게임 진행 → 이긴 고객 카운터 안내** 전 funnel 한 cycle 닫기.

---

## 1. 1차 시도 (커밋 `3d59bab`) — RPS 자체 구현

### 1.1 BT Minigame 노드 (3-phase StatefulActionNode)

`include/dobi_npc_bt/minigame.hpp` 를 stub 39 줄 → 실 구현 ~200 줄:
- **phase 1 UTTER_INVITE**: `/dialog/request "minigame_invite"` publish → `/dialog/utter_done` 대기 (페르소나가 게임 권유 발화)
- **phase 2 GAME_RUNNING**: `/minigame/start` (Empty) publish → `/minigame/result` (MinigameResult) 대기
- **phase 3 UTTER_RESULT**: customer 승리면 `minigame_win`, 패배면 `minigame_lose` 발화

반환: `completed=true` 면 SUCCESS (이기든 지든 funnel 진행), abort/timeout 만 FAILURE.

### 1.2 BT LeadIn 노드 (3-phase 시뮬)

`include/dobi_npc_bt/lead_in.hpp` 단발 발화 → 3-phase:
- **UTTER_DEPART**: "절 따라오세요" 발화
- **SIMULATE_TRAVEL**: `travel_sec` (기본 6.0) 가상 진행 — vicpinky 없는 노트북 단독 시연용
- **UTTER_ARRIVED**: "도착했습니다" 발화

`simulate=true` (기본) — vicpinky 없는 노트북 단독.
Phase 후속: `simulate=false` 시 Nav2 NavigateToPose 액션 client (현재는 fallback 처리).

### 1.3 face_avatar / GEVA suspend/resume

게임이 같은 디스플레이 + 같은 카메라를 점유해야 하므로 양보 인터페이스 추가:

| 토픽 | 타입 | 처리 |
|---|---|---|
| `/face_avatar/suspend\|resume` | Empty | face_avatar: 화면 검정 + expression defer / 복귀 |
| `/geva/suspend\|resume` | Empty | GEVA: cv2.VideoCapture release / 다시 open |

GEVA 가 카메라 자원을 해제하지 않으면 게임이 카메라 못 잡음.

### 1.4 RPS 자체 구현 (`rps_node.py`, ~340 줄)

mediapipe `gesture_recognizer.task` (~10MB) 다운로드 + pygame 풀스크린 RPS UI 작성:
- 3 라운드 best-of-3, "READY → ROCK → PAPER → SCISSORS!" 카운트다운
- gesture 라벨: `Closed_Fist=rock`, `Open_Palm=paper`, `Victory=scissors`
- Castro-Gonzalez 70% 명시 3-way 분포 (P=0.7 → customer 70.7% / tie 14.8% / robot 14.5%, 1만회 시뮬 검증)

라이브 결과: **사용자 평가 "게임이 별로야"** — 텍스트 위주, 카메라 피드 미표시, 단조로움. 다음 단계로 진로 전환.

### 1.5 persona YAML 4종 stage 4개 추가

`generic/casual_browser/friendly_child/professional_adult` 에 `minigame_invite/win/lose + leadin_arrived` 추가. 페르소나별 톤 차이 살림 (casual=가볍게, friendly=활기, professional=절제).

---

## 2. 2차 진로 전환 (커밋 `15dd274`) — PlayWait 게임 통합

사용자 제안: "내가 이전에 만든 게임을 사용할 수 있어?" — `~/PlayWait/games/06_rps_evolution` (RPS 진화, 666 줄, 5종 손, 한글 UI, 사운드 7개) 발견. PlayWait 자체가 사용자의 별 프로젝트라 moca 와 격리:

> "결국 둘다 별도의 프로젝트이니, 게임 모듈을 /moca 에 새로 만든 /game 디렉토리에 카피하는 방식으로 추가해 나가면 어때?"

### 2.1 통합 패턴 — subprocess wrapper

게임은 self-contained Python (cv2 메인 루프 + 사운드/UI/AI/judge 분리). ROS 노드가 직접 import 하면 의존성/lifecycle 얽힘 → **subprocess wrapper** 로 격리:

1. ROS `minigame_runner` 노드가 `/minigame/start` 수신 → suspend publish → settle 0.4s
2. 5초 카운트다운 + 게임 룰 (pygame 풀스크린, 자체)
3. `python3 game.py --auto-play --difficulty <D> --auto-exit N --ready-delay D --result-json <tmp> --fullscreen` subprocess
4. JSON 결과 read → MinigameResult publish
5. resume publish → IDLE 복귀

게임 코드 변경 최소 (~60 줄 patch): auto_play 멤버 + GAME_OVER hook (`_save_result_json`) + update_phase auto-skip + run loop auto-exit + main argparse.

### 2.2 moca/games/ 카피 + game.py patch

| 게임 | 카피 크기 | 핵심 패턴 |
|---|---|---|
| `06_rps_evolution` | 9.3 MB | 5종 손, 3선 2승, 한글 UI, 사운드 7종 |
| `07_speed_counter` | 5.6 MB | 양손 손가락 합산, 5연속 정답 = 우승, 60초 timeout |
| `01_cafe_ninja` | 4.7 MB | 검지로 떨어지는 메뉴 베기, 폭탄 회피 |

세 게임 모두 같은 4 patch + `--fullscreen` CLI:
- `__init__` 에 `auto_play / auto_play_difficulty / auto_play_ready_delay / result_json_path / auto_exit_sec / game_started_at / game_over_at` 멤버 추가
- `change_phase` (또는 `self.phase=` 직접 할당 위치) 에 GAME_OVER 진입 시 `_save_result_json` + `game_over_at` 기록
- `update_phase` 시작에 `auto_play` 분기 — DIFFICULTY_SELECT auto-skip → READY auto-skip (delay 후) → 게임 진행
- `run` 메인 루프에 auto-exit 체크 (GAME_OVER N 초 후 break)
- `main` 에 argparse — 5 인자 + `--fullscreen`
- `setup()` 끝에 `is_fullscreen=True` 시 `cv2.setWindowProperty(WND_PROP_FULLSCREEN, WINDOW_FULLSCREEN)`

JSON 형식 통일 — `_save_result_json`:
```json
{"customer_wins": int, "robot_wins": int, "ties": int,
 "rounds_played": int, "completed": bool, "duration_sec": float}
```

각 게임 마다 customer/robot 매핑 다름:
- RPS: GameState 의 user_score/ai_score 그대로
- Speed Counter: `END_WIN` → customer_wins=1, 그 외 (timeout/too_many_fails/none) → robot_wins=1
- Cafe Ninja: `END_WIN` → customer_wins=1, 그 외 (timeout/lives_out/none) → robot_wins=1

### 2.3 minigame_runner 일반화

`rps_node.py` 폐기 (rename) → `minigame_runner_node.py`. 핵심 변경:

| 변경 | 이유 |
|---|---|
| `/minigame/start`: `Empty` → `String` (game_id) | 다중 게임 dispatch |
| `DEFAULT_GAME_REGISTRY` dict | game_id → game.py 매핑. 게임 추가 시 한 곳만 등록 |
| `DEFAULT_GAME_PARAMS` dict | 게임별 `auto_exit_sec / ready_delay_sec / explain` |
| `_show_explain_countdown` 메서드 | 게임 시작 전 5초 카운트다운 + 게임 룰 (pygame 풀스크린) |
| 의존성 제거 | mediapipe / pygame / cv2 ROS 노드 자체엔 불필요 (subprocess 가 자체 보유) |

`/minigame/start` 가 Empty 에서 String 으로 바뀌면서 BT Minigame 노드의 publish 도 변경. game_pool 에 3 게임 등록.

### 2.4 BT Minigame `game_type` rotation

cafe_funnel_v1.xml 의 `<Minigame game_type="rps"/>` hardcoded 였던 것을 → `game_type="rotate"`. `Minigame::resolve_game_type()`:

```cpp
if (requested == "rotate") {
  static std::atomic<size_t> counter{0};
  const auto & pool = game_pool();  // {"rps", "speed_counter", "cafe_ninja"}
  return pool[counter.fetch_add(1) % pool.size()];
}
if (requested == "random") { /* uniform random */ }
return requested;  // 명시 game_id 그대로
```

매 funnel cycle 마다 다른 게임 — 호객 다양성. selected_game_type_ 멤버에 onStart 에서 한 번 결정 후 phase 전체 일관 사용.

### 2.5 invite stage_id 분기

게임마다 룰이 다르므로 페르소나가 다른 phrase 발화해야 자연:

| game_type | invite stage_id |
|---|---|
| rps | `minigame_invite` (친숙, 기존 phrase) |
| speed_counter | **`minigame_invite_speed_counter`** (양손 합산 룰 설명) |
| cafe_ninja | **`minigame_invite_cafe_ninja`** (검지로 베기 룰 설명) |

persona YAML 4종에 새 stage 추가 — 페르소나별 톤 + face_expression 매핑.

### 2.6 5초 카운트다운 (minigame_runner 자체 pygame)

각 게임마다 카운트다운 시각 통일이 어려워 (ui_renderer 다름) — minigame_runner 가 게임 subprocess 띄우기 전 자체 pygame 풀스크린으로 처리:

```
+-----------------------------------+
|        가위바위보                 |
|                                   |
|  카운트가 끝나면 가위 / 바위 / 보!  |
|  3판 2선승. 이기면 추천 메뉴 안내! |
|                                   |
|              5                    |  ← countdown 5→4→3→2→1
+-----------------------------------+
```

`DEFAULT_GAME_PARAMS[game_id]["explain"]`: title + rules (list) + countdown_sec. 새 게임 추가 시 한 줄 등록만. ESC 누르면 게임 미시작 + FAILURE result publish.

### 2.7 사운드 교체 — 06 RPS

사용자 피드백 후 mp3 다운로드 → ffmpeg 로 wav 변환 (pygame.mixer mp3 일부 환경에서 비안정):
- `countdown.wav` 4.05s — 카운트다운 진입 시 1번만 재생 (3-2-1 매 숫자 trigger 시 overlap 발견 → `countdown_played` set 의 sentinel 활용)
- `victory.wav` 10.21s — 게임 우승 시
- `lose.wav` 3.92s — 라운드/게임 패배 시

theme.py SOUND_FILES 매핑 갱신.

### 2.8 sim_funnel_demo.launch.py 신규

한 줄 풀 시연:
```bash
ros2 launch dobi_npc_bringup sim_funnel_demo.launch.py
```

`dev_common.launch.py` include + `initial_mode=npc` + `fullscreen=true` (face_avatar 풀스크린) + persona casual_browser. mode_manager 가 NPC stack (bt_executor + minigame_runner) 자동 spawn.

---

## 3. 발견 / 함정

### 3.1 PlayWait 권한 분리

내가 처음에 PlayWait/games/06/src/game.py 에 patch 적용을 시도. 권한 시스템이 거부 (moca 외부 프로젝트). 일부 edit 만 통과 → broken 상태로 남음. 사용자 결정으로 **moca/games 에 통째 카피 + 카피본에서만 patch** 패턴 채택. PlayWait 원본은 사용자가 직접 `git checkout` 으로 revert.

이 패턴이 좋은 이유:
- 두 프로젝트 lifecycle 독립
- moca 가 게임 specific patch 자유 (auto_play, JSON output 등)
- PlayWait 가 향후 게임 추가 시 cherry-pick 으로 통합 가능

### 3.2 face_avatar `_on_resume` `OverflowError`

게임 종료 후 face_avatar 가 안 떠서 추적:
- 1차 추정: X11 stacking 에서 face_avatar 윈도우 가려짐 → `set_mode` 재호출 + `toggle_fullscreen × 2` + `wmctrl -a` 추가
- 여전히 안 뜸 → wmctrl 시스템에 있는데 face_avatar 가 죽고 있던 것
- 콘솔 로그에서 진짜 원인 발견:

```
File ".../face_avatar_node.py", line 289, in _on_resume
    self.screen = pygame.display.set_mode(
                  ^^^^^^^^^^^^^^^^^^^^^^^^
OverflowError: signed integer is greater than maximum
```

`self.screen.get_flags()` 가 SDL2 internal high-bit flags (예 `_NET_WM_FULLSCREEN_DESKTOP` 0x00001001 위) 포함 → pygame `set_mode(flags=...)` 가 받지 못해 OverflowError. **노드가 매번 죽고 있었음**.

**해결**: `__init__` 에서 명시 `_init_size / _init_flags` 저장 → resume 에서 그 값 사용 (`pygame.FULLSCREEN` 또는 `pygame.NOFRAME` 또는 `0` 셋 중 하나).

이걸로 face_avatar 가 게임 끝난 후 정상 복귀.

### 3.3 minigame_runner pygame 카운트다운 윈도우 잔존

`pygame.quit()` 호출 후에도 X11 윈도우가 즉시 destroy 안 되고 face_avatar 위에 stacking 잔존하는 케이스 발견:

```
$ wmctrl -l
0x0440000a  0 pc Dobi NPC face avatar           ← 살아있음
0x04a0000a  0 pc Dobi minigame: 가위바위보       ← pygame.quit 후에도 잔존
```

**해결**: `_show_explain_countdown` finally 에 `pygame.display.quit()` 명시 + `wmctrl -c "Dobi minigame: <title>"` 강제 close.

### 3.4 카운트다운 4 초 사운드 vs 게임 timing 3 초 overlap

countdown.wav 4.05s 인데 game.py 가 3-2-1 매 숫자 (1초 간격) 마다 `play("countdown")` 호출 → 4 초 사운드 3 개가 1초 간격으로 overlap 재생. 사용자 피드백:

> 1 → "4초 사운드 한 번만" 적용. game.py update_phase 의 COUNTDOWN 분기에서 `not self.countdown_played` 일 때만 1번 play, 그 후 trigger 무시.

### 3.5 auto_exit_sec 정책 진화

| 시점 | rps | speed_counter | cafe_ninja | 배경 |
|---|---|---|---|---|
| 초기 | 11.0 | 4.0 | 4.0 | rps victory.wav 10.21s 끝까지 |
| 사용자 피드백 1 | 2.0 | 2.0 | 2.0 | "딜레이 시간이 좀 길어 2초 정도면 줄여줘" |
| 사용자 피드백 2 (확정) | **5.0** | **5.0** | **5.0** | "5초로 재 수정해줘" |

5.0 통일 → minigame_win/lose phrase 까지 자연 진행. RPS 우승 시 victory.wav 10.21s 가 5초 후 잘림 — 후속에 result-based 분기 (win 시만 길게) 검토.

### 3.6 game_type=rotate 와 process-단위 atomic counter

`std::atomic<size_t> counter` 를 함수 static 으로 두어 BT 트리 재생성 (예 mode_manager 가 NPC stack respawn) 에도 살아남는 변수. 단 bt_executor process 종료 시 reset. funnel 한 cycle 당 Minigame onStart 1번 → cycle 1: rps, cycle 2: speed_counter, cycle 3: cafe_ninja, cycle 4: rps... 순환.

random 모드도 같은 game_pool 활용.

### 3.7 BT Minigame 에 ros_node 인자 필요

기존 stub `factory.registerNodeType<dobi_npc_bt::Minigame>("Minigame")` (가변 인자 X) 에서 → ros_node 받는 생성자로 바뀌면서 `factory.registerNodeType<dobi_npc_bt::Minigame>("Minigame", node)` 등록 변경. bt_executor_node.cpp 1줄.

---

## 4. 변경 파일 (커밋 `15dd274`)

### 4.1 새 파일

| 파일 | 변경 |
|---|---|
| `games/06_rps_evolution/` | 9.3 MB 카피 + game.py patch + countdown/victory/lose wav 교체 |
| `games/07_speed_counter/` | 5.6 MB 카피 + game.py patch |
| `games/01_cafe_ninja/` | 4.7 MB 카피 + game.py patch |
| `src/dobi_npc/dobi_npc_minigame/dobi_npc_minigame/minigame_runner_node.py` | 신규 (~270 줄) |
| `src/dobi_npc/dobi_npc_bringup/launch/sim_funnel_demo.launch.py` | 신규 (~50 줄) |

### 4.2 수정

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/minigame.hpp` | stub → 3-phase StatefulActionNode + game_type rotate/random + game_pool + invite_stage 분기 |
| `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/lead_in.hpp` | 단발 발화 → 3-phase 시뮬 (UTTER_DEPART → SIMULATE_TRAVEL → UTTER_ARRIVED) |
| `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` | game_type="rotate" 기본 |
| `src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp` | Minigame 등록에 ros_node 추가 |
| `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` | suspend/resume 토픽 + `_init_size/_init_flags` 저장 + set_mode/toggle/wmctrl raise |
| `src/dobi_npc/dobi_npc_dialog/config/personas/{generic,casual_browser,friendly_child,professional_adult}.yaml` | minigame_invite/win/lose + leadin_arrived + minigame_invite_speed_counter + minigame_invite_cafe_ninja stage 추가 + face_expression 매핑 |
| `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py` | suspend/resume 토픽 (cv2.VideoCapture release/reopen) |
| `src/dobi_npc/dobi_npc_minigame/package.xml` | mediapipe/pygame/cv2 의존 제거 (subprocess 가 자체 보유) |
| `src/dobi_npc/dobi_npc_minigame/setup.py` | rps_node → minigame_runner entry point |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_npc.launch.py` | rps_node → minigame_runner |
| `scripts/download_models.sh` | gesture_recognizer.task 추가 (1 차 시도 잔존, 사용 X) |

### 4.3 삭제

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_minigame/dobi_npc_minigame/rps_node.py` | minigame_runner_node.py 로 rename + 일반화 |

---

## 5. 라이브 검증

```bash
ros2 launch dobi_npc_bringup sim_funnel_demo.launch.py
```

### 5.1 cycle 1 (RPS) 검증

- IceBreak 발화 ("심심하면 한 판 하실래요?") ✓
- minigame_invite 발화 → Minigame onStart ✓
- 5초 카운트다운 + 게임 룰 표시 ✓
- 게임 풀스크린 + 손 인식 + 사운드 ✓
- minigame_win/lose 발화 → Offer → LeadIn ✓
- LeadIn "절 따라오세요" → 6초 가상 진행 → "도착했습니다" ✓

### 5.2 cycle 2-3 검증

- cycle 2: speed_counter (양손 합산 게임 룰 음성 + 5초 카운트다운 + 게임) ✓
- cycle 3: cafe_ninja (검지로 메뉴 베기 게임 룰 음성 + 5초 카운트다운 + 게임) ✓
- cycle 4: 다시 RPS (rotation 정상 순환) ✓

### 5.3 face_avatar 복귀

OverflowError fix 후:
- 게임 끝 → face_avatar resume 콘솔 로그 ✓
- toggle_fullscreen × 2 + wmctrl -a 작동 → face_avatar 풀스크린 표정 다시 표시 ✓
- minigame_runner 카운트다운 윈도우 wmctrl -c 강제 close → face_avatar 가려짐 회피 ✓

---

## 6. 다음 / TODO 갱신

### CLAUDE.md TODO 변경

- `[ ] Phase 3 RPS 미니게임 + Polite phrase + OMX 가위바위보 (W7-9)` → **부분 완료**:
  - PlayWait 06_rps_evolution + Castro-Gonzalez 70% (구현 자체에서 통계 검증 통과) ✓
  - Polite phrase: persona YAML minigame_invite/win/lose 4종 ✓
  - OMX 가위바위보 (실 로봇 손): vicpinky/OMX 없는 노트북 단독이라 미적용 — Phase 4+ 후속

### 후속 (관련성 가까움)

- [ ] **PlayWait 원본 revert**: 사용자가 `cd ~/PlayWait && git checkout games/06_rps_evolution/src/game.py` 실행 (1차 시도 시 들어간 update_phase auto_play 분기 제거)
- [ ] **rps victory.wav 잘림**: auto_exit_sec=5.0 이라 우승 시 5.21s 잘림. 해결 옵션:
  - (a) victory.wav 짧은 걸로 교체 (1~2초)
  - (b) result-based 분기 — game.py 에 `--auto-exit-win N` 추가, win 시 길게 lose 시 짧게
- [ ] **사운드 후보 정리**: 06 sounds dir 의 mp3 (youwin/scratchonix-victory-chime/freesound_arcade-countdown/lose/countdown/victory.mp3) + lose_old.wav + victory_old.wav + countdown-922.wav 가 모두 카피본에 잔존. 비교용이거나 정리 — 사용자 결정.
- [ ] **gesture_recognizer.task 모델 미사용**: 1차 RPS 자체 구현에서 다운로드한 모델. 2차 통합으로 미사용. download_models.sh 에서 제거 또는 cleanup.

### Phase 후속 (먼 미래)

- [ ] **결과 narrative 강화**: minigame_win 시 LeadIn 활성, minigame_lose 시 Offer 만 (현재는 둘 다 SUCCESS) — `customer_won` 출력 포트 + LeadIn 앞 IfCondition
- [ ] **RandomSelector** BT 노드 — game_type 외에도 페르소나/게임 조합 다양화
- [ ] **게임 추가 매뉴얼**: PlayWait 의 다른 게임 (02 emoji_face_battle / 04 kpop_dance / 05 silent_charades 등) 통합 시 본 회고를 reference. 패턴 4 patch + GAME_REGISTRY/GAME_PARAMS 한 줄.

---

## 7. 한 줄 요약

> PlayWait 3 게임 (RPS / 스피드 카운터 / 카페 닌자) 을 moca/games 카피 + subprocess wrapper 로 통합. minigame_runner 가 game_id rotate, 5초 카운트다운 + 게임 룰 표시, face_avatar `OverflowError` fix 로 게임 종료 후 정상 복귀. `sim_funnel_demo.launch.py` 한 줄로 IceBreak → Minigame(rotate) → Offer → LeadIn(시뮬) 풀 cycle 라이브 시연 가능.
