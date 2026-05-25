# CLAUDE.md — moca 워크스페이스 컨텍스트

> 이 문서는 Claude(또는 다른 LLM 어시스턴트)와 작업할 때 매번 참조할 프로젝트 컨텍스트다.
> 사람도 새로 합류한 팀원이라면 이 문서부터 읽으면 된다.

**프로젝트**: Dobi Barista 호객 BT 시스템
**작업자**: 공국진 (Stephen, gjkong / skong097 / kong@pinklab.art)
**소속**: PinkLAB (핑크랩, pinklab.art)
**시작일**: 2026-05-01
**현재 Phase**: 0-B 완료, Phase 1 진입 준비

---

## 🛑 0-A. 세션 규칙 — 팀 작업 중 RPi 접근 금지 (조건부, 사용자 명시)

사용자/팀이 **실물 Vic Pinky (RPi 192.168.0.138 / vic@) 사용 중** 신호 시 → Claude 는 RPi 에 어떤 명령도 보내지 않는다.

- 금지 명령: `ssh vic@192.168.0.138`, `sshpass`, `scp ... 192.168.0.138`, `ros2 daemon --remote`
- 금지 스크립트: `run_teleop_ui.sh` (step 3 자동 RPi SSH bringup)
- PC 단독 작업 (Gazebo 시뮬 등): `ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1` 강제. **DOMAIN=99 (시뮬 전용 격리 도메인)** + **LOCALHOST_ONLY=1 (loopback 만)**. 도메인 차원 격리 + 네트워크 차원 격리 이중. 라이브 RPi (DOMAIN=22) 와 토픽 비호환 — 시뮬에서 라이브 코드 그대로 검증 시 환경 변수만 22 로 바꿔 동일 코드 작동.
- 해제: 사용자 명시 ("RPi 사용 OK") 까지 유지. 묵시적 해제 X.

본 규칙은 메모리 [[feedback_no_rpi_when_team_working]] 에 영구화. 일일 백업 [[feedback_daily_backup_routine]] 도 신호 시기엔 PC 백업만.

---

## 🛑 0-B. 절대 규칙 — vic_pinky 관련 자산 일체 수정 금지 (2026-05-19 영구화)

> **사전 숙지 원칙 (사용자 명시 2026-05-19)**: doby 는 매 코드 작업 진입 (Edit/Write/scp/rsync/cp/git checkout 등) 직전 본 §0-B 를 반드시 사전 숙지한다. 사용자 결정과 본 정책이 충돌하는 것처럼 보이면 항상 정책 우선 + 사용자에게 재확인. "사소해 보이는 1줄 patch" 도 예외 X. 본 원칙은 작업 진입 회수만큼 매번 적용.

**doby 는 vic_pinky 트리 + vic_pinky 의존 운영 스크립트 어떤 형태로도 수정/덮어쓰기 X.**

### 범위 (광의 해석 — 사용자 명시 강력 강조)

- **vic_pinky 패키지 트리**:
  - PC: `src/shared/vic_pinky/` 전체 (bringup.launch.xml, twist_mux.yaml, collision_monitor.yaml, velocity_smoother.yaml, zlac_driver.py, bringup.py 등)
  - RPi: `~/vicpinky_ws/` 전체 + `/etc/ros2`, udev, systemd 환경
- **vic_pinky 의존 운영 스크립트** (scripts/ 디렉토리 안에 있어도 vic_pinky 와 직접 연계되면 보호):
  - `scripts/run_vic_bringup.sh`, `scripts/stop_vic_bringup.sh`
  - `scripts/run_robot_cam.sh`, `scripts/stop_robot_cam.sh`
  - `scripts/run_teleop_ui.sh`, `scripts/stop_teleop_ui.sh`
  - `scripts/run_nav2.sh`, `scripts/stop_nav2.sh`
  - `scripts/run_3stage.sh` (RPi bringup + 카메라 + Nav2 + dev_common 통합 wrapper)
  - 향후 vic_pinky 연계 신규 스크립트도 동일 정책 적용

### 금지 액션

