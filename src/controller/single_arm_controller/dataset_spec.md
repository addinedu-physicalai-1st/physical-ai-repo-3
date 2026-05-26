# 카페 Pick-and-Place 데이터셋 명세서 v2

> 목표: GR00T N1.7 (3B) fine-tuning 기준 추론 성공률 **90%** 달성

---

## 1. 데이터셋 구성

### 1.1 카테고리 A — Long Episode

에피소드 구성 원칙:

- home 자세에서 시작 → task 수행 → home 자세로 복귀
- **성공**: 정상 완료
- **재시도**: 그립 실패 → 짧은 후퇴 → 재시도 → 성공 (한 에피소드 안에서 처리)


| ID  | 시나리오         | 환경 상태          | 성공      | 재시도    | **합계**  |
| --- | ------------ | -------------- | ------- | ------ | ------- |
| A-1 | 컵만 1개        | cup=1          | 30      | 5      | **35**  |
| A-2 | 접시만 1개       | plate=1        | 30      | 5      | **35**  |
| A-3 | 접시만 2개       | plate=2        | 30      | 10     | **40**  |
| A-4 | 컵만 2개        | cup=2          | 30      | 10     | **40**  |
| A-5 | 접시 1개 + 컵 1개 | plate=1, cup=1 | 38      | 12     | **50**  |
| A-6 | 접시 1개 + 컵 2개 | plate=1, cup=2 | 35      | 10     | **45**  |
| A-7 | 빈 환경 멈춤      | 비어있음 (2종)      | 18      | 0      | **18**  |
|     | **합계**       |                | **211** | **52** | **263** |


**A-7 빈 환경 sub-case 비율: 7 : 11 (sub-case 1 : sub-case 2)**

실제 운영에서 "빈 환경"의 대부분은 작업 완료 후 pick workspace만 비는 sub-case 2다.
VLM이 배워야 할 핵심은 **"place 구역에 물체가 있어도 pick 대상이 없으면 stop"** 이므로
헷갈릴 수 있는 sub-case 2 비중을 높인다.


| Sub-case | 환경 상태                                               | 에피소드 |
| -------- | --------------------------------------------------- | ---- |
| 1        | pick workspace + place workspace 모두 비어있음            | 7    |
| 2        | pick workspace 비어있음, place workspace에 완료된 object 존재 | 13   |


**Sub-case 2 — place 구역 물체 구성 (A 카테고리 완료 상태 재현):**


| place 구역 내용  | 에피소드 | 대응 시나리오  |
| ------------ | ---- | -------- |
| 컵 1개         | 2    | A-1 완료 후 |
| 접시 1개        | 2    | A-2 완료 후 |
| 접시 2개        | 2    | A-3 완료 후 |
| 컵 2개         | 2    | A-4 완료 후 |
| 접시 1개 + 컵 1개 | 2    | A-5 완료 후 |
| 접시 1개 + 컵 2개 | 1    | A-6 완료 후 |


**배치 원칙:**

- 물체 위치는 에피소드마다 place 구역 안에서 변화 (항상 같은 자리 금지 — VLM의 위치 shortcut 학습 방지)
- 물체끼리 겹치지 않되 완벽 정렬하지 않음 (자연스러운 완료 상태)
- 접시 위 음식·컵 안 음료를 에피소드마다 다르게 — 공간적 판단을 학습하게 함

---

### 1.2 카테고리 B — Atomic-focused Demo

목적: A 카테고리 성공률을 높이는 foundation. 특히 그립 성공률과 multi-object handling 강화.


| ID  | Skill                | 주요 다양화 포인트                      | **합계**  |
| --- | -------------------- | ------------------------------- | ------- |
| B-1 | 접시 단독 pick-and-place | 위치 **3×4 격자 균등 커버 (12개 위치)**, 음식 종류 10종+ | **50**  |
| B-2 | 컵 단독 pick-and-place  | 위치 **3×4 격자 균등 커버 (12개 위치)**, 음료 종류 10종+ | **50**  |
| B-3 | 연속 접시 처리 (접시 2개)     | 두 접시 위치 조합                      | **20**  |
| B-4 | 연속 컵 처리 (컵 2~3개)     | 컵 개수 2-3, 위치 조합                 | **20**  |
| B-5 | 재시도 recovery         | 컵 10 ep + 접시 10 ep              | **20**  |
|     | **합계**               |                                 | **170** |


