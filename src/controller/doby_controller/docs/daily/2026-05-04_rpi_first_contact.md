# RPi 1차 연결 — vic_pinky bringup 자동 스크립트 + SafetyCheck 라이브 검증

**작성일**: 2026-05-04
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 체크리스트**: `docs/rpi_integration_checklist.md` §1~§4.1
**상태**: vic_pinky RPi 5(192.168.0.138) ↔ 노트북(192.168.0.154) 도메인 22 토픽 발견 + 자동 bringup 스크립트 2종 + SafetyCheck `/battery_state` 통합 라이브 검증 통과.

---

## 0. 시작 시점 컨텍스트

전날(2026-05-03) **노트북 단독 트랙 + 14 커밋 완료** (Phase 2 W4):
- GEVA → EmotionMonitor → TTS → face_avatar 4 코어
- utter_done, face/utter sync, abort reset, hysteresis, log noise, 애니메이션 v2, dwell, **SafetyCheck `/battery_state` 통합** 8건

본 트랙 목표: **RPi 실물과 첫 도메인 22 통신 + bringup 자동화 + SafetyCheck 동작 라이브 확인**.

---

## 1. 작업 흐름

### Step 1: 네트워크 정정 (4개 문서 + IP/계정 갱신)

기존 `192.168.104.x` 서브넷 가정이 잘못됨. 실제는:
- vic_pinky: **192.168.0.138** (계정 `vic`, 암호 `1`)
- 노트북: **192.168.0.154** (DHCP, 검증 시점)

기존 `scripts/run_*.sh` 5개와 `docs/cabot_README.md`는 이미 `192.168.0.138 / vic@`로 일치 — 즉 cabot 시절부터 운영되던 설정. **moca 트랙 문서만 옛 IP 들고 있던 것**.

수정 파일 4개:
- `CLAUDE.md` §3 개발PC/로봇 IP, §9 로봇 연결
- `docs/rpi_integration_checklist.md` 대상 문구 + ping/ssh 명령 6곳
- `docs/cafe_npc_camera_architecture.md` 아키텍처 다이어그램 헤더
- `docs/cafe_npc_implementation_plan.md` §1.1 하드웨어

### Step 2: SSH + ROS 환경 검증

```bash
sshpass -p '1' ssh vic@192.168.0.138 "uname -a; cat /etc/os-release | head -3"
# Linux pinky 6.8.0-1052-raspi #56-Ubuntu (aarch64)
# Ubuntu 24.04.2 LTS
```

RPi `~/.bashrc` 환경:
```
source /opt/ros/jazzy/setup.bash
source ~/vicpinky_ws/install/setup.bash
ROS_DOMAIN_ID=22
```

→ moca 정책(§9)과 일치. 별도 export 불필요.

장치 확인:
- `/dev/ttyUSB0`, `/dev/ttyUSB1` (ZLAC 모터 / sllidar)
- `~/vicpinky_ws/install/vicpinky_bringup/share/vicpinky_bringup/launch/bringup.launch.xml`

### Step 3: `run_vic_bringup.sh` / `stop_vic_bringup.sh` 작성

`run_teleop_ui.sh` 패턴 차용 (원격 SSH 기동 + 로컬 검증) + teleop 의존성 제거:

`run_vic_bringup.sh` 6단계:
1. 로컬 ROS env (domain=22, fastrtps, FASTRTPS profile unset)
2. ping + sshpass 점검
3. RPi에 SSH → `pgrep [v]icpinky_bringup` 검사 후 미실행이면 setsid+nohup 백그라운드 기동 (원격 로그 `~/logs/bringup.log`)
4. moca 핵심 토픽 4종 발견 (10초 polling, 모두 OK이면 조기 break)
   - `/battery_state` (SafetyCheck 입력)
   - `/odom`, `/joint_states`, `/scan`
