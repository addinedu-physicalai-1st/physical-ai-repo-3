# 카메라 2/3 모델 스왑 + 코드 patch + SoT 정정

**작성일**: 2026-05-06
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "카메라 3 추가 결정 (2026-05-05)" 의 코드 patch 적용 + SoT `docs/cafe_npc_camera_architecture.md` §3·§3.5 정정
**커밋**: 후속
**상태**: 카메라 3 (RPC-20F, 노트북 USB 외장) 물리 연결 + game.py 3종 + minigame_runner + geva_node 코드 patch 적용 + SoT 문서 §3 (카메라 2 = HCAM01N) / §3.5 (카메라 3 = RPC-20F) 일괄 정정. 라이브 cycle 검증 (`sim_funnel_demo.launch.py`) 통과.

---

## 0. 시작 컨텍스트

전 세션 (2026-05-05) 까지:
- Phase 3 미니게임 3종 (RPS / Speed Counter / Cafe Ninja) PlayWait subprocess wrapper 통합 완료
- minigame_runner 가 `/face_avatar/suspend|resume` + `/geva/suspend|resume` 로 카메라 1 (GEVA) 양보
- 단일 카메라 정책의 Salichs 2014 학술 정합 위반 식별 (게임 ~30~50초 동안 GEVA 정지 → abort_trigger 발동 불가)
- 카메라 3 추가 결정 (`docs/cafe_npc_camera_architecture.md` §3.5) — 노트북 USB 외장 1대로 게임 손 인식 분리. 모델은 보유 자산 HCAM01N 재활용 가정

본 세션 시작 시 사용자 보고: **카메라 2/3 물리 모델 스왑** —
- RPi 직결 (카메라 2): RPC-20F → **HCAM01N 으로 원복**
- 노트북 외장 (카메라 3): HCAM01N → **RPC-20F "RF20" 로 변경**

이유: RPC-20F 의 autofocus continuous + 1080p 능력이 close-range (0.3~0.8m) 손 인식에 더 적합. RPi follow 는 HCAM01N 고정초점으로 검증된 `run_robot_cam.sh` 그대로 사용 가능.

---

## 1. SoT 우선 갱신 (memory + CLAUDE.md TODO)

물리 변경 보고 받자마자:

1. `~/.claude/.../memory/project_camera_architecture.md` — description + 본문 + 4축 분리표 갱신. 카메라 2 = HCAM01N (`0c45:6367`), 카메라 3 = RPC-20F (`1bcf:2281`, autofocus). 모델 변천사 단락 신설 (HCAM → RPC → HCAM 원복) + follow_controller 재튜닝 필요 표시
2. `CLAUDE.md` §10 카메라 아키텍처 갱신 절 — 카메라 2/3 모델 스왑 결정 한 줄 추가, 카메라 3 코드 patch 항목 신설, follow_controller 재튜닝 항목 신설, 마지막 갱신 일자 라인 갱신

코드 patch 진입 전 SoT 먼저 잠그는 패턴 — 작업 도중 의존하는 결정이 모호하면 안 됨.

---

## 2. 카메라 3 코드 patch (commit 후속)

### 2.1 game.py 3종 — `--camera-index` argparse + `self.camera_index` 멤버

`games/{06_rps_evolution, 07_speed_counter, 01_cafe_ninja}/src/game.py` 동일 4 patch:

```python
# __init__ 끝
self.camera_index = 0  # PlayWait 단독 실행 시 0, moca minigame_runner 가 override

# setup() 시작
self.cap = cv2.VideoCapture(self.camera_index)  # 기존 cv2.VideoCapture(0) 교체

# main() argparse
parser.add_argument(
    "--camera-index", type=int, default=0,
    help="cv2.VideoCapture 인덱스 (기본 0=내장. moca 외장 캠은 2 등).")

# main() 인스턴스 셋업
_game_instance.camera_index = int(args.camera_index)
```

### 2.2 minigame_runner_node.py — `game_camera_index` ROS 파라미터

```python
# default 2 (UVC 외장 일반 인덱스). launch arg 로 환경별 override.
self.declare_parameter('game_camera_index', 2)
self._game_camera_index = int(self.get_parameter('game_camera_index').value)

# subprocess cmd 끝에 추가
"--camera-index", str(self._game_camera_index),

# /geva/suspend + /geva/resume publisher + topic 파라미터 일괄 제거
# /face_avatar/suspend|resume 는 디스플레이 양보 위해 유지
```

docstring 헤더 갱신 — 카메라 분리 정책 (게임 중에도 GEVA 가동) + Salichs 2014 학술 정합 회복 명시.

### 2.3 geva_node.py — suspend/resume subscriber 폐기