---

### 1.3 전체 요약


|        | 에피소드 수  |
| ------ | ------- |
| 카테고리 A | 263     |
| 카테고리 B | 170     |
| **합계** | **433** |


---

### 1.4 데이터 수집 명령어

#### 사전 확인

카메라 인덱스와 포트를 먼저 확인한다.

```bash
# 카메라 인덱스 확인
python scripts/show_cameras.py

# 로봇 포트 확인
ls /dev/ttyUSB*
```

#### 기본 명령어 템플릿

```bash
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyUSB0 \
  --robot.cameras='{
    "top":   {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30},
    "wrist": {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30}
  }' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyUSB1 \
  --dataset.repo_id=local/<DATASET_NAME> \
  --dataset.root=datasets/<DATASET_NAME> \
  --dataset.num_episodes=<N> \
  --dataset.single_task="<PLACEHOLDER>" \
  --dataset.fps=30 \
  --dataset.episode_time_s=<T> \
  --dataset.reset_time_s=30 \
  --dataset.push_to_hub=false \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2
```

> `single_task`는 녹화 시 placeholder로만 사용. 실제 instruction은 라벨링 절차(섹션 3)에서 `apply_labels.py`로 적용한다.

#### 시나리오별 파라미터


| ID  | DATASET_NAME      | num_episodes | episode_time_s | PLACEHOLDER                                |
| --- | ----------------- | ------------ | -------------- | ------------------------------------------ |
| A-1 | `a1_cup1`         | 35           | 25             | `"pick up cup and place at target zone"`   |
| A-2 | `a2_plate1`       | 35           | 25             | `"pick up plate and place at target zone"` |
| A-3 | `a3_plate2`       | 40           | 40             | `"pick up plate and place at target zone"` |
| A-4 | `a4_cup2`         | 40           | 40             | `"pick up cup and place at target zone"`   |
| A-5 | `a5_plate1_cup1`  | 50           | 35             | `"pick up plate and place at target zone"` |
| A-6 | `a6_plate1_cup2`  | 45           | 50             | `"pick up plate and place at target zone"` |
| A-7 | `a7_empty`        | 18           | 8              | `"return to home"`                         |
| B-1 | `b1_plate_atomic` | 50           | 20             | `"pick up plate and place at target zone"` |
| B-2 | `b2_cup_atomic`   | 50           | 20             | `"pick up cup and place at target zone"`   |
| B-3 | `b3_plate_seq`    | 20           | 40             | `"pick up plate and place at target zone"` |
| B-4 | `b4_cup_seq`      | 20           | 40             | `"pick up cup and place at target zone"`   |
| B-5 | `b5_retry`        | 20           | 25             | `"pick up plate and place at target zone"` |


#### 예시 — A-1 (컵 1개)

```bash
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyUSB0 \
  --robot.cameras='{
    "top":   {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30},
    "wrist": {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30}
  }' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyUSB1 \
  --dataset.repo_id=local/a1_cup1 \
  --dataset.root=datasets/a1_cup1 \
  --dataset.num_episodes=35 \
  --dataset.single_task="pick up cup and place at target zone" \
  --dataset.fps=30 \
  --dataset.episode_time_s=25 \
  --dataset.reset_time_s=30 \
  --dataset.push_to_hub=false \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2
```

#### 녹화 중 키 조작


| 키     | 동작                |
| ----- | ----------------- |
| `→`   | 현재 에피소드 저장 후 다음으로 |
| `←`   | 현재 에피소드 삭제 후 재녹화  |
| `Esc` | 녹화 종료             |


---

## 2. Instruction 라벨링

### 2.1 사용 task instruction

```
task_index 0  →  "pick up plate and place at target zone"
task_index 1  →  "pick up cup and place at target zone"
task_index 2  →  "return to home"
```

### 2.2 시나리오별 라벨링 규칙