5. `/battery_state` percentage 1회 echo (퍼센트 변환 + SafetyCheck 임계 안내)
6. Nav2 `/navigate_to_pose` action 존재 여부 (없어도 계속 — Approach BT는 dummy fallback)

`stop_vic_bringup.sh`:
- 기본: SSH로 SIGINT → 2초 → SIGKILL (`vicpinky_bringup`, `ros2 launch vicpinky`, `sllidar`)
- `--keep` 플래그: 원격 유지하고 로컬 ros2 daemon만 정리

환경변수: `ROBOT_IP`, `ROBOT_USER`, `ROBOT_PASS`, `ROBOT_DOMAIN_ID` 모두 export로 override 가능.

**버그 1 → fix**: 초안의 `ros2 topic echo --field percentage --once | tail -1`은 YAML 구분자 `---`만 잡았음. `grep -E '^[0-9]' | head -1`로 변경. 또한 `awk`로 `0.917 → 91.7%` 형식 변환 추가.

### Step 4: 실 시동 검증 (`bash scripts/run_vic_bringup.sh`)

| 항목 | 결과 |
|---|---|
| ping 192.168.0.138 |  |
| 원격 SSH (vic@) |  |
| `pgrep` 미실행 감지 → setsid+nohup 기동 |  |
| 토픽 발견 4/4 |  |
| 배터리 percentage 91.7% |  (voltage 28.68V, 7S 만충 29.4V 근접) |
| Nav2 action 부재 안내 |  (vicpinky_navigation 별도 — 의도) |
| 재실행 idempotent |  (이미 실행 중이면 재기동 안 함) |

### Step 5: SafetyCheck 라이브 검증 (`dev_all.launch.py` + 합성 저전압)

**시퀀스**:
1. dev_all launch 백그라운드 (`fullscreen:=false`)
2. T+1.2s: 합성 저전압(10%) 5Hz publish 시작 → 실 1Hz 91.7% 압도
3. T+7s: 합성 중단 → 실 91.x% 복귀
4. SIGINT로 launch 종료, 좀비 정리

**캡처된 SafetyCheck transition** (6회):
```
[bt_executor] [WARN] [SafetyCheck] battery low:  10.0% < 20.0% → alarm
[bt_executor] [INFO] [SafetyCheck] battery recovered: 91.9% → normal
[bt_executor] [WARN] [SafetyCheck] battery low:  10.0% < 20.0% → alarm
[bt_executor] [INFO] [SafetyCheck] battery recovered: 91.1% → normal
[bt_executor] [WARN] [SafetyCheck] battery low:  10.0% < 20.0% → alarm
[bt_executor] [INFO] [SafetyCheck] battery recovered: 90.6% → normal
```

`Registered: 9 user + 41 builtin nodes` — BT 정상 등록.

---

## 2. 핵심 학습

### Race condition을 통한 SafetyCheck state-edge 입증

합성 5Hz와 실 1Hz가 같은 토픽에 동시 publish되니 atomic 캐시(`std::atomic<float> battery_pct_`)가 두 publisher의 race로 빠르게 토글. 의도하지 않은 시나리오였지만 결과적으로:
- `last_warned_low_` boolean의 1회 WARN 정책 작동 검증
- recovery INFO도 1회만 출력 (스팸 방지)
- 6번의 transition을 모두 잡아냄 → 반응성 빠름

**실 운영에서는 race 없음** — bringup 단독 publisher라 안정적 91% 유지, SafetyCheck FAILURE 지속.

### `run_teleop_ui.sh` 패턴의 재사용 가치

cabot 시대 작성된 패턴이지만 그대로 운영 가치:
- `setsid nohup ... & sshpass -f ssh` 백그라운드 기동
- pgrep `[v]icpinky_bringup` 패턴 (regex char class로 self-match 방지)
- 원격 로그 `~/logs/bringup.log` 분리
- `ros2 daemon stop/start`로 캐시 갱신

본 트랙은 teleop UI 부분만 잘라내고 토픽 검증 로직 추가. 향후 추가 모듈(GEFA usb_cam 등)은 같은 패턴 확장.

