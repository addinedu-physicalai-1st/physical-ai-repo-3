# 2026-05-20 — person_tracking ↔ 모객 BT funnel 통합 (Phase 2 W4 후속)

> spec: `docs/superpowers/specs/2026-05-20-person-tracking-bt-integration-design.md`
> plan: `docs/superpowers/plans/2026-05-20-person-tracking-bt-integration-plan.md`
> 브랜치: `feat/person-tracking-bt-integration` (~/moca, main 에서 cut)
> 작성: 2026-05-20 (doby)

---

## 1. 무엇을 했는가

팀원 머지 (`f8fce31`) 로 들어온 `person_tracking_pkg` (YOLOv8 + DBSCAN + BoT-SORT +
MediaPipe Pose) 출력을 모객 BT funnel 의 stage 1 IdleScan / stage 2 Approach 로 흡수.
노트북 단독 환경에서 funnel 한 사이클을 토픽 흐름 수준까지 검증 가능한 구조로 정비.

### 1.1 commit 7 개 (~/moca feat/person-tracking-bt-integration)

| sha | 내용 |
|---|---|
| `8895ac3` | BT IdleScan: Stateful + /person_tracking/tracks 5-frame stable 판정 |
| `52b5057` | BT IdleScan: stale guard 추가 — msg_timeout_sec=0.5s 초과 시 stable_count reset (code review 후속) |
| `061469e` | BT Approach: Nav2 액션 제거 + /approach/enable 게이트 + bh 안정 검사 |
| `151115f` | approach_controller: /approach/enable Bool 게이트 + PD reset on disable |
| `8984fbd` | geva_node: cv2.VideoCapture 폐기 → /webcam/image_raw 토픽 구독 |
| `ae8888a` | dev_common: webcam_master 추가 + use_webcam arg + person_tracking input 분기 |
| `9fbad34` | cafe_funnel_v1.xml: IdleScan stable_frames/msg_timeout_sec + Approach bh_threshold/stable_frames/lost_timeout_sec 포트 명시 |

### 1.2 변경 7 파일 + 신규 테스트 1

- `dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp` (37 → 121 lines) — Stateful + tracks 구독 + 5 frames stable + stale guard
- `dobi_npc_bt/include/dobi_npc_bt/approach.hpp` (287 → 145 lines) — Nav2 액션 제거 + /approach/enable + bh 안정 + lost timeout
- `dobi_npc_bt/src/bt_executor_node.cpp` (+1 line) — IdleScan 등록 시 node 인자 추가
- `dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` (+9 lines) — Stage 1-2 신규 포트
- `person_tracking_pkg/person_tracking_pkg/approach_controller_node.py` (+19 lines) — `/approach/enable` 구독 + 게이트 + PD reset
- `person_tracking_pkg/test/test_approach_controller_gate.py` (신규 85 lines) — pytest 2 케이스 (default=False no_publish + enable=True publish)
- `dobi_npc_emotion/dobi_npc_emotion/geva_node.py` (+24/-23 lines) — cv2.VideoCapture 폐기 → /webcam/image_raw 구독
- `dobi_npc_bringup/launch/dev_common.launch.py` (+32/-3 lines) — webcam_master + use_webcam arg + person_tracking input 분기

---

## 2. 핵심 결정 (사용자 확정)

| # | 결정 | 채택 사유 |
|---|---|---|
| D1 | BT 게이트 + controller 유지 | 공통 자산 보존 + funnel 진행 재활용 |
| D2 | 카메라 1 (노트북 내장) v4l2 마스터 + 토픽 분배 | GEVA 와 동시 점유 충돌 해소 |
| D3 | IdleScan 1+ 5 frames | 단발 frame false-positive 차단 |
| D4 | Approach bh≥0.6 5 frames | 거리 기반 안정 종료 |
| D5 (도출) | min_group_size=1 (이미 적용) | D3 solo 모객 정합 |

---

## 3. 자체-검증 (Task 8 통합 빌드 결과)

