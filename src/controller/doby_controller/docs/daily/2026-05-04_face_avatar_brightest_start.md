# face_avatar v2.1 — start_at_brightest 옵션 (fade-in 검정 회피)

**작성일**: 2026-05-04 (tts abort dwell 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "face_avatar brightest 시작 옵션: fade-in 검정 회피"
**선행**:
- v1 (2026-05-02): `pygame.image.load`이 첫 프레임만 → 검정 화면. 해결: PIL로 모든 프레임 스캔 → brightest 1장 정적 표시
- v2 (2026-05-03): 정적 → 애니메이션. PIL ImageSequence + native duration loop. **expression 전환 시 frame 0부터 → 1초 검정 fade-in 재발**

**상태**: `start_at_brightest` 파라미터(기본 True) 추가. GIF별 brightest frame index 캐시 → 표정 전환 시 그 인덱스부터 재생. 라이브 검증 완료.

---

## 0. 시작 컨텍스트

v2 애니메이션이 self-contained하지만 GIF 자산 자체가 fade-in 인트로로 시작하는 게 문제. PinkLAB vicpinky_emotion 8 GIF가 모두 영상 효과로 검정에서 페이드인되는 구조.

라이브 측정 (max_frames_per_gif=20):
```
basic     idx=0   mean=32.0   (이미 brightest)
hello     idx=16  mean=32.0   ← 80% 검정 후 표정
happy     idx=0   mean=30.0
fun       idx=6   mean=31.9
interest  idx=9   mean=35.2
bored     idx=9   mean=23.1
sad       idx=11  mean=30.5
angry     idx=5   mean=22.8
```

→ 표정 전환 시 매번 검정 깜빡임 발생. 운영자 발표/시연에서 즉각성 떨어뜨림.

---

## 1. 구현 — `face_avatar_node.py` (~30줄)

### 1.1 파라미터

```python
self.declare_parameter('start_at_brightest', True)
```

— True가 기본. 운영 정책상 abort 시 검정 1초가 차단 신호로 의도되면 false 해제.

### 1.2 GIF 로드 시 brightest_idx 측정

```python
from PIL import Image, ImageSequence, ImageStat

def _load_gif_animation(self, path, name) -> Tuple[FrameList, int]:
    # ... 1단계 모든 프레임 수집, 2단계 다운샘플 (기존 그대로) ...
    
    # 3단계: PIL → pygame Surface + brightness 측정
    brightest_idx = 0
    brightest_mean = -1.0
    for i, (rgba, duration) in enumerate(all_frames):
        try:
            mean_l = ImageStat.Stat(rgba.convert('L')).mean[0]
        except Exception:
            mean_l = 0.0
        if mean_l > brightest_mean:
            brightest_mean = mean_l
            brightest_idx = i
        # ... 기존 surface 생성 ...
    
    return result, brightest_idx
```

— PIL `ImageStat.Stat(rgba.convert('L')).mean[0]`로 luminance 평균. v1 era에서 numpy 사용했으나 본 작업에서는 PIL ImageStat 사용 (numpy 의존 제거 v2 정책 유지).

### 1.3 캐시 저장 + 시작 인덱스 헬퍼

```python
self.frames: dict = {}          # name -> FrameList (기존)
self.brightest_idx: dict = {}   # name -> int (v2.1 신규)

# 로드 루프
frame_list, brightest = self._load_gif_animation(path, name)
if frame_list:
    self.frames[name] = frame_list
    self.brightest_idx[name] = brightest

def _start_index_for(self, name: str) -> int:
    if self.start_at_brightest:
        return self.brightest_idx.get(name, 0)
    return 0

def _switch_to(self, name: str):
    self.current = name
    self._frame_index = self._start_index_for(name)
    self._frame_started_ms = pygame.time.get_ticks()
```

— `__init__`의 초기 `self._frame_index` 설정도 같은 헬퍼로 통합.

---

## 2. 라이브 검증

### 2.1 `start_at_brightest=true` (기본)

```bash
ros2 run dobi_npc_dialog face_avatar \
  --ros-args -p fullscreen:=false -p start_at_brightest:=true
```

```
[INFO]   basic: 160 frames → 20 sampled (6400 ms total, brightest idx=0 mean=32.0)
[INFO]   hello: 82 frames → 20 sampled (3280 ms total, brightest idx=16 mean=32.0)
[INFO]   happy: 68 frames → 20 sampled (2720 ms total, brightest idx=0 mean=30.0)
[INFO]   fun: 76 frames → 20 sampled (3040 ms total, brightest idx=6 mean=31.9)
[INFO]   interest: 82 frames → 20 sampled (3280 ms total, brightest idx=9 mean=35.2)
[INFO]   bored: 110 frames → 20 sampled (4400 ms total, brightest idx=9 mean=23.1)
[INFO]   sad: 132 frames → 20 sampled (5280 ms total, brightest idx=11 mean=30.5)
[INFO]   angry: 60 frames → 20 sampled (2400 ms total, brightest idx=5 mean=22.8)
[INFO] loaded 8/8 expressions, ..., start_at_brightest=True
```

— ✅ 8 GIF 모두 brightest idx 측정 + 캐시. hello 16번째가 가장 밝음 (fade-in 한가운데).

### 2.2 `start_at_brightest=false` (옵션 해제, 컨트롤)

```
[INFO] loaded 8/8 expressions, ..., start_at_brightest=False
[INFO] face: basic -> hello
```

— ✅ 옵션 비활성. expression 전환 시 frame 0부터 시작 (기존 v2 동작 유지).

### 2.3 시각 효과 (사용자 주관)

- True: 표정 전환 즉시 visible. cycle 진행되다 자연 fade-out → fade-in 다시 brightest로 돌아오는 "숨쉬기" 느낌.
- False: 매 전환마다 검정 1초 → fade-in. 의식적인 "리셋" 신호. abort 시 차단감으로는 적절.

기본은 호객 funnel 정상 흐름의 즉각성을 우선 → `True`.

---

## 3. 발견 / 함정

### 3.1 max_frames 다운샘플 후 brightest 측정

기존 v2가 다운샘플(160→30 또는 20)을 먼저 한 뒤 surface 변환. brightest 측정도 다운샘플 후 시점에서 수행 → idx 값은 sampled 인덱스 기준. v1 era 절대 idx (160 중 X)와 다름.

같은 step배 보정으로 의미는 동일 (전체 사이클 중 brightest 위치 보존).

### 3.2 mean luminance 값이 v1 (~43) 보다 낮음 (~32)

v1은 원본 해상도로 측정. v2는 다운샘플(20프레임)에 한 컷씩 평균. 절대값보다 GIF 간 상대 비교가 의미 있음. 32~35 범위면 충분히 표정 visible.

### 3.3 cycle 진행 중 dim 구간 재출현

start_at_brightest=True여도 frame index가 자연 cycle하므로 brightest 이후 진행되다 wrap → 0번 (검정) 다시 거침. 즉 첫 1초 즉각성은 확보, 이후 cycle은 GIF 의도대로.

대안 (미구현): `frames[name]` 자체를 `frames[brightest:]`로 trim → cycle도 dim 구간 안 거침. 단 GIF 의도(예: 숨쉬는 듯한 lull)를 손실. 현 구현은 "첫인상" 만 개선하는 보수적 선택.

### 3.4 abort 시 검정 fade-in의 의미

회고 anim_v2 §"abort_expression 시도 같은 시작 정책"에서 언급된 트레이드오프 — abort 시 검정 1초가 "차단" 시각 신호로 자연스러울 수 있음. start_at_brightest=False로 끄면 abort 표정도 검정 fade-in. 페르소나별 정책이 필요해지면 후속 (TODO §"persona별 dwell/abort_expression").

### 3.5 PIL ImageStat — numpy 의존 회피

v1은 numpy로 픽셀 평균. v2 cleanup에서 numpy import 제거. 본 작업도 PIL ImageStat 표준 라이브러리 사용으로 일관.

---

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` | `start_at_brightest` 파라미터 + `_load_gif_animation` brightness 측정 + `brightest_idx` 캐시 + `_start_index_for` 헬퍼 + `_switch_to` 갱신 + ImageStat import (~30줄) |

---

## 5. 다음 / TODO 갱신

### CLAUDE.md TODO 변경
- `[ ] face_avatar brightest 시작 옵션: fade-in 검정 회피` → **`[x] face_avatar brightest 시작 (2026-05-04, start_at_brightest=true 기본, hello idx=16/20 가장 극단)`**

### 후속 (관련성)
- [ ] **frames trim 옵션**: brightest 이후만 보존 → cycle 중 dim 구간 회피. 운영 정책 따라 선택.
- [ ] **persona별 start_at_brightest**: 페르소나 YAML에 옵션 노출 → professional_adult는 즉각, friendly_child는 fade-in 으로 부드럽게 등 — 영상 톤 미세 조정.

---

## 6. 한 줄 요약

> face_avatar에 `start_at_brightest` 추가. GIF별 brightest frame index 미리 캐시 → 표정 전환 시 즉시 visible. hello가 idx=16/20으로 가장 극단(80% 검정 후 표정). 라이브 검증 통과.
