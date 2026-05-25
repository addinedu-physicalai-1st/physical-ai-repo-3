# Phase 0-A 회고 — cabot → moca 마이그레이션 + 검증 빌드

**작성일**: 2026-05-01
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `cafe_npc_implementation_plan.md` Phase 0
**상태**: ✅ Phase 0-A 완료

---

## 0. 오늘의 목표 vs 실제 결과

| 계획 | 결과 |
|---|---|
| `~/moca` 워크스페이스 생성 | ✅ 완료 |
| cabot에서 vic_pinky 마이그레이션 | ✅ 완료 (전체 복사) |
| 다른 팀 모듈과 통합 가능한 구조로 분리 | ✅ `src/shared/`, `src/dobi_npc/` 분리 |
| 검증 빌드 성공 | ✅ vicpinky_description, vicpinky_navigation 빌드 OK |

---

## 1. 최종 디렉토리 구조

```
~/moca/
├── .gitignore
├── README.md                  (Phase 0-B에서 채울 예정)
├── moca.repos                 (Phase 0-B에서 채울 예정)
│
├── src/
│   ├── shared/                ← 모든 팀원 공유 자산
│   │   └── vic_pinky/         (PinkLAB 공식 + 로컬 변경 보존)
│   │       ├── vicpinky_description    [✅ 빌드 대상]
│   │       ├── vicpinky_navigation     [✅ 빌드 대상]
│   │       ├── vicpinky_bringup        [❌ COLCON_IGNORE - 로봇 전용]
│   │       ├── vicpinky_gazebo         [❌ COLCON_IGNORE - 시뮬 환경]
│   │       └── vicpinky_emotion        [❌ COLCON_IGNORE - RPi.GPIO 의존]
│   │
│   └── dobi_npc/              ← 본 작업 (호객 BT) — Phase 0-B에서 채움
│       (현재 빈 디렉토리)
│
├── docs/
│   ├── daily/
│   ├── cabot_legacy/          (cabot의 docs 보존)
│   └── cabot_README.md        (참고용)
│
├── config/personas/           (Phase 1 Week 3에서 채움)
├── scripts/                   (운영 스크립트 자리)
├── datasets/, maps/, tools/, web/, models/yolo/  (cabot에서 가져옴)
│
└── build/, install/, log/     ← colcon 빌드 산출물
```

---

## 2. 핵심 의사결정 5가지

### 결정 1: 마이그레이션 범위 → 전체 복사
- **이유**: 의존성 누락 위험 회피, 디스크 비용 작음 (~70MB)
- **대안 기각**: 선별 복사는 빌드 실패 시 추적 비용 큼

### 결정 2: 디렉토리 구조 → `src/shared/` + `src/dobi_npc/` 분리
- **이유**: 다른 팀원이 다른 모듈을 합칠 예정, 통합 표준 사전 확립
- **다른 팀원 모듈 자리**: `src/<group_name>/` 추가하면 됨
- **대안 기각**:
  - 옵션 B (모듈별 독립 워크스페이스): overlay 체인 복잡
  - 평면 구조: 누구 작업물인지 모호

### 결정 3: 변경사항 보존 → 별도 git 브랜치
- **현재 git 상태**:
  - `main`: PinkLAB 원본 (51da1b1, 손상 없음)
  - `feature/dobi-npc-base`: 로컬 변경사항 스냅샷 (193bb22)
- **복구 가능**: `git reset --hard 51da1b1` 또는 `git checkout main`

### 결정 4: 개발 PC에서 3개 패키지 빌드 제외
- **`vicpinky_bringup` (이미 IGNORE)**: ZLAC 모터 드라이버 — 로봇만
- **`vicpinky_gazebo` (이미 IGNORE)**: Gazebo 시뮬 — 별도 환경
- **`vicpinky_emotion` (오늘 추가 IGNORE)**: RPi.GPIO 의존 — 노트북 빌드 불가
- **로봇(라즈베리파이 5)에서**: 위 IGNORE 파일 삭제하면 5개 모두 빌드 가능

### 결정 5: Python 의존성 → ROS2 표준 (venv 없음)
- **이유**: ROS2와 venv는 ABI 충돌 가능, colcon 자체가 격리 메커니즘
- **혼합 시나리오 (Phase 2)**: 그때 가서 재결정

---

## 3. 주요 발견 사항

### 발견 1: `bringup.py`에 BatteryState 발행 추가 (+46/-4 줄)
- **토픽**: `/battery_state` (sensor_msgs/BatteryState), 1Hz
- **소스**: ZLAC 모터 드라이버의 bus voltage (Modbus 0x20A1)
- **파라미터**: 7S Li-ion 가정 (21.0V 컷오프 ~ 29.4V 만충)
- **호객 BT 영향**: ⭐ **SafetyCheck 노드의 1순위 입력**
  - 배터리 < 20% → abort (충전소 복귀)
  - "잠시 충전하고 올게요" phrase 추가 필요

### 발견 2: `vicpinky_emotion` 패키지의 정체
- **표시 매체**: 240×320 SPI LCD (RPi GPIO 직결, 노트북 화면 아님)
- **어휘**: 8개 GIF (basic, hello, happy, fun, interest, bored, sad, angry)
- **인터페이스**: `/set_emotion` 서비스 (`pinky_interfaces/srv/Emotion`)
- **호객 BT 영향**: ⭐ **BT의 표정 출력 채널**
  - 페르소나 YAML에 `face_expression` 필드 추가 필요
  - 8개 어휘를 Russell V-A 좌표와 매핑 가능