- `from std_msgs.msg import Empty` import 제거
- `suspend_topic` / `resume_topic` 파라미터 + `_suspended` 플래그 + `_on_suspend`/`_on_resume` 메서드 + subscriber 일괄 제거
- `_tick()` 의 `if self._suspended or self.cap is None:` → `if self.cap is None:` 단순화

### 2.4 mode_npc.launch.py — `game_camera_index` launch arg 노출

```python
from launch_ros.descriptions import ParameterValue

game_camera_index_arg = DeclareLaunchArgument(
    'game_camera_index', default_value='2', ...)

Node(
    ...,
    parameters=[{
        'game_camera_index': ParameterValue(
            LaunchConfiguration('game_camera_index'),
            value_type=int),
    }],
)
```

`ParameterValue(value_type=int)` wrap 이유: `LaunchConfiguration` 은 substitution → string 으로 들어와서 `declare_parameter('game_camera_index', 2)` (int default) 와 타입 미스매치 가능. `ParameterValue` 가 명시 cast.

### 2.5 sim_funnel_demo.launch.py — docstring 정책 반영

기존 "GEVA 웹캠과 RPS 웹캠 중복 점유 차단 동일 패턴 (/geva/suspend|resume)" → 카메라 분리 정책 + Salichs 학술 정합 회복 + 단일 카메라 회귀 시 git history 참조 안내.

---

## 3. 라이브 검증

### 3.1 카메라 인덱스 매핑 실측 (사용자 카메라 3 연결 후)

```
HD Webcam (Bison 5986:211b, 노트북 내장)        → /dev/video0
SNAP U2  (Sunplus 1bcf:2281, 노트북 외장 RPC-20F) → /dev/video2
```

기본값과 정확히 매칭 → launch arg override 불필요.

cv2.VideoCapture(0) / (2) 양쪽 isOpened + read 성공 (640×480 frame).

### 3.2 sim_funnel_demo cycle

vic_pinky 충전 중이라 휠 보호 우선. 안전 검증:
- 현재 ROS_DOMAIN_ID=22 에 노드/액션 서버 모두 비어있음 → vic_pinky RPi ROS 꺼진 상태
- Approach 는 Nav2 액션 client only — 서버 미발견 시 fallback SUCCESS, `/cmd_vel` 직접 발행 안 함
- LeadIn 은 `simulate=true` 기본 (cafe_funnel_v1.xml 명시 없음 → default)
- 추가 안전망으로 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 환경변수로 도메인 격리

```bash
source ~/moca/install/setup.bash
ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ros2 launch dobi_npc_bringup sim_funnel_demo.launch.py
```

라이브 로그 (90초 시점 점검):
- `geva_node` 10Hz, face_detected=100% — 카메라 1 안정
- IceBreak 발화 진입: `[casual_browser/icebreak/face=hello] "안녕하세요! 더운데 시원한 거 한 잔 어떠세요?"`
- `face_avatar (suspended): interest -> hello (defer render)` — 게임 진입 시 face suspend 정상
- `display resumed` — 게임 종료 후 face_avatar 풀스크린 복귀 정상
- `/cmd_vel` 토픽 미존재 — vic_pinky 휠 보호 확인

사용자 보고: **"잘 동작해"** — full funnel cycle 통과.

### 3.3 `ROS_LOCALHOST_ONLY` deprecation 처리

처음 시도 시 `ROS_LOCALHOST_ONLY=1` 사용 → ros2 jazzy 워닝:
```
[WARN] [rcl]: ROS_LOCALHOST_ONLY is deprecated but still honored if it is enabled.
              Use ROS_AUTOMATIC_DISCOVERY_RANGE and ROS_STATIC_PEERS instead.
```

→ 최종 권장 명령은 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 사용.

---

## 4. SoT 문서 정정 (`docs/cafe_npc_camera_architecture.md`)

### 4.1 §1 토폴로지 다이어그램

- RPi USB 측: "로이체 RPC-20F" → "HCAM01N (Microdia, USB 외장)"
- 노트북 측: 카메라 1 줄 아래 "[카메라 3] 외장 RPC-20F /dev/video2" 신규 행 추가

### 4.2 §3 카메라 2 (전면 재작성)

- 제목 "로이체 RPC-20F" → "HCAM01N"
- §3.1 하드웨어: 모델 = HCAM01N, 칩셋 = Microdia `0c45:6367`, 인터페이스 = RPi USB 2.0 Bus 4-1, 포커스 = 고정초점
- §3.2 영상 스펙 (신설): MJPG 1280×720 / YUYV 640×480, USB 2.0 대역폭 한계, ros-jazzy-v4l2-camera 0.7.1 의 MJPG → rgb8 cv_bridge 빈 encoding 예외 → YUYV 우회. USB auto-suspend 해제 필수
- §3.4 ROS2 인터페이스: 발행자 = `scripts/run_robot_cam.sh`, 노트북 측 사람 검출 = mediapipe efficientdet_lite0
- §3.5 BT 단계 담당: mode_follow (person_detector + follow_controller) 추가
- §3.6 Phase 4 화각 재평가: 그대로 유지 (HCAM01N 도 60~80° 추정)

