# follow 라이브 검증 시도 — 사고 모음 + 인프라 발견 (postmortem)

**작성일**: 2026-05-06
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "follow_controller 재튜닝 (HCAM01N 화각 vs RPC-20F 차이)"
**커밋**: 후속 (web/ gitignore 라 코드 변경분 commit 미진행)
**상태**: follow 라이브 검증 미완 (USB power 부족 + 배터리 20%). 단 7가지 사고/발견 정리 — 다음 follow 시도 전 인프라 패치 가이드.

---

## 0. 시작 컨텍스트

본 세션 직전:
- 카메라 2/3 모델 스왑 + 코드 patch 완료 (commit `043eb9a`) → SoT 정정 + 회고 (`2026-05-06_camera3_swap_and_patch.md`) → commit
- `stop_moca.sh` 추가 (commit `e7ad11e`) — 좀비 노드 정리 + 사고 가시화
- 운영 UI 확장 (`teleop_server.py` + `operator.html`) — V·A circumplex / 라포 / 미니게임 패널
  - **단 `web/` 가 .gitignore 라 git 추적 안 됨**. 작업 사본 보관

목표: vic_pinky 충전 끝났으니 follow_controller 재튜닝 라이브 검증 (HCAM01N 화각 가정).

---

## 1. 시도 흐름 (timeline)

대략 시간순:

1. RPi 측 `vicpinky_bringup` ssh nohup 시동 시도 (1차) — 모터 "Failed to set velocity mode" + 라이다 timeout 둘 다 fail
2. 첫 시도 (PID 3765) 만 모터 정상 응답 — 우리 SIGKILL 정리 후 계속 fail
3. 가설: SIGKILL 이 ZLAC 직렬 통신 abnormal 종료 → fault state. **사용자 본체 power cycle 부탁** (사용자 직접)
4. power cycle 후에도 동일 fail — 가설 변경: E-Stop 눌림 → **사용자 E-Stop 해제** → 모터 OK
5. 라이다 별 issue (timeout) — 직렬 포트 좀비 lock 의심 (PID 5798/6049 이미 죽었는데 fuser 가 lock 표시)
6. 카메라 2 (HCAM01N) 가 RPi 에 인식 안 됨 — 케이블 점검 → 노트북에서 인식 OK 후 RPi 다른 포트로 옮김 → 인식
7. 그 과정에서 **사용자 보유 외장 캠이 SNAP U2 두 대** 였음을 발견. HCAM01N 은 별 카메라 (SoT 가정 정확)
8. 직렬 포트 좀비 lock 안 풀려서 **RPi reboot** (사용자 직접 콘솔 `sudo reboot`)
9. reboot 후 깨끗한 상태에서 풀 시동 OK — moter, lidar, camera 2 모두 정상 토픽 흐름
10. follow 모드 시작 — `/cmd_vel 30Hz`, `/robot_cam/persons 8Hz`, `/mode/state follow`
11. 그러나 **vic_pinky 가 거의 안 움직임**. 사용자 "잘 안 오지?", "제자리에서 꿈틀", "회전도 안해"
12. 자체 테스트 — 직접 `cmd_vel 0.15 m/s` 보냄. odom dx=7mm (예상 375mm) → 거의 정지
13. 0.3 m/s + 회전 0.5 rad/s 시도. 휠 속도 측정: vx=0.015 m/s (5%), wz=0 (회전 무응답)
14. 의심: E-Stop 또 눌렸을 가능성 → **사용자 E-Stop 다시 풀기** → 휠 정상 작동
15. 직접 cmd 0.2 m/s 후진 (forward 명령에 후진) — odom dx=-0.53m, dy=-0.20m, **부호 반전 확인**
16. 운영 UI 종료 후 follow 다시 — `/cmd_vel publisher 2 (follow_controller + cabot_teleop_bridge)` 충돌 발견
17. teleop_server 3개 인스턴스 좀비 (PID 31233, 34216, 38073) — `stop_moca --with-ui` 패턴 매칭 부정확 → 직접 SIGKILL
18. 정리 후 다시 시동 — 카메라 2 가 USB power 부족으로 disconnect (`Error dequeueing buffer: No such device (19)`). 배터리 20%
19. **전체 종료** (사용자 "일단 모두 종료해")

총 ~1시간 30분 진단. follow 라이브 동작 자체 검증은 미완. 단 7가지 사고/발견 + 인프라 후속 트랙 명확화.

---

## 2. 사고 모음 (7건)

### 2.1 좀비 노드 — 어제 sim_funnel 의 잔여

