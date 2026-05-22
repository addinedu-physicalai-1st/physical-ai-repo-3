# 카페 Pick-and-Place 데이터셋 명세서 v3

> 목표: GR00T N1.7 (3B) fine-tuning 기준 추론 성공률 **90%** 달성

---

## 1. 데이터셋 구성

### 1.1 통합 시나리오

에피소드 구성 원칙:

- home 자세에서 시작 → task 수행 → home 자세로 복귀
- **성공**: 정상 완료
- **재시도**: 그립 실패 → 짧은 후퇴 → 재시도 → 성공 (한 에피소드 안에서 처리)

모든 시나리오는 **12개 위치를 균등하게 커버**하며 단일 학습으로 통합한다.
시나리오마다 에피소드 수를 **48개**로 통일하여 학습 시 클래스 불균형을 방지한다.


| ID  | 시나리오         | 환경 상태          | 위치 전략          | **합계** |
| --- | ------------ | -------------- | --------------- | ------ |
| S-1 | 컵 단독         | cup=1          | 12위치 × 4회      | **48** |
| S-2 | 접시 단독        | plate=1        | 12위치 × 4회      | **48** |
| S-3 | 컵 2개         | cup=2          | 48조합 × 1회      | **48** |
| S-4 | 접시 2개        | plate=2        | 48조합 × 1회      | **48** |
| S-5 | 접시 1개 + 컵 1개 | plate=1, cup=1 | 16조합 × 3회      | **48** |
| S-6 | 접시 1개 + 컵 2개 | plate=1, cup=2 | 24조합 × 2회      | **48** |
| S-7 | 빈 환경 멈춤      | 비어있음 (2종)      | sub-case 7 : 13 | **20** |
|     | **합계**       |                |                 | **308** |


---

### 위치 전략 상세

#### 단일 object (S-1, S-2) — 12위치 × 4회 = 48ep

3×4 격자 12개 위치를 순환하며, 각 위치에서 4회 수집한다.

```
수집 순서: episode_index % 12 → 해당 위치 번호 (①~⑫)
각 회차마다 다른 음식/음료 fill level 사용
```

---

#### 2개 동종 (S-3, S-4) — 48조합 × 1회 = 48ep

서로 다른 열에 있는 두 위치의 조합을 사용한다. 열 조합 3종 × 16조합 = 48개 조합.

```
열 조합 1 — 좌열 × 중열 (ep  0~15):
  좌열 ①④⑦⑩  ×  중열 ②⑤⑧⑪  →  4×4 = 16조합

열 조합 2 — 좌열 × 우열 (ep 16~31):
  좌열 ①④⑦⑩  ×  우열 ③⑥⑨⑫  →  4×4 = 16조합

열 조합 3 — 중열 × 우열 (ep 32~47):
  중열 ②⑤⑧⑪  ×  우열 ③⑥⑨⑫  →  4×4 = 16조합
```

수집 순서: `episode_index % 48` → 위 순서대로 조합 번호 사용

---

#### 혼합 컵1+접시1 (S-5) — 16조합 × 3회 = 48ep

접시는 **좌열**, 컵은 **우열**에만 배치한다.

```
접시 위치: 좌열 ①④⑦⑩  (4개)
컵   위치: 우열 ③⑥⑨⑫  (4개)
조합:      4 × 4 = 16가지

수집 순서:
  ep  0~15: 1번째 순환 (조합 ①③ → ①⑥ → ①⑨ → ①⑫ → ④③ → ...)
  ep 16~31: 2번째 순환 (동일 조합, 다른 음식)
  ep 32~47: 3번째 순환 (동일 조합, 다른 음식)
```

---

#### 혼합 컵2+접시1 (S-6) — 24조합 × 2회 = 48ep

접시는 **좌열**, 컵 2개는 **우열**에만 배치한다.

