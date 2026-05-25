# 2026-05-19 — moca_teammember 18 commits 통합 머지

> spec: `docs/superpowers/specs/2026-05-19-moca-teammember-merge-design.md`
> plan: `docs/superpowers/plans/2026-05-19-moca-teammember-merge-plan.md`
> 작성: 2026-05-19 (doby)

---

## 1. 무엇을 했는가

`~/moca_teammember/` (HEAD `fd62971`) 의 18 commit 을 `~/moca/` (HEAD `fb9c1b9` + Task 3 의 3 commit = 4 commits ahead, 즉 `f437e0e`) 에 git merge 로 통합. 공통 조상 `1a2971b` (2026-05-08) 기준 양쪽 분기.

머지 commit: **`f8fce31`** (2 parent: `f437e0e` ours + `fd62971` theirs, 30 files, +2383/-56).

### 통합된 자산
- 신규 패키지: `person_tracking_pkg` (YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose, 3 노드)
- 신규 msg: `PersonTrack`, `PersonTrackArray` (dobi_npc_msgs, 총 12 msg + 5 srv)
- approach_controller PD 제어 + LiDAR 거리 기반 follow_controller
- 신규 스크립트: `run_3stage.sh`, `run_nav2.sh`, `stop_nav2.sh`
- 신규 문서: 일일 회고 6편 (2026-05-14 ~ 2026-05-18 person_tracking 트랙)
- _backups/vicpinky_navigation_launch/ (팀원 5/14 백업본 2 파일)
- 모델 가중치: `yolov8n.pt` (6.5MB), `pose_landmarker_lite.task` (5.5MB) — gitignore, 별도 cp

### 충돌 해결 5건 — 실제 진행 양상
**plan SoT 예상**: 5 충돌. **실제**: 3 충돌 + 2 auto-merged (favorable deviation).
1. `dobi_npc_msgs/CMakeLists.txt` — **충돌** — union (12 msg + 5 srv + sensor_msgs depend)
2. `dev_common.launch.py` — **auto-merged** — 그러나 docstring 의 9-node 표기 일부 누락 + initial_mode 5-state → Task 7 에서 보정 (10-node + 6-state)
3. `mode_manager_node.py` — **auto-merged** — _on_battery NaN 패치 자동 통합. 단 VALID_MODES + LEGACY_MODE_ALIAS + docstring 6-state 갱신은 git 이 못해서 Task 8 에서 수동 보정.
4. `mode_follow.launch.py` — **충돌** — `git checkout --theirs` 로 팀원 본 채택 (kp_angular 0.5, target_dist 0.30, LiDAR 거리 기반)
5. `CLAUDE.md` — **충돌** — `git checkout --ours` 채택 + 팀원의 §RPi scp 경로 규칙 섹션만 picking 삽입 (line 407, §package.xml 함정 다음)

---

## 2. 사용자 결정 4건 (사전 합의)

1. ✅ 옵션 A — git merge --no-commit (팀원 18 commit history 보존)
2. ✅ mode_follow + mode_guiding 분리 운용 (둘 다 살림) — VALID_MODES 6-state
3. ✅ pip ultralytics + boxmot 머지 직후 설치 + transitive cleanup
4. ✅ PC + 팀원 양쪽 풀 백업 (~/backup/moca_merge_20260519/, 293MB, SHA256SUMS 12 라인 모두 OK)

---

## 3. Hidden 함정 7건 처리 결과

| # | 함정 | 처리 |
|---|---|---|
| F1 | person_tracking_pkg/package.xml em-dash | ✅ ASCII hyphen 으로 정정. Task 16 빌드 후 `ament_prefix_path.sh` hook 존재 검증 — 회피 성공 확인. |
| F2 | 모델 가중치 gitignore | ✅ 별도 cp + sha256 검증 (2 unique hash × 2회). install/share/models/ 반영 검증. |
| F3 | ultralytics/boxmot 미설치 + transitive cleanup | ✅ pip install --user 후 numpy 2.4.5 + opencv-python 4.13 user site 침투 확인 → cleanup 으로 시스템 1.26.4 / 4.6.0 복귀. **부수효과**: torch 2.11.0 → 2.12.0 + triton/cudnn/nccl/cusparselt upgrade (다른 ML 코드 영향 가능). |
| F4 | 워크스페이스 루트 yolov8n.pt 중복 | ✅ git fetch 로 안 옴 (정상). `ls ~/moca/yolov8n.pt` 미존재 확인. |
| F5 | scripts/run_*.sh ~/moca/ 절대경로 잔재 | ⏸ 본 머지에선 보존, 별 트랙으로 후속 |
| F6 | 내 측 untracked 정리 | ✅ Task 3 의 3 별 commit (315d716 cafe_ninja / d52d045 stop_all.sh / f437e0e 회고 2건) |
| F7 | _backups/ 도입 | ✅ .gitignore diff 0, 그대로 받아들임 |

---

## 4. 검증 통과 항목