전 세션 (2026-05-05) sim_funnel `Ctrl+C` 시 ros2 launch 부모는 죽었지만 자식 노드 8개 (geva_node / rapport_tracker / persona_manager / dialog_router / tts_node / mode_manager / minigame_runner / 등) 가 orphan 으로 살아남음.

**증상 (오늘 첫 시동 시):** geva_node 가 `/dev/video0` 점유 → 새 GEVA 가 카메라 못 잡고 RuntimeError 즉사 → BT funnel 진행 X / 발화 X.

**해결:** SIGTERM 으로 정리. 이 사고는 본 세션 시작 시 이미 `stop_moca.sh` 로 자동화 (commit `e7ad11e`).

### 2.2 sink MUTED — system 사운드 안 들림

발화 dispatch + mp3 합성은 정상이지만 **시스템 default sink (Speaker+Headphones) 가 MUTED** 상태라 들리지 않음.

```
*   53. ... Speaker + Headphones [vol: 0.88 MUTED]
   python3.12 70 → ALC256 Analog:playback_FR/FL [active]
                                                  ↑ stream 정상, sink 음소거
```

**해결:** `wpctl set-mute @DEFAULT_AUDIO_SINK@ 0`. `stop_moca.sh` 가 종료 시 sink 상태 표시 + unmute 명령 안내. 단 GNOME 키패드 / hotkey 토글이 시동 사이 자주 발생 — 자동 unmute 까지는 수동 결정.

### 2.3 ZLAC 모터 컨트롤러 — SIGKILL 후 fault state

vicpinky_bringup 첫 시동 (PID 3765) 만 정상 응답. 그 후 SIGKILL 정리 + 재시동 시 모두 `Failed to set velocity mode! Shutting down.` fail. 같은 시점 sllidar 도 timeout fail.

**원인:** SIGKILL 이 ZLAC 직렬 통신을 abnormal 종료. ZLAC 컨트롤러가 fault state 진입 → 다음 enable 명령 무시.

**해결:** vic_pinky 본체 power cycle. 단 cycle 만으로 부족 — 추가로 E-Stop 해제 필요.

### 2.4 E-Stop 자주 눌림 — USB 케이블 정리 위험

세션 중 E-Stop 이 **두 번 눌림**:
- 1차: 첫 fail 무더기. 사용자 E-Stop 해제 → 모터 정상 응답
- 2차: 우리 자체 테스트 시 휠 안 움직임. 사용자 E-Stop 다시 해제 → 정상

**가설:** USB 케이블 (카메라 / ZLAC / 라이다) 을 RPi 에 꽂았다 빼는 동안 E-Stop 버튼이 의도 없이 눌림. vic_pinky 본체 layout 점검 필요 — E-Stop 위치가 USB 포트 근처면 가드 검토.

### 2.5 USB serial driver 좀비 lock

SIGKILL 로 sllidar / bringup 죽인 후 `fuser /dev/ttyUSB0 ttyUSB1` 결과:

```
/dev/ttyUSB0:  vic 5798  (sllidar_node 좀비 lock)
/dev/ttyUSB1:  vic 6049  (bringup 좀비 lock)
```

PID 들이 `/proc` 에 없는데 (이미 죽음) fuser 가 lock 표시. 새 시동의 sllidar/bringup 이 USB 못 잡아 fail.

**해결:** USB 케이블 hot-plug 또는 RPi reboot. 본 세션은 **`sudo reboot`** 로 해결 (사용자 직접 콘솔). USB 재꽂기로는 lock 안 풀림 (확인됨).

**예방:** 종료 절차에 SIGTERM only 권장 (SIGKILL 회피). 단 SIGTERM 도 ros2 launch 가 자식 정리 못 하는 케이스 있어서 절대 안전 X.

### 2.6 `cabot_teleop_bridge` cmd_vel 충돌

운영 UI 의 `teleop_server.py` 안 `TeleopBridge._tick` 이 20Hz timer 로 cmd_vel publish. **키 alive timeout (0.4s) 후에도 cmd 0,0 을 계속 publish**.

```
/cmd_vel publishers:
  follow_controller       (0.2 m/s 시도)
  cabot_teleop_bridge     (0,0 자동 publish)
                              ↓
                       vic_pinky_bringup (race)
```

→ follow_controller 가 0.20 m/s 보내도 cabot_teleop_bridge 가 0 으로 덮어쓰며 모터에 stable cmd 도달 X. odom 측정: 0.15 m/s 명령에 9mm 만 이동 (예상 375mm).

**해결책 (코드 패치 필요):** `_tick` 에서 mode_state 가 `idle` 가 아닐 때 cmd_vel publish skip. follow / serving / npc 모드는 각자 cmd publisher 가 있으므로 운영 UI 는 monitoring only.