```
접시 위치:  좌열 ①④⑦⑩  (4개)
컵 2개 조합: 우열 C(4,2) = ③⑥ / ③⑨ / ③⑫ / ⑥⑨ / ⑥⑫ / ⑨⑫  (6조합)
총 조합:    4 × 6 = 24가지

수집 순서:
  ep  0~23: 1번째 순환 (24조합 순서대로)
  ep 24~47: 2번째 순환 (동일 조합, 다른 음식)
```

---

#### 빈 환경 (S-7) — 20ep

실제 운영에서 "빈 환경"의 대부분은 작업 완료 후 pick workspace만 비는 sub-case 2다.
VLM이 배워야 할 핵심은 **"place 구역에 물체가 있어도 pick 대상이 없으면 stop"** 이므로
헷갈릴 수 있는 sub-case 2 비중을 높인다.


| Sub-case | 환경 상태                                               | 에피소드 |
| -------- | --------------------------------------------------- | ---- |
| 1        | pick workspace + place workspace 모두 비어있음            | 7    |
| 2        | pick workspace 비어있음, place workspace에 완료된 object 존재 | 13   |


**Sub-case 2 — place 구역 물체 구성:**


| place 구역 내용  | 에피소드 | 대응 시나리오  |
| ------------ | ---- | -------- |
| 컵 1개         | 2    | S-1 완료 후 |
| 접시 1개        | 2    | S-2 완료 후 |
| 컵 2개         | 2    | S-3 완료 후 |
| 접시 2개        | 2    | S-4 완료 후 |
| 접시 1개 + 컵 1개 | 2    | S-5 완료 후 |
| 접시 1개 + 컵 2개 | 3    | S-6 완료 후 |


**배치 원칙:**

- 물체 위치는 에피소드마다 place 구역 안에서 변화 (항상 같은 자리 금지 — VLM의 위치 shortcut 학습 방지)
- 물체끼리 겹치지 않되 완벽 정렬하지 않음 (자연스러운 완료 상태)
- 접시 위 음식·컵 안 음료를 에피소드마다 다르게 — 공간적 판단을 학습하게 함

---

### 1.2 전체 요약


|            | 에피소드 수  |
| ---------- | ------- |
| S-1 ~ S-6  | 288     |
| S-7 (빈 환경) | 20      |
| **합계**     | **308** |


---

### 1.3 데이터 수집 명령어

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


| ID  | DATASET_NAME       | num_episodes | episode_time_s | PLACEHOLDER                                |
| --- | ------------------ | ------------ | -------------- | ------------------------------------------ |
| S-1 | `s1_cup1`          | 48           | 25             | `"pick up cup and place at target zone"`   |
| S-2 | `s2_plate1`        | 48           | 25             | `"pick up plate and place at target zone"` |
| S-3 | `s3_cup2`          | 48           | 40             | `"pick up cup and place at target zone"`   |
| S-4 | `s4_plate2`        | 48           | 40             | `"pick up plate and place at target zone"` |
| S-5 | `s5_plate1_cup1`   | 48           | 35             | `"pick up plate and place at target zone"` |
| S-6 | `s6_plate1_cup2`   | 48           | 50             | `"pick up plate and place at target zone"` |
| S-7 | `s7_empty`         | 20           | 8              | `"return to home"`                         |


#### 예시 — S-1 (컵 단독)

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
  --dataset.repo_id=local/s1_cup1 \
  --dataset.root=datasets/s1_cup1 \
  --dataset.num_episodes=48 \
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
| S-1  | `[1]` 전체 → `[2]` 마지막 ~20 frame                                    |
| S-2  | `[0]` 전체 → `[2]` 마지막 ~20 frame                                    |
| S-3  | `[1]` 전체 (두 컵 연속, task_index 변경 없음) → `[2]` 마지막 ~20 frame (**segment 재시작** 경계 표시) |
| S-4  | `[0]` 전체 (두 접시 연속) → `[2]` 마지막 ~20 frame (**segment 재시작** 경계 표시) |
| S-5  | `[0]` 접시 완료까지 → `[1]` 컵 완료까지 → `[2]` 마지막 ~20 frame                |
| S-6  | `[0]` 접시 완료까지 → `[1]` 두 컵 모두 완료까지 (연속) → `[2]` 마지막 ~20 frame      |
| S-7  | `[2]` 전체 episode                                                  |