- [x] 12 packages 격리 셸 빌드 통과 (3.5s)
- [x] ros2 pkg list 9 dobi/person/vicpinky 패키지 정상 등록
- [x] bt_executor 9 user nodes 등록 + cafe_funnel_v1.xml load + tick loop 시작
- [x] pytest 2 케이스 PASS (test_approach_controller_gate)
- [x] §0-B vic_pinky 트리 + RPi 자산 touch 0 (모든 commit 검증)
- [x] §0-A RPi 접근 명령 사용 X (PC 단독 모드 99 + LOCALHOST_ONLY=1 전제)

---

## 4. Phase A/B 라이브 검증 (보류 — 사용자 입회 필요)

본 trake 의 라이브 검증 절차는 노트북 카메라 앞에 사용자 입회 필요:

**Phase A** — 카메라 + 인식 흐름 (5 분):
```bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true
# /webcam/image_raw 30Hz / /person_tracking/tracks 10Hz+ / /customer_pose 발행 / /emotion/state 발행 검증
```

**Phase B** — BT funnel 1 사이클 (10 분):
```bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging
# IdleScan SUCCESS / /approach/enable=true / /bt/cmd_vel 발행 / Approach SUCCESS / IceBreak 진입 검증
```

합격 기준은 `docs/superpowers/plans/2026-05-20-person-tracking-bt-integration-plan.md`
Task 9-10 의 합격 기준 표 참조. 라이브 검증 결과는 본 회고 §6 으로 후속 추가.

**모터 검증 (RPi 라이브)**: §0-A 해제 + 사용자 명시 후속 트랙. 본 plan 범위 밖.

---

## 5. 발견 / 함정

### 5.1 dev (~/physical-ai-repo-3) 의 dirty state — 작업 위치 갱신

오전 본인이 사용자 결정 "github dev 로 가야돼" 따라 Task 2 결과를 dev 의 doby_controller/ 로 cp 시도 → dev 의 working tree 가 dirty (14 modified + 13 untracked) + 원격 origin/dev 와도 divergent (local 14↑ + origin 37↑) 발견 → cp 위험 인식 + revert → ~/moca 에서 마무리 + 사용자가 dev 정리 후 직접 sync 정책으로 합의.

메모리 [[project_sot_transition_to_physical_ai_repo_3]] + [[user_directly_runs_git_push]] 저장.

### 5.2 code review 발견 — stale message guard

Task 2 code review (Important): person_tracking_node 단절 시 last_tracks_ 가 stale 유지 → stable_count_ 누적 → 잘못된 SUCCESS 위험. 카메라/USB 불안정 환경 재현 가능성.
Fix: `msg_timeout_sec` (default 0.5s) InputPort + `last_msg_time_` + `has_msg_` 멤버. onRunning 진입 시 stale 검사 → reset. 1 commit (52b5057) 추가.

### 5.3 QoS 불일치 — pytest 작성 시 발견

Task 4 implementer 가 plan 의 test 코드 그대로 사용 시 발견:
- approach_controller_node 가 `/bt/cmd_vel` 을 `BEST_EFFORT` QoS 로 발행
- 테스트 구독자가 default `RELIABLE` 로 시도하면 메시지 미전달 (QoS incompatible)
Fix: 테스트 파일에 `QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)` 명시.

plan 의 결함 — 향후 plan 작성 시 QoS 명시 권장.

### 5.4 dev_common.launch.py 의 use_compressed True → False

기존 person_tracking_node 가 `use_compressed=True` 로 `/robot_cam/image_raw/compressed` 구독. RPi 카메라 발행 환경에서는 `image_transport republish` 노드가 같이 떠서 compressed sibling 토픽이 발행됨. 그러나 webcam_master (v4l2_camera_node) 는 raw `/webcam/image_raw` 만 발행, compressed sibling 자동 X. 따라서 `use_compressed=False` 로 변경.

후속: republish 노드 추가 시 압축 토픽 사용 가능. CPU 부담 트레이드오프 검토.

### 5.5 Important 검토 미해결 — Minor 2 건

Task 2 code review minor:
- bbox 음수 면적 방어 (`std::max(0.0f, area)`) — YOLO+BoT-SORT 가 보장하나 방어적 fix 권장. 미적용 (후속).
- RUNNING 중 중간 카운트 로그 — 라이브 디버깅 편의. 미적용 (필요 시 추가).

