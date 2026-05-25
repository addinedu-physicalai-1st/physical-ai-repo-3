# Phase 0-B 회고 — dobi_npc 패키지 골격 + git 초기화

**작성일**: 2026-05-01 (Phase 0-A 회고와 같은 날, 분리 작성)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `cafe_npc_implementation_plan.md` Phase 0
**선행 문서**: `2026-05-01_phase0a_migration.md`
**상태**: ✅ Phase 0-B 완료 → Phase 1 진입 가능

---

## 0. 오늘의 목표 vs 실제 결과

| 계획 | 결과 |
|---|---|
| 메타파일 작성 (.gitignore, README.md, moca.repos) | ✅ |
| dobi_npc 6개 패키지 골격 생성 | ✅ (5개 + bringup launch placeholder) |
| 더미 노드로 빌드 검증 | ✅ 8 packages / 2.87s |
| CLAUDE.md 작성 | ✅ 398 lines |
| moca git 초기화 + 첫 커밋 | ✅ commit 8750eab |

---

## 1. 생성된 패키지 (6개)

```
~/moca/src/dobi_npc/
├── dobi_npc_msgs/          [ament_cmake] — 4 interfaces
│   ├── msg/EmotionState.msg      (Russell V,A + Salichs confidence)
│   ├── msg/RapportEvent.msg      (BT EmotionMonitor input, EmotionState 중첩)
│   ├── msg/MinigameResult.msg    (RPS Castro-González pattern)
│   └── srv/SetPersona.srv        (Isla character hierarchy)
│
├── dobi_npc_bt/            [ament_cmake] — C++ + BehaviorTree.CPP v4
│   ├── include/dobi_npc_bt/dummy_action.hpp
│   ├── src/bt_executor_node.cpp
│   └── (bt_xml/, launch/, config/) ← 빈 디렉토리, Phase 1에서 채움
│
├── dobi_npc_emotion/       [ament_python] — Phase 2 자리
│   └── dummy_emotion_node.py  ← 견고한 main() 패턴 reference
│
├── dobi_npc_dialog/        [ament_python] — Phase 1 W3 자리
│   └── dummy_dialog_node.py
│
├── dobi_npc_minigame/      [ament_python] — Phase 3 자리
│   └── dummy_minigame_node.py
│
└── dobi_npc_bringup/       [ament_python] — Phase 4 자리
    ├── launch/.gitkeep
    └── config/.gitkeep
```

---

## 2. 핵심 의사결정 4가지

### 결정 1: dobi_npc_msgs를 가장 먼저 생성
- **이유**: 다른 5개 패키지가 모두 의존, 빌드 순서상 첫 번째
- **결과**: 의존 패키지들이 `EmotionState`, `RapportEvent` 등을 자연스럽게 import 가능

### 결정 2: 메시지 4개만 정의 (PersonaCommand는 보류)
- **이유**: Phase 1 W3에서 페르소나 구조 확정 후 추가하는 게 안전
- **현재 메시지**: EmotionState, RapportEvent, MinigameResult, SetPersona

### 결정 3: 더미 노드의 견고한 main() 패턴 확립
- **계기**: 첫 dummy_emotion_node.py가 SIGTERM에 traceback + RCLError로 종료
- **개선**: `ExternalShutdownException` 잡고 `if rclpy.ok()` 가드 추가
- **효과**: 종료 코드 0 (깨끗한 종료)
- **자산화**: Phase 1+ 모든 ROS2 Python 노드의 표준 main() 템플릿이 됨

### 결정 4: vic_pinky를 .gitignore + moca.repos로 외부 관리
- **이유**:
  - PinkLAB 공식 저장소를 moca git이 침범하지 않음
  - 다른 PC/로봇으로 복제 시 `vcs import src < moca.repos` 한 줄로 복원
  - 다른 팀원도 자기 모듈을 src/<group>/에 넣으면 됨
- **대안 기각**: git submodule(복잡), embedded repo(경고+불완전)

---

## 3. 빌드 검증 결과

### 8개 패키지 모두 빌드 성공

```
Summary: 8 packages finished [2.87s]
```

| 패키지 | 빌드 시간 | 비고 |
|---|---|---|
| vicpinky_description | 0.14s | (Phase 0-A에서 빌드) |
| vicpinky_navigation | 0.14s | (Phase 0-A에서 빌드) |
| dobi_npc_msgs | 0.54s | rosidl 메시지 생성 |
| dobi_npc_bt | 0.80s | C++ + BT.CPP v4 컴파일 |
| dobi_npc_bringup | 2.10s | ament_python |
| dobi_npc_dialog | 2.09s | ament_python |
| dobi_npc_emotion | 2.08s | ament_python |
| dobi_npc_minigame | 2.06s | ament_python |