이 패치가 본 세션의 가장 중요한 후속 트랙.

### 2.7 USB power 부족 — 배터리 저하 시 카메라 disconnect

배터리 20% 시점에 RPi v4l2_camera_node 로그:

```
[ERROR] [v4l2_camera]: Error dequeueing buffer: No such device (19)
[ERROR] [v4l2_camera]: Error dequeueing buffer: No such device (19)
... (반복)
```

USB 카메라가 power 부족으로 disconnect. lsusb 에는 인식되지만 v4l2 stream 끊김. 배터리 추가 부하 (모터 + 라이다 + 카메라 동시) 시 USB 5V 공급 부족.

**대응:** Phase 4 운영 시 배터리 30% 미만이면 follow / NPC 모드 자동 abort. SafetyCheck 의 `battery_min` 임계 (현재 0.20 = 20%) 를 0.30 으로 상향 검토.

---

## 3. 부수 발견 (3건)

### 3.1 모터 cmd 부호 반전

직접 cmd_vel `linear.x = +0.2` 보냈는데 vic_pinky 가 후진 (odom dx=-0.53m). 회고 (`2026-05-04_follow_tune_smoothing.md`) 의 "v 부호 반전" 라이브 튜닝 항목과 일치.

**의미:** vic_pinky 모터 frame 이 ROS REP-103 표준 (x forward) 과 반대 mounted. follow_controller 는 `kp_linear = -0.4` 음수 게인으로 이 반전을 보정 중. 직접 cmd_vel publish 시엔 보정 없으므로 -x 가 forward.

**후속:** vicpinky_bringup 에서 cmd_vel 받을 때 부호 보정하면 표준 인터페이스 가능. 단 vic_pinky 측 launch arg 추가 필요 — moca 트랙 외부.

### 3.2 angular cmd 거의 무응답

직접 cmd `angular.z = +0.4 rad/s` 보냈는데 odom 측정 wz = 0.012 (거의 0). 양 휠 부호 정렬 별 이슈일 가능성.

회고 (`2026-05-04_follow_tune_smoothing.md`) 에서 "회전 게인 1/3 절감 + EMA + align_gate" 튜닝 했지만 그건 **회전이 너무 빨라서** 였음. 오늘 결과는 정반대 — **회전 자체가 안 됨**. 환경 변수 또는 vic_pinky 본체 상태에 따라 달라지는 듯.

**후속:** vic_pinky 정상 환경에서 단순 회전 cmd 명령으로 양 휠 RPM 측정 + 부호 검증. 한 휠만 도는지 양 휠 같은 방향 도는지 (= 회전 안 함).

### 3.3 카메라 2 모델 — 사용자 자산 정정

본 세션 시작 시 SoT 갱신 (`2026-05-06_camera3_swap_and_patch.md`) 에서 카메라 2 = HCAM01N 으로 명시. 본 세션 진행 중 사용자가 노트북에 카메라 2 잠시 꽂았을 때 발견:

- 사용자가 보유한 외장 캠 = **SNAP U2 (Sunplus 1bcf:2281) 두 대**
- HCAM01N 은 별 카메라로 따로 보유 — RPi 측 lsusb 에 잡힘 확인됨

즉 "카메라 2 = HCAM01N" 가정이 맞고, "RPi 직접 연결한 카메라 = HCAM" 도 SoT 와 일치. 단 사용자 의도가 두 SNAP U2 + HCAM01N 셋 모두 활용인지, 또는 둘만 사용인지 명확화 후속.

**현 시점 SoT (2026-05-06 기준):**
- 카메라 1 (노트북 내장): Bison 5986:211b (`/dev/video0`)
- 카메라 2 (RPi USB): HCAM01N Microdia 0c45:6367 (`/dev/video0` on RPi)
- 카메라 3 (노트북 USB 외장): SNAP U2 Sunplus 1bcf:2281 (`/dev/video2`)
- 추가 SNAP U2 1대 보유 (역할 미정)

---

## 4. 발견된 후속 트랙 (우선순위)

### 4.1 [P1] `teleop_server.py` cmd_vel mode-aware 패치

**문제:** §2.6 — cabot_teleop_bridge 가 mode 무관 cmd_vel 0 자동 publish. follow / serving / npc 와 race.

**패치:**
```python
def _tick(self):
    # idle 모드일 때만 운영 UI 의 cmd_vel publish (텔레옵 기능)
    # follow / serving / npc 모드는 각 stack 의 controller 가 publish
    mode = (self._latest_mode_state or {}).get('current_mode', 'idle')
    if mode != 'idle':
        return
    # ... 기존 cmd_vel publish 로직
```