| 시나리오 | 라벨링 전략                                                            |
| ---- | ----------------------------------------------------------------- |
| A-1  | `[1]` 전체 → `[2]` 마지막 ~20 frame                                    |
| A-2  | `[0]` 전체 → `[2]` 마지막 ~20 frame                                    |
| A-3  | `[0]` 전체 (두 접시 연속, task_index 변경 없음) → `[2]` 마지막 ~20 frame        |
| A-4  | `[1]` 전체 (두 컵 연속) → `[2]` 마지막 ~20 frame                           |
| A-5  | `[0]` 접시 완료까지 → `[1]` 컵 완료까지 → `[2]` 마지막 ~20 frame                |
| A-6  | `[0]` 접시 완료까지 → `[1]` 두 컵 모두 완료까지 (연속) → `[2]` 마지막 ~20 frame      |
| A-7  | `[2]` 전체 episode                                                  |
| B-1  | `[0]` 전체 → `[2]` 마지막 ~20 frame                                    |
| B-2  | `[1]` 전체 → `[2]` 마지막 ~20 frame                                    |
| B-3  | `[0]` 1번 접시 / `[0]` 2번 접시 (**segment 재시작**) → `[2]` 마지막 ~20 frame |
| B-4  | `[1]` 1번 컵 / `[1]` 2번~ 컵 (**segment 재시작**) → `[2]` 마지막 ~20 frame  |
| B-5  | 해당 object의 task_index 전체 → `[2]` 마지막 ~20 frame                    |


### 2.3 B-3, B-4 Segment 재시작 상세

A-3/A-4는 multi-object 구간 전체를 동일 task_index로 연속 라벨링하지만,
B-3/B-4는 각 object 처리의 **시작 frame을 수동으로 정확히 경계 표시**한다.

```
B-3 에피소드 예시 (접시 2개, 총 370 frame):

  frame   0 ~ 169 : task_index=0  ← 1번 접시  [시작 상태: 접시 2개]
  frame 170 ~ 349 : task_index=0  ← 2번 접시  [시작 상태: 접시 1개, 경계 수동 라벨링]
  frame 350 ~ 369 : task_index=2  ← home 복귀
```

**학습 효과**: 모델이 "pick up plate" instruction을

- 접시 2개인 상태 (1번 segment 시작)
- 접시 1개 남은 상태 (2번 segment 시작)

두 시각적 상태 모두에서 학습하여, 추론 시 동일 instruction 2회 호출이 안정적으로 동작한다.

---

## 3. 라벨링 절차

전체 흐름: **영상 시청 → JSON 작성 → 검증 → 적용**

### 3.1 사전 준비

```bash
mkdir -p labels
```

데이터셋마다 `labels/{dataset_name}.json` 파일 하나씩 작성한다.

---

### 3.2 Step 1 — 에피소드 목록 확인

```bash
python scripts/episode_info.py --dataset datasets/serving_a2
```

```
 ep   seek(s)  frame_start  frame_end  n_frames
  0      0.00            0        587       588
  1     19.60            0        490       491
```

- `seek(s)`: mpv에서 해당 에피소드가 시작되는 시각(초)
- `n_frames`: 에피소드 총 프레임 수 (frame_index 최댓값 = n_frames - 1)

---

### 3.3 Step 2 — 에피소드 영상 시청

```bash
python scripts/episode_info.py --dataset datasets/serving_a2 --ep 0 --play
```


| 키         | 동작                   |
| --------- | -------------------- |
| `space`   | 일시정지                 |
| `,` / `.` | 프레임 1개 뒤/앞           |
| `←` / `→` | 5초 뒤/앞               |
| `[` / `]` | 재생속도 -10% / +10%     |
| `o`       | OSD 토글 (현재 재생 시각 표시) |


---

### 3.4 Step 3 — 경계 프레임 식별

경계 프레임 = task_index가 바뀌는 첫 번째 frame_index

**시각적 기준:**


| 경계                                  | 찾는 순간                                            |
| ----------------------------------- | ------------------------------------------------ |
| `[pick up X]` → `[return to home]`  | 그리퍼가 object에서 완전히 떨어지고 팔이 홈 방향으로 움직이기 시작하는 첫 프레임 |
| `[pick up plate]` → `[pick up cup]` | 접시에서 그리퍼가 떨어지고 팔이 컵 쪽으로 방향을 트는 첫 프레임             |


**frame_index 계산:**