### stderr 경고

```
UserWarning: Unbuilt egg for pytest-repeat [unknown version]
```

→ 4개 ament_python 패키지에서 공통 발생, 시스템 메타데이터 이슈, **무해**.

### 더미 노드 실행 검증

```
ros2 run dobi_npc_emotion dummy_emotion_node    → 종료 코드 0 ✅
ros2 run dobi_npc_dialog dummy_dialog_node      → 종료 코드 0 ✅
ros2 run dobi_npc_minigame dummy_minigame_node  → 종료 코드 0 ✅
```

---

## 4. 문제와 해결

### 문제 1: 첫 더미 노드의 종료 처리 결함
- **증상**: `timeout 3 ros2 run ...` 시 `ExternalShutdownException` + `RCLError: rcl_shutdown already called` 발생
- **원인**: `except KeyboardInterrupt:` 만 잡아서 SIGTERM은 미처리
- **해결**: 4개 더미 노드를 견고한 패턴으로 일괄 재작성
- **자산화**: 이 패턴이 Phase 1+ 표준이 됨, CLAUDE.md 섹션 5에 명시

### 문제 2: docs/에 핵심 .md 파일이 없음
- **증상**: git 추적 검증 시 `[C] docs 추적 대상 (상세)`이 비어있음
- **원인**: master.md만 있고 plan.md, phase0a_migration.md는 ~/Downloads/0501/에 있었음
- **해결**: `cp`로 docs/에 배치 후 git 재검증 → 64 파일 추적

### 문제 3: rapport_event.msg가 짧아 보임 (10줄)
- **확인**: 빈 줄 미포함이라 그렇게 보였을 뿐, 실제 5개 필드 모두 정상
- **결과**: 중첩 메시지(`EmotionState emotion`)도 ros2 interface show에서 정확히 풀림

---

## 5. CLAUDE.md 작성

**위치**: `~/moca/CLAUDE.md` (398 lines, 15KB)

**10개 섹션:**
1. 한 줄 정의
2. 6-Layer 학술 토대
3. 워크스페이스 구조
4. **검증된 ROS2 인터페이스 명세** ⭐ (Phase 0-A 발굴 결과)
5. **표준 코드 패턴** ⭐ (Python main(), C++ BT 노드)
6. Phase 진행 상황
7. 작업 규칙 (Stephen 워크플로우)
8. 외부 자산 위치
9. 자주 쓰는 명령어
10. Open Questions / TODO

**의도**: Phase 1+ 매번 참조할 단일 진실원. 새 팀원 합류 시 이 문서부터 읽으면 됨.

---

## 6. git 저장소 상태

```
[main (root-commit) 8750eab] Phase 0 complete
 64 files changed, 3546 insertions(+)
```

### 추적 파일 카테고리

| 카테고리 | 파일 수 |
|---|---|
| src/dobi_npc/ | 51 |
| scripts/ | 6 |
| docs/ | 3 (master + plan + 회고) |
| 최상위 | 4 (.gitignore, CLAUDE.md, README.md, moca.repos) |
| **합계** | **64** |

### 의도적으로 제외된 것

- `src/shared/vic_pinky/` (외부 저장소, moca.repos로 복원)
- `build/`, `install/`, `log/` (빌드 산출물)
- `maps/`, `datasets/`, `web/`, `models/` (cabot 무거운 자산)
- `docs/cabot_legacy/`, `docs/cabot_README.md` (참고용)
- `*.pt`, `*.pth`, `*.onnx` 등 (모델 가중치)

### 두 git 이력의 분리

```
~/moca/.git                           ← moca 본체 (1 commit)
└── main: 8750eab "Phase 0 complete"

~/moca/src/shared/vic_pinky/.git      ← PinkLAB (.gitignore로 추적 X)
├── main: 51da1b1 (PinkLAB 원본)
└── feature/dobi-npc-base: 193bb22   ← 본 프로젝트 변경사항
```

---

## 7. 발견된 인터페이스 자산 (Phase 0-A에서 시작, Phase 0-B에서 정리)

CLAUDE.md 섹션 4에 명시. Phase 1+에서 직접 활용:

### 입력 (BT 구독)
- `/battery_state` (sensor_msgs/BatteryState) — **SafetyCheck 1순위**
- `/odom`, `/joint_states`, `/scan` — 표준

### 출력 (BT 발행/호출)
- `/cmd_vel`, `NavigateToPose` 액션 — 이동
- `/set_emotion` (pinky_interfaces/srv/Emotion) — **표정 출력**
- 표정 어휘: `basic, hello, happy, fun, interest, bored, sad, angry`

---

## 8. 시간 분석

| 단계 | 예상 | 실제 |
|---|---|---|
| Phase 0-A 마이그레이션 | 30분 | ~2시간 (변경사항 분석 깊이 들어감) |
| Phase 0-B 패키지 골격 | 30분 | ~1시간 (더미 견고화 추가) |
| **Phase 0 합계** | 1시간 | ~3시간 |

**시간 초과 원인 (긍정적)**:
- BatteryState 발굴 → CLAUDE.md 섹션 4의 핵심 자산
- pinky_emotion 8 어휘 발견 → BT 출력 채널 사전 정의
- 더미 노드 견고화 → Phase 1+ 모든 노드의 표준 패턴

→ Phase 1 코딩 속도가 그만큼 빨라질 자산이 됨.

---

## 9. Phase 1 진입 준비 상태 체크리스트

Phase 1 Week 1 시작 시 즉시 활용 가능한 자산:

- [x] ROS2 워크스페이스 (`moca_build`, `moca_activate` alias)
- [x] BT.CPP v4 시스템 설치 (`ros-jazzy-behaviortree-cpp 4.8.3`)
- [x] 빌드 가능한 6개 dobi_npc 패키지 골격
- [x] 4개 커스텀 메시지 (EmotionState, RapportEvent, MinigameResult, SetPersona)
- [x] 견고한 Python main() reference (`dummy_emotion_node.py`)
- [x] C++ BT 노드 reference (`dummy_action.hpp`, `bt_executor_node.cpp`)
- [x] CLAUDE.md (인터페이스 명세 + 코드 패턴 + 워크플로우)
- [x] `/battery_state`, `/set_emotion` 인터페이스 명세
- [x] vic_pinky 빌드 검증 완료 (`vicpinky_navigation`, `vicpinky_description`)

→ **Phase 1 Week 1 첫 작업: `dummy_action.hpp`를 6개 BT 액션 노드로 분기**
   (SafetyCheck, IdleScan, Approach, IceBreak, Minigame, Offer, LeadIn + BatteryCheck 추가)

---

## 10. Open Questions (CLAUDE.md 섹션 10에서 발췌, 다음 Phase에서 결정)

- [ ] BatteryCheck를 SafetyCheck에 통합 vs 별도 BT 노드?
- [ ] 페르소나 YAML에 `face_expression` 필드 어떻게 (stage별 매핑)?
- [ ] EyeCon 포팅의 라이브러리 의존성 (시스템 pip vs venv)?
- [ ] OMX와 Vic Pinky 같은 ROS_DOMAIN_ID(22)?
- [ ] 파일럿 데이터 형식 (rosbag2 + 설문 CSV)?

---

## 11. 회고 한 줄

> Phase 0-B는 "패키지 6개 만들기"로 끝날 줄 알았는데, 더미 노드 종료 처리 결함 발견 → 견고한 main() 패턴 확립 → Phase 1+ 모든 노드의 표준이 됨. 작은 디테일 하나가 16주 작업의 코드 품질을 결정한다는 것을 다시 확인. 또한 CLAUDE.md를 단순한 README가 아니라 "인터페이스 명세 + 코드 패턴 + 워크플로우"의 단일 진실원으로 만든 것이 가장 큰 수확.

---

## 12. 다음 일정

- **Phase 1 Week 1 (다음 세션)**: BT 노드 6~8개 골격 작성
  - SafetyCheck, BatteryCheck (Marzinotto priority safety)
  - IdleScan, Approach, IceBreak, Minigame, Offer, LeadIn
  - cafe_funnel_v1.xml 작성
  - Groot2로 시각화 검증

- **Phase 1 Week 2**: Approach를 Nav2 NavigateToPose Action Client로
- **Phase 1 Week 3**: 페르소나 YAML 3종 + Phrase Pool

---

*저장 위치: `~/moca/docs/daily/2026-05-01_phase0b_skeleton.md`*
*git 추적됨: 다음 commit에 포함 (현재 untracked)*
