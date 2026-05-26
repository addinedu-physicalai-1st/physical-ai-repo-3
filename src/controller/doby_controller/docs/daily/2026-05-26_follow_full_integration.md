# 2026-05-26 — 추종 시나리오 전체 연동

> 작성: 2026-05-26 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: 그룹 감지 → 감정 분석 → 1인 추종 전체 시나리오 자동 연동

---

## 0. 세션 배경

### 문제 인식

2026-05-22 customer_identity_node(ReID P0) 구현 완료 후,
전체 추종 시나리오를 테스트하려고 보니 연동 고리가 끊겨 있었음.

```
그룹 감지 → 그룹 접근 → 호객/감정분석 → [단절] → 1인 추종
```

### 단절의 원인 2가지

1. **카메라 불일치**
   - `person_tracking_node` → 로봇 카메라 (`/robot_cam/image_raw`)
   - `GEVA(geva_node)` → 노트북 웹캠 (별도 VideoCapture)
   - 서로 다른 화면을 보기 때문에 GEVA가 분석한 감정이 어느 track_id인지 알 수 없음

2. **track_id 미포함**
   - `EmotionState.msg`에 track_id 필드 없음
   - "누군가 웃고 있다"는 알지만 "몇 번 track_id가 웃고 있다"는 모름
   - → customer_id와 연결 불가 → 추종 대상 특정 불가

---

## 1. 해결 방향

**카메라 통일**: GEVA를 로봇 카메라(`/robot_cam/image_raw`)로 변경
→ person_tracking과 같은 화면 → track_id 연결 가능

**3단계 자동 연동 파이프라인** 신설:
```
GEVA(감정+track_id) → target_selector(customer_id 선택) → follow_controller(추종)
```

---

## 2. 구현 내용

### Task 1: EmotionState.msg — track_id 필드 추가

```
int32 track_id    # -1 = 미식별, 0+ = BoT-SORT track_id
```

### Task 2: geva_node.py 수정

| 항목 | 이전 | 변경 |
|---|---|---|
| 이미지 소스 | 노트북 웹캠 (VideoCapture) | `/robot_cam/image_raw` 구독 |
| 분석 방식 | 전체 화면 얼굴 1개 | 각 track bbox ROI 안에서 분석 |
| 발행 | valence, arousal만 | + track_id 포함 |
| 트리거 | 타이머 기반 tick | `/person_tracking/tracks` 수신 시 |

valence 가장 높은 사람의 track_id를 `/emotion/state`에 포함해서 발행.

### Task 3: target_selector_node.py 신설

```
/emotion/state (valence + track_id)
      +
/customer/registry (track_id → customer_id)
      ↓
valence > threshold(0.3) 이면
      ↓
/follow/target (customer_id 발행)
```

파라미터:
- `valence_threshold`: 0.3 (호감 판별 기준)
- `lock_duration_sec`: 5.0 (한 번 선택 후 유지 시간, 흔들림 방지)

### Task 4: follow_controller_node.py 수정

- `/follow/target` 구독 추가 → target_customer_id 자동 갱신
- `/customer/registry` 구독 → customer_id → track_id 매핑
- `/person_tracking/tracks` 구독 → track_id → bbox
- `target_customer_id` 파라미터: 빈 문자열이면 가장 큰 사람 폴백 (기존 동작 유지)

### Task 5: mode_follow.launch.py 갱신

추가된 노드:
- `customer_identity_node` (dobi_npc_identity)
- `target_selector_node` (dobi_npc_bringup)

---

## 3. 완성된 전체 추종 시나리오

```
[수동] 추종 모드 ON
        ↓
로봇 카메라 (단일 소스)
        ↓
person_tracking_node
  → /person_tracking/tracks (track_id + bbox + group_id)
        ↓                              ↓
customer_identity_node           geva_node
  → /customer/registry             → /emotion/state
    (customer_id ↔ track_id)         (valence + track_id)
        ↓                              ↓
              target_selector_node
                → /follow/target (customer_id)
                        ↓
              follow_controller_node
                → /follow/cmd_vel
[수동] 추종 모드 OFF
```

모드 켜고 끄는 것만 수동, 내부 동작은 전부 자동.

---

## 4. 기술 검증 현황

| 단계 | 항목 | 상태 |
|---|---|---|
| 1단계 | EmotionState.msg track_id 추가 | ✅ 빌드 완료 |
| 1단계 | geva_node 로봇 카메라 전환 | ✅ 빌드 완료 |
| 1단계 | target_selector_node 구현 | ✅ 빌드 완료 |
| 1단계 | follow_controller customer_id 기반 추종 | ✅ 빌드 완료 |
| 2단계 | 실물 추종 시나리오 전체 테스트 | ⏳ 빅핑키 필요 |

---

## 5. 커밋

```
0ab92db feat(follow): full follow scenario integration -- camera unify + customer_id auto tracking
```

변경 파일:
- `dobi_npc_msgs/msg/EmotionState.msg`
- `dobi_npc_emotion/dobi_npc_emotion/geva_node.py`
- `dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py`
- `dobi_npc_bringup/dobi_npc_bringup/target_selector_node.py` (신규)
- `dobi_npc_bringup/launch/mode_follow.launch.py`
- `dobi_npc_bringup/setup.py`

---

## 6. 다음 세션 진입점

1. **실물 추종 시나리오 테스트** (빅핑키 필요)
   - `mode_follow.launch.py` 전체 기동
   - GEVA → target_selector → follow_controller 자동 연동 확인
   - valence_threshold 실측 조정 (기본값 0.3)
   - customer_id ReID 재식별 확인 (사람 사라졌다 재등장)
2. **파라미터 튜닝**
   - `target_dist`, `kp_linear`, `kp_angular`
   - `lock_duration_sec` 흔들림 방지 검증

---

*다음 갱신: 실물 테스트 후*