### 2.3 S-3, S-4 Segment 재시작 상세

S-5/S-6는 task_index가 바뀌지만,
S-3/S-4는 각 object 처리의 **시작 frame을 수동으로 정확히 경계 표시**한다.

```
S-4 에피소드 예시 (접시 2개, 총 370 frame):

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
python scripts/episode_info.py --dataset datasets/s2_plate1
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
python scripts/episode_info.py --dataset datasets/s2_plate1 --ep 0 --play
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
| S-3/S-4 object 간 경계                 | 이전 object를 내려놓고 팔이 다음 object 쪽으로 방향을 트는 첫 프레임    |


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

S-1 / S-2 (단일 object, 경계 1개):

```json
"0": [
  {"start": 0,        "end": boundary-1, "task_index": 1},
  {"start": boundary, "end": N,          "task_index": 2}
]
```

S-6 (plate → cup → home, 경계 2개):

```json
"0": [
  {"start": 0,          "end": plate_done,    "task_index": 0},
  {"start": plate_done+1,"end": cup_done,     "task_index": 1},
  {"start": cup_done+1, "end": N,             "task_index": 2}
]
```

S-3 / S-4 (segment 재시작, 경계 여러 개):

```json
"0": [
  {"start": 0,            "end": obj1_done,  "task_index": 1},
  {"start": obj1_done+1,  "end": obj2_done,  "task_index": 1},
  {"start": obj2_done+1,  "end": N,          "task_index": 2}
]
```

S-7 (전체 home):

```json
"0": [
  {"start": 0, "end": N, "task_index": 2}
]
```

---

### 3.6 Step 5 — 검증 (dry-run)

```bash
python scripts/apply_labels.py \
  --dataset datasets/s2_plate1 \
  --labels labels/s2_plate1.json \
  --dry-run
```

확인 항목:

- `N frames updated` 숫자가 예상 범위인지
- `[warn] N episodes not labeled` 경고가 없는지

---

### 3.7 Step 6 — 적용

```bash
python scripts/apply_labels.py \
  --dataset datasets/s2_plate1 \
  --labels labels/s2_plate1.json
```

원본 parquet은 `.bak_YYYYMMDD_HHMMSS`로 자동 백업된다.

---

### 3.8 권장 작업 순서

라벨링 난이도 낮은 것부터 진행한다:


| 순서  | 데이터셋        | 경계 수  | 이유                    |
| --- | ----------- | ----- | --------------------- |
| 1   | s7_empty    | 0     | 전체 `[2]` home         |
| 2   | s1_cup1     | 1개    | 단일 object             |
| 3   | s2_plate1   | 1개    | 단일 object             |
| 4   | s3_cup2     | 여러 개  | segment 재시작 경계 표시     |
| 5   | s4_plate2   | 여러 개  | segment 재시작 경계 표시     |
| 6   | s5_plate1_cup1 | 2개  | plate → cup 전환        |
| 7   | s6_plate1_cup2 | 가장 복잡 | 혼합 다수 처리              |


---

## 5. 학습 방법

### 5.1 1-Stage Fine-tuning 구조

```
GR00T N1.7 (pre-trained base)
        │
        ▼  S-1 ~ S-7 전체로 fine-tune
