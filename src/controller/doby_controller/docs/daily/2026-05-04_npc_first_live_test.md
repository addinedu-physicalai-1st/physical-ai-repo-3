# NPC 모드 ↔ vic_pinky RPi 첫 실물 통합 테스트 (Step 4 안전 검증 1차)

**작성일**: 2026-05-04 (저녁 트랙)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 체크리스트**: `docs/rpi_integration_checklist.md` §3 + §4.2 (실주행은 보류)
**선행 트랙**:
- 오전: `2026-05-04_rpi_first_contact.md` (RPi 1차 연결, run_vic_bringup.sh, SafetyCheck 라이브)
- 오후: `2026-05-04_approach_safety_patch.md` (cmd_vel watcher, allow_dummy_goal=false)
**상태**: NPC funnel + RPi bringup 통합 라이브 7분, **Approach 안전 가드 34회 발동, /cmd_vel TRIP 0건**. 실 Nav2 주행은 map frame/Nav2 stack 미해결로 보류.

---

## 0. 시작 컨텍스트

오전·오후 트랙에서:
- RPi 5(192.168.0.138) ↔ 노트북(192.168.0.154) 도메인 22 통신 확립
- `run_vic_bringup.sh` / `stop_vic_bringup.sh` 자동화
- SafetyCheck `/battery_state` 라이브 검증 (실 RPi 연결)
- cmd_vel watcher (`scripts/cmd_vel_watch.py`) — TRIP 시 옵션으로 RPi bringup KILL
- Approach `allow_dummy_goal` 안전 가드 (기본 false, dummy goal Nav2 송신 영구 차단)

본 트랙 목표: 위 안전 장치들이 **NPC 풀 스택 + 실 vic_pinky bringup** 통합 환경에서 의도대로 동작하는지 라이브 검증. 사용자 흐름:
> teleop으로 안전 위치로 이동 → teleop만 종료(bringup 유지) → cmd_vel watcher → NPC 모드(`dev_all.launch.py`) 시동

---

## 1. 작업 흐름

### Step 1: teleop UI 기동 — RPi USB 캠 enumeration 실패 발견

`bash scripts/run_teleop_ui.sh` 실행 → bringup은 SSH로 자동 기동되었으나 usb_cam 단계에서 exit 1.

**원인**: RPi `lsusb`에 비디오 클래스 디바이스 0건. `/dev/video*`는 모두 `pispbe`/`rpivid` (CSI/ISP). UVC 카메라 enumerate 실패.

**dmesg 분석**:
```
[ 4804.649750] usb 4-1: USB disconnect, device number 2
... (재시도 5회 모두 error -71) ...
[ 4807.216634] usb usb4-port1: unable to enumerate USB device
```

부팅 후 ~80분 시점에 한 번 끊겼고 USB 포트가 디바이스에 주소 할당조차 못 함 (EPROTO). 케이블 점검만으로는 OS가 디바이스를 못 봄.

**해결**: RPi 재부팅 → USB 스택 재초기화 → `Bus 004 Device 002: ID 0c45:6367 Microdia HCAM01N` + `/dev/video0,1` 정상 enumerate.

### Step 2: `run_teleop_ui.sh` SKIP_CAM 분기 추가

USB 캠 enumeration 실패 케이스를 위해 스크립트에 우회 옵션 추가:
```bash
if [ "${SKIP_CAM:-0}" = "1" ]; then
    echo " [INFO] usb_cam SKIP (SKIP_CAM=1) — UI 영상 패널은 빈 상태로 동작"
else
    # ... 기존 usb_cam 기동 ...
    [ERROR] 시:  HINT  USB 캠 미연결이면  SKIP_CAM=1 bash run_teleop_ui.sh  로 우회
fi
```

본 테스트 시점에는 재부팅으로 카메라 복구되어 SKIP_CAM 없이 정상 진행. 미래에 카메라 끊겼을 때 빠른 우회로 사용 가능.

### Step 3: teleop으로 안전 위치 이동 → bringup 유지하며 종료

