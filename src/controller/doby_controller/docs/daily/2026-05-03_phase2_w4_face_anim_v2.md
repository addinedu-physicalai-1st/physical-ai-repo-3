# Phase 2 W4 회고 — face_avatar 애니메이션 v2 (모든 프레임 + GIF 재생)

**작성일**: 2026-05-03
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: 직전 회고 §4 face_avatar 애니메이션 v2 트랙
**상태**: 정적 1프레임 → 모든 프레임 + GIF native duration loop 재생. 사용자 확인: "각 표정이 살아있는 느낌이야".

---

## 0. 발견 → 해결

### 발견 (face_avatar v1 한계)
- pygame.image.load는 GIF 첫 프레임만 가져옴 → fade-in 검정 문제
- v1 해결: PIL ImageSequence로 모든 프레임 enumerate → brightest 1장 선택 (정적 표시)
- 그러나 **표정 자산은 LCD 애니메이션용** — 깜빡임/입 움직임 등이 정적 표시로 사라짐
- 표정에 생명감 부족 (사용자 표정 자산 의도와 다름)

### 해결 (v2)
**모든 프레임 → max_frames(기본 30)로 균등 다운샘플 → 화면 크기에 맞춰 미리 scale → pygame Surface 리스트 캐시. GIF native duration으로 무한 loop 재생.**

---

## 1. 작업 흐름

### Step 1: 메모리 산정 + 다운샘플링 정책

**원본 프레임 수**: basic 160 / hello 82 / happy 68 / fun 76 / interest 82 / bored 110 / sad 132 / angry 60 = **총 770프레임**

**원본 그대로 캐시 시 메모리** (RGBA, 화면 크기 기준):
- 풀스크린 1920×1080: 770 × 8.3MB = **6.4 GB** ← 위험
- 윈도우 800×600: 770 × 1.9MB = **1.5 GB**

해결: **max_frames_per_gif** 파라미터로 균등 다운샘플링.
- 기본 30프레임 (대략 1초 @ 30fps 자연스러운 표정 cycle)
- 8 GIF × 30 = 240프레임
- 풀스크린 ~2GB / 윈도우 ~460MB — 견딜 만함
- 운영 시 더 줄이려면 `-p max_frames_per_gif:=15` 등

**duration 보정**: 다운샘플링하면 frame 간격이 늘어남 → 각 frame의 native duration을 step배(=원본/sampled 비율)로 곱해서 **전체 재생 시간 유지**:
```
basic: 160 frames → 20 sampled, 6400ms total (원본 6.4초 유지)
```

### Step 2: 코드 변경

**파일 통째로 다시 작성** (변경 범위가 커서). 핵심 변경:

| v1 | v2 |
|---|---|
| `_load_gif_brightest_frame` → 정적 1장 | `_load_gif_animation` → FrameList (튜플 리스트) |
| `self.images[name] = Surface` | `self.frames[name] = [(Surface, duration_ms), ...]` |
| `self.dirty` 플래그 | `_frame_index` + `_frame_started_ms` |
| 변경 시에만 render | `_advance_frame()` + 매 tick render (필요시) |
| numpy import (brightness 계산) | numpy 제거 (다운샘플링은 단순 슬라이싱) |

핵심 헬퍼:
```python
def _load_gif_animation(self, path, name) -> FrameList:
    img = Image.open(path)
    all_frames = [(f.convert('RGBA').copy(), int(f.info.get('duration', 33)))
                  for f in ImageSequence.Iterator(img)]
    n_total = len(all_frames)
    if n_total > self.max_frames:
        step = n_total / self.max_frames
        indices = [int(i * step) for i in range(self.max_frames)]
        sampled = [all_frames[i] for i in indices]
        sampled = [(rgba, max(33, int(dur * step))) for rgba, dur in sampled]
        all_frames = sampled
    return [(self._fit_to_screen(
                pygame.image.fromstring(rgba.tobytes(), rgba.size, rgba.mode)
                .convert_alpha()), dur)
            for rgba, dur in all_frames]

def _advance_frame(self) -> bool:
    frame_list = self.frames.get(self.current, [])
    if len(frame_list) <= 1:
        return False
    _, duration = frame_list[self._frame_index]
    if pygame.time.get_ticks() - self._frame_started_ms >= duration:
        self._frame_index = (self._frame_index + 1) % len(frame_list)
        self._frame_started_ms = pygame.time.get_ticks()
        return True
    return False

def _switch_to(self, name):
    """expression 전환 — 첫 프레임부터 reset (자연 fade-in)."""
    self.current = name
    self._frame_index = 0
    self._frame_started_ms = pygame.time.get_ticks()
```