```
frame_index = round((mpv_현재시각(초) - seek_s) × 30)
```

예: 에피소드 0 (seek_s = 0.00), mpv에서 18.40초에 경계 발견
→ frame_index = round((18.40 − 0.00) × 30) = **552**

---

### 3.5 Step 4 — label JSON 작성

**기본 구조:**

```json
{
  "tasks": [
    "pick up plate and place at target zone",
    "pick up cup and place at target zone",
    "return to home"
  ],
  "episodes": {
    "0": [
      {"start": 0,   "end": 551, "task_index": 1},
      {"start": 552, "end": 587, "task_index": 2}
    ],
    "1": [
      {"start": 0,   "end": 469, "task_index": 1},
      {"start": 470, "end": 490, "task_index": 2}
    ]
  }
}
```

> `task_index`는 `tasks` 배열의 인덱스 (section 2.1 기준: plate=0, cup=1, home=2)

**시나리오별 JSON 패턴:**

A-1 / A-2 (단일 object, 경계 1개):

```json
"0": [
  {"start": 0,        "end": boundary-1, "task_index": 1},
  {"start": boundary, "end": N,          "task_index": 2}
]
```

A-6 (plate → cup → home, 경계 2개):

```json
"0": [
  {"start": 0,          "end": plate_done,   "task_index": 0},
  {"start": plate_done+1,"end": cup_done,    "task_index": 1},
  {"start": cup_done+1, "end": N,            "task_index": 2}
]
```

B-3 / B-4 (segment 재시작, 경계 여러 개):

```json
"0": [
  {"start": 0,            "end": obj1_done,  "task_index": 0},
  {"start": obj1_done+1,  "end": obj2_done,  "task_index": 0},
  {"start": obj2_done+1,  "end": N,          "task_index": 2}
]
```

A-8 (전체 home):

```json
"0": [
  {"start": 0, "end": N, "task_index": 2}
]
```

---

### 3.6 Step 5 — 검증 (dry-run)

```bash
python scripts/apply_labels.py \
  --dataset datasets/serving_a2 \
  --labels labels/serving_a2.json \
  --dry-run
```

확인 항목:

- `N frames updated` 숫자가 예상 범위인지
- `[warn] N episodes not labeled` 경고가 없는지

---

### 3.7 Step 6 — 적용

```bash
python scripts/apply_labels.py \
  --dataset datasets/serving_a2 \
  --labels labels/serving_a2.json
```

원본 parquet은 `.bak_YYYYMMDD_HHMMSS`로 자동 백업된다.

---

### 3.8 권장 작업 순서

라벨링 난이도 낮은 것부터 진행한다:


| 순서  | 데이터셋           | 경계 수  | 이유                     |
| --- | -------------- | ----- | ---------------------- |
| 1   | serving_a7     | 0     | 전체 `[2]` home          |
| 2   | serving_a2, a3 | 1개    | 단일 object              |
| 3   | serving_b1, b2 | 1개    | 단일 object atomic       |
| 4   | serving_a4     | 1개    | 연속 처리이나 task_index 불변  |
| 5   | serving_b5     | 1개    | 재시도 포함이나 task_index 불변 |
| 6   | serving_a1     | 2개    | plate → cup 전환         |
| 7   | serving_b3, b4 | 여러 개  | segment 재시작 경계 표시      |
| 8   | serving_a5     | 가장 복잡 | 혼합 다수 처리               |


---

## 5. 학습 방법

### 5.1 2-Stage Fine-tuning 구조

```
GR00T N1.7 (pre-trained base)
        │
        ▼  Stage 1: B 카테고리만 fine-tune
Stage 1 checkpoint  ← atomic skill 성공률 90%+ 확보
        │
        ▼  Stage 2: A+B 전체로 이어서 fine-tune
Final model  ← long episode 추론 성공률 90% 목표
```

Stage 2는 pre-trained base에서 재시작하지 않고 **Stage 1 체크포인트를 초기값으로** 사용한다.
Stage 1에서 확보한 그립 정확도·재시도 패턴을 Stage 2가 계승하면서 long episode 흐름을 추가 학습한다.

---

### 5.2 Stage 1 — Atomic Skill 강화