문서 상단에 모델 변천 인용 (2026-05-04 HCAM → RPC → 2026-05-06 HCAM 원복) 명시 — 회고 다시 안 봐도 추적 가능.

### 4.3 §3.5 → §3.5a 카메라 3 (모델 확정 + 코드 영향 적용 완료)

- 제목 "(2026-05-05 추가 결정)" → "(2026-05-05 추가, 2026-05-06 모델 확정 + 코드 patch 적용)"
- §3.5a.2 하드웨어: TBD 전체 → RPC-20F (Sunplus SNAP U2 `1bcf:2281`), `/dev/video2`, autofocus continuous, MJPG 1920×1080 능력 명기
- §3.5a.5 코드 영향: "(적용 예정)" → "(2026-05-06 적용 완료)" + 실제 patch 5개 항목 (game.py 3종 / minigame_runner / mode_npc.launch / minigame_runner publisher 폐기 / geva_node subscriber 폐기) + 라이브 검증 명령 + 사용자 "잘 동작해" 문장

기존 §3.5 가 §3 의 하위 absolute 번호 (3.5 = "Phase 4 화각 재평가") 와 충돌해서 §3.5a 로 명명. 향후 §3.5/§3.5a 두 절은 별 논리 — Phase 4 재평가는 카메라 2 후보, §3.5a 는 카메라 3 명세.

### 4.4 §4 4축 분리표

"(신규)" 표기 제거. 모델 / 포커스 / `/dev/videoN` 행 추가 — 빠른 매핑 시 본 표만 봐도 충분.

### 4.5 §10 결정 이력

- 2026-05-04 항목 신설: HCAM01N 실측 정정 트랙 + 같은 날 RPC-20F 카메라 2 교체 시도 (autofocus 검토)
- 2026-05-06 항목 신설: 모델 스왑 확정 + 코드 patch 적용 + 라이브 cycle 검증 통과

### 4.6 §11 TODO

- 카메라 3 모델/마운트 결정 → [x] 완료
- 카메라 3 적용 후 코드 patch → [x] 완료
- 신규: follow_controller 재튜닝 (HCAM01N 화각 vs RPC-20F 화각 차이) — `2026-05-04_follow_tune_smoothing.md` 의 게인/EMA/align_gate 라이브 재검증
- 신규: 카메라 3 마운트 거치대 설계 (노트북 화면 하단 고정, 손 거리 0.3~0.8m 유지)
- 신규: MJPG 1080p 경로 복구 (v4l2_camera_node cv_bridge 우회)

### 4.7 §12 연관 문서

본 회고 + `2026-05-04_robot_cam_raw_publisher.md` + `2026-05-04_follow_tune_smoothing.md` 추가.

---

## 5. 발견 / 함정

### 5.1 launch arg 타입 캐스트

ros2 jazzy 의 `LaunchConfiguration` substitution 은 string 만 반환. `declare_parameter('game_camera_index', 2)` 가 int default 라 dict literal `{key: LaunchConfiguration(...)}` 그대로면 타입 미스매치 위험.

```python
# 안전한 패턴
'game_camera_index': ParameterValue(
    LaunchConfiguration('game_camera_index'),
    value_type=int),
```

### 5.2 ROS_LOCALHOST_ONLY deprecation

jazzy 부터 deprecated. 새 권장:
- `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` (단순 격리)
- `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` + `ROS_STATIC_PEERS=...` (peer 명시)

LOCALHOST 는 multicast 끔 + 같은 host 안 process 끼리만 통신. vic_pinky 충전 중일 때 휠 보호로 충분.

### 5.3 게임 cycle 짧게 보임 (1.5초 만에 face resume)

라이브 검증 90초 시점 로그에 face suspend → 1.5초 만에 resume 보였음. 사용자 "잘 동작해" 보고로 정상 판정 — 한 cycle 이미 끝나서 두 번째 cycle 진입 직전 잠깐 suspend 한 케이스로 추정.

후속 라이브에서 cycle 별 stage transition 로그 (BT phase change) 더 자세히 보려면:
- `bt_executor` 의 ROS log level INFO → DEBUG
- 또는 `groot` GUI 로 BT 실시간 관찰

### 5.4 SoT 절 번호 충돌

기존 SoT §3.5 = "Phase 4 화각 재평가 시 후보 (RPC-20F 광각 부족 확인 후 교체 검토용)" — RPC-20F 가 카메라 2 였을 때 의미. 이제 카메라 2 = HCAM01N 으로 바뀌었으니 §3.6 으로 번호 이동, 그리고 카메라 3 절은 §3.5a 명명.