run loop:
```python
while running:
    rclpy.spin_once(self, timeout_sec=0.0)
    for event in pygame.event.get(): ...
    if self._advance_frame():
        self._render()  # 프레임 변화 시에만 (clock cap이 30fps 보장)
    self.clock.tick(self.fps_cap)
```

### Step 3: 자체 검증 (windowed 400×300, max_frames=20)

```
basic: 160 frames → 20 sampled (6400 ms total)
hello: 82 → 20 (3280 ms)
happy: 68 → 20 (2720 ms)
fun: 76 → 20 (3040 ms)
interest: 82 → 20 (3280 ms)
bored: 110 → 20 (4400 ms)
sad: 132 → 20 (5280 ms)
angry: 60 → 20 (2400 ms)
```

8/8 로드 + duration 보정 정상 (basic 6.4초 유지). expression 전환 정상 (`face: basic -> fun`).

### Step 4: 사용자 라이브 검증

> "각 표정이 살아있는 느낌이야."

표정 8개가 LCD GIF 의도대로 자연스러운 애니메이션으로 재생됨. v1의 정적 표시 한계 극복.

---

## 2. 핵심 학습

### Frame caching vs lazy loading 트레이드오프

| 전략 | 메모리 | CPU | 첫 프레임 latency |
|---|---|---|---|
| **모두 미리 caching** (선택) | 큼 (수백 MB~수 GB) | 작음 (blit만) | 0 |
| Lazy loading (PIL Image.seek) | 작음 (1프레임만) | 큼 (매 프레임 disk seek + scale) | 매번 ~10ms |
| LRU cache | 중간 | 중간 | 첫 N회만 큼 |

표정 전환 시 latency 0이 호객 인터랙션에 중요. 메모리는 다운샘플링으로 통제.

### 다운샘플링과 duration 보정

균등 sampling으로 프레임 수만 줄이면 재생 속도가 빨라짐 (30 frame을 1초에 재생 vs 60 frame을 1초에 = 2배 빠름). **duration을 step배로 보정**하면 전체 재생 시간 유지.

```
원본 60 frames * 33ms = 1980ms 총
sampled 30 frames * 66ms (=33*2) = 1980ms 총 ✓
```

이게 자연스러움 — 표정 cycle 속도가 자산 의도와 일치.

### `max(33, int(dur * step))` 가드

GIF의 duration이 가끔 0이거나 매우 작은 값일 수 있음 (저장 도구 따라). step 곱한 후에도 0 가능 → 33ms 최소 보장. 30fps cap과 일관.

### Expression 전환 시 frame reset = 자연 fade-in

`_switch_to`에서 `frame_index = 0`로 reset → 새 GIF의 첫 프레임부터 시작. fade-in으로 자연스러운 표정 도입. 만약 기존 frame_index 유지하면 새 GIF 중간부터 재생되어 부조화.

### `_advance_frame()` 변화 감지로 불필요 render 회피

매 30fps tick마다 render할 수도 있지만 — frame이 같으면 GPU/CPU 낭비. `_advance_frame()`이 True 반환할 때만 `_render()`. CPU 절약.

단, expression 전환 시 즉시 render 필요 — `_switch_to`에서 _frame_started_ms를 now로 설정하니 다음 _advance_frame이 자동 detect (또는 첫 _render 1회로 보장).

### numpy 의존 제거

v1은 brightest frame 선택 위해 numpy로 픽셀 평균. v2는 다운샘플링이 단순 슬라이싱 → numpy 불필요. import 제거. dependency 단순화.

(package.xml의 python3-numpy depend는 그대로 유지 — 다른 노드(geva_node)가 사용. dialog 패키지 자체엔 안 쓰지만 시스템 dep라 무해.)

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **표정 생명감 큰 차이**: 정적 1프레임 vs 애니메이션 — 사용자 즉시 체감. "살아있는 느낌"
- **메모리 안정**: max_frames=30 + 화면 크기 scale로 풀스크린 ~2GB 수준. 16~32GB 노트북에서 견딜 만함
- **GIF native duration이 자연스러운 박자**: vicpinky_emotion 자산이 LCD에서 적절한 timing으로 만들어졌음 — 그대로 사용

### 위험 요소