| 항목                          | 값                          |
| --------------------------- | -------------------------- |
| 데이터                         | B-1~B-5 (170 episode)      |
| 목표                          | 단일 pick-and-place 성공률 90%+ |
| max-steps                   | 5,000                      |
| learning-rate               | 1e-4                       |
| batch-size                  | 8                          |
| gradient-accumulation-steps | 4                          |
| effective batch-size        | 32                         |
| action-horizon              | 16                         |
| save-steps                  | 1,000                      |


### 5.3 Stage 2 — Full Task 통합


| 항목                          | 값                       |
| --------------------------- | ----------------------- |
| 초기 체크포인트                    | Stage 1 best checkpoint |
| 데이터                         | A+B 전체 (433 episode)    |
| 목표                          | long episode 추론 성공률 90% |
| max-steps                   | 25,000                  |
| learning-rate               | 5e-5                    |
| batch-size                  | 8                       |
| gradient-accumulation-steps | 4                       |
| effective batch-size        | 32                      |
| action-horizon              | 16                      |
| save-steps                  | 5,000                   |


### 5.4 데이터 분할

```
학습:  403 episode (93%)
검증:   30 episode (7%)
```

검증 세트 구성: A 시나리오별 2~~3 ep, B 시나리오별 1~~2 ep (균등 추출)

---

### 5.5 추론 시 Instruction Switching

```python
def run_task():
    while True:
        env = vlm.analyze(top_view_image)  # Qwen3-VL 8B

        if env.plates > 0:
            vla.execute("pick up plate and place at target zone")

        elif env.cups > 0:
            vla.execute("pick up cup and place at target zone")

        else:
            vla.execute("return to home")
            break
```

전환 감지는 VLM이 top view 이미지로 수행한다.
매 VLA 호출이 object 1개 처리 단위이므로 그립 성공 감지는 불필요하다.

---

### 5.6 음식·음료 다양성 수집 전략

#### 음식 9종 번호 부여

수집 전 9가지 음식에 번호를 부여한다. 에피소드 순번에 따라 자동 순환한다.

```
food_type = episode_index % 9

0: ___________   1: ___________   2: ___________
3: ___________   4: ___________   5: ___________
6: ___________   7: ___________   8: ___________
```

#### 데이터셋별 종당 등장 횟수


| 데이터셋 | 에피소드 | 접시 수/ep | 총 음식 등장 | **종당 횟수** |
| ---- | ---- | ------- | ------- | --------- |
| B-1  | 50   | 1개      | 50      | **5~6회**  |
| A-2  | 35   | 1개      | 35      | **3~4회**  |
| A-3  | 40   | 2개      | 80      | **8~9회**  |
| A-5  | 50   | 1개      | 50      | **5~6회**  |
| A-6  | 45   | 1개      | 45      | **5회**    |
| B-3  | 20   | 2개      | 40      | **4~5회**  |


#### 에피소드 세팅 시트 (예시: B-1 첫 18 ep)


| ep  | food_type | 격자 위치           |
| --- | --------- | --------------- |
| 0   | 0번 음식     | 격자 A            |
| 1   | 1번 음식     | 격자 B            |
| 2   | 2번 음식     | 격자 C            |
| ... | ...       | ...             |
| 9   | 0번 음식     | 격자 J (A와 다른 구역) |
| 10  | 1번 음식     | 격자 K            |


> **원칙**: 같은 음식이 같은 위치에 반복되지 않도록 음식 순환과 격자 순환을 독립적으로 진행한다.

#### 다수 접시 시나리오 — 음식 조합 규칙

접시 2개 이상인 에피소드에서는 **한 에피소드 안에 반드시 다른 음식 2종**을 사용한다.

```
에피소드 i 기준:
  접시 1: food_type = (i * 2)     % 9
  접시 2: food_type = (i * 2 + 1) % 9
```


| ep  | 접시 1 | 접시 2 |
| --- | ---- | ---- |
| 0   | 0번   | 1번   |
| 1   | 2번   | 3번   |
| 2   | 4번   | 5번   |
| 3   | 6번   | 7번   |
| 4   | 8번   | 0번   |
| 5   | 1번   | 2번   |


#### 음료 1종 고정 — fill level 변화

음료 종류는 고정이지만 채움 정도를 에피소드마다 변화시킨다.

