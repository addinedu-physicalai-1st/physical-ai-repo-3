# 2026-05-21 — follow 모드 카메라 토픽 수정 + Git 워크플로우 정립

> 작성: 2026-05-21 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: 1인 추종 구현 + Git 워크플로우 정립 + mobility_controller 이관 검토

---

## 0. 세션 시작 전 상태

어제(2026-05-20) 수정된 코드들이 커밋 안 된 상태로 로컬에만 존재.
- `run_robot_cam.sh` — if false → if true 수정
- `dev_common.launch.py` — dbscan_eps 450.0, min_group_size 2
- `approach_controller_node.py` — EMA 필터, 거리 비례 Kp
- `person_tracking_node.py` — MediaPipe 제거, YOLO26 GPU

---

## 1. Git 워크플로우 정립

### 오늘 한 것
```bash
git fetch origin          # 원격 정보 다운로드 (파일 변화 없음)
git fetch origin dev:dev  # 로컬 dev 브랜치 최신화
git merge dev             # 피처 브랜치에 팀원 코드 합치기
```
→ 충돌 없이 깔끔하게 merge 완료. 팀원 코드(GEVA, 감정분석 등) 피처 브랜치에 합류.

### 매일 루틴 확정

**일과 끝 (저녁):**
```bash
git add .
git commit -m "작업 내용"
git push origin feature/dobby-follower
```

**매일 아침:**
```bash
git fetch origin dev:dev
git merge dev
```

---

## 2. 팀원 코드 확인 (dev 머지 후)

### GEVA 감정분석 파이프라인

```
geva_node.py
  → /emotion/state (EmotionState: valence, arousal, confidence)
  → rapport_tracker_node.py
  → /rapport/event (RapportEvent: engagement_up / abort_trigger / neutral_continue)
```

**현재 한계**: GEVA가 track_id를 제공하지 않음. 어떤 사람이 호감인지 특정 불가.
**결정**: track_id 연동은 추후 과제로 스킵. 지금은 가장 가까운 사람(큰 bbox) 추종.

---

## 3. 1인 추종 — 이미 구현됨 확인

`mode_follow.launch.py` 구성:
- `person_detector_node` (MediaPipe efficientdet_lite0) → `/robot_cam/persons`
- `follow_controller_node` (P제어 + LiDAR + EMA) → `/follow/cmd_vel`

### 3.1 발견한 버그: 카메라 토픽 불일치

**증상**: person_detector_node가 카메라 영상을 받지 못함.

**원인**: `mode_follow.launch.py`의 `input_topic`이 `/image_raw`로 설정되어 있었음.
우리 카메라(SNAP U2)는 `/robot_cam/image_raw/compressed`로 발행.

**수정**: `input_topic` → `/robot_cam/image_raw` + `use_compressed: True` 추가.

```python
# 수정 전
'input_topic': '/image_raw',

# 수정 후
'input_topic': '/robot_cam/image_raw',
'use_compressed': True,
```

---

## 4. follow_controller_node 현재 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| target_dist | 0.30m | 유지할 거리 |
| kp_linear | 0.8 | 거리 P 게인 |
| kp_angular | 0.5 | 각도 P 게인 |
| max_linear | 0.4 m/s | 최대 직진 속도 |
| max_angular | 0.6 rad/s | 최대 회전 속도 |
| angle_smoothing_alpha | 0.4 | EMA 필터 |
| scan_stop_dist | 0.30m | 장애물 정지 거리 |

---

## 5. mobility_controller 이관 검토

팀장님 요청: doby_controller의 주행 코드를 mobility_controller로 이관.

**이관 대상 5개 파일:**
| 파일 | 역할 |
|---|---|
| `group_approach_node.py` | 그룹 접근 결정 |
| `approach_controller_node.py` | 그룹 접근 cmd_vel |
| `follow_controller_node.py` | 1인 추종 cmd_vel |
| `guiding_controller_node.py` | 안내 주행 (Nav2) |
| `patrol_scheduler_node.py` | 테이블 순회 (Nav2) |

**현재 mobility_controller 상태**: C++ 스텁만 있음 → Python 패키지 추가 필요.
**결정**: 팀장님께 구조 확인 후 진행 예정.

---

## 6. 검증 현황

| 항목 | 결과 |
|---|---|
| 그룹 감지 (DBSCAN) | ✅ |
| 그룹 접근 (approach_controller) | ✅ |
| 1인 추종 코드 존재 확인 | ✅ |
| 1인 추종 카메라 토픽 수정 | ✅ |
| 1인 추종 실물 테스트 | ⏳ 다음 세션 |

---

## 7. 다음 세션 진입점 (2026-05-22)

1. **1인 추종 실물 테스트** ← 최우선
   - `mode_follow.launch.py` 실행해서 person_detector + follow_controller 동작 확인
   - target_dist, kp_linear/angular 파라미터 튜닝
2. **데모 영상 촬영**
   - 사진: 그룹 클러스터링
   - 영상: 그룹 접근 / 1인 추종
3. **mobility_controller 이관** (팀장님 구조 확인 후)
4. **track_id 기반 추종** (GEVA 연동 후)

---

*다음 갱신: 2026-05-22 1인 추종 실물 테스트 후*
