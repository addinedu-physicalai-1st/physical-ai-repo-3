# 🔢 스피드 카운터 (Speed Counter)

> **PlayWait W2** — 두 번째 게임
> **기술**: MediaPipe Hands (양손)
> **난이도**: ⭐⭐
> **상태**: 코드 구현 완료, 단위 테스트 39/39 통과 (실기 테스트 대기)

---

## 📌 한 줄 소개

화면에 뜨는 숫자(1~10)를 **양손 손가락 합산**으로 빠르게 표현해 **5연속 정답**에 도달하면 승리하는 콤보 게임.

## 🎮 게임 규칙

- 1~10 중 무작위 출제 (직전 숫자 회피)
- 두 손 손가락의 합으로 답을 만든다 (예: 7 = 5 + 2 또는 4 + 3)
- 콤보가 쌓일수록 제한 시간 단축
- 즉시 종료 조건: 5연속 정답(승) / 60초 경과(패) / 누적 오답 5회(패)

### 콤보 단계와 제한 시간

| 콤보 | Easy | Normal | Hard |
|---|---|---|---|
| 0~2 (워밍업) | 4.0초 | 3.0초 | 2.0초 |
| 3~4 (가속) | 3.5초 | 2.5초 | 1.7초 |
| 5+ (최고) | 3.0초 | 2.0초 | 1.4초 |

## 🚀 실행

```bash
cd ~/PlayWait
python -m games.07_speed_counter.src.game

# 단독 모듈 테스트
python -m games.07_speed_counter.src.hand_counter      # 양손 합산기
python -m games.07_speed_counter.src.question_gen      # 출제기
python -m games.07_speed_counter.src.score_tracker     # 점수 추적기
python -m games.07_speed_counter.src.sound_manager     # 사운드 6종 시연

# 단위 테스트
.venv/bin/pytest games/07_speed_counter/tests/ -v
```

## ⌨️ 조작

| 키 | 동작 |
|---|---|
| **1 / 2 / 3** | 난이도 선택 (쉬움 / 보통 / 어려움) |
| **SPACE** | 게임 시작 |
| **R** | 재시작 (게임 종료 후) |
| **Q / ESC** | 종료 |
| **F** | 전체 화면 토글 |
| **+ / =** | 화면 확대 (0.25배씩, 최대 3.0) |
| **- / _** | 화면 축소 (0.25배씩, 최소 0.5) |
| **0** | 기본 크기 (1.5배) 리셋 |

## 🧱 구조

```
07_speed_counter/
├── README.md                     # 본 문서
├── W2_스피드카운터_기획서.md       # 상세 기획서
├── src/
│   ├── game.py                   # 메인 게임 (5페이즈 상태머신)
│   ├── hand_counter.py           # 양손 손가락 합산 + StabilityBuffer
│   ├── question_gen.py           # 출제기 + 가속 시간 계산 (순수 함수)
│   ├── score_tracker.py          # 콤보·오답·시간·종료조건 (순수 클래스)
│   ├── theme.py                  # PinkLAB 디자인 토큰 (W1 공유)
│   ├── ui_renderer.py            # 한글 PIL 배치 렌더러 (W1 공유 + W2 컴포넌트)
│   └── sound_manager.py          # pygame 사운드 (W1 공유)
├── assets/sounds/                # W1 사운드 6종 재활용
└── tests/
    ├── conftest.py               # src/ 경로 주입
    ├── test_question_gen.py      # 23 cases
    └── test_score_tracker.py     # 16 cases
```

## 🔄 페이즈 흐름

```
DIFFICULTY_SELECT → READY → QUESTION ↻ ROUND_RESULT
                                          ↓
                                       GAME_OVER
```

`QUESTION` 페이즈는 제한 시간 종료 시점에 안정화 버퍼(`StabilityBuffer`, window=5/threshold=4)의 확정값을 정답과 비교한다.

## 🎨 디자인 (W1 표준 준수)

- 카메라 캡처 640×480 @ 30fps, 화면은 `DISPLAY_SCALE=1.5`로 960×720 표시
- PinkLAB 핑크 `#FF6B9D` 메인, 정답 초록 / 오답 빨강 / 경고 노랑
- 한글 UI는 PIL 배치 렌더링(`begin_frame` → `draw_text_korean` → `flush_text`)
- 안전 종료: try-finally + signal(SIGINT/SIGTERM) + atexit

## ✅ Definition of Done

- [x] 양손 손가락 합산 1~10 알고리즘 구현
- [x] 가속 시간 단축이 콤보별로 정확히 작동 (단위 테스트로 검증)
- [x] 5연속 / 60초 / 오답 5회 종료 조건 (단위 테스트로 검증)
- [x] 한글 UI 정상 표시 (W1 인프라 재활용)
- [x] 사운드 6종 재활용
- [x] 단위 테스트 39건 전부 통과
- [ ] **실기 플레이 테스트** (Stephen 직접 수행)
- [ ] 30fps 유지 확인 (실기 테스트 시 측정)

## 📝 W1 → W2 변경 핵심

| 항목 | W1 (가위바위보) | W2 (스피드 카운터) |
|---|---|---|
| 손 개수 | 1손 (`max_num_hands=1`) | 2손 (`max_num_hands=2`) |
| 출력 | 손 모양 5종 | 손가락 합계 0~10 |
| 안정화 윈도우 | 10/7 (느림) | 5/4 (빠름) |
| 진행 방식 | 라운드 기반 (3선 2승) | 시간 기반 + 콤보 |
| AI 상대 | Doby 3난이도 | (없음 — 시간 가속이 난이도) |
| 신규 컴포넌트 | — | 출제 숫자, 타이머 바, 콤보 점수바 |