- **풀스크린 시 메모리 ~2GB**: 더 작은 노트북 / 다른 무거운 노드와 동시 실행 시 부담. `max_frames_per_gif`로 조정. 운영 환경에서 측정 필요.
- **다운샘플링 시 미세 표정 손실**: 20프레임으로 줄이면 짧은 micro-expression(예: 눈 깜빡임 1프레임)이 sampling 인덱스에 따라 빠질 수 있음. 표정 인식 쪽 (vicpinky 원본 의도) 검증 필요한 표정은 max_frames 늘리는 검토.
- **첫 프레임이 검정**: GIF가 fade-in으로 시작 → frame=0 시작 시 검정 → 1초 안에 정착 표정. v1처럼 brightest frame부터 시작하는 옵션 검토 가능.
- **다중 monitor 미고려**: pygame.display.Info()는 primary monitor만. 외부 디스플레이 운영 시 monitor index 선택 필요.
- **GIF가 큰 transparent 영역**: convert('RGBA') 후 alpha 채널 보존. blit 시 검은 배경에 합성 — alpha가 의도대로 보이는지 자산별 확인 필요.

### 갭

- **brightest frame 시작 옵션 미구현**: 현재는 frame 0부터. 운영 정책에 따라 시작 인덱스를 brightest로 둘 수 있음. 후속.
- **표정별 다른 재생 정책**: hello/angry는 한 번 후 정지, happy/fun은 loop 같은 표정 의도 매핑은 현재 없음. 모두 loop. 자산 별 정책 메타데이터 추가 검토 (예: persona YAML 또는 별도 `face_policy.yaml`).
- **abort_expression 시도 같은 시작 정책**: 현재 abort_expression(basic)도 frame 0부터 시작 → fade-in 검정. abort 시각적 신호로 검정 1초가 자연스러우나, basic 정착 표정으로 즉시 가도록 brightest_index 옵션 검토.

---

## 4. 다음 일정

### 즉시 가능 (선택)

- **abort dwell time**: abort 후 일정 시간 face publish 무시 (basic 유지)
- **min_confidence 임계**: rapport_tracker에 conf 게이팅
- **brightest frame 시작 옵션**: 위 갭 §3
- **자투리**: YAML 스키마, BT 단위 테스트, 영어 phrase

### Phase 후속

- W2.5 (RPi): GEFA, decision_rule fusion
- Phase 3: RPS 미니게임
- Phase 4: 운영 환경 메모리/CPU 측정 + max_frames 튜닝

---

## 5. 산출물 위치

### 수정 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` (전면 재작성, ~50줄 추가)

### 신규 파일
- `docs/daily/2026-05-03_phase2_w4_face_anim_v2.md` (본 회고)

### 변경 없음
- 다른 모든 노드, 메시지, BT XML, persona YAML — 그대로

### 다음 커밋
- W4 face anim v2 + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_dialog --symlink-install
'
```

### 자체 검증 (windowed)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_dialog face_avatar \
  --ros-args -p fullscreen:=false -p window_width:=400 -p window_height:=300 \
  -p max_frames_per_gif:=20

# loading 로그 (기대):
#   basic: 160 frames → 20 sampled (6400 ms total)
#   ...
#   loaded 8/8 expressions, max_frames_per_gif=20, fps_cap=30

# 1~8 키로 표정별 애니메이션 확인
```

### 라이브 풀스크린
```bash
ros2 run dobi_npc_dialog face_avatar
# 또는 더 가볍게 (메모리 ~1GB)
ros2 run dobi_npc_dialog face_avatar --ros-args -p max_frames_per_gif:=15
```

### 통합 (전체 호객 시나리오)
```bash
pkill -KILL -f "geva_node|rapport_tracker|bt_executor|persona_manager|face_avatar|tts_node" 2>/dev/null
ros2 launch dobi_npc_bringup dev_all.launch.py
# face_avatar는 launch에서 windowed default — 통합 시 다른 작업과 동시
```

### 운영 시 메모리 조정
```bash
# 가벼운 메모리 환경
ros2 run dobi_npc_dialog face_avatar --ros-args -p max_frames_per_gif:=10

# 부드러운 애니메이션 (메모리 충분 시)
ros2 run dobi_npc_dialog face_avatar --ros-args -p max_frames_per_gif:=60 -p fps_cap:=60
```

---

**상태**: face_avatar 애니메이션 v2 완료. 표정 살아있는 느낌 확인. 다음은 abort dwell time / min_confidence / brightest 시작 / 자투리 또는 휴식.