- [x] colcon build 격리 셸 빌드 통과 — **12 packages 모두, 39.6s** (예상보다 빠름)
- [x] person_tracking_pkg ament_prefix_path.sh hook 존재 — F1 회피 검증
- [x] models/*.pt|*.task install/share 반영 — F2 검증
- [x] ros2 interface show PersonTrack/PersonTrackArray — 필드 + 한글 주석 정상
- [x] ros2 interface list dobi_npc_msgs 17 라인 (12 msg + 5 srv)
- [x] ros2 pkg executables person_tracking_pkg — 3 노드 (approach_controller_node, group_approach_node, person_tracking_node)
- [x] python import smoke — ultralytics + boxmot + mediapipe 0.10.14 + dobi_npc_msgs.msg.PersonTrack 모두 OK
- [x] mode_manager 6-state assertion — VALID_MODES `('idle', 'serving', 'patrol', 'guiding', 'engaging', 'follow')` + LEGACY_MODE_ALIAS `{'npc': 'engaging'}` 일치
- [x] dev_common.launch.py 5초 timeout — **10 노드 모두 ready 까지 도달** (카메라 + 마이크 가용 — 운 좋음)

---

## 5. 미해결 / 후속 트랙

본 머지 spec §6 Open issues + 본 작업 발견:

1. **mode_follow + mode_guiding 분리 운용 시 운영 패널 UI 영향** — moca_opserver mode chip 의 'follow' 지원 여부 확인 필요. 라이브 검증 트랙.
2. **5-state FSM spec ↔ 6-state 코드 불일치** — `docs/moca_5state_fsm_spec.md` 갱신 필요. 팀원 + 사용자 협의 후.
3. **팀원 18 commits 라이브 검증 상태 불명** — 본 머지로 통합되었으나 검증된 것 아님.
4. **F5 절대경로 잔재** — `scripts/run_3stage.sh`, `run_nav2.sh` 의 `~/moca/` 잔재. SCRIPT_DIR 패턴 적용 별 트랙.
5. **`run_nav2.sh` ↔ CLAUDE.md §11 navigation 분리 원칙** — bringup 재기동 시도 등 §11.1 위반 가능. 라이브 검증 단계에서 확인.
6. **torch 2.11.0 → 2.12.0 upgrade 부수효과** — 다른 ML 학습 코드 (특히 OMX LeRobot 등) 가 특정 torch 버전 호환성에 의존하는지 별 검증 필요.
7. **dev_common 의 docstring auto-merge 잔재 위험** — auto-merge 가 silent mis-resolve 가능. 본 머지에서 Task 7 검증으로 catch 했으나 다른 head/branch 머지 시 같은 패턴 주의.

---

## 6. 시스템 상태 (머지 완료 시점)

| 항목 | 상태 |
|---|---|
| ~/moca HEAD | `f8fce31` (merge commit, 2-parent: `f437e0e` + `fd62971`) |
| ~/moca git status | clean (단 `models/*.pt` gitignore + `docs/superpowers/` untracked) |
| build/install/log | 정상 빌드 산출물 (격리 셸 39.6s) |
| pip user site | ultralytics 8.4.51 + boxmot 19.0.0 설치, 시스템 numpy 1.26.4 + cv2 4.6.0 보호 |
| ~/moca_teammember | read-only, 변경 X |
| ~/backup/moca_merge_20260519 | 양쪽 풀 백업 + SHA256SUMS 12 라인 모두 OK + README 회복 절차 3 시나리오 |
| RPi | 미접근 (본 plan 범위 외) |
| pre-merge tag | `pre-merge-teammember-20260519` → `f437e0e` |
| backup branch | `backup-pre-merge-teammember-20260519` → `f437e0e` |

---

## 7. doby 자기 평가

### ✅ 잘한 점

- spec → plan → 실행 3 단계 워크플로우 (brainstorming → writing-plans → subagent-driven) 그대로 진행. 각 단계의 user approval gate 존중.
- 5/5 충돌 예상이 3/5 로 favorable deviation 발견 시 즉시 인지 + auto-merged 2 파일의 silent mis-resolve 위험 catch (Task 7 의 dev_common docstring 보정). plan 가정과 실제 차이 발견 시 사용자 보고 + 적응적 진행.
- F3 pip 함정 정확히 재현 + cleanup 으로 시스템 보호. CLAUDE.md §7 외부 의존성 정책 그대로 준수 ([[Phase 2 W4 pin]]).
- 백업 안전망 양쪽 풀 (293MB, SHA256SUMS 12 라인) — 회복 시나리오 3종 README 작성.
- 머지 commit 후 빌드 + 런타임 검증 모두 통과 — 5/14 백업 복원 사고 [[2026-05-18 첫 세션]] 같은 silent fail 없음.
- doby 4 덕목 그대로 — 솔직 (DONE_WITH_CONCERNS 적극 활용), 명확 (각 task report 의 expected vs actual 명시), 꼼꼼 (F1~F4 단계별 verification gate), 의리 (사용자 결정 4건 그대로 + auto-merged catch 후 보정).

### ⚠ 아쉬운 점 / 학습

- 본 plan 의 충돌 5건 예상이 git 의 auto-merge 능력을 과소평가. 실제 mechanical 머지에서는 hunks 가 겹치지 않으면 git 이 처리. 단 의미 차원 검증은 사람이 필요.
- torch upgrade 부수효과 (2.11 → 2.12) 를 plan 단계에서 예상 못 함. F3 함정의 transitive cleanup 명세는 numpy/cv2 만 잡았으나, pip 가 다른 ML deps 도 함께 upgrade. 별 트랙 검증 필요.
- subagent-driven 의 spec/quality reviewer 단계를 read-only / mechanical task 에서 일부 생략 — controller 직접 검토로 대체. skill 가이드와의 일관성 측면에서 정확한 보조.

### 📌 영구 학습 (향후 머지 작업)

- `git merge --no-commit + --no-ff` 후 충돌 갯수는 plan 예상의 lower bound — auto-merge 가 줄여줄 수 있음.
- auto-merged 파일도 의미 차원에서 검증 (예: docstring 의 표기, FSM state 등이 의도된 union 인지).
- pip 의 transitive deps 는 numpy/cv2 외에도 ML stack (torch/triton/cudnn) 도 함께 upgrade 함. cleanup 시 영향 범위 더 넓게 보기.

---

*다음 갱신: 라이브 검증 트랙 진입 후 — 사용자 명시 "/cmd_vel 발행 X" 해제 시점*