### 도메인 22 cross-machine 발견 — 무설정 동작

별도 NIC 튜닝, multicast route, fastdds profile 없이 **양 머신이 같은 서브넷(192.168.0.x) + 동일 ROS_DOMAIN_ID + 동일 RMW(fastrtps)** 만으로 토픽 발견 즉시 성공. cabot 시대의 `fastdds_pc.xml` 잔재(192.168.104.x)가 활성화돼 있으면 깨질 수 있어서 `unset FASTRTPS_DEFAULT_PROFILES_FILE` 추가.

### Approach dummy goal 안전 — Nav2 부재가 자연 차단

검증 중 SafetyCheck recovered 직후 funnel이 다음 단계 진행 시도. Approach 노드가 dummy goal (1.0, 0.0)을 Nav2에 송신하려 했으나 **`vicpinky_navigation` Nav2 미실행이라 action server 자체가 없음** → 송신 실패, cmd_vel 0건. 의도된 fallback 작동.

다만 Phase 후속에서 `vicpinky_navigation`을 띄우면 dummy goal이 실 Nav2로 전달될 위험 — 체크리스트 §5와 W2 회고에서 경고한 그대로. 실물 Approach 검증 전에 `/customer_pose` 미수신 시 Nav2 송신 차단 정책 명시 필요.

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **vic_pinky 호스트네임 `pinky`** — RPi 5, Ubuntu 24.04.2 LTS, kernel 6.8.0-1052-raspi (aarch64). ROS Jazzy 정상 빌드.
- **배터리 28.68V / 91.7%** — 7S Li-ion 만충 29.4V 근접. SafetyCheck 임계 0.20 한참 위. 실물 테스트 안전.
- **`/battery_state` 발행 1Hz** — vic_pinky bringup 정상 publish (CLAUDE.md §4.1 명세 일치).
- **노트북 도메인 22 토픽 발견 즉시 성공** — 양 머신 fastrtps 통일 + 동일 서브넷이면 무설정 작동.

### 위험 요소

- **Approach Nav2 송신 위험 (실 운영 시)**: `vicpinky_navigation` 띄우면 BT의 Approach가 `/customer_pose` 미수신 시에도 dummy goal (1.0, 0.0)을 Nav2 action으로 송신. 실물 vic_pinky가 랜덤 1m 이동 위험. **첫 통합 테스트는 cmd_vel 차단 필수**. `docs/rpi_integration_checklist.md` §5에 이미 경고됨.
- **암호 `1` 하드코딩**: 스크립트에 `ROBOT_PASS=1` 기본값. 운영 환경에선 SSH key 인증 권장. 현재는 cabot 호환성 우선.
- **DHCP IP 변동성**: 노트북·로봇 모두 DHCP. IP 바뀌면 스크립트 환경변수 override 필요 (`ROBOT_IP=... bash run_vic_bringup.sh`).
- **`fastdds_pc.xml` 잔재**: cabot 시대 환경변수가 살아있으면 토픽 발견 실패. `unset FASTRTPS_DEFAULT_PROFILES_FILE` 스크립트에 포함 — 안전망.

### 갭

- **GEFA USB 카메라 (RPC-20F)** — 본 트랙엔 미포함. W2.5 작업 시 `run_vic_bringup.sh`에 `usb_cam` 기동 단계 추가 (run_teleop_ui.sh §4 usb_cam 부분 패턴 재사용 가능).
- **Nav2 stack 자동 기동 미포함** — 현재 bringup만. 후속에 `run_vic_nav2.sh` 또는 `run_vic_bringup.sh --with-nav` 옵션 추가 검토.
- **노트북 측 `dev_all.launch.py` 자동 기동 미포함** — 의도적 분리. 통합 시나리오용 `run_moca_all.sh` 별도 검토.
- **합성 저전압 검증의 자연성**: 실 운영에선 1Hz 단독 publisher라 race 없음. 검증 결과의 "6회 토글"은 합성 시나리오 한정 — 실물에선 alarm 1회 발동 후 지속.