```
fill_level = episode_index % 3

0: full  (가득)
1: half  (절반)
2: low   (1/4 정도)
```


| 비율       | 설명               |
| -------- | ---------------- |
| full 40% | 컵 안 색 면적 최대      |
| half 40% | 중간               |
| low 20%  | 색 면적 최소, 컵 내벽 노출 |


#### 수집 전 체크리스트

```
□ 음식 9종 목록 작성 및 번호 부여
□ 세팅 시트 출력 (ep → food_type 미리 계산)
□ 다수 접시 시나리오: 에피소드마다 음식 조합 확인
□ 음료 fill level: full/half/low 순서 확인
□ 각 에피소드 시작 전 음식·위치 세팅 후 녹화
```

---

### 5.7 학습 시 Augmentation

음료 1종 고정의 한계를 보완하고 전반적인 시각 robustness를 높이기 위해 적용한다.

#### 적용 대상 및 우선순위


| 대상         | 이유                    | 우선순위 |
| ---------- | --------------------- | ---- |
| 컵 에피소드 전체  | 음료 1종만 학습 → 색상 다양성 부족 | 높음   |
| 접시 에피소드 전체 | 음식 9종이지만 새 음식 일반화 대비  | 중간   |
| 전체 공통      | 조명·그림자 변화 대응          | 낮음   |


#### Augmentation 파라미터

GR00T fine-tuning의 학습 config에 아래 값을 적용한다.

```yaml
image_augmentation:
  # 조명·명도 변화 (접시 음식 색상 다양화)
  brightness: 0.2
  contrast:   0.2

  # 채도 변화 (음료 색상 다양화 — 컵에서 특히 중요)
  saturation: 0.4

  # 색상 변화 (다른 음료색 시뮬레이션)
  hue: 0.08

  # 미세 블러 (카메라 포커스 변화 대응)
  gaussian_blur:
    kernel_size: 3
    probability: 0.3

  # 적용 확률
  apply_probability: 0.8
```

#### 주의 사항

- **horizontal flip 비활성화**: 공간적 방향성(좌/우)이 중요한 manipulation task이므로 flip 적용 금지
- **geometric augmentation 최소화**: crop·rotate는 위치 학습을 방해할 수 있으므로 사용하지 않음
- **saturation 범위**: 0.4로 설정하면 같은 음료가 진하게 또는 연하게 보여 다른 음료 색상을 간접 커버
- **augmentation은 wrist + top 카메라 양쪽**에 동일하게 적용 (일관성 유지)

---

## 6. 위치 다양성과 공간 일반화

### 6.1 VLA의 위치 일반화 실패 — SmolVLA 논문 근거

SmolVLA 논문(arxiv 2602.24143)은 현재 VLA 모델의 위치 일반화 한계를 정량적으로 측정했다.
워크스페이스 35×50cm 기준, 위치 랜덤화 정도에 따른 성공률:


| 조건            | 영역 크기       | 성공률     | 도달률(Reach) |
| ------------- | ----------- | ------- | ---------- |
| Small jitter  | 4×6 cm      | **90%** | 100%       |
| Medium jitter | 8×12 cm     | 37%     | 93%        |
| Large jitter  | 12×16 cm    | 41%     | 100%       |
| Full random   | 전체 35×50 cm | **2%**  | 4%         |


**핵심 발견**: demo를 10,000개 → 100,000개로 늘려도 Full random에서 성공률 개선 없음.
데이터 양으로는 해결되지 않으며, 실패 원인은 motor execution 실패가 아닌
**instruction grounding 실패** — "어떤 객체를 집어야 하는가" 판단을 못 하는 것이다.

### 6.2 절대 좌표 vs 상대 좌표 — 위치 외움의 근본 원인

ACT와 SmolVLA가 좌표를 외우는 근본 원인은 **절대 좌표 기반 action** 때문이다.


| 항목           | ACT                 | SmolVLA             | GR00T N1.7                           |
| ------------ | ------------------- | ------------------- | ------------------------------------ |
| Action 표현    | **절대 좌표** (x, y, z) | **절대 좌표** (x, y, z) | **상대 좌표** (Δx, Δy, Δz)               |
| 위치 일반화       | 학습한 좌표만 실행          | 학습한 좌표만 실행          | 현재 pose 기준 delta이므로 위치 무관            |
| VLM backbone | 없음                  | 소형 VLM              | **Cosmos-Reason2-2B**                |
| Pretraining  | 없음                  | 제한적                 | **EgoScale: 20,000시간** egocentric 영상 |