### 발견 3: Nav2 BT가 시스템에 이미 설치됨
- `nav2_behavior_tree`, `nav2_bt_navigator` 등이 Jazzy apt 패키지에 포함
- **호객 BT 영향**: BehaviorTree.CPP 별도 설치 불필요할 가능성 — Phase 1 Week 1에서 확인

### 발견 4: `pinky_interfaces` 의존성은 vic_pinky 외부
- 본 프로젝트 노트북에서는 빌드 대상이 아니므로 무시 가능
- 로봇에 가서 빌드할 때만 필요 (이미 로봇에 설치되어 있음)

---

## 4. 문제와 해결

### 문제 1: `~/moca`가 이미 존재함
- **상황**: 빈 디렉토리이지만 미리 만들어져 있었음
- **해결**: 안전 검증 후 `mkdir -p`로 그대로 사용

### 문제 2: `--noprofile --norc`인데도 robot_arm 환경 잔존
- **원인**: `bash -c`는 부모 셸의 환경 변수 상속
- **영향**: 빌드에는 문제없음 (의존성 무관)
- **차후 대응**: 완전 격리 필요 시 `env -i` 사용

### 문제 3: 빌드 산출물(build/install/log)이 13:54에 이미 존재
- **원인**: 다른 터미널에서 미리 빌드해두심
- **결정**: incremental 빌드로 진행 (이미 결과가 정상이므로)

---

## 5. 검증된 인터페이스 명세 (Phase 1에서 활용)

호객 BT가 사용할 ROS2 인터페이스들이 모두 식별되었습니다:

### 입력 토픽 (BT가 구독)
| 토픽 | 타입 | 용도 |
|---|---|---|
| `/odom` | nav_msgs/Odometry | 로봇 위치 |
| `/joint_states` | sensor_msgs/JointState | 관절 상태 |
| `/battery_state` | sensor_msgs/BatteryState | ⭐ SafetyCheck용 |

### 출력 토픽/서비스 (BT가 발행/호출)
| 인터페이스 | 타입 | 용도 |
|---|---|---|
| `/cmd_vel` | geometry_msgs/Twist | 직접 제어 (사용 자제) |
| Nav2 액션 | nav2_msgs/action/NavigateToPose | Approach 노드 |
| `/set_emotion` | pinky_interfaces/srv/Emotion | ⭐ 표정 출력 (8 어휘) |

### 표정 어휘 (8개)
```
basic, hello, happy, fun, interest, bored, sad, angry
```

---

## 6. .bashrc에 추가된 alias (예정)

```bash
alias moca_activate='source ~/moca/install/setup.bash 2>/dev/null && echo "[moca workspace 활성화]"'
alias moca_clean='cd ~/moca && rm -rf build install log && echo "[moca: build/install/log 삭제]"'
alias moca_build='bash --noprofile --norc -c "source /opt/ros/jazzy/setup.bash && cd ~/moca && colcon build --symlink-install"'
```

---

## 7. 계획서(`cafe_npc_implementation_plan.md`) 갱신 필요 사항

다음 사항을 v1.1 갱신 시 반영:

1. **워크스페이스 위치**: `~/dev_ws/dobi_npc_ws` → `~/moca/src/dobi_npc/`
2. **vicpinky_emotion 활용**: Phase 1 Week 3에 "표정 출력 통합" 추가
3. **BatteryCheck 노드**: Phase 1 Week 1에 추가 (Marzinotto priority safety의 일등 후보)
4. **페르소나 YAML 스키마**: `face_expression` 필드 추가, 8 어휘 제약
5. **다른 팀원 통합 고려**: 디렉토리 구조 명시 (`src/shared/`, `src/dobi_npc/`, `src/<other>/`)

---

## 8. Phase 0-B (다음 작업)

### 목표
`~/moca/src/dobi_npc/` 안에 호객 BT 시스템의 6개 ROS2 패키지 골격 생성 + CLAUDE.md 작성

### 생성할 패키지
```
~/moca/src/dobi_npc/
├── dobi_npc_msgs/         (커스텀 메시지 정의)
├── dobi_npc_bt/           (BT 노드 - C++)
├── dobi_npc_emotion/      (감정 인식 - Python)
├── dobi_npc_dialog/       (대화/페르소나 - Python)
├── dobi_npc_minigame/     (RPS - Python)
└── dobi_npc_bringup/      (통합 launch)
```

### 추가 산출물
- `~/moca/CLAUDE.md` (프로젝트 컨텍스트 + 6-Layer 매핑)
- `~/moca/README.md` (빌드 가이드)
- `~/moca/moca.repos` (vcs import용)
- `~/moca/.gitignore` (빌드 산출물 제외)

---

## 9. 다음 일정

- **Phase 0-B**: 다음 세션에서 즉시 진행
- **Phase 1 Week 1**: BT 노드 6~7개 골격 작성 (예상 시작: 다음 주 월요일)

---

## 10. 회고 한 줄

> 단순한 디렉토리 복사일 줄 알았는데, 진행하면서 발견한 BatteryState 토픽 추가, vicpinky_emotion LCD 어휘 8개, Nav2 BT 사전 설치 등 — Phase 1 코딩 속도를 좌우하는 인터페이스 명세가 자연스럽게 모였다. Phase 0-A는 "환경 준비"가 아니라 "시스템 인터페이스 발굴" 단계였다.

---

*저장 위치 권장: `~/moca/docs/daily/2026-05-01_phase0a_migration.md`*
