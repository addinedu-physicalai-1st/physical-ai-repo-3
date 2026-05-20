# Phase 2 W4 회고 — 노트북 풀스크린 face_avatar GUI

**작성일**: 2026-05-02
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 계획서**: `cafe_npc_implementation_plan.md` Phase 2 §4 W4 (Open Question 해결)
**선행 문서**: `2026-05-02_phase2_w4_geva.md` (①), `2026-05-02_phase2_w4_emotion_monitor.md` (②)
**상태**: 노트북 단독 트랙 ④ face_avatar 본 작업 + 검증 완료. 다음은 ③ TTS.

---

## 0. 오늘의 목표 vs 실제 결과

| 계획 | 결과 |
|---|---|
| 프레임워크 결정 (pygame/Qt/웹) | ✅ pygame 선택, apt python3-pygame 2.5.2 |
| `face_avatar_node.py` — 풀스크린 GIF 8 표정 | ✅ 풀스크린 1920x1080 작동, 8/8 GIF 로드 |
| `persona_manager` 확장 — face_expression 동시 발행 | ✅ /face_avatar/expression 토픽 추가 |
| 자산 처리 (vicpinky_emotion/emotion/*.gif 8개, 33MB) | ✅ 복사 없이 직접 참조 (gif_dir 파라미터) |
| 검증 (단독 / persona 통합 / 풀스크린 / 1~8 키) | ✅ 4개 모두 통과 (디버깅 2건 후) |

---

## 1. 작업 흐름 (시간순)

### Step 0: 결정 정렬

- **프레임워크**: pygame (가장 단순, ROS와 충돌 없음). Qt/웹은 33MB GIF 8개 + 풀스크린이라는 요구사항 대비 과함.
- **패키지 위치**: `dobi_npc_dialog`에 통합 (페르소나 출력 = phrase + face). 새 패키지 신설 회피.
- **자산**: `src/shared/vic_pinky/vicpinky_emotion/emotion/` 직접 참조. 33MB 자산을 dobi_npc_dialog로 복사하면 git에 부적합 + 데이터 중복. vic_pinky는 자체 git이라 우리 moca git과 무관.
- **토폴로지**:
  ```
  BT (IceBreak/Offer/LeadIn) ──/dialog/request──▶ persona_manager
                                                      ├──/dialog/utter──▶ TTS (③)
                                                      └──/face_avatar/expression──▶ face_avatar_node (④)
  ```
  BT는 변경 없음. persona_manager가 phrase + face를 동시 발행.

### Step 1: pygame 설치

- `sudo apt install -y python3-pygame` → pygame 2.5.2 (SDL 2.30.0)
- mediapipe와 달리 transitive 충돌 없음 (SDL2 binding만, numpy/cv2 의존성 없음)
- 격리 셸 검증: `rclpy + pygame + mediapipe` 모두 import OK

### Step 2: face_avatar_node.py 작성

핵심 구조:
- `pygame.init()` + 풀스크린/윈도우 모드
- 8 GIF 미리 로드 + `_fit_to_screen` (aspect 보존 smoothscale)
- `/face_avatar/expression` (std_msgs/String) 구독
- ROS spin + pygame event loop 통합:
  ```python
  while running:
      rclpy.spin_once(self, timeout_sec=0.0)  # non-blocking
      for event in pygame.event.get():
          # ESC 종료, 1~8 키 수동 표정 전환
      if dirty:
          self._render(); dirty = False
      self.clock.tick(30)
  ```
- 견고한 main() (CLAUDE.md §5.1)
- 마우스 커서 자동 숨김

### Step 3: persona_manager 확장

`_handle_request`에 face_expression 동시 발행 추가:
- 새 publisher: `self.face_pub_ = self.create_publisher(String, '/face_avatar/expression', 10)`
- 새 헬퍼: `_pick_face_expression(stage_id)` — 페르소나 YAML의 `face_expression[stage_id]` lookup
- phrase와 face를 같은 콜백에서 발행 (race 없음)

### Step 4: setup.py / package.xml 갱신

- entry_point: `face_avatar = dobi_npc_dialog.face_avatar_node:main`
- `<depend>python3-pygame</depend>` + `python3-pil` + `python3-numpy` (시스템 apt)

### Step 5: 빌드 + 자체 검증

빌드 통과 (1.4s). `face_avatar` entry_point 등록 확인.

자체 검증:
- 윈도우 모드 640x480 → 8 GIF 로드, 5 표정 전이 정상, 잘못된 expression에 warn
- persona_manager 통합 → casual_browser/friendly_child 페르소나별 face_expression 정확히 발행 (`fun`/`happy`/`fun` 매핑 검증)

### Step 6: 사용자 라이브 검증 — 함정 2건 발견

#### 함정 6.1: 풀스크린이 작은 윈도우로 떨어짐 (스크린샷 `docs/daily/assets/dobi_npc_face_avatar.png`)

**증상**: `fullscreen=True` (default)로 실행했는데 약 350x300 작은 윈도우로 뜸.

**원인**: `pygame.display.set_mode((0, 0), pygame.FULLSCREEN)` — `(0, 0)` 사이즈는 풀스크린 성공 시에만 의미. 풀스크린 실패 시 default 작은 윈도우로 fallback.

**해결**:
```python
info = pygame.display.Info()
sw, sh = info.current_w, info.current_h
try:
    self.screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
except pygame.error:
    self.screen = pygame.display.set_mode((sw, sh), pygame.NOFRAME)  # borderless fallback
```
- 데스크톱 해상도(1920x1080)를 명시적으로 가져와 set_mode에 전달
- FULLSCREEN 실패 시 NOFRAME(borderless) fallback
- 사용자 환경: X11 (XDG_SESSION_TYPE=x11). 그래도 (0, 0) 트릭은 신뢰성 낮음.

#### 함정 6.2: hello.gif가 검은 화면 ("2번 키 표정만 안 보임")

**증상**: 풀스크린에서 1~8 키로 표정 전환했는데 2번(hello)만 화면에 안 보임. 다른 7개는 정상.

**원인**: `pygame.image.load()`는 GIF의 **첫 프레임만** 로드. hello.gif는 fade-in으로 시작해서 첫 프레임이 완전 검정(평균 RGB = 0.0). 다른 GIF들은 첫 프레임이 30~46.

분석:
```python
# pygame.image.load 후 평균 픽셀 brightness
basic       1000x750  mean RGB= 43.2
hello       1000x750  mean RGB=  0.0   ← fade-in 시작
happy       1000x750  mean RGB= 40.4
fun         1000x750  mean RGB= 43.1
interest    1000x750  mean RGB= 46.0
bored       1000x750  mean RGB= 31.1
sad         1000x750  mean RGB= 40.4
angry       1000x750  mean RGB= 29.4
```

**해결**: Pillow로 모든 프레임 enumerate → 평균 RGB 최대 프레임 자동 선택.

```python
from PIL import Image, ImageSequence
img = Image.open(path)
best = None
best_brightness = -1.0
for frame in ImageSequence.Iterator(img):
    rgba = frame.convert('RGBA')
    brightness = float(np.asarray(rgba)[..., :3].mean())
    if brightness > best_brightness:
        best_brightness = brightness
        best = rgba.copy()
return pygame.image.fromstring(best.tobytes(), best.size, best.mode)
```

수정 후 brightness:
```
basic    160 frames, brightest 43.2
hello     82 frames, brightest 43.1   ← 0.0 → 43.1 (정상)
happy     68 frames, brightest 40.4
fun       76 frames, brightest 43.1
interest  82 frames, brightest 47.5
bored    110 frames, brightest 31.1
sad      132 frames, brightest 41.1
angry     60 frames, brightest 30.8
```

추가 의존성: `python3-pil` (시스템 Pillow 10.2.0, apt 기본 설치).

#### 함정 6.3: 좀비 노드 폭격 ("1~8 키가 골고루 안 바뀜")

**증상**: 풀스크린에서 1~8 키 눌러도 fun/happy 표정만 반복.

**원인**: 검증 스크립트들이 백그라운드 PID를 capture했지만 wait이 누락되거나 launch 자식 프로세스가 살아남아 좀비 6마리가 누적:
- geva_node × 1, rapport_tracker × 1
- bt_executor × 2 (`ros2 launch`로 띄운 것)
- persona_manager × 2

좀비 bt_executor가 매 100ms tick마다 IceBreak/Offer/LeadIn을 publish → 좀비 persona_manager가 받아서 face_expression 발행 → 사용자 키 입력이 즉시 덮어씌워짐.

**해결**: `pkill -TERM -f "bt_executor|persona_manager|face_avatar|geva_node|rapport_tracker"` + SIGKILL fallback. 좀비 정리 후 사용자가 1~8 키로 8 표정 모두 정상 전환 확인.

**향후 예방**:
- `ros2 launch` 대신 `ros2 run`으로 직접 띄울 것 (launch는 자식 프로세스 lifecycle 관리가 까다로움)
- Bash 검증 스크립트에서 `kill $PID; wait` 누락 금지
- 검증 종료 시 항상 `pgrep`으로 잔존 확인

---

## 2. 핵심 학습 (개념 정리)

### pygame + ROS 통합 패턴

```python
while running and rclpy.ok():
    rclpy.spin_once(self, timeout_sec=0.0)  # non-blocking
    for event in pygame.event.get():
        ...
    if dirty:
        self._render()
    self.clock.tick(30)
```

- pygame이 main loop 소유 → 키보드/창 이벤트 즉시 반응
- ROS spin은 매 프레임 1회 non-blocking 호출 → 콜백 처리
- `dirty` 플래그로 불필요한 re-render 회피 (표정 변화 시에만 화면 갱신)
- `clock.tick(30)`으로 30fps cap (CPU 절약)

대안 (더 복잡): 별도 thread에서 `rclpy.spin(node)`. 단점은 pygame이 thread-safe하지 않아 UI 호출이 main thread에 한정되는 점.

### GIF 첫 프레임 함정 일반화

**`pygame.image.load(gif_path)`는 첫 프레임만 가져온다**. 첫 프레임이 fade-in/transparent intro이면 의도와 다른 결과. **모든 GIF 자산을 검수해야 함**:

1. 모든 프레임 enumerate (Pillow `ImageSequence.Iterator`)
2. brightness/saliency 기반 자동 선택 (현재 v1 방식)
3. 또는 모든 프레임을 list로 보관 + 30fps 애니메이션 재생 (v2, Phase 후속)

vicpinky 자산은 PinkyPro LCD에서 애니메이션으로 사용되도록 설계. 노트북 풀스크린에서도 진짜 자연스러우려면 v2 (애니메이션 재생)가 필요하나, v1은 정착 표정 1프레임이 충분.

### 풀스크린 신뢰성

`(0, 0)` 사이즈로 FULLSCREEN flag를 보내는 패턴은 **풀스크린 실패 시 silent fallback**. SDL2/pygame의 일반적 패턴:

```python
info = pygame.display.Info()
sw, sh = info.current_w, info.current_h
try:
    screen = pygame.display.set_mode((sw, sh), pygame.FULLSCREEN)
except pygame.error:
    screen = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
```

명시적 데스크톱 크기 + fallback이 환경 차이(X11/Wayland/Xinerama 등)에 강건.

### ROS launch의 자식 프로세스 lifecycle

`ros2 launch xxx.launch.py`는 launch_ros가 자식 노드를 spawn. 부모 launch 프로세스에 `kill -TERM`을 보내도 자식 노드는 살아남는 경우가 많음. SIGINT(`-INT`)를 보내야 launch_ros가 자식까지 정리. 그래도 누락되면 좀비.

검증 스크립트 권장 패턴:
```bash
ros2 run pkg node > /tmp/log 2>&1 &
PID=$!
... 검증 ...
kill -INT $PID 2>/dev/null
wait $PID 2>/dev/null
# 추가 안전장치
pgrep -af "node_name" | grep -v grep && pkill -KILL -f "node_name"
```

---

## 3. 발견 / 위험 요소 / 갭

### 발견

- **vicpinky 자산 직접 참조의 가치**: 33MB를 dobi_npc_dialog로 복사하지 않고 vicpinky_emotion에서 직접 참조. 단일 진실 원본 유지 + git 무관. vic_pinky가 자체 git이라 우리 moca git이 자산 무게에서 자유로움.
- **face_expression deep_merge 정상 작동 확인**: friendly_child가 `face_expression: {icebreak: fun, offer: happy, leadin: fun}`을 정확히 override (generic의 hello/interest/happy를 가림). Phase 1 W3에서 만든 deep_merge 로직이 face_expression dict에도 잘 적용됨.
- **persona_manager의 단일 콜백에서 phrase+face 동시 발행**: 두 토픽 발행이 같은 `_handle_request`에서 일어나므로 race 없음. TTS와 face가 시각/청각 channel에서 동기화됨.

### 위험 요소

- **GIF 정적 1프레임의 한계**: 표정이 살아있는 느낌이 약함. v2 애니메이션 재생이 자연스러움 + 카페 손님에게 더 친근.
- **풀스크린 환경 종료 어려움**: ESC만 종료. 운영 시 사용자가 키보드 접근 못 하면 노드 외부 종료 필요. SIGTERM/SIGINT로 정상 종료되도록 견고한 main() 패턴은 이미 적용됨.
- **다중 monitor 미고려**: `pygame.display.Info()`는 primary monitor만 반환. 카페 매장에 외부 디스플레이 연결 시 모니터 선택 파라미터 필요 (Phase 4).
- **SDL_VIDEODRIVER 환경 의존**: 우리 검증은 X11. Wayland 환경에서 풀스크린이 다르게 동작할 가능성. CLAUDE.md §3에 환경 가정 추가 검토.
- **GIF 크기 33MB**: vic_pinky 자체 git에 보존. moca 외 사용자가 워크스페이스를 clone하면 vic_pinky vcs import + 자체 git pull 필요. README 갱신 필요.

### 갭

- **face_avatar의 단위 테스트 부재**: pygame이 디스플레이 의존이라 headless 단위 테스트 까다로움. SDL_VIDEODRIVER=dummy로 가능하지만 v1은 미적용.
- **계획서 Phase 2 W4의 GEFA(자세/접근/회피)는 RPi 부재로 미수행** — W4.5 별도 트랙으로 보류.

---

## 4. 다음 일정

### 노트북 단독 트랙 (사용자 합의 순서)

- ✅ ① GEVA — `2026-05-02_phase2_w4_geva.md`
- ✅ ② EmotionMonitor BT 통합 — `2026-05-02_phase2_w4_emotion_monitor.md`
- ✅ ④ 노트북 풀스크린 face_avatar GUI — 본 회고
- 🔜 **③ TTS 노드** — `/dialog/utter` 구독 → 음성 출력. 엔진 결정 필요 (espeak-ng / piper / Google TTS / Edge TTS 등)

### Phase 2 W4 잔여 (소규모)

- [ ] **사용자 라이브 표정 검증**: 카메라 앞에서 happy/sad/angry/fear 짓고 (geva → tracker → emotion_monitor → root abort) + (persona_manager → face_avatar) 전체 사슬을 한 번에 시각 확인.
- [ ] **GIF 애니메이션 v2** (선택): Pillow로 모든 프레임 추출 + 30fps 재생. 표정에 생동감 추가.
- [ ] **다중 monitor 파라미터** (선택): 외부 디스플레이 사용 시 monitor index 선택.

### RPi 확보 시 (별도 트랙)

- W2.5: vic_pinky RPi 5 셋업, 카메라 2 raw publisher, vcs import 후 vic_pinky 자체 git에서 face GIF 자산 동기화
- W4.5: GEFA → decision_rule_node fusion

---

## 5. 산출물 위치

### 신규 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/face_avatar_node.py` (200줄, pygame + Pillow brightest-frame)

### 수정 파일
- `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/persona_manager_node.py` (face_pub_ + _pick_face_expression 추가)
- `src/dobi_npc/dobi_npc_dialog/setup.py` (entry_point face_avatar)
- `src/dobi_npc/dobi_npc_dialog/package.xml` (depend: python3-pygame, python3-pil, python3-numpy)

### 변경 없음
- vicpinky_emotion 자산 8 GIF — 직접 참조 (gif_dir 파라미터 기본값)
- BT 노드 / cafe_funnel_v1.xml — 변경 없음

### 다음 커밋
- W4 face_avatar 산출물 + 본 회고 단일 커밋

---

## 6. 빌드/실행 검증 명령어 (재현용)

### 0회차 환경 셋업 (1회)
```bash
sudo apt install -y python3-pygame python3-pil python3-numpy
# (mediapipe는 GEVA 회고 참조)
```

### 빌드
```bash
env -i HOME=$HOME PATH=/usr/bin:/bin bash --noprofile --norc -c '
  source /opt/ros/jazzy/setup.bash
  cd ~/moca
  colcon build --packages-select dobi_npc_dialog --symlink-install
'
```

### 실행 (단독 — 키보드 1~8 수동 검증)
```bash
source /opt/ros/jazzy/setup.bash
source ~/moca/install/setup.bash
ros2 run dobi_npc_dialog face_avatar
# 기대 로그: FULLSCREEN mode: <해상도>, loaded 8/8 expressions
# 1~8 키: basic / hello / happy / fun / interest / bored / sad / angry
# ESC: 종료
```

### 실행 (페르소나 통합)
```bash
ros2 run dobi_npc_dialog face_avatar &
ros2 run dobi_npc_dialog persona_manager &
ros2 service call /set_persona dobi_npc_msgs/srv/SetPersona "{persona_name: friendly_child}"
ros2 topic pub --once /dialog/request std_msgs/String "{data: 'icebreak'}"
# face가 'fun'으로 전환됨 (friendly_child의 face_expression.icebreak)
```

### 옵션
```bash
# 윈도우 모드 (디버깅)
ros2 run dobi_npc_dialog face_avatar --ros-args -p fullscreen:=false -p window_width:=800 -p window_height:=600

# 자산 디렉토리 변경
ros2 run dobi_npc_dialog face_avatar --ros-args -p gif_dir:=/path/to/other/gifs

# 토픽 변경 (멀티-디스플레이 시)
ros2 run dobi_npc_dialog face_avatar --ros-args -p topic:=/face_avatar/secondary
```

### 좀비 정리 (검증 후)
```bash
pkill -TERM -f "bt_executor|persona_manager|face_avatar|geva_node|rapport_tracker"
sleep 1
pkill -KILL -f "bt_executor|persona_manager|face_avatar|geva_node|rapport_tracker" 2>/dev/null
pgrep -af "bt_executor|persona_manager|face_avatar|geva_node|rapport_tracker" | grep -v grep || echo "모두 정리됨"
```

---

**상태**: ④ face_avatar 완료. 풀스크린 1920x1080 + 1~8 키 + persona 통합 모두 검증. 다음은 ③ TTS — 엔진 결정 필요.