ACT와 SmolVLA는 action을 월드 좌표계의 절대값으로 출력하기 때문에,
학습 데이터에 없는 위치에 object가 놓이면 엉뚱한 좌표로 이동한다.

GR00T는 **현재 end-effector 위치를 기준으로 한 delta(이동량)** 를 출력하므로,
"5cm 앞으로, 3cm 오른쪽으로" 같은 상대적 명령이 된다.
object가 어느 위치에 있든 카메라 이미지를 보고 delta를 계산하면 되므로
절대 좌표 외움 문제가 구조적으로 완화된다.

### 6.3 본 시스템의 구조적 해결 — VLM+VLA 분리 파이프라인

SmolVLA의 실패(instruction grounding)를 본 시스템은 파이프라인 설계로 우회한다.

```
[Qwen3-VL 8B]  top view 이미지 분석 → 객체 위치 파악 → "어떤 것을 집을지" 결정
        ↓
[GR00T N1.7]   wrist + top 카메라 기반 visual feedback으로 실행만 담당
               → instruction grounding 문제와 분리됨
```

VLA가 "어떤 것을 집어야 하는가"를 직접 판단하지 않으므로
VLA에게 요구되는 과제는 **motor execution의 위치 일반화**만으로 좁혀진다.

### 6.4 격자(Grid) 설계

**OMX reach 범위 기준: 3열 × 4행 = 12개 위치**

OMX 팔의 실제 reach 범위와 컵 지름(6.5cm)을 함께 고려한다.

```
컵 간 최소 간격: 지름 6.5cm + 여유 1cm = 7.5cm
→ X: 3.25 / 10.75 / 18.25  (3열, 간격 7.5cm)
→ Y: 3.25 / 10.75 / 18.25 / 25.75  (4행, 간격 7.5cm)
→ 합계: 3×4 = 12개 위치

reach 범위: X 최대 18.25+3.25 = 21.5cm
            Y 최대 25.75+3.25 = 29.0cm
```

```
(단위: cm)

        3.25  10.75  18.25
 3.25 ── ①──── ②──── ③
        |      |      |
10.75 ── ④──── ⑤──── ⑥
        |      |      |
18.25 ── ⑦──── ⑧──── ⑨
        |      |      |
25.75 ── ⑩──── ⑪──── ⑫

중심 간격: 7.5cm  /  컵 사이 틈: 1cm
좌열(①④⑦⑩)  중열(②⑤⑧⑪)  우열(③⑥⑨⑫)
```

> 표시 위치에 정확히 놓을 필요 없음. ±1cm 오차는 자연스러운 위치 다양성이 됨.

**수집 순서**: `episode_index % 12` → 해당 위치 번호 사용

### 6.5 카테고리별 위치 다양성 요구사항

위치 다양성은 B-1/B-2만의 문제가 아니다. **모든 카테고리**에 적용된다.

#### 단일 object (B-1, B-2, A-1, A-2)

pick 위치를 워크스페이스 전체에 균등하게 분포시킨다.

```
pick workspace를 3×4 = 12개 위치로 분할 (6.4 격자 참조)
각 위치에서 최소 1회 이상 demo 수집 (B-1/B-2는 4~5회)

[격자 — 간격 7.5cm]
┌──────┬──────┬──────┐
│  ①  │  ②  │  ③  │  ← 상단 (근거리)
├──────┼──────┼──────┤
│  ④  │  ⑤  │  ⑥  │
├──────┼──────┼──────┤
│  ⑦  │  ⑧  │  ⑨  │
├──────┼──────┼──────┤
│  ⑩  │  ⑪  │  ⑫  │  ← 하단 (원거리)
└──────┴──────┴──────┘
셀 크기: 7.5×7.5cm  /  컵 사이 틈: 1cm
좌열(①④⑦⑩)  중열(②⑤⑧⑪)  우열(③⑥⑨⑫)
```

#### 다수 object (A-3~A-4, B-3, B-4)

