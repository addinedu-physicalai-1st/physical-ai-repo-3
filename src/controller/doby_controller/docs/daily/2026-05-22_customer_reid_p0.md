# 2026-05-22 — Customer ReID P0 구현 (customer_identity_node)

> 작성: 2026-05-22 (doby)
> 브랜치: feature/dobby-follower
> 세션 목표: STEP 4 대상 인식 유지 — insightface ArcFace 기반 customer_identity_node 구현

---

## 0. 세션 배경

### 왜 이걸 만들었나

전체 로봇 흐름:
```
그룹 감지 → 그룹 접근 → 홍보/게임(팀원) → 감정분석(팀원) → 대상 선택 → 1인 추종
```

문제: GEVA(감정분석)는 `/emotion/state`로 "호감 있음"을 발행하지만 **track_id를 제공하지 않음**.
→ "어떤 사람이 호감인지" 특정 불가 → follow 대상 선택 불가.

### 기존 설계의 한계

| 항목 | 기존 | 문제 |
|---|---|---|
| track_id (BoT-SORT) | 세션 임시 번호 | 사람이 잠깐 사라지면 새 번호 부여 |
| Visual Re-ID | 옷/체형 기반 | 미구현 상태였음 |
| MediaPipe Pose | 관절 추정 | 시각화용이라 2026-05-19 제거됨 |

### 해결책

**insightface ArcFace** 기반 `customer_identity_node` 신규 구현:
- 얼굴 임베딩(512차원)으로 동일인 판별
- `customer_id` (12-hex 영속 ID) 부여
- track이 끊겨도 재등장 시 같은 customer_id 유지

---

## 1. 최종 선정 기술 변경

| STEP | 이전 | 현재 |
|---|---|---|
| STEP 4 대상 인식 유지 | Visual Re-ID + MediaPipe Pose | **insightface ArcFace (face ReID)** |

---

## 2. 구현 내용 (Task 1~5)

### Task 1: 신규 메시지 생성

- `dobi_npc_msgs/msg/CustomerIdentity.msg` — 단일 손님 식별 결과
- `dobi_npc_msgs/msg/CustomerRegistry.msg` — 전체 손님 배열
- `dobi_npc_msgs/CMakeLists.txt` 등록 + 빌드 완료

### Task 2: dobi_npc_identity 패키지 골격

- `package.xml`, `setup.py`, `setup.cfg`, `resource/`, `__init__.py`
- `colcon build` 통과, `ros2 pkg list` 등록 확인

### Task 3: customer_registry.py (순수 로직 TDD)

**핵심 로직:**
- `cosine_similarity(a, b)` — 0 벡터 division-by-zero 회피
- `CustomerRegistry.resolve(track_id, embedding)` — 바인딩 캐시 or 재매칭 or 신규 생성
- `release_track(track_id)` — track 소실 시 바인딩 제거 (customer는 registry 유지)

**pytest 9개 전부 통과:**
- cosine_similarity 동일/직교/0벡터
- 신규 얼굴 → 신규 customer_id
- track 끊겼다 재등장 → 같은 customer_id ← P0 핵심
- 다른 얼굴 → 다른 customer_id
- 살아있는 track → 캐시 반환 (churn 흡수)
- resolve_no_face (얼굴 없을 때)
- match_threshold 경계값

### Task 4: insightface 도입 + face_embedder.py

**설치:**
```bash
pip install --user insightface==0.7.3 onnxruntime==1.18.1
```

**발견한 문제:**
- `opencv-python-headless 4.11.0` 이 딸려와서 시스템 cv2 4.6.0 오염
- `pip uninstall --yes opencv-python-headless` 로 복구

**face_embedder.py:**
- `embed_largest_face(bgr_image)` — 이미지에서 가장 큰 얼굴 임베딩 추출
- `embed_in_roi(bgr_image, bbox)` — bbox ROI 안에서 임베딩 추출
- 스모크 테스트: 빈 이미지 → None 반환 ✅

**buffalo_l 모델:** `~/.insightface/models/buffalo_l/` 자동 다운로드 완료

### Task 5: customer_identity_node.py (ROS 노드)

**구독:**
- `/webcam/image_raw` (Image) — 얼굴 인식용 이미지
- `/person_tracking/tracks` (PersonTrackArray) — track_id + bbox

**발행:**
- `/customer/registry` (CustomerRegistry) — customer_id 포함 전체 손님 배열

**동작 흐름:**
```
PersonTrackArray 수신
  ↓
각 track의 bbox에서 얼굴 임베딩 추출 (embed_in_roi)
  ↓
CustomerRegistry.resolve() → customer_id 부여
  ↓
/customer/registry 발행
```

**빌드 + 기동 확인:**
```
[INFO] customer_identity_node ready (threshold=0.5, image=/webcam/image_raw)
```

---

## 3. 기술 검증 현황 업데이트

| 단계 | 항목 | 상태 |
|---|---|---|
| 1단계 | insightface ArcFace 임베딩 추출 로직 | ✅ pytest 9개 |
| 1단계 | cosine similarity 재식별 로직 | ✅ pytest 9개 |
| 2단계 | opencv-python-headless 충돌 수정 | ✅ |
| 2단계 | /customer/registry 토픽 발행 | ✅ 노드 기동 확인 |
| 3단계 | 동일인 재등장 customer_id 일치 | ⏳ 실물 테스트 |
| 3단계 | match_threshold 실측값 (0.35~0.55) | ⏳ 실물 테스트 |

---

## 4. 커밋 목록

```
900399d feat(identity): add CustomerIdentity / CustomerRegistry messages
6fbeb88 feat(identity): scaffold dobi_npc_identity package
95894ac feat(identity): customer_registry -- embedding match + customer_id (TDD, 9 passed)
b92021b feat(identity): face_embedder -- insightface ArcFace wrapper
214812c feat(identity): customer_identity_node -- ROS node wiring
```

---

## 5. 다음 세션 진입점

1. **Task 6 실물 재식별 테스트** ← 웹캠 + person_tracking 기동 필요
   - 사람 등장 → customer_id 확인
   - 사람 사라졌다 재등장 → 같은 customer_id 확인
   - match_threshold 실측 조정 (기본값 0.5)
2. **1인 추종 실물 테스트** ← 빅핑키 필요
   - mode_follow.launch.py 실행
   - target_dist, kp_linear/angular 파라미터 튜닝
3. **데모 영상 촬영** ← 빅핑키 필요

---

*다음 갱신: Task 6 실물 테스트 후*