```bash
bash scripts/run_teleop_ui.sh                 # 영상 + 키 조작 정상
# 안전 위치(전후좌우 1.5m+ 여유) 이동 후
bash scripts/stop_teleop_ui.sh                # --all 없이 → bringup 유지
pgrep -af 'teleop_server|run_teleop_ui'       # 잔류 없음 확인
```

브라우저 탭도 닫음 (잔류 키 입력 방지).

### Step 4: cmd_vel watcher 백그라운드 + grep 필터 함정

watcher를 Monitor로 백그라운드 띄우고 TRIP 이벤트만 알림 받도록 grep 필터 적용:
```bash
python3 scripts/cmd_vel_watch.py --linear-thresh 0.05 --angular-thresh 0.05 \
  | grep -E "TRIP|WATCHING|FINAL|nonzero=[1-9]|peak_lin=[^0]|peak_ang=[^0]"
```

**함정**: `TRIP` 패턴이 5초 요약의 `TRIPPED=False`도 매칭 → 모든 5초 요약이 알림으로 새어나옴.

**수정**: 패턴을 좁혀 실제 trip 이벤트만 잡도록 — `TRIP:|TRIPPED=True|nonzero=[1-9]|WATCHING|FINAL`. `TRIP:`는 콜론 포함, `TRIPPED=True`는 명시. 재시동 후 깨끗.

본 테스트 7분 동안 TRIP/nonzero 알림 0건. → `/cmd_vel`에 단 한 건의 명령도 송신되지 않음.

### Step 5: NPC 모드(`dev_all.launch.py`) 시동 — 표정/음성/BT 정상

별 터미널에서:
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 launch dobi_npc_bringup dev_all.launch.py 2>&1 | tee /tmp/dobi.log
```

시동 직후 정상 라인 모두 확인:
- `geva_node ... loaded 8/8 expressions` (face_avatar 자산)
- `rapport_tracker: hysteresis on=5 off=5`
- `tts_node ready`
- `face_avatar_node: WINDOWED 800x600`
- `Registered: 9 user + 41 builtin nodes` (BT)

사용자 보고: **"표정 및 음성 잘 보여."** — 풀스크린/창 GUI 정상, TTS 출력 정상.

### Step 6: Approach 안전 가드 라이브 검증

테스트 ~7분 동안 BT가 cafe_funnel을 반복 순환. `/customer_pose` publisher 없는 환경 (fake_customer 미기동) → 매 사이클 Approach가 dummy goal 경로로 진입 시도.

**로그 결과** (`grep -c`로 정확 카운트):
```
[Approach] goal_valid=false (customer_pose/goal_pose 미연결).
  allow_dummy_goal='false' (false) → Nav2 송신 스킵, fallback SUCCESS.
```
**34회** 발동, 매번 동일 패턴. dummy goal이 Nav2로 송신된 건수 0. 결과적으로 watcher TRIP 0건.

오후 트랙에서 추가한 `allow_dummy_goal=false` 기본값 + string port 수동 변환이 **풀 BT cycle 환경에서 일관성 있게 적용됨**. BT funnel은 Approach SUCCESS 후 ice_break/persona_manager/TTS/face까지 정상 순환:
```
stage3_ice_break: ...
[persona_manager] [casual_browser/icebreak/ko/ko-KR-SunHiNeural/face=hello]
  안녕하세요! 오늘 어떤 음료가 끌리세요?