객체 간 위치 **조합**이 중요하다. 각 객체를 같은 구역에 몰아넣지 않는다.

```
[좋은 예] 접시 2개:  (좌상단, 우하단) / (중앙, 좌하단) / ...
[나쁜 예] 접시 2개:  (중앙좌, 중앙우) 패턴만 반복
```

3열(좌/중/우) 기준으로 서로 다른 열 조합이 골고루 등장하도록 한다. (좌+중, 좌+우, 중+우 3가지 조합 × 상단/하단 행 변화)

#### 혼합 object (A-6, A-7)

접시 위치 × 컵 위치 조합 다양성이 필요하다.
접시 구역과 컵 구역이 겹치지 않는 배치를 우선한다.

#### 재시도 (B-5)

그립 실패가 일어나는 위치도 워크스페이스 전반에 걸쳐 분포해야 한다.
특정 위치에서만 실패하는 패턴이 생기지 않도록 한다.

### 6.6 카테고리별 위치 커버리지 수집 가이드

> **원칙**: 같은 위치에서 N번 반복하는 것보다 다른 위치에서 1번씩 N곳이 낫다.


| ID  | 시나리오         | 성공  | 재시도 | 합계  | 위치 전략                                        | 음식 종당 횟수  |
| --- | ------------ | --- | --- | --- | -------------------------------------------- | --------- |
| B-1 | 접시 단독        | 50  | 0   | 50  | 3×4 격자 균등 (12개 위치), 위치당 4~5회                 | **5~6회**  |
| B-2 | 컵 단독         | 50  | 0   | 50  | 3×4 격자 균등 (12개 위치), 위치당 4~5회                 | —         |
| B-3 | 연속 접시 2개     | 20  | 0   | 20  | 두 접시를 서로 다른 열(좌/중/우)에 배치, 열 조합 3가지 이상        | **4~5회**  |
| B-4 | 연속 컵 2~3개    | 20  | 0   | 20  | 컵들을 서로 다른 열에 배치, 행도 분산                       | —         |
| B-5 | 재시도 recovery | 0   | 20  | 20  | 12개 위치 전반에 분산 (특정 위치 편중 금지)                  | **2~3회**  |
| A-1 | 컵 1개         | 30  | 5   | 35  | 3×4 격자 균등 (12개 위치), 위치당 3회                   | —         |
| A-2 | 접시 1개        | 30  | 5   | 35  | 3×4 격자 균등 (12개 위치), 위치당 3회                   | **3~4회**  |
| A-3 | 접시 2개        | 30  | 10  | 40  | 두 접시를 서로 다른 열에 배치, 상단/하단 행도 분산               | **8~9회**  |
| A-4 | 컵 2개         | 30  | 10  | 40  | 두 컵을 서로 다른 열에 배치, 상단/하단 행도 분산               | —         |
| A-5 | 접시1 + 컵1     | 38  | 12  | 50  | 접시 열 × 컵 열 조합 (좌×우, 중×우, 좌×중 등) 다양화         | **5~6회**  |
| A-6 | 접시1 + 컵2     | 35  | 10  | 45  | 접시와 컵 2개가 모두 다른 열에 위치, 행 조합 다양화             | **5회**    |
| A-7 | 빈 환경         | 18  | 0   | 18  | 위치 무관 (sub-case 1 : sub-case 2 = **7 : 11**) | —         |


### 6.5 참고 문헌

- [SmolVLA: Robust Skills, Brittle Grounding (arxiv 2602.24143)](https://arxiv.org/html/2602.24143)
- [GR00T N1: An Open Foundation Model for Generalist Humanoid Robots](https://arxiv.org/html/2503.14734v1)
- [NVIDIA Isaac GR00T N1.7 — HuggingFace Blog](https://huggingface.co/blog/nvidia/gr00t-n1-7)
- [EgoScale: Scaling Dexterous Manipulation with Diverse Egocentric Human Data](https://arxiv.org/html/2602.16710v1)
- [DataPlatter: Boosting Robotic Manipulation Generalization with Minimal Costly Data](https://arxiv.org/html/2503.19516v1)
- [Object-Focus Actor for Data-efficient Robot Generalization](https://arxiv.org/html/2505.15098)