---

## 4. 다음 일정

### 즉시 가능

- **Approach 안전 정책**: `/customer_pose` 미수신 시 Nav2 송신 금지 명시 (코드 + 회고). 실물 Approach 검증 전 필수.
- **체크리스트 §4.2 Approach Nav2 통합 검증**: `vicpinky_navigation` Nav2 stack 띄우고 cmd_vel 모니터링 (별도 안전 차단 준비).
- **체크리스트 §4.3 cafe_funnel 1 사이클 통합**: SafetyCheck 통과 + EmotionMonitor 통과 + funnel 정상 진행 → 15~20초 기록.
- **체크리스트 §4.4 abort 카메라 검증**: hysteresis 5프레임 ON/OFF 실 표정으로 검증.

### Phase 후속

- **W2.5 GEFA**: RPi USB 카메라(RPC-20F) → 자세/접근/회피 분석 → `/emotion/state` (source=`body`)
- **decision_rule_node**: GEVA + GEFA Salichs 2014 fusion → `/emotion/state` (source=`fused`)
- **min_confidence**: rapport_tracker GEVA 신뢰도 게이팅
- **SafetyCheck `/scan` 통합**: 1.0m 이내 인간 감지 → alarm

---

## 5. 산출물 위치

### 신규 파일
- `scripts/run_vic_bringup.sh` (5577 bytes, 실행권한)
- `scripts/stop_vic_bringup.sh` (2391 bytes, 실행권한)
- `docs/daily/2026-05-04_rpi_first_contact.md` (본 회고)

### 수정 파일 (IP/계정 갱신)
- `CLAUDE.md` §3, §9
- `docs/rpi_integration_checklist.md` (대상 + ssh/ping 명령)
- `docs/cafe_npc_camera_architecture.md` (다이어그램 헤더)
- `docs/cafe_npc_implementation_plan.md` §1.1

### 변경 없음
- BT 노드, 메시지, persona YAML, dobi_npc 코드 — 모두 그대로
- 단, **SafetyCheck `/battery_state` 통합이 실물에서 동작 확인됨** (2026-05-03 ab354bd 커밋이 라이브 환경에서 입증됨)

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 시동
```bash
bash ~/moca/scripts/run_vic_bringup.sh
# 또는 환경변수 override
ROBOT_IP=192.168.0.99 bash ~/moca/scripts/run_vic_bringup.sh
```

### SafetyCheck 라이브 검증
```bash
# 좀비 정리
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null

# 노트북 dev_all 백그라운드
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
export ROS_DOMAIN_ID=22
ros2 launch dobi_npc_bringup dev_all.launch.py fullscreen:=false > /tmp/dobi.log 2>&1 &
sleep 3

# 합성 저전압 5Hz (8s 동안)
ros2 topic pub --rate 5 /battery_state sensor_msgs/msg/BatteryState \
  "{header: {frame_id: 'base_link'}, voltage: 21.5, percentage: 0.10, present: true}" &
SYNTH_PID=$!
sleep 8
kill -INT $SYNTH_PID

# 결과 확인
grep -E "SafetyCheck" /tmp/dobi.log
# 기대: alarm + recovered transition

# 정리
pkill -INT -f "ros2 launch dobi_npc_bringup"
sleep 3
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
```

### 종료
```bash
bash ~/moca/scripts/stop_vic_bringup.sh         # 원격 bringup 종료
bash ~/moca/scripts/stop_vic_bringup.sh --keep  # 원격 유지, 로컬만 정리
```

---

**상태**: RPi 1차 통신 + 자동 bringup 스크립트 + SafetyCheck 라이브 검증 완료. 다음은 Approach Nav2 통합 검증 전 안전 정책 강화 또는 cafe_funnel 1 사이클 라이브 검증.