- Edit/Write 도구로 위 자산의 어떤 파일도 변경 X
- scp / rsync / cp 로 PC ↔ RPi 덮어쓰기 X (`--exclude=COLCON_IGNORE` 추가해도 의미 차원 위반)
- git checkout / reset / merge / stash 등 git state 변경 X
- install/share/* 강제 cp X
- ros2 param set 런타임 파라미터 변경 X
- launch arg override 도 운영값 침범 X
- ⚠ "1줄짜리 작은 patch", "환경변수 누락 fix" 등 사소해 보이는 변경도 절대 X

### 허용 액션 (read-only 진단만)

- `cat`, `ls`, `head`, `tail`, `git status`, `git log`, `git diff`
- `ros2 topic echo --once`, `ros2 topic hz`, `ros2 node list`, `ros2 lifecycle nodes`, `ros2 param get`, `ros2 service list`
- 위 스크립트 실행 (`bash run_*.sh`, `bash stop_*.sh`) — 호출만 OK, 내용 수정 X
- `pgrep`, `ps`, `kill` 본인 spawn 한 process 만

### 문제 발견 시 절차 (위반 회피)

1. read-only 진단으로 증상 + 가설 작성
2. 사용자에게 솔직 보고 — "X 위치에 patch 가 필요해 보이지만 본 정책상 doby 수정 금지"
3. **사용자 명시 승인 + 팀원 협의 후에만** 수정 진행
4. 수정 시에도 변경 전 백업 ([[feedback_rpi_backup_before_change]]) + 최소 변경 원칙 ([[feedback_dont_touch_working_code]])

### 본 정책 발생 배경

- 2026-05-18 1차 세션: PC SoT 를 RPi 로 일방 rsync → PinkLAB main 신규 8 commits 손실 + 5/14 백업 복원으로 4-5 시간 소실
- 2026-05-19 본 세션: `run_3stage.sh` (vic_pinky 연계 운영 스크립트) 의 DDS env 누락 발견 후 doby 가 "1줄 patch" 시도 → 사용자 강력 명시 거부 → 즉시 revert + 본 정책 명문화

### 자동 분류기 정합

본 정책에 위배되는 Bash 도구 호출 (예: `ssh sshpass vic@138`, scp 덮어쓰기) 은 Claude Code auto-mode classifier 가 자동 거부. doby 가 우회 시도 금지.

### 관련 메모리

- [[feedback_no_vic_pinky_modification]] (본 §0-B 동기화)
- [[feedback_dont_touch_working_code]] (잘 동작하는 코드 일반 보호)
- [[feedback_no_rpi_when_team_working]] (§0-A 정합)
- [[project_operation_architecture_pc_centric]] (rsync exclude 정책)

본 정책은 사용자 명시 해제까지 영구 유지.

---

## ⚠ 0. 절대 규칙 — `~/cabot` 은 다른 프로젝트, 참조 금지

**`~/cabot/`** 은 본 moca 프로젝트와 **별개의 다른 프로젝트**다. Phase 0-A (2026-05-01) 마이그레이션 이후 일부 자산이 moca 로 옮겨졌지만, **`~/cabot/` 자체는 다른 코드베이스**.

- 코드/스크립트/launch/config 작성 시 **`~/cabot/` 경로를 절대 참조하지 말 것**.
- 기존 스크립트에 `$HOME/cabot` 같은 잔재가 있으면 **즉시 워크스페이스 루트로 수정** (2026-05-19 현재 루트: `$HOME/physical-ai-repo-3/src/controller/doby_controller` — 그러나 절대경로 하드코딩보다 §7 SCRIPT_DIR/env 기반 추정 권장. 예: 2026-05-09 `run_teleop_ui.sh` 의 `WS="$HOME/cabot"` 사고).
- moca 의 SoT 는 항상 **`~/physical-ai-repo-3/src/controller/doby_controller/`** 트리. 같은 파일이 두 곳에 있으면 본 경로가 권위적.
- 마이그레이션 참고용으로 일부 docs (`~/physical-ai-repo-3/src/controller/doby_controller/docs/cabot_legacy/`) 는 보존되지만, 그 외 cabot 코드는 의존성으로 취급 X.

---

## 1. 한 줄 정의

> **카페에서 손님에게 호객 행위를 하는 자율 로봇의 행동 의사결정 시스템.**
> Vic Pinky Pro 모바일 베이스 위에 BehaviorTree.CPP 기반 5-stage funnel BT를 얹고,
> 사용자의 감정 상태(Russell 차원 모델)에 따라 호객 전략을 동적으로 조정한다.

---

## 2. 학술 토대 — 6-Layer 청사진

본 시스템의 모든 의사결정은 45년에 걸친 6편의 핵심 논문에 학술 근거를 둔다.
상세는 `docs/cafe_npc_paper_master.md` 참조.

```
┌──────────────────────────────────────────────────────────────┐
│ [Layer 6] 미래 확장 — Iovino+ (2022) BT 서베이                │
│ [Layer 5] BT 형식화 — Marzinotto+ (2014) 표준                 │
│ [Layer 4] 게임 인터랙션 — Castro-González+ (2016) RPS+Polite  │
│ [Layer 3] 다중모달 감정 — Salichs+ (2014) GEFA+GEVA           │
│ [Layer 2] 감정 모델 — Russell (1980) Circumplex (V, A)        │
│ [Layer 1] BT 시작 — Isla (2005) Halo 2 패러다임               │
└──────────────────────────────────────────────────────────────┘
```

**v2 컴포넌트 ↔ 학술 근거 매핑**:
| 컴포넌트 | 근거 |
|---|---|
| 5-stage funnel (IDLE→APPROACH→ICEBREAK→MINIGAME→OFFER→LEAD-IN) | Isla 2005 |
| 페르소나 상속 (Generic→Casual/Friendly/Professional) | Isla 2005 character hierarchy |
| `valence_arousal_mapper` (7-emotion → V,A 좌표) | Russell 1980 |
| GEFA+GEVA → Decision Rule | Salichs 2014 |
| Abort 트리거 (V<-0.5, A>0.4) | Russell 1980 + Salichs 2014 |
| 가위바위보 미니게임 + Polite phrase pool | Castro-González 2016 |
| 70% 고객 승리율 | Castro-González 2016 (engagement > winning) |
| BT XML 표준 (Sequence, Fallback, Parallel) | Marzinotto 2014 |
| Phase 5 XAI/Learning 확장 | Iovino 2022 미해결 과제 |

### ⚠ 약어 GEVA / GEFA — 본 프로젝트 정의 (Salichs 원어와 모달리티가 다름, 주의)

Salichs 2014 학술 원어 (검증됨):
- **GEVA = Gender and Emotion Voice Analysis** (Chuck 언어로 작성된 음성 분석 모듈)
- **GEFA = Gender and Emotion Facial Analysis** (SHORE + CERT 통합 얼굴 분석 모듈)

즉 원어 모달리티는 **GEVA=Voice / GEFA=Face**.

본 프로젝트는 **모달리티 매핑을 의도적으로 재정의**해서 사용한다 (약어 풀이 자체는 원어 유지):

| 약어 | 본 프로젝트 매핑 (구현 계획 + 코드 + 회고) | Salichs 원어 모달리티 |
|---|---|---|
| **GEVA** | **노트북 웹캠 → 얼굴 표정 → V·A** (face) | Voice (음성) |
| **GEFA** | **RPi USB 캠 → 자세/접근/회피** (body, RPi 확보 시) | Face (얼굴) |

본 프로젝트는 **얼굴=GEVA, 자세=GEFA**로 일관 사용. 학술 발표/논문 작성 시점에서만 원어 매핑(face=GEFA, voice=GEVA) 명기. 코드/노드명/회고는 본 정의 그대로.

따라서 `dobi_npc_emotion/geva_node.py`는 **얼굴 표정 분석 노드**이고, 향후 추가될 `gefa_node.py`는 **자세 분석 노드**가 된다 (`/emotion/state` 토픽의 `source` 필드로 구분: `"face"` vs `"body"`).

원어 풀이/정의는 `docs/cafe_npc_paper_master.md` §Layer 3 참조.

---

## 3. 워크스페이스 구조

```
~/physical-ai-repo-3/src/controller/doby_controller/   ← 통합 워크스페이스 (다른 팀원 모듈도 추후 합쳐짐 — 2026-05-19 이전 `~/moca/`)
├── CLAUDE.md                            ← 본 문서 (프로젝트 컨텍스트)
├── README.md                            ← 빌드 가이드
├── moca.repos                           ← vcs import용
├── .gitignore                           ← 빌드 산출물 + 무거운 자산 제외
│
├── src/
│   ├── shared/                          ← 모든 팀원 공유 자산
│   │   └── vic_pinky/                   ← PinkLAB 공식 (자체 git: pinklab-art/vic_pinky)
│   │       ├── vicpinky_description     [✅ 빌드 대상]
│   │       ├── vicpinky_navigation      [✅ 빌드 대상]
│   │       ├── vicpinky_bringup         [❌ COLCON_IGNORE — 로봇만]
│   │       ├── vicpinky_gazebo          [❌ COLCON_IGNORE — 시뮬]
│   │       └── vicpinky_emotion         [❌ 노드 미사용 — vicpinky는 LCD 없음. 자산(emotion/*.gif 8개)만 노트북 풀스크린에서 재활용]
│   │
│   └── dobi_npc/                        ← 본 작업 (호객 BT 6 패키지)
│       ├── dobi_npc_msgs/               (커스텀 메시지 4종)
│       ├── dobi_npc_bt/                 (C++ BT 노드)
│       ├── dobi_npc_emotion/            (감정 인식 — Phase 2)
│       ├── dobi_npc_dialog/             (페르소나/TTS — Phase 1 W3)
│       ├── dobi_npc_minigame/           (RPS — Phase 3)
│       └── dobi_npc_bringup/            (통합 launch — Phase 4)
│
├── docs/
│   ├── daily/                           ← 일일 회고 (.md)
│   ├── cafe_npc_paper_master.md         ← 학술 척추
│   ├── cafe_npc_implementation_plan.md  ← 16주 구현 계획
│   └── cabot_legacy/                    ← cabot 시절 문서 (참고용, gitignore)
│
├── config/personas/                     ← Phase 1 W3에서 채움
├── scripts/                             ← 운영 스크립트
└── (gitignore: build/, install/, log/, maps/, datasets/, web/, models/)
```

### 빌드 명령어

```bash
# scripts/moca_env.sh 를 source 하면 아래 함수들이 현재 셸에 로드된다
# (.bashrc 는 손대지 않는 방식 — 2026-05-19 사용자 결정)
source ~/physical-ai-repo-3/src/controller/doby_controller/scripts/moca_env.sh

moca_cd          # 워크스페이스 루트로 이동
moca_build       # 격리 셸 (--noprofile --norc) 에서 colcon 빌드 — robot_arm 자동 source 영향 회피
moca_activate    # install/setup.bash 활성화
moca_clean       # build/install/log 삭제

# 직접 호출 (스크립트 source 없이)
cd ~/physical-ai-repo-3/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

`MOCA_WS_ROOT` 환경변수는 `moca_env.sh` 가 SCRIPT_DIR/.. 기준으로 자동 추정 — 다른 머신/clone 위치에서도 동일 작동 (§7 상대경로 컨벤션 정합).

### 개발 PC vs 로봇 차이

- **개발 PC** (192.168.0.154, vic_pinky 상단 거치): vicpinky_description, vicpinky_navigation + dobi_npc 6개 = 8 패키지 빌드. **노트북 풀스크린에서 얼굴 표현 + 페르소나 아바타 + 미니게임 UI 담당**.
- **로봇** (라즈베리파이 5, 192.168.0.138, 계정 `vic`): vicpinky_bringup, vicpinky_gazebo의 COLCON_IGNORE 삭제 후 빌드. **vicpinky_emotion 노드는 vicpinky가 LCD 없어서 미사용** (자산만 노트북에서 재활용).

---

## 4. 검증된 ROS2 인터페이스 명세

Phase 0-A에서 발굴한 인터페이스. Phase 1+에서 BT 노드를 짤 때 직접 참조한다.

### 4.1 입력 토픽 (BT가 구독)

| 토픽 | 타입 | 발행자 | 용도 |
|---|---|---|---|
| `/odom` | nav_msgs/Odometry | vicpinky_bringup | 로봇 위치 추정 |
| `/joint_states` | sensor_msgs/JointState | vicpinky_bringup | 휠 관절 상태 |
| **`/battery_state`** ⭐ | sensor_msgs/BatteryState | vicpinky_bringup | **SafetyCheck 1순위 입력** |
| `/scan` | sensor_msgs/LaserScan | RPLiDAR | Nav2 obstacle |

**`/battery_state` 세부:**
- 발행 주기: 1Hz
- 7S Li-ion 가정: 21.0V (컷오프) ~ 29.4V (만충)
- `percentage` 필드: 0.0~1.0 (clamp 적용)
- **호객 BT 임계값**: percentage < 0.20 → abort + 충전소 복귀

### 4.2 출력 토픽/액션/서비스 (BT가 발행/호출)

| 인터페이스 | 타입 | 용도 |
|---|---|---|
| `/cmd_vel` | geometry_msgs/Twist | 직접 제어 (사용 자제, Nav2 우선) |
| `NavigateToPose` 액션 | nav2_msgs/action/NavigateToPose | **Approach 노드의 본 인터페이스** |
| `/dialog/request` | std_msgs/String | **BT → persona_manager** (W3 통합, stage_id 발행) |
| `/dialog/utter` | std_msgs/String | **persona_manager → TTS** (Phase 2, 선택된 phrase 발행) |
| `/face_avatar/expression` ⭐ | std_msgs/String (TBD) | **노트북 풀스크린 얼굴 표현 GUI 입력 (Phase 2 신규, 8 어휘)** |

**얼굴 표정 8 어휘 (vicpinky_emotion/emotion/*.gif 자산 그대로):**
```
basic, hello, happy, fun, interest, bored, sad, angry
```

**주의**: vicpinky는 PinkyPro의 LCD가 없어 **`/set_emotion` (pinky_interfaces) 미사용**. 같은 8 어휘를 노트북 풀스크린 GUI 노드에 매핑.

**Russell V-A 좌표와의 권장 매핑:**
```
                Activation (high)
                      ▲
            angry     │  fun
                      │
        Unpleasant ───┼─── Pleasant
                      │
              sad     │  happy / interest
                      │
                bored / basic
                Activation (low)
```

### 4.3 dobi_npc_msgs 커스텀 메시지

```
# msg/EmotionState.msg     — 사용자 감정 상태 (Russell V,A + Salichs 신뢰도)
std_msgs/Header header
float32 valence            # -1.0 ~ +1.0
float32 arousal            # -1.0 ~ +1.0
float32 confidence         # 0.0 ~ 1.0
string source              # "face" | "voice" | "fused"
string[] flags             # ["mask_smile", "voice_only", "agree", "conflict"]

# msg/RapportEvent.msg     — BT의 EmotionMonitor가 받는 이벤트
std_msgs/Header header
string event_type          # "engagement_up/down" | "abort_trigger" | "neutral_continue"
float32 weight             # -1.0 ~ +1.0
EmotionState emotion       # 중첩 (이벤트를 일으킨 감정)
string reason              # "anger_detected" | "smile_genuine" | ...

# msg/MinigameResult.msg   — RPS 결과 (Castro-González 패러다임)
std_msgs/Header header
string game_id
uint32 rounds_played, customer_wins, robot_wins, ties
float32 customer_win_rate  # 목표: 0.7
float32 duration_sec
bool completed

# srv/SetPersona.srv       — 페르소나 전환
string persona_name        # "casual_browser" | "friendly_child" | "professional_adult"
---
bool success
string current_persona
```

### 4.4 vic_pinky 로컬 변경사항 (보존됨)

`~/physical-ai-repo-3/src/controller/doby_controller/src/shared/vic_pinky/` 에 다음 변경이 `feature/dobi-npc-base` 브랜치에 보존됨:

- **bringup.py**: `/battery_state` 토픽 발행 추가 (BatteryState, 1Hz, 7S Li-ion 가정)
- **zlac_driver.py**: `GET_BUS_VOLTAGE` Modbus 레지스터(0x20A1) 추가
- **vicpinky_emotion/**: PinkyPro LCD용 패키지. vicpinky는 LCD 없어 노드 미사용. **자산(emotion/*.gif 8개)만 노트북 풀스크린 GUI에서 재활용**
- **COLCON_IGNORE**: 개발 PC에서 emotion/bringup/gazebo 빌드 제외

**원본 보존**: `main` 브랜치는 PinkLAB 원본(51da1b1) 그대로. `git checkout main` 하면 원본 복구.

---

## 5. 표준 코드 패턴

### 5.1 ROS2 Python 노드 main() — 견고한 라이프사이클

**모든 dobi_npc Python 노드는 이 패턴을 따른다.** Phase 0-B에서 확립.

```python
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException


class XxxNode(Node):
    def __init__(self):
        super().__init__('xxx_node')
        # ...


def main(args=None):
    rclpy.init(args=args)
    node = XxxNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # KeyboardInterrupt: Ctrl+C
        # ExternalShutdownException: SIGTERM, lifecycle, etc.
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
```

**reference 파일** (Phase 1에서 카피해서 시작):
- `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/dummy_emotion_node.py`

### 5.2 BT 노드 (C++) — Phase 0-B 더미

`src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/dummy_action.hpp`가 reference.
Phase 1 W1에서 IdleScan, Approach, IceBreak 등으로 교체된다.

```cpp
class XxxAction : public BT::SyncActionNode  // 또는 StatefulActionNode
{
public:
  XxxAction(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}

  static BT::PortsList providedPorts() {
    return { BT::InputPort<std::string>("port_name") };
  }

  BT::NodeStatus tick() override {
    // ...
    return BT::NodeStatus::SUCCESS;
  }
};
```

---

## 6. Phase 진행 상황

### ✅ Phase 0-A (완료, 2026-05-01)
- cabot → moca 마이그레이션
- src/shared/, src/dobi_npc/ 분리 구조
- vic_pinky 검증 빌드 (vicpinky_description, vicpinky_navigation)
- vic_pinky 로컬 변경사항을 feature 브랜치에 보존
- 회고: `docs/daily/2026-05-01_phase0a_migration.md`

### ✅ Phase 0-B (완료, 2026-05-01)
- 메타파일 (.gitignore, README.md, moca.repos)
- dobi_npc 6개 패키지 골격 생성
- 더미 노드 + 빌드 검증 통과 (8개 패키지)
- 견고한 main() 패턴 확립
- CLAUDE.md, git 저장소 초기화

### 🔜 Phase 1 (다음, Week 1-3)
**대응 학술 Layer**: Layer 1 (Isla 2005), Layer 5 (Marzinotto 2014)

**목표**: 5-stage funnel BT를 BehaviorTree.CPP로 구현 (감정 인식 없이도 작동)

**Week별 작업:**
- **W1**: 6개 BT 노드 골격 (SafetyCheck, IdleScan, Approach, IceBreak, Minigame, Offer, LeadIn) → cafe_funnel_v1.xml
- **W2**: Approach를 Nav2 Action Client로 (Proxemic 1.5m, abort 1.0m)
- **W3**: 페르소나 상속 (3종 YAML) + Phrase Pool

**Phase 1에 추가될 자산** (Phase 0-A에서 발굴):
- BatteryCheck 노드 (Marzinotto priority safety의 1등 후보)
- 얼굴 표정 8 어휘 (노트북 풀스크린 GUI 입력 — Phase 2 face_avatar 노드 신설 시 통합)

### 🗓 Phase 2-5 개요
- **Phase 2 (W4-6)**: 감정 인식 ROS2 노드 (EyeCon 포팅, GEFA+GEVA, Decision Rule)
- **Phase 3 (W7-9)**: RPS 미니게임 + Polite phrase + OMX 가위바위보
- **Phase 4 (W10-12)**: 통합 + N=5 파일럿 테스트
- **Phase 5 (W13-16)**: XAI / Learning (Iovino 2022 미해결 과제)

상세는 `docs/cafe_npc_implementation_plan.md` 참조.

---

## 7. 작업 규칙 (Stephen 선호 워크플로우)

### 디버깅 스타일
- **한 단계씩**: 명령어 한 블록 → 결과 확인 → 다음
- **부분 패치 지양**: 파일 통째로 다시 쓰기 선호 (sed 패턴 매칭은 함정)
- **검증 우선**: 빌드/실행 검증 후에 다음 작업

### 일일 .md 루틴
- 하루 마지막 코드 작성 후 → 일일 .md 작성
- 위치: `~/physical-ai-repo-3/src/controller/doby_controller/docs/daily/YYYY-MM-DD_<topic>.md`
- 내용: 변경사항 + 회고 + 발견 + 다음 일정

### ⭐ 일일 백업 루틴 (2026-05-14 부터 적용 — **매우 중요**)
- **작업 시작 전 매일 1회** PC + RPi 양쪽 소스 백업 본 생성 (오늘부터 모든 작업의 사전 조건).
- 위치: `~/backup/moca_daily_YYYYMMDD/`
  - `laptop/` — `git_state.txt`, `moca_unstaged.patch`, `moca_staged.patch`, `moca_src_<sha>.tar.gz` (src/scripts/config/launch/docs 만, build/install/log/maps/.venv 제외)
  - `rpi/` — `git_state.txt`, `dpkg_list.txt`, vic_pinky workspace tar.gz, /etc/ros2 등 환경 설정 사본
  - `README.md` — 그 날 백업 시점/사유/git sha/RPi 호스트명/네트워크 상태 1~2줄
- **RPi 가 SSH 안 되면 그 날 작업 보류** — 라이브 변경의 회복 경로가 없는 상태에서 작업 금지.
- 기존 백업 컨벤션 호환: `~/backup/moca_phase_a_20260509/` 처럼 phase 단위 백업은 보존 (덮어쓰기 X).
- 관련 메모리: [[feedback_rpi_backup_before_change.md]] (변경 전 백업 — 본 루틴과 별개로 RPi 자산 변경 직전엔 한 번 더).

### 최신 파일 우선
- 사용자가 업로드한 파일이 있으면 **항상 그 파일을 기준**으로 작업
- 이전 버전 사용 금지

### 외부 의존성 버전 정책 (Phase 1 진입 시점 기준 — 2026-05-01)
- **BehaviorTree.CPP**: `ros-jazzy-behaviortree-cpp 4.8.3-1noble` (apt 공식, 4.9.0 업그레이드 보류)
- **ROS2 distro**: Jazzy (Ubuntu 24.04 noble)
- **mediapipe**: `0.10.14` (Phase 2 W4 진입 시 핀, EyeCon v3.5 검증 버전). `pip install --user mediapipe==0.10.14`. **주의**: 기본 설치 시 `numpy==2.x` + `opencv-contrib-python==4.13.x`가 user site에 같이 들어와 시스템 ROS(numpy 1.26.4 + cv2 4.6.0)를 깨뜨리므로, 설치 직후 `pip uninstall --yes numpy opencv-contrib-python` 필수.
- **edge-tts**: `7.2.7` (Phase 2 W4-③ 진입 시 핀, EyeCon v3.5 검증 버전). `pip install --user edge-tts==7.2.7`. transitive 의존성(aiohttp/yarl 등)은 ROS와 충돌 없음 — 별도 cleanup 불필요. **인터넷 필요** (Microsoft 클라우드 TTS). 다른 팀원이 LLM/TTS 조사 중이라 추후 변경 가능 — 변경 시 `tts_node.py` 재구현 + persona YAML `voice` 섹션 + 본 정책 갱신.
- **pygame**: 시스템 apt `python3-pygame` 2.5.2. SDL2 binding, 다른 의존성 없어 안전.
- **Pillow**: 시스템 apt `python3-pil` 10.2.0. GIF 프레임 분석에 사용.
- **opencv-python**: 시스템 cv2 4.6.0 (apt `python3-opencv`) 사용. **pip 별도 설치 금지** — `cv_bridge`가 시스템 cv2에 빌드돼 있어 충돌.
- **numpy**: 시스템 numpy 1.26.4 (apt `python3-numpy`) 사용. **pip로 numpy 2.x 설치 금지** — 시스템 matplotlib/cv_bridge가 numpy 1.x로 컴파일됨.
- **변경 시점**: Phase 종료 회고 (`docs/daily/`)에 사유와 함께 기록
- **금지**: Phase 1~4 진행 중 BT/mediapipe 메이저 버전 임의 변경

### 검증 빌드 환경
- **격리 셸**: `bash --noprofile --norc -c '...'` 로 .bashrc 영향 없이 빌드
- 이유: 자동 source되는 robot_arm 워크스페이스가 의존성 추적을 흐림
- **완전 격리가 필요할 때**: `env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '...'` — 부모 셸의 `AMENT_PREFIX_PATH` 등이 colcon prefix chaining에 영향을 주는 경우 사용

### package.xml 작성 함정 (Phase 2 W4에서 발견)
- **`<description>`에 유니코드 특수문자(`—` em-dash, `→`, `·`, 한글) 사용 금지**: colcon 파서가 `<build_type>ament_python</build_type>` 인식에 실패하여 install 시 `ament_prefix_path` hook이 생성되지 않는다. 결과적으로 `ros2 run <pkg>`가 "Package not found"로 실패.
- **증상**: 빌드는 통과하나 `install/<pkg>/share/<pkg>/hook/`에 `pythonpath.sh`만 있고 `ament_prefix_path.sh` 누락. `package.dsv`에 ament_prefix_path source 라인 누락.
- **해결**: description은 ASCII만 사용. 한글 설명이 필요하면 README나 회고 .md에 작성.
- **패키지명/버전/메인테이너 등 다른 필드는 영향 없음** — `<description>` 노드만 함정.

### RPi scp 경로 규칙 (2026-05-18 사고에서 확립)

**`run_vic_bringup.sh`는 `~/vicpinky_ws`에서 bringup을 실행한다. `~/physical-ai-repo-3/src/controller/doby_controller`로 scp해도 RPi에 적용 안 됨.**

vicpinky_bringup 파일을 RPi에 반영할 때는 아래 두 경로 모두 전송해야 한다:

```bash
# 소스
scp <파일> vic@192.168.0.138:~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/launch/<파일명>

# install
scp <파일> vic@192.168.0.138:~/vicpinky_ws/install/vicpinky_bringup/share/vicpinky_bringup/launch/<파일명>
```

- scp 후 반드시 **bringup 재시작** 필요 — 실행 중인 프로세스에는 미적용
- velocity_smoother 출력 토픽 내부명: `cmd_vel_smoothed` (`smoothed_cmd_vel` 아님)

### 언어
- 주 작업 언어: **한국어**
- 코드 주석: 한국어 + 영어 혼용 OK
- 영어로 답변 안 함 (사용자 한국어 입력 시 한국어 응답)

### ⭐ 상대경로 컨벤션 (2026-05-16 — 협업/GitHub 공개 대비)

**왜**: 본 저장소는 동료 (송민규/류재상/김진우/김덕현/안순혁) 와 공유 + GitHub 공개 예정.
다른 home, 다른 워크스페이스 이름, 다른 clone 위치에서도 동일하게 작동해야 함.

**금지 패턴** (신규 코드 + 기존 코드 발견 즉시 수정):
- `WS="$HOME/physical-ai-repo-3/src/controller/doby_controller"` (또는 `$HOME/moca`, `$HOME/cabot` 같은 옛 경로 — §0 cabot 금지 / §3 SoT 위반)
- `os.path.expanduser('~/physical-ai-repo-3/.../...')` 절대 디렉토리 명시
- launch XML 의 `$(env HOME)/moca/...`
- `/home/gjkong/...` 직접 경로

**bash 스크립트 — SCRIPT_DIR 기반 워크스페이스 추정**:
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
```

**Python ROS 노드 — 우선순위 3단**:
1. ament 패키지 자산 → `from ament_index_python.packages import get_package_share_directory`
2. 워크스페이스 자산 → 환경변수 + 워크스페이스 추정 fallback (예: `face_avatar_node._find_workspace_root()`, `minigame_runner_node._games_root()` 참조)
3. launch 가 노드 파라미터로 절대경로 주입 (예: `mode_serving.launch.py` 의 `tables_yaml`)

워크스페이스 추정 helper 패턴 (Python):
```python
def _find_workspace_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(here, 'src')) and (
            os.path.isfile(os.path.join(here, 'moca.repos')) or
            os.path.isfile(os.path.join(here, 'CLAUDE.md'))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here: break
        here = parent
    return ''
```

**launch XML — env var + 패키지 share fallback**:
```xml
<arg name="map" default="$(env MOCA_MAP_PATH $(find-pkg-share moca_navigation)/../../../maps/mapv5.yaml)"/>
```

**예외 (그대로 허용)**:
- `~/.gazebo/models` — Gazebo 표준 사용자 캐시 경로
- docstring/주석 안의 예시 명령 (사용자 안내용, 코드 동작 무관)
- 외부 자산 참조 표 (§8) — 참조 위치 안내라 절대경로 OK

**환경변수 컨벤션**:
- `MOCA_WS_ROOT` (선택) — 워크스페이스 루트 명시
- `MOCA_GIF_DIR` — face_avatar gif 디렉토리 override
- `MOCA_GAMES_DIR` — minigame games/ 디렉토리 override
- `MOCA_MAP_PATH` — nav2 map yaml 경로 override

본 컨벤션 위반 발견 시: 즉시 SCRIPT_DIR/env/추정 helper 로 교체. CLAUDE.md §0 cabot 절대 참조 금지와 함께 PR 리뷰 시 점검.

상세: 2026-05-16 회고 `docs/daily/2026-05-16_relative_path_convention.md` (별도 작성 예정).

---

## 8. 주요 외부 자산 (참조 위치)

| 자산 | 위치 | 용도 |
|---|---|---|
| EyeCon v3.5 | `~/dev_ws/eyecon` | Phase 2 GEFA+GEVA 포팅 원본 |
| 피노키오 v3.5 | `~/dev_ws/eyecon` | LLM 대화 전략 참고 |
| Pinky Nav2 튜닝 | `~/cabot/src/.../vicpinky_navigation/params` | 본 워크스페이스로 마이그레이션됨 |
| OMX LeRobot | `~/robot_arm/` | Phase 3 RPS 모션 참고 |
| ~~dalimi 천장 카메라~~ | ~~`~/dev_ws/dalimi_gazebo_teleop`~~ | **제외** (맵 좌표계 불일치) |
| vicpinky_emotion 자산 | `~/physical-ai-repo-3/src/controller/doby_controller/src/.../vicpinky_emotion/emotion/*.gif` | **노트북 풀스크린 얼굴 표현 GUI 입력 (8 어휘 .gif)** |

---

## 9. 자주 쓰는 명령어 모음

### 빌드/실행
```bash
moca_build                  # 전체 빌드
moca_activate               # 빌드 결과 활성화
moca_clean                  # build/install/log 삭제

# 개별 패키지 빌드
colcon build --packages-select dobi_npc_bt --symlink-install

# 더미 노드 실행 (Phase 0-B)
ros2 run dobi_npc_emotion dummy_emotion_node
ros2 run dobi_npc_bt bt_executor
```

### 검증
```bash
# 모든 패키지 등록 확인
ros2 pkg list | grep -E "dobi_npc|vicpinky"

# 메시지 인터페이스
ros2 interface list | grep dobi_npc_msgs
ros2 interface show dobi_npc_msgs/msg/EmotionState
```

### 로봇 연결 (참고)
```bash
# 로봇 IP: 192.168.0.138, 계정 vic, ROS_DOMAIN_ID=22
ssh vic@192.168.0.138
ros2 topic echo /battery_state    # 배터리 상태 확인
# /set_emotion 서비스는 vicpinky에 LCD가 없어 미제공.
# 얼굴 표현은 노트북 풀스크린 GUI 노드(Phase 2)가 담당.
```

---

## 10. Open Questions / TODO

### 해결된 항목 (2026-05-01 ~ 2026-05-03)

- [x] **Phase 1 W3**: 페르소나 YAML `face_expression` 필드 → 8 어휘 매핑 (페르소나 YAML)
- [x] **Phase 2 W4**: face_avatar GUI 프레임워크 → **pygame** (apt python3-pygame 2.5.2). Qt/웹 비교 후 단순성 + ROS 호환성으로 선택.
- [x] **Phase 2 W4**: face_avatar 자산 처리 → vicpinky_emotion에서 직접 참조 (`gif_dir` 파라미터, 33MB 복사 회피)
- [x] **Phase 2 W4**: EyeCon 포팅 의존성 → **mediapipe 0.10.14 user pip + numpy/cv2 시스템 apt** (transitive cleanup 필수). edge-tts 7.2.7 user pip.
- [x] **Phase 1 W1**: BatteryCheck → **SafetyCheck에 통합** (`/battery_state.percentage < battery_min`). 별도 노드 불필요.

### 노트북 단독 트랙 완료 (2026-05-02 ~ 2026-05-03)

호객 BT 시스템이 노트북 단독으로 자연스러운 호객 동작 수준 달성:
- ① GEVA (웹캠 → V·A) → ② EmotionMonitor (BT alarm) → ③ TTS (페르소나 voice) → ④ face_avatar (풀스크린 GIF)
- 후속: utter_done 동기화, face/utter sync, abort reset, hysteresis, log noise filter, 애니메이션 v2, dwell, SafetyCheck 배터리

### RPi 연동 직전 (2026-05-04 실물 테스트)

체크리스트: `docs/rpi_integration_checklist.md`

- [ ] **W2.5**: vic_pinky RPi 5 연동 + ROS_DOMAIN_ID=22 검증 + 실 `/battery_state` SafetyCheck 동작 확인
- [ ] **Approach Nav2 안전**: dummy goal(/customer_pose 미수신 시) Nav2 송신 금지 명시 — 실물 안전 위험 (W2 회고 §3)
- [x] **카메라 2 raw publisher** (2026-05-04): `scripts/run_robot_cam.sh` — RPi v4l2_camera_node spawn → `/robot_cam/image_raw` 발행. 실 카메라는 HCAM01N (Microdia, 아키텍처 SoT의 RPC-20F와 다름). YUYV 640x480 @ 28Hz 검증. MJPG 경로는 v4l2_camera_node 빌드 제약(cv_bridge 빈 encoding)으로 YUYV 우회. 회고 `2026-05-04_robot_cam_raw_publisher.md`. SoT 정정 + MJPG 복구는 후속.

### Phase 3 미니게임 통합 완료 (2026-05-05)

- [x] **PlayWait 3 게임 통합 (2026-05-05)**: 06_rps_evolution / 07_speed_counter / 01_cafe_ninja 를 moca/games 카피 + game.py 4 patch + minigame_runner subprocess wrapper. cafe_funnel_v1.xml `<Minigame game_type="rotate"/>` 로 cycle 마다 순환. 회고 `2026-05-05_three_games_integration.md`. 패턴 메모리 `project_playwait_integration.md` (5단계 표준).
- [x] **face_avatar suspend/resume + X11 raise fix (2026-05-05)**: `_init_size/_init_flags` 명시 저장 (get_flags() OverflowError 회피) + set_mode + toggle_fullscreen × 2 + wmctrl -a 트리거. minigame_runner pygame 카운트다운 윈도우 잔존 시 wmctrl -c 강제 close.
- [x] **5초 카운트다운 + 게임 룰 표시 (2026-05-05)**: minigame_runner 자체 pygame 풀스크린 — 게임 subprocess 띄우기 전 5초 카운트다운 + game-specific 룰 텍스트. ESC 중도 포기 가능. DEFAULT_GAME_PARAMS.explain 섹션.

### 카메라 아키텍처 갱신 (2026-05-05 ~ 2026-05-06)

- [x] **카메라 3 추가 결정 (2026-05-05)**: 노트북 USB 외장 1대 — 게임 손 인식 전용. 카메라 1 (GEVA) + 게임 단일 카메라 점유 충돌 회피 + Salichs 2014 학술 정합 회복 (게임 중 abort_trigger 정상 작동).
- [x] **카메라 2/3 모델 스왑 확정 (2026-05-06)**: 사용자 물리 재배치 — RPi 직결(카메라 2)은 **HCAM01N (Microdia 0c45:6367)**, 노트북 외장(카메라 3)은 **RPC-20F "RF20" (Sunplus SNAP U2 1bcf:2281)**. autofocus continuous + 1080p 인 RPC-20F 를 close-range 손 인식에 배치. RPi 측은 검증된 HCAM01N (`run_robot_cam.sh`) 그대로.
- [x] **카메라 3 코드 patch (2026-05-06)**: game.py 3종 `--camera-index` (default 0) + minigame_runner `game_camera_index` 파라미터 (default 2) + mode_npc.launch.py launch arg 노출 + `/geva/suspend|resume` 폐기 (geva_node + minigame_runner + sim_funnel_demo 주석 일괄 정리). 빌드 + import smoke + argparse 검증 통과. 라이브 검증은 카메라 3 물리 연결 후.
- [ ] **SoT 문서 정정 (2026-05-06)**: `docs/cafe_npc_camera_architecture.md` §3 (카메라 2 = HCAM01N) + §3.5 (카메라 3 = RPC-20F 신설) 일괄 갱신. 회고 작성과 함께.
- [ ] **follow_controller 재튜닝 (2026-05-06+)**: HCAM01N 화각이 RPC-20F 와 다름 → `2026-05-04_follow_tune_smoothing.md` 게인/EMA/align_gate 라이브 재검증 필요.
- [ ] **운영자 모니터링 UI 확장 (2026-05-06)**: `web/static/operator.html` + `teleop_server.py` 확장 — V/A 차트 (Russell circumplex) + 호객 funnel 진행 + 게임 결과 + rapport 타임라인. **신규 페이지 X 기존 자산만 확장** (사용자 결정).
- [ ] **장기 세션 로거**: 추후 검토 (사용자 결정 — 2026-05-05 보류)

### Phase 후속 (실물 테스트 결과 후 우선순위 결정)

- [~] **W4.5 GEFA 부분 (2026-05-04)**: RPi USB 캠 → person bbox (mediapipe efficientdet_lite0) → `vision_msgs/Detection2DArray /robot_cam/persons`. 자세/접근/회피 분류와 `/emotion/state (source="body")` 발행은 **후속** (mediapipe pose 또는 추가 분석 필요).
- [x] **follow 모드 실 구현 (2026-05-04)**: `mode_follow.launch.py` stub → person_detector + follow_controller 2 노드. Detection2DArray → P 제어 cmd_vel. 안전 가드 4종(abort dwell / detection lost / scan front 0.8m / scan_min_range 0.25m). target_height_ratio=0.5 라이브 캘리브 필요. 회고 `2026-05-04_follow_mode.md`.
- [ ] **decision_rule_node**: GEVA + GEFA Salichs 2014 fusion → `/emotion/state` (source="fused")
- [ ] **min_confidence 임계**: rapport_tracker GEVA 신뢰도 게이팅 (카페 조명/거리 변동 대응)
- [x] **SafetyCheck /scan 통합** (2026-05-04): 1.0m 이내 obstacle alarm. vicpinky 섀시 자기반사 0.18~0.21m → `scan_min_range=0.25` XML 기본값으로 마스킹. 회고 `2026-05-04_safety_check_scan.md`. 라이브 테스트에서 미세 튜닝 + 사람/벽 구분(GEFA 의존) 후속.
- [x] **음성/표정 dwell 통합** (2026-05-04): tts_node에 `abort_dwell_sec=2.0` 추가. face_avatar와 대칭. 회고 `2026-05-04_tts_abort_dwell.md`. 페르소나별 세밀화는 후속.
- [x] **face_avatar brightest 시작** (2026-05-04): `start_at_brightest=true` 기본. GIF별 brightest idx 캐시 (hello 16/20, fun 6/20 등) → 표정 전환 즉시 visible. 회고 `2026-05-04_face_avatar_brightest_start.md`.
- [ ] **persona별 dwell/abort_expression**: 글로벌 → 페르소나 YAML 필드
- [ ] **자투리**: YAML 스키마(jsonschema), BT 단위 테스트 골격, 영어 phrase 검증

### 안전 영역 침입 일시정지/재개 (2026-05-08 — 기술 조사 완료, 적용 계획 수립)

전체 기술 조사 + 적용 계획: `docs/cafe_npc_safety_zone.md`. 학술(Trautman 2010 freezing problem, Bdiwi 2022 SSM dynamic switching, Babel 2022 재개 충돌) + 표준(EN/KS B ISO 13482 1차, IEC 60204-1 Cat 2 + Monitored Standstill, ISO 3691-4 이중 영역, ISO/TS 15066 SSM, ISO 13849-1 PL=d) + 현업(MiR 2단 zone, Pudu pause-then-push, Diligent intent signaling, Starship 정면/측면 이분법) + ROS2 도구(nav2_collision_monitor + collision_detector + twist_mux + velocity_smoother) 통합.

핵심 결정: 작업 영역 침입 시 **abort 가 아닌 일시정지(IEC 60204-1 Cat 2 + Monitored Standstill)** + 자동 재개. 3계층 안전 (Hard SafetyCheck / **신규 PauseGate** / Social EmotionMonitor). 기존 1.0m 임계값이 SSM 표준 산식(Vic Pinky 0.3m/s + 100ms 응답)과 일치 — 사후 검증됨.

- [x] **Phase A** (2026-05-09 완료): apt 4 패키지 설치 + twist_mux 통합 + cmd_vel 토픽 rename + e_stop default-false publisher. 회고 `docs/daily/2026-05-09_phase_a_twist_mux_integration.md`. 발견: twist_mux 4.5.0 use_stamped/lock default 변경, zlac_driver deadman 부재 (Phase B 의 velocity_timeout 으로 자동 보강 예정).
- [ ] **Phase B** (D+2~3, 1일): velocity_smoother + collision_monitor (Stop polygon 0.4m + Slowdown polygon 0.7m). twist_mux out → `/cmd_vel_raw` 로 변경하면서 두 노드 끼워넣기.
- [ ] **Phase C** (D+4~5, 2일): SafetyZoneState 메시지 + safety_zone_monitor_node + IsZoneClear BT Condition + cafe_funnel pause gate + onHalted() pause/abort 분기
- [ ] **Phase D** (D+6~8, 2일): 의도 표현 (TTS pause_excuse + resume_after_pause + face_avatar 큐) + persona YAML safety section
- [ ] **Phase E** (D+9~12, 2일): Freezing 회피 (long_pause timer + abort fallback) + operator UI + /safety/state 토픽
- [ ] **Phase F (선택)**: VelocityPolygon 전환, 사람/사물 fusion, 점주 양보 모드, peek-and-pass, eye-gaze ack, 점주 e-stop 물리 버튼, stage-aware SSM, vic_pinky LED 컨트롤러

분산 DDS 함정: cmd_vel 차단 4 노드(twist_mux + smoother + monitor + zlac_driver) **반드시 RPi 단일 호스트** 배치. Wi-Fi 단절 시 fail-safe.

미해결 표준 갭: ROS2 + BT.CPP 자체는 PL=d 인증 미보유 — 카페 환경은 best-effort safety 충분, 산업 인증 필요 시 Phase F + 외부 검증. 공공장소 갭(Salem 2021)은 BT funnel + emotional abort + 점주 override 로 보강 — 회고/논문에 명기.

### M4+ 영구 데이터 / 운영 마감 (2026-05-17 추가)

- [x] **Gazebo wall ↔ PGM map 정합 진단** (2026-05-17 완료): **원 가설 기각**. `walls_high.stl` 가 현 PGM 직후 재생성 + `<pose>-51.320 -6.624 0 ...</pose>` origin 정확 offset → wall ↔ PGM 정합 OK. 진짜 root cause: AMCL likelihood field fundamental 문제 (N-S symmetric 카페 + spawn NE 코너 → mirror basin lock-in). 5 patches 적용 (recovery_alpha=0, do_beamskip=true, init cov 작게, yaml self-init only, PGM 가구 19개 추가) — planner failure 해결 ✓ 그러나 motion 1cm 직후 wrong basin jump 여전. 회고 `docs/daily/2026-05-17_amcl_drift_sim_diagnosis.md`.
- [ ] **Sim AMCL drift 후속 — deeper patches 또는 다른 localization** ⚠ (2026-05-17): 5 patches 후 잔존. 후보: sigma_hit 0.2→0.05, alpha1~5 0.05→0.01, controller xy_goal_tolerance 0.25→0.05, spawn 카페 중앙 이동 (sim 만), cartographer/slam_toolbox, RPi 라이브 (§0-A 해제). SoT 메모리 [[project_amcl_drift_sim_limitation]].
- [ ] **🎯 다음 세션 — RPi 라이브 진행 (2026-05-18 예정)**: sim 우회 → 실 lidar + 실 카페 배치에서 AMCL 안정 검증 + 영상 촬영. 점검 리스트 + 작업 계획 SoT: `docs/cafe_npc_rpi_live_amcl_checklist.md` (12 단계 — 진입 조건 §0-A 해제 확인부터 영상 촬영 + escalation 까지). 라이브 검증 후 cartographer 또는 다른 localization escalation 여부 결정.
- [ ] **opennav_docking 통합** ⚠ (2026-05-17 저녁): 운영 dock 3cm 표준 구현. `ros-jazzy-opennav-docking 1.3.11` apt 설치됨. DockServer + dock_database.yaml (home + T01~T05 dock_pose) + serving_dispatcher 변경 (Nav2 staging + DockRobot action + UndockRobot) + mode_serving.launch 갱신. 2시간 추정. SoT 회고 `docs/daily/2026-05-17_dock_staging_separation_nav2_combo_dds_issue.md` §5.3. 메모리 [[project_dock_vs_staging_separation]].
- [ ] **Nav2 combo 비교 시뮬 재시도** ⚠ (2026-05-17 저녁): DDS sim fragility 로 중단됨. 후보 — NavfnPlanner / SmacPlanner2D / SmacHybrid(REEDS_SHEPP, DUBIN 부적합) × DWB / RPP / MPPI. PC 재부팅 또는 RMW cyclonedds 후 25분. 메모리 [[project_sim_dds_shm_fragility]].
- [ ] **sim DDS SHM 안정화** ⚠ (2026-05-17 저녁): mode_manager 발행 X (RTPS SHM port lock 실패). PC 재부팅 또는 RMW cyclonedds 또는 FastDDS XML profile. 메모리 [[project_sim_dds_shm_fragility]] SoT.
- [ ] **DB schema 팀 협의** ⏸ (2026-05-17 보류): `docs/moca_db_schema.md` v0.1 초안 작성됨 (PostgreSQL 16 on 5090 + 3 DB 분리: orders/telemetry/kpi + 14 테이블 + Alembic). 진행 전 팀원 협의 필요 — 엔진/호스트/보존 정책/PII/D1~D10 미해결 결정. 협의 후 v0.2 + DDL SQL 파일화 (`docs/sql/0001_initial.sql`) → 5090 PG 설치는 별 인프라 트랙.
- [ ] **floorplan 동적 마커 복구**: 어제 tview.png 정적 교체로 robot tracking + 테이블 점유 색상 손실. tview.png 위 SVG/Canvas overlay + 픽셀 좌표 매핑 + store 바인딩 복원.
- [ ] **alarm_dwell teardown 최적화**: pytest 시나리오 `_ensure_idle` 7s safety 누적 — test-only `clear_alarm` endpoint 또는 ack_alarm 확장으로 단축. 풀 suite 60s → ~30s.
- [ ] **cache busting 자동화**: 7 페이지 `?v=YYYYMMDDx` 일괄 bump (Makefile or build hook). 2026-05-16 사고 재발 방지.
- [ ] **NTP 6대 통합 표시**: chrony 5090 master 적용 후 reporter or 5090 web endpoint 로 6대 상태 모음 → settings 페이지. RPi 부분은 §0-A 해제 시점.
- [ ] **라이트 테마 토글**: data-theme="light" 토큰 정의됨, 토글 UI 만 추가.
- [ ] **i18n ko/en**: 텍스트 분리.

### Phase 3+ (먼 미래)

- [ ] **Phase 3**: OMX와 Vic Pinky 통합 — 같은 ROS2 도메인(22)? 아니면 분리?
- [ ] **Phase 4**: 파일럿 데이터 저장 형식 — rosbag2 + 별도 설문 CSV?
- [ ] **TTS 엔진 변경 가능성**: 다른 팀원이 LLM/TTS 조사 중. 변경 시 영향 범위는 `tts_node.py` + persona YAML voice 섹션 + requirements.txt만.

---

## 11. Navigation 모드 코드 분리 원칙 ⭐ (2026-05-14)

**왜**: 2026-05-12 라이브에서 teleop_ui + Nav2 동시 가동 시 **직진 못함** 증상 발생 → main 통째 롤백. Root cause 2개 동시 작용. 새 navigation 코드 작성 시 같은 함정 회피.

### 11.1 teleop_ui.sh 가 이미 점유 (navigation 코드 금지 영역)

| 자산 | 띄우는 주체 | navigation 신규 코드 |
|---|---|---|
| RPi `vicpinky_bringup.launch.xml` (twist_mux, velocity_smoother, collision_monitor, e_stop_pub, zlac_driver) | `run_teleop_ui.sh` step 3 | **재기동 X, 의존만** |
| `/joy/cmd_vel` 발행 (priority **100**) | `teleop_server.py:998` cmd_pub | **같은 토픽 발행 절대 X** |
| dev_common 7 노드 (geva, rapport, persona, dialog, face_avatar, tts, **mode_manager**) | `dev_all.launch.py` step 4d | **재기동 X**, mode_manager 는 클라이언트로만 |
| mode stack spawn | `mode_manager` | **직접 spawn X** — `SetMode` 서비스로만 |
| FastAPI 서버 (port 8765) | `teleop_server.py` (teleop_ui 마지막) | **재기동 X**, endpoint 추가만 |

### 11.2 navigation 신규 코드 책임 영역 (충돌 0)

| 자산 | 책임 주체 | 토픽/인터페이스 |
|---|---|---|
| Nav2 stack (`vicpinky_navigation/bringup_launch.xml`) | `NavRunner` (teleop_server 내부 subprocess) | controller → smoother → `/bt/cmd_vel` (priority 80) |
| RViz `nav2_view` | `NavRunner` 동시 spawn | — |
| `serving_dispatcher` (mode_serving stack) | `mode_manager` 가 SetMode 시 spawn | **NavigateToPose action client만** (cmd_vel publisher 절대 X) |
| `/serving/goto_table`, `/serving/state`, `/serving/reload_tables` | dispatcher | 신규 토픽 |
| `/api/tables/*`, `/api/serving/*`, `/api/launch/nav2/*` | `teleop_server.py` 신규 라우터 | 신규 path |
| `tables.yaml` | `dobi_npc_bringup/config/` | 신규 yaml |

### 11.3 직진 못함 — 검증된 root cause 2 개 (R1, R2)

**R1**: `teleop_server.py:_tick()` idle 영구 발행 (priority 100 → Nav2 priority 80 영구 차단). 가드: idle + alive timeout 만료 + target=0 → publish skip. 위치: `web/teleop_server.py:1113-1136`.

**R2**: `velocity_smoother` 노드 이름 RPi 측 + Nav2 측 중복. Nav2 launch 측 이름을 `nav2_velocity_smoother` 로 rename. 위치: `src/shared/vic_pinky/vicpinky_navigation/launch/navigation_launch.xml` (composable_node name + lifecycle_nodes_nav 리스트).

라이브 검증 (Nav2 가동 직후):
```bash
ros2 topic hz /joy/cmd_vel              # idle 인데 20Hz → R1 재발
ros2 node list | grep velocity_smoother # 1개 → R2 OK, 2개 → R2 재발
ros2 lifecycle nodes                    # nav2_velocity_smoother + velocity_smoother 둘 다 active 여야
```

### 11.4 신규 navigation 코드 작성 시 체크리스트

- [ ] 새 노드가 `/joy/cmd_vel`, `/bt/cmd_vel`, `/follow/cmd_vel`, `/cmd_vel*` 발행하는가? → **금지** (mux 우회 위험)
- [ ] 새 노드가 `vicpinky_bringup` 노드 이름과 겹치나? → rename
- [ ] 새 launch 가 RPi 측 노드 (twist_mux/smoother/monitor/zlac_driver) 재기동 시도하나? → 제거
- [ ] `mode_serving` stack 의 dispatcher 가 cmd_vel publisher 만들었나? → 제거, NavigateToPose action client 로 대체
- [ ] `teleop_server.py` 가 `app = FastAPI()` 재선언했나? → 기존 인스턴스에 라우터 추가만
- [ ] `NavRunner` 와 `SlamRunner` 가 상호 배제 되나? → 동시 가동 시 reject 가드

### 11.5 관련 메모리/문서

- [[project_navigation_code_separation]] (본 §11 동기화)
- [[project_cmd_vel_safety_pipeline]] (RPi cmd_vel chain SoT)
- [[feedback_dont_touch_working_code]] (수정 최소 원칙)
- `docs/cafe_npc_serving_mode.md` (서빙 모드 SoT — 백업본에 있음, 복원 시 동기화)

---

*마지막 갱신: 2026-05-19 (팀원 person_tracking + follow LiDAR 통합 머지 — §RPi scp 규칙 추가, mode_manager 6-state)*
*다음 갱신 예정: 머지 빌드/import 검증 후 라이브 검증*