Final model  ← pick-and-place 추론 성공률 90% 목표
```

모든 시나리오가 동일한 에피소드 수(48ep)이므로 클래스 가중치 없이 균등 학습한다.

---

### 5.2 학습 파라미터


| 항목                          | 값                          |
| --------------------------- | -------------------------- |
| 데이터                         | S-1~S-7 전체 (308 episode)   |
| 목표                          | pick-and-place 추론 성공률 90%  |
| max-steps                   | 18,000                     |
| learning-rate               | 1e-4                       |
| batch-size                  | 8                          |
| gradient-accumulation-steps | 4                          |
| effective batch-size        | 32                         |
| action-horizon              | 16                         |
| save-steps                  | 2,000                      |


### 5.3 데이터 분할

```
학습:  278 episode (90%)
검증:   30 episode (10%)
```

검증 세트 구성: 각 시나리오에서 균등 추출 (S-1~S-6 각 4~5 ep, S-7 2 ep)

---

### 5.4 추론 시 Instruction Switching

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

### 5.5 음식·음료 다양성 수집 전략

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
| S-2  | 48   | 1개      | 48      | **5~6회**  |
| S-4  | 48   | 2개      | 96      | **10~11회** |
| S-5  | 48   | 1개      | 48      | **5~6회**  |
| S-6  | 48   | 1개      | 48      | **5~6회**  |


#### 에피소드 세팅 시트 (예시: S-2 첫 18 ep)


| ep  | food_type | 격자 위치           |
| --- | --------- | --------------- |
| 0   | 0번 음식     | 격자 ① (ep%12=0) |
| 1   | 1번 음식     | 격자 ②           |
| 2   | 2번 음식     | 격자 ③           |
| ... | ...       | ...             |
| 12  | 3번 음식     | 격자 ① (2번째 순환)  |
| 13  | 4번 음식     | 격자 ②           |


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

### 5.6 학습 시 Augmentation

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

### 6.5 시나리오별 위치 커버리지 수집 가이드

> **원칙**: 같은 위치에서 N번 반복하는 것보다 다른 위치에서 1번씩 N곳이 낫다.


| ID  | 시나리오         | 에피소드 | 위치 전략                                             | 음식 종당 횟수   |
| --- | ------------ | ---- | ------------------------------------------------- | ---------- |
| S-1 | 컵 단독         | 48   | 12위치 × 4회, `ep%12` 위치 순환                          | —          |
| S-2 | 접시 단독        | 48   | 12위치 × 4회, `ep%12` 위치 순환                          | **5~6회**   |
| S-3 | 컵 2개         | 48   | 열 조합 3종(좌+중 / 좌+우 / 중+우) × 각 16조합, 각 1회           | —          |
| S-4 | 접시 2개        | 48   | 열 조합 3종 × 각 16조합, 각 1회                            | **10~11회** |
| S-5 | 접시1 + 컵1     | 48   | 좌열(접시)×우열(컵) 16조합 × 3회                            | **5~6회**   |
| S-6 | 접시1 + 컵2     | 48   | 좌열(접시)4 × 우열(컵2 조합 C(4,2)=6) = 24조합 × 2회          | **5~6회**   |
| S-7 | 빈 환경         | 20   | 위치 무관 (sub-case 1 : sub-case 2 = **7 : 13**)      | —          |


### 6.6 참고 문헌

- [SmolVLA: Robust Skills, Brittle Grounding (arxiv 2602.24143)](https://arxiv.org/html/2602.24143)
- [GR00T N1: An Open Foundation Model for Generalist Humanoid Robots](https://arxiv.org/html/2503.14734v1)
- [NVIDIA Isaac GR00T N1.7 — HuggingFace Blog](https://huggingface.co/blog/nvidia/gr00t-n1-7)
- [EgoScale: Scaling Dexterous Manipulation with Diverse Egocentric Human Data](https://arxiv.org/html/2602.16710v1)
- [DataPlatter: Boosting Robotic Manipulation Generalization with Minimal Costly Data](https://arxiv.org/html/2503.19516v1)
- [Object-Focus Actor for Data-efficient Robot Generalization](https://arxiv.org/html/2505.15098)