`mode_state` 캐시 (이미 `_on_mode_state` 에서 갱신 중) 를 활용. 1줄 가드 추가.

### 4.2 [P1] `stop_moca.sh` 패턴 보정

**문제:** `--with-ui` 의 패턴 (`moca/web/teleop_server.py` 절대경로) 이 사용자 셸 상대경로 (`web/teleop_server.py`) 못 잡음.

**패치:** PATTERNS 에 `web/teleop_server.py` (상대경로 fallback) 추가. 또는 `teleop_server.py` 단순 매칭 (다른 teleop_server 와 충돌 위험 적음).

### 4.3 [P2] vic_pinky bringup 종료 절차 개선

**문제:** §2.5 — SIGKILL 후 USB serial driver 좀비 lock. 다음 시동 fail.

**개선안:**
- ros2 launch 부모에 SIGTERM only (SIGKILL 회피)
- 자식 정리 못 하는 케이스에는 사용자에게 "RPi reboot 또는 USB hot-plug" 안내
- `stop_moca.sh` 가 RPi 측 정리는 시도 안 함 (별 호스트). RPi 측 stop 스크립트 별도 필요할 수도

### 4.4 [P2] SafetyCheck battery_min 상향

**문제:** §2.7 — 배터리 20~30% 시 USB power 부족으로 카메라 disconnect.

**제안:** SafetyCheck `battery_min` 임계 0.20 → 0.30 (라이브 검증으로 미세 조정).

### 4.5 [P3] E-Stop 위치 가드

**문제:** §2.4 — USB 케이블 정리 시 E-Stop 눌림 빈번.

**제안:** vic_pinky 본체 layout 점검. E-Stop 위치 변경 또는 보호 가드 (실제 가능성은 사용자 결정).

### 4.6 [P3] vicpinky_bringup cmd_vel 부호 정상화

**문제:** §3.1 — 모터 frame 이 ROS REP-103 반대. follow_controller 가 보정 중이지만 vicpinky_bringup 에서 보정하면 표준 인터페이스 회복.

**제안:** vicpinky_bringup launch arg 로 wheel direction reverse 추가. moca 트랙 외부.

---

## 5. 미완 작업 (다음 follow 시도 전 체크)

1. [ ] vic_pinky 배터리 충전 (현재 20%)
2. [ ] §4.1 patch (teleop_server cmd_vel mode-aware) — follow 동시에 운영 UI 화면 보려면 필수
3. [ ] §4.2 patch (stop_moca 패턴 보정) — 다음 정리 시 깔끔
4. [ ] follow_controller 재튜닝 (HCAM01N 화각 vs RPC-20F 차이) — `target_height_ratio / align_gate / EMA` 라이브 조정. **본 세션 본 목적 미완**.
5. [ ] §3.2 회전 cmd 무응답 — 단순 회전 테스트로 양 휠 부호 검증 필요

---

## 6. 변경 파일 (본 세션, commit 미진행)

### 6.1 git 추적 안 되는 변경 (web/ gitignore)

| 파일 | 변경 |
|---|---|
| `web/teleop_server.py` | EmotionState/RapportEvent/MinigameResult 구독 + emotion/rapport/minigame 캐시 + `/ws/telemetry` snapshot 확장 |
| `web/static/operator.html` | V·A circumplex SVG + 라포 카운터 4종 + 미니게임 결과 + ws-status 라이브 표시 + 자동 재연결 |

### 6.2 진행 중 (본 회고)

| 파일 | 변경 |
|---|---|
| `docs/daily/2026-05-06_follow_postmortem_and_infra.md` | 신규 (본 회고) |

### 6.3 후속 commit 후보

§4.1, §4.2 patch + 본 회고 묶어 commit. `web/teleop_server.py` 변경분은 gitignore 정책에 따라 별 결정.

---

## 7. 한 줄 요약

> follow 라이브 검증 시도 — vic_pinky 충전 후 진입했으나 좀비/E-Stop/USB serial lock/카메라 disconnect/cmd_vel race 등 7건 사고로 ~90분 소모. follow 동작 자체 미검증. 핵심 발견: ① teleop_server 의 cmd_vel publisher 가 mode 무관 충돌 (P1 패치 필요), ② SIGKILL 후 USB serial driver 좀비 lock (RPi reboot 외엔 해소 어려움), ③ E-Stop 이 USB 케이블 정리 시 의도 없이 눌림. 본 회고가 다음 follow 시도 전 인프라 보강 가이드.