[tts_node] speak '안녕하세요! 오늘 어떤 음료가 끌리세요?'
[face_avatar] face: happy -> hello
```

### Step 7: SafetyCheck 라이브 검증 — 정상 silent

`grep -iE "safety|batter" /tmp/dobi.log` → 결과 0줄.

코드 확인 (`safety_check.hpp`):
- 정상(pct ≥ battery_min) → silent FAILURE → `cafe_funnel` 진행
- 임계 미만 → SUCCESS + WARN log + alarm

**라이브 측정**: `ros2 topic echo /battery_state --field percentage --once` → `0.4345` (43.4%). 임계 20% 위 → silent FAILURE가 정상.

오전 트랙에서 합성 저전압 publish로 검증한 alarm 발동 경로가 본 테스트에서 silent 경로로 일관 동작.

### Step 8: 실 Nav2 주행 검증 보류 — map frame 부재

사용자 옵션 결정 단계에서 fake_customer + Nav2 주행 시도 검토:

```bash
# 점검
ros2 action list                                # /navigate_to_pose 존재
ros2 node list | grep -iE "nav2|controller|planner|amcl|bt_navigator"  # 0건
ros2 run tf2_ros tf2_echo map base_link         # Invalid frame ID "map"
```

**발견**:
- `/navigate_to_pose` action server는 떠 있음 (출처 미확인 — vicpinky_bringup 자체 구현 가능성)
- 표준 Nav2 노드(controller/planner/amcl/bt_navigator) 0건
- `map` TF 부재 → fake_customer 기본값 `frame_id='map'`으로 띄우면 TF 실패로 goal reject

→ 실 주행 검증은 별도 트랙에서 SLAM/amcl 띄우거나 `/navigate_to_pose` 출처를 명확히 한 뒤 진행. 본 트랙은 **C 옵션(종료 + 회고)** 선택.

---

## 2. 핵심 학습

### 안전 장치의 통합 검증 — 이중 안전이 라이브에서 일관됨

오전·오후 트랙에서 만든 4층 안전 (CLAUDE.md/회고 참조):
| 층 | 메커니즘 | 본 테스트 결과 |
|---|---|---|
| L1 코드 (Approach allow_dummy_goal) | dummy goal Nav2 송신 차단 | 34회 차단  |
| L2 코드 (Approach abort_threshold) | 거리 < 1.0m 시 FAILURE | 본 테스트 미적용 (customer_pose 자체 없음) |
| L3 외부 (cmd_vel watcher) | /cmd_vel 임계 초과 시 KILL 옵션 | TRIP 0건  |
| L4 물리 | 사용자 비상 정지 | 미사용 |

L1이 source에서 차단하므로 L3가 trip할 일 자체가 없음. 시스템 전체가 "안전한 상태"로 7분 라이브.

### Monitor grep 필터 — 부분 매칭 함정

grep 패턴 `TRIP`이 의도와 달리 정상 5초 요약의 `TRIPPED=False`도 매칭. 결과적으로 모든 요약이 알림으로 새어나옴.

**수정 원칙**: 패턴을 **이벤트 시그니처 단위**로 작성 (단어 일부 매칭 회피).
- 잘못: `TRIP|FINAL|nonzero=[1-9]`
- 옳음: `TRIP:|TRIPPED=True|FINAL|nonzero=[1-9]|WATCHING`

콜론·등호값 등 이벤트의 **실제 형태**까지 명시하면 false-positive 차단.

### USB 카메라 -71 enumerate 실패 → 케이블 점검만으론 부족

dmesg `error -71` (EPROTO)는 USB 포트가 디바이스 주소 할당 단계에서 실패. 케이블이 꽂혀 있어도 OS는 디바이스를 못 보는 상태. 이때 lsusb에 0건이고 `/dev/video*`도 안 생김.

**복구 우선순위**:
1. 다른 USB 포트로 옮기기 (포트 power cycle)
2. 물리 unplug 5초+ replug (kernel state 클리어)
3. **RPi 재부팅** (USB 스택 전체 재초기화) ← 본 테스트에서 효과
4. 케이블 교체

본 환경에선 RPi 재부팅으로 즉시 복구. 향후 동일 증상 시 빠른 단계 결정 가능.

### `run_teleop_ui.sh` SKIP_CAM 분기 — 운영자 hint 포함

usb_cam 기동 실패 시 ERROR 메시지에 `HINT: SKIP_CAM=1 bash run_teleop_ui.sh로 우회` 포함. 운영자가 막혔을 때 다음 액션을 즉시 알 수 있음.

이전 트랙들에서도 같은 원칙이 반복 등장: **로그/에러 메시지에 다음 행동을 가능한 만큼 포함** (allow_dummy_goal 패치의 raw value 노출, hysteresis raw 카운트 노출 등).

### `/navigate_to_pose` action 존재 ≠ Nav2 stack 살아있음

action list에 잡히지만 표준 Nav2 노드가 보이지 않는 상태. vicpinky_bringup이 자체 구현으로 action server를 띄웠을 가능성.

**시사점**: Approach가 `navigate_to_pose` 클라이언트만 만들면 통신은 되나, server 측 구현(어떤 planner/controller로 어디까지 처리)을 모르고는 실 주행 결과 예측 불가. **실 주행 트랙은 server 출처 명확화 + map frame 확보를 선결**.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **Approach 안전 가드가 풀 BT cycle 환경에서 일관 동작** — 단일 사이클 검증(오후 트랙)이 다중 사이클로 확대되어도 동일 결과.
- **SafetyCheck silent FAILURE 경로 정상** — 정상 배터리 시 로그 0줄, alarm 시 WARN — 디자인대로.
- **RPi USB 스택 reboot 의존성** — error -71 발생 시 hot-replug보다 reboot가 빠름.
- **grep 패턴 부분 매칭 함정** — `TRIP` ⊂ `TRIPPED=False`. 향후 Monitor 필터 작성 시 단어 경계 또는 명시 시그니처 사용.

### 위험 요소 (본 테스트는 회피, 실 주행 트랙에 이월)

- **map frame 부재 + Nav2 stack 출처 미확인** → 실 주행 검증 미수행. 다음 트랙 선결 조건.
- **fake_customer 기본 frame='map'** → SLAM/amcl 없이는 무용. odom/base_link frame 옵션 사용 권장.
- **`/navigate_to_pose` server 출처 미확인** — Nav2 full stack 인지 vicpinky 자체 구현인지에 따라 처리 결과 다름.

### 갭

- **W4.5 GEFA 사전작업**: USB 캠은 살아있음 (`/dev/video0`, `/dev/video1`, `Microdia HCAM01N`). 본 테스트 직후 raw publisher 추가 가능 상태.
- **SafetyCheck alarm 라이브 측정 미수행** (옵션 2 선택 안 됨). 합성 저전압 publish 한 cycle 캡처는 다음 트랙에서.
- **/scan SafetyCheck 통합** — 1.0m 이내 인간 감지 alarm. CLAUDE.md TODO §10에 이미 등록.

---

## 4. 다음 일정

### 단기 (이어가기)
- [ ] **W4.5 GEFA 사전작업**: USB 캠(`/dev/video0`) raw publisher (`image_raw`/`compressed`) RPi 측 또는 노트북 USB 직결 결정
- [ ] **SafetyCheck alarm 라이브** (5분): `ros2 topic pub --once /battery_state` 합성 저전압 → 한 cycle alarm 캡처
- [ ] **`/navigate_to_pose` server 출처 확인**: `ros2 action info /navigate_to_pose` + vicpinky_bringup launch 트레이스

### 중기 (실 Nav2 주행 트랙)
- [ ] **map frame 확보**: SLAM toolbox 빠른 매핑 또는 fake_customer를 `odom` frame으로 띄움
- [ ] **실 주행 1m 미만 짧은 검증**: watcher panic threshold(linear>0.6, angular>2.0)로 재시동, fake_customer 짧은 거리(예: customer_x=2.0 → goal 0.5m 전진)

### Phase 후속 (CLAUDE.md TODO 그대로)
- decision_rule_node (GEVA + GEFA fusion)
- SafetyCheck `/scan` 통합
- 음성/표정 dwell 통합
- persona별 dwell/abort_expression

---

## 5. 변경된 파일

```
scripts/run_teleop_ui.sh
  + SKIP_CAM=1 환경변수 분기 (Step 4 usb_cam 단계)
  + ERROR 시 HINT 메시지

docs/daily/2026-05-04_npc_first_live_test.md  (본 회고)
```

기존 코드 변경 없음. 안전 검증 1차 통과로 5aa49ce + 129b34d + ab354bd 패치들의 **실물 환경 효과 입증**.

---

*마지막 갱신: 2026-05-04 저녁 (NPC ↔ RPi 통합 라이브 7분, Approach 가드 34회 , /cmd_vel TRIP 0건 )*
*다음 갱신 예정: W4.5 USB 캠 raw publisher 또는 실 Nav2 주행 트랙*