---

## 6. Phase A/B 라이브 검증 결과 (2026-05-20 18:00 — 통과)

### 6.1 환경 설치

`ros-jazzy-v4l2-camera 0.7.1` 노트북 미설치 발견 → 사용자 직접 `sudo apt install -y ros-jazzy-v4l2-camera`. 그 외 의존성 (cv_bridge, image_tools, usb_cam) 모두 가용.

### 6.2 Phase A — 카메라 + 인식 흐름 (5 분, 합격 5/5)

```bash
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true
# ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 (PC 단독 격리, §0-A 정합)
```

| # | 항목 | 측정 결과 |
|---|---|---|
| A1 | `/webcam/image_raw` | **29.0 Hz** (target 30Hz, ±1Hz 정상) |
| A2 | `/person_tracking/tracks` | **10.0 Hz** (YOLO 추론 부하) |
| A3 | `/customer_pose` | 발행 ✓ (x≈0.51 y≈0.49 z=bh=1.01, 매우 가까운 거리에서 측정) |
| A4 | `/person_tracking/approach_target` | data=0 발행 ✓ (solo 손님 group_id=0, min_group_size=1 정합) |
| A5 | `/emotion/state` | 10 Hz + rapport_tracker_node 가 V=-0.33 A=0.16 conf=0.30 같이 평가 ✓ (geva 토픽 구독 전환 검증) |

### 6.3 Phase B — BT funnel 1+ 사이클 통합 (10 분, 합격 7/7)

```bash
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode '{requested_mode: engaging}'
# response: success=True current_mode='engaging' reason='transition_started'
# bt_executor + minigame_runner spawn 확인
```

30s 사용자 거리 시퀀스 (1.5-2m → 가까이) 동안 발행 시퀀스:

```
/approach/enable:  True  →  False              (IdleScan SUCCESS → Approach SUCCESS)
/dialog/request:   icebreak                    (Stage 3 진입)
                   minigame_invite_speed_counter  (Stage 4 — rotate cycle)
                   icebreak                    (2nd cycle 자동 재진입!)
                   minigame_invite_cafe_ninja     (rotate: speed_counter → cafe_ninja)
```

| # | 항목 | 결과 |
|---|---|---|
| B1 | IdleScan 5 frames stable 후 SUCCESS | ✓ (`/approach/enable=True` 토글) |
| B2 | Approach onStart → /approach/enable=True | ✓ |
| B3 | enable=true 동안 /bt/cmd_vel 발행 | ✓ (controller 게이트 작동) |
| B4 | bh≥0.6 5 frames → Approach SUCCESS | ✓ (`/approach/enable=False` 전이) |
| B5 | enable=false 후 cmd_vel 정지 | ✓ (controller gate skip) |
| B6 | IceBreak (/dialog/request: icebreak) | ✓ |
| B7 | Minigame rotate cycle | ✓ (speed_counter → cafe_ninja) |

**핵심 성취**: 모객 funnel IdleScan → Approach → IceBreak → Minigame 1 cycle + **자동 재진입 (2nd cycle)** 성공. ReactiveFallback + Sequence 정합 + rotate game_type 의 cycle 순환 검증.

### 6.4 발견 사항

- `/customer_pose.z (bh)` 가 매우 가까이 (얼굴 클로즈업) 시 **1.0+ 까지 측정**됨 — 정규화 0~1 가정 초과. YOLO 가 frame 밖으로 일부 나간 사람의 bbox 도 그대로 좌표 출력 → bh = bbox_height/image_height 가 1.0 초과 가능. BT bh_threshold=0.6 검증엔 영향 X (이상 큰 값일수록 SUCCESS 빨라짐). 후속에서 실 거리 캘리브 시 참고.
- 검증 시 사용자 첫 위치가 너무 가까웠어 IdleScan → Approach SUCCESS 가 1-2초 안에 완료됨. 의도된 동작 — funnel 후속 stage (IceBreak/Minigame) 정상 진입으로 검증 완료.
- minigame_runner 가 rotate cycle 의 두 게임 (`speed_counter`, `cafe_ninja`) 을 차례로 invite. rps 가 첫 cycle 에 없음 → rotate index 가 1 또는 2 부터 시작했거나 cycle 순서 변경 가능성. 본 trake 영향 X (Phase 3 미니게임 자체 검증 별 트랙).
- ROS_LOCALHOST_ONLY=1 deprecation 경고 발생. ROS_AUTOMATIC_DISCOVERY_RANGE + ROS_STATIC_PEERS 로 교체 권장 (별 트랙).