§3.5 / §3.5a / §3.6 셋이 비교적 가까운 번호라 향후 누군가 §3.5 로 카메라 3 을 찾을 가능성. 안내가 필요하면 §3.5a 도입부에 한 줄 추가 가능 — 본 회고 작성 시점에는 SoT 본문에서 명확히 해 둠 (§3.5a 제목 = "카메라 3 — RPC-20F").

---

## 6. 변경 파일

### 6.1 코드 (5)

| 파일 | 변경 |
|---|---|
| `games/06_rps_evolution/src/game.py` | `self.camera_index=0` 멤버 + `--camera-index` argparse + `cv2.VideoCapture(self.camera_index)` |
| `games/07_speed_counter/src/game.py` | 동일 패턴 |
| `games/01_cafe_ninja/src/game.py` | 동일 패턴 |
| `src/dobi_npc/dobi_npc_minigame/dobi_npc_minigame/minigame_runner_node.py` | `game_camera_index` ROS 파라미터 (default 2) + `--camera-index` cmd 전달 + `/geva/suspend\|resume` publisher 제거 + 헤더 docstring 갱신 |
| `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py` | suspend/resume subscriber + `_on_suspend`/`_on_resume` + `_suspended` 플래그 + `from std_msgs.msg import Empty` 일괄 제거 |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_npc.launch.py` | `game_camera_index` launch arg + `ParameterValue(value_type=int)` wrap |
| `src/dobi_npc/dobi_npc_bringup/launch/sim_funnel_demo.launch.py` | docstring 카메라 분리 정책 반영 |

### 6.2 문서 (3)

| 파일 | 변경 |
|---|---|
| `docs/cafe_npc_camera_architecture.md` | §1 토폴로지 / §3 카메라 2 (HCAM01N) / §3.5a 카메라 3 (RPC-20F 확정) / §4 4축 분리표 / §10 결정 이력 / §11 TODO / §12 연관 문서 일괄 갱신 |
| `CLAUDE.md` | §10 카메라 아키텍처 갱신 절 — 모델 스왑 + 코드 patch [x] + follow 재튜닝 신규 항목 + 마지막 갱신 라인 |
| `~/.claude/.../memory/project_camera_architecture.md` | description + 모델 변천사 + 본문 카메라 2/3 명세 + 4축 분리표 |

---

## 7. 다음 / TODO

### 직후 (관련성 가까움)

- [ ] **follow_controller 재튜닝 (라이브)**: HCAM01N 화각 (60~80° 추정) vs RPC-20F 화각이 다름. `2026-05-04_follow_tune_smoothing.md` 의 게인/EMA/align_gate 라이브 재검증. vic_pinky 충전 끝나고 실 follow 모드 가동 시.
- [ ] **운영자 모니터링 UI 확장**: `web/static/operator.html` + `teleop_server.py` 확장 — V/A 차트 (Russell circumplex) + 호객 funnel 진행 + 게임 결과 + rapport 타임라인. 신규 페이지 X 기존 자산만 확장 (사용자 결정).

### Phase 후속 (먼 미래)

- [ ] **카메라 3 마운트 거치대 설계**: 노트북 화면 하단 고정, 손 거리 0.3~0.8m 유지. 카메라 1 (얼굴 정면) 화각과 분리 보장.
- [ ] **MJPG 1080p 경로 복구**: `ros-jazzy-v4l2-camera 0.7.1` cv_bridge 빈 encoding 예외 우회 (별 빌드 또는 image_transport). 카메라 2 도 카메라 3 도 1080p 능력 활용 미보유 상태.
- [ ] **카메라 3 autofocus 컨트롤 노출**: RPC-20F autofocus continuous 가 게임에 이상적. v4l2 ctrl 파라미터 노출 (`focus_auto`, `focus_absolute`).
- [ ] **decision_rule_node**: GEVA + GEFA Salichs 2014 fusion → `/emotion/state` (source="fused"). 카메라 분리 후 GEFA 채널 (RPi 카메라 2 mediapipe pose 또는 추가 분석) 도입 시 진입.

---

## 8. 한 줄 요약

> 카메라 2 (RPi) = HCAM01N 원복 / 카메라 3 (노트북 외장) = RPC-20F 신설 으로 모델 스왑 확정. game.py 3종 + minigame_runner + geva_node + mode_npc.launch.py 코드 patch 적용 (`/geva/suspend\|resume` 폐기 → 게임 중에도 GEVA 가동 → Salichs 2014 학술 정합 회복). SoT 문서 §3·§3.5·§4·§10·§11 일괄 정정. 라이브 cycle 검증 통과 (사용자 "잘 동작해"). 후속: follow_controller 재튜닝 (HCAM01N 화각 변경분) + 운영자 모니터링 UI 확장.