### 6.5 §0-A / §0-B 준수

- ROS_DOMAIN_ID=99 + LOCALHOST_ONLY=1 격리. RPi vic_pinky cmd_vel 미도달 → 모터 미가동.
- 사용자가 검증 중 "e-stop 해제" 알림 — RPi 실 모터 가동 준비 상태이나 본 검증은 노트북 토픽까지만. 실 모터 검증은 §0-A 해제 + DOMAIN=22 전환 별 트랙.

---

## 7. 미해결 / 후속 트랙

1. **dev sync** (사용자 직접): ~/moca 의 commit 7 개 + spec + plan + 본 회고 를 dev 의 `src/controller/doby_controller/` 로 일괄 sync. dev 의 dirty state 정리 + origin/dev 와의 divergent 해결은 사용자 영역.
2. **bh ↔ 실거리 캘리브**: bbox 높이 비율은 사람 키 + 자세에 의존. 노트북 카메라 1 (내장) 화각 ≠ 운영 카메라 2 (abko RPi). RPi 라이브 시 재튜닝.
3. **controller close_threshold (0.999) vs BT bh_threshold (0.6)**: 책임 경계 재검토.
4. **YOLO 부하 idle 영구 발생**: dev_common always-on 정책 → engaging 진입 시 spawn 분리 별 트랙.
5. **stage 4 Minigame 카메라 (3, 외장) ↔ stage 1-2 카메라 1 ON/OFF 동기**: 별 트랙.
6. **multi-customer handoff**: 본 trake 는 top track_id 한 명 고정. 다중 손님 핸드오프 정책 후속.
7. **stable_frames / bh_threshold 의 페르소나별 차등화**: persona YAML 필드 후속.
8. **BT XML 의 IdleScan stable_frames default vs XML override 검증**: code review minor — XML 의 attr 명시는 본 commit 에서 적용됨 ✓.
9. **bbox 음수 면적 방어**: code review minor — 미적용 후속.

---

## 8. §0-B vic_pinky + §0-A RPi 영향

**0** — 본 trake 의 모든 commit 검증 결과:
- `src/shared/vic_pinky/` touch 0
- `scripts/run_vic_bringup.sh`, `run_robot_cam.sh`, `run_teleop_ui.sh`, `run_nav2.sh`, `run_3stage.sh` touch 0
- RPi SSH / sshpass / scp / ROS_DOMAIN_ID=22 등 명령 사용 0
- `/bt/cmd_vel` 발행 측 게이트만 추가, twist_mux / zlac_driver / collision_monitor 변경 0

---

## 9. 학술 정합

본 통합은 학술 청사진을 변경하지 않음:

- Layer 1 (Isla 2005): BT funnel 6-stage 그대로
- Layer 2 (Russell 1980): EmotionMonitor abort 로직 그대로
- Layer 3 (Salichs 2014): GEVA 가 카메라 1 점유에서 토픽 구독으로 바뀐 것 외 동일
- Layer 4 (Castro-González 2016): Minigame stage 그대로
- Layer 5 (Marzinotto 2014): ReactiveFallback + Sequence 형식화 그대로

---

## 10. 관련 메모리 / 문서

- `CLAUDE.md` §0-B (vic_pinky 트리 절대 수정 금지)
- `CLAUDE.md` §11 (Navigation 코드 분리 원칙)
- 메모리: [[project_sot_transition_to_physical_ai_repo_3]] (SoT 전환 의도 + dev 정리 후 일괄 sync)
- 메모리: [[user_directly_runs_git_push]] (push 사용자 직접 정책)
- 메모리: [[feedback_auto_mode_minimize_questions]] (묻기 자제 + reasonable default)
- spec / plan: `docs/superpowers/{specs,plans}/2026-05-20-*`
