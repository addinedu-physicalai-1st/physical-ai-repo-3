# 카페 호객 로봇 BT 시스템 — 단계별 구현 계획서

**작성일**: 2026-05-01
**작성자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 행위 시스템
**기반 문서**: `cafe_npc_paper_master.md` (6-Layer 학술 통합본)
**관련 프로젝트**: Dobi Barista (Vic Pinky Pro + OpenMANIPULATOR-X)
**목표**: 6-Layer 학술 척추를 실제 ROS2 시스템으로 검증 가능하게 구현
**총 기간**: 16주 (4개월) — Dobi Barista 23주 데모 일정과 정합

---

## 0. 계획서의 의도

본 계획서는 `cafe_npc_paper_master.md`의 6-Layer 학술 토대를 **실제 작동하는 ROS2 시스템**으로 옮기기 위한 실현 가능한 로드맵이다. 핵심 원칙:

1. **점진적 통합**: 각 Layer를 독립 노드로 먼저 검증 → 통합 BT로 결합
2. **기존 자산 재사용**: EyeCon v3.5(13지표 + 7감정), Vic Pinky Pro 베이스, Nav2 튜닝 결과를 활용
3. **5~10명 파일럿 검증**: Castro-González 2016 표본 규모(N=12)와 일치하는 현실적 검증
4. **Phase 단위 산출물**: 각 Phase 끝에 실행 가능한 데모 + 회고 문서

```
Phase 0 (Week 0)      → 환경 준비 / 기존 자산 정리
Phase 1 (Week 1-3)    → Layer 1·5 — BT 기본 funnel + BehaviorTree.CPP
Phase 2 (Week 4-6)    → Layer 2·3 — 감정 인식 ROS2 노드 (EyeCon 포팅)
Phase 3 (Week 7-9)    → Layer 4 — RPS 미니게임 + Polite Persona
Phase 4 (Week 10-12)  → 통합 + 5명 파일럿 테스트
Phase 5 (Week 13-16)  → Layer 6 확장 (XAI / Learning 시작)
```

---

## 1. 개발 환경과 전제 조건

### 1.1 하드웨어
- **모바일 베이스**: Vic Pinky Pro (192.168.0.138, 계정 `vic`, ROS_DOMAIN_ID=22)
- **매니퓰레이터**: OpenMANIPULATOR-X (`/dev/omx_follower`, `/dev/omx_leader`)
- **카메라** (단일 진실 원본: `docs/cafe_npc_camera_architecture.md`):
  - **카메라 1 — 노트북 내장 "HD Webcam"** (Bison `5986:211b`, MSI Bravo 17 D7VF, 1280×720@30fps MJPEG, 고정초점) — Salichs **GEVA** (근거리 표정·시선)
  - **카메라 2 — 로이체 RPC-20F** (USB 외장, vic_pinky RPi 5 USB 직결) — Salichs **GEFA** (원거리 자세·환경)
  - 천장 카메라는 **Phase 3까지 고려 없음** (Phase 4에서 로봇 위치 redundancy용으로 평가)
- **마이크**: USB 어레이 마이크 (카페 소음 환경 대응)
- **개발 PC / vic_pinky 탑재 노트북**: MSI Bravo 17 D7VF (RTX 4060 Laptop GPU, ROS_DOMAIN_ID=22)
- **디스플레이**: 노트북 화면 = 페르소나 아바타 / 미니게임 UI (기존 7인치 터치 스크린 운명 미결)

### 1.2 소프트웨어 스택
| 구성 요소 | 기술 선택 | 학술 근거 |
|---|---|---|
| BT 엔진 | **BehaviorTree.CPP 4.x** | Marzinotto 2014, Iovino 2022 |
| BT 시각화 | **Groot2** | Isla 2005 디버깅 철학 |
| ROS 미들웨어 | **ROS2 Jazzy + Zenoh** | 기존 Pinky 환경 |
| 감정 인식 | **EyeCon v3.5 포팅** | Salichs 2014 GEFA+GEVA |
| 네비게이션 | **Nav2 (튜닝 완료본 재사용)** | 기존 튜닝 결과 활용 |
| LLM (선택) | **Ollama EXAONE 7.8B** | 페르소나 발화 생성 (제한적) |
| 코드 언어 | **C++ (BT 노드) + Python (감정/대화)** | BehaviorTree.CPP 표준 |

### 1.3 기존 자산 매핑 (재사용 우선)

| 기존 프로젝트 | 재사용 부분 | 용도 |
|---|---|---|
| **EyeCon v3.5** | 13지표 + 7감정 + 라다 차트 | 감정 인식 노드 코어 |
| **Pinocchio (피노키오)** | 4-패널 대시보드 + LLM 대화 전략 | Decision Rule 참고 |
| **Pinky Nav2 튜닝** | costmap, planner 파라미터 | 호객 시 안전 이동 |
| ~~**dalimi_gazebo_teleop**~~ | ~~천장 카메라 + AprilTag pose~~ | **제외** (맵 좌표계 불일치) |
| **GHOST-5** | 모듈식 노드 구조 | ROS2 패키지 골격 |
| **Home Guard Bot** | LLM + ROS2 Jazzy 통합 패턴 | 대화 노드 골격 |

---

## 2. Phase 0: 환경 준비 (Week 0 — 사전 1주)

### 2.1 목표
실제 코드 작성 전, 워크스페이스와 의존성을 정리하고 6-Layer 매핑을 코드 골격으로 변환.

### 2.2 작업 항목

**(1) 워크스페이스 생성**
```bash
mkdir -p ~/dev_ws/dobi_npc_ws/src
cd ~/dev_ws/dobi_npc_ws/src
ros2 pkg create --build-type ament_cmake dobi_npc_bt        # BT 노드 (C++)
ros2 pkg create --build-type ament_python dobi_npc_emotion  # 감정 인식
ros2 pkg create --build-type ament_python dobi_npc_dialog   # 대화/페르소나
ros2 pkg create --build-type ament_python dobi_npc_minigame # RPS 미니게임
ros2 pkg create --build-type ament_cmake dobi_npc_msgs      # 커스텀 메시지
ros2 pkg create --build-type ament_python dobi_npc_bringup  # launch 파일
```

**(2) BehaviorTree.CPP + Groot2 설치 검증**
```bash
sudo apt install ros-jazzy-behaviortree-cpp
# Groot2 AppImage 다운로드 후 실행 테스트
```

**(3) 커스텀 메시지 정의 (`dobi_npc_msgs/msg/`)**
- `EmotionState.msg` — valence, arousal, confidence, source
- `RapportEvent.msg` — event_type, weight, timestamp
- `PersonaCommand.msg` — phrase_id, gesture_id, emotion_target
- `MinigameResult.msg` — game_id, winner, rounds, duration

**(4) 깃 저장소 초기화 + CLAUDE.md 작성**
- `~/dev_ws/dobi_npc_ws/CLAUDE.md`: 프로젝트 컨텍스트, 6-Layer 매핑, 디버깅 규칙
- `.gitignore`, `README.md` (논문 6편 출처 명시)

### 2.3 산출물
- [x] 워크스페이스 빌드 성공 (`colcon build`)
- [x] Groot2로 빈 BT XML 시각화 가능
- [x] CLAUDE.md, README.md 커밋

### 2.4 확인 기준
```bash
cd ~/dev_ws/dobi_npc_ws && colcon build && source install/setup.bash
ros2 pkg list | grep dobi_npc  # 6개 패키지 확인
```

---

## 3. Phase 1: BT 기본 Funnel 구현 (Week 1-3)

**대응 학술 Layer**: Layer 1 (Isla 2005), Layer 5 (Marzinotto 2014)

### 3.1 목표
감정 인식 없이도 작동하는 **5-stage funnel BT**를 BehaviorTree.CPP로 구현. 모든 호객 의사결정의 골격이 됨.

### 3.2 BT 구조 설계

```
RootSequence
├── Fallback (priority safety)
│   ├── SafetyCheck       ← Marzinotto 형식 보장 (가장 왼쪽)
│   └── Sequence (호객 funnel)
│       ├── IdleScan          [Stage 1] 고객 후보 탐지
│       ├── Approach          [Stage 2] Proxemic 거리로 접근
│       ├── IceBreak          [Stage 3] 인사 발화
│       ├── Minigame          [Stage 4] RPS (Phase 3에서 채움)
│       ├── Offer             [Stage 5] 메뉴 제안
│       └── LeadIn            [Stage 6] 카운터로 안내
└── EmotionMonitor (Parallel — Phase 2에서 활성화)
```

### 3.3 Week별 작업 분해

#### **Week 1**: 노드 인터페이스 + 더미 구현
- [ ] BT 노드 6개 C++ 클래스 골격 (`SafetyCheck`, `IdleScan`, `Approach`, `IceBreak`, `Minigame`, `Offer`, `LeadIn`)
- [ ] 각 노드는 `tick()`에서 `SUCCESS` 반환하는 더미 구현
- [ ] `cafe_funnel_v1.xml` BT XML 작성 + Groot2 검증
- [ ] launch 파일: `bt_executor` 단독 실행 → 콘솔 로그로 흐름 확인

```cpp
// 예시: IceBreak.hpp
class IceBreak : public BT::SyncActionNode {
public:
  IceBreak(const std::string& name, const BT::NodeConfiguration& config);
  static BT::PortsList providedPorts() {
    return { BT::InputPort<std::string>("phrase_pool_id") };
  }
  BT::NodeStatus tick() override;
};
```

#### **Week 2**: Approach 노드를 Nav2와 연결
- [ ] `Approach` 노드를 Nav2 Action Client로 변환
- [ ] **Proxemic 거리 정의**: 사회적 거리 1.2m → 1.5m (한국 카페 기준)
- [ ] **`/customer_pose` (geometry_msgs/PoseStamped) 구독 → Nav2 goal로 변환**
  - W2 개발: fake publisher (노트북 내장 웹캠 또는 임의 좌표) 사용
  - Phase 2 이후: 카메라 2 (RPC-20F GEFA) → 사람 검출 → pose 발행
- [ ] **abort 시나리오**: 고객이 1.0m 이내로 접근하면 즉시 정지

```python
# 사회적 거리 표 (Hall 1966 기반, 한국 문화 보정)
SOCIAL_DISTANCE = {
  'public': 3.7,      # 무관계
  'social': 1.5,      # 호객 시작 거리 (1.2m가 너무 가까운 한국 보정)
  'personal': 0.8,    # 미니게임 거리
  'intimate': 0.45,   # 절대 진입 금지
}
```

#### **Week 3**: 페르소나 상속 + Phrase Pool
- [ ] `DobiBaristaGenericPersona` 베이스 클래스 (YAML 정의)
- [ ] 3개 자식 페르소나: `FriendlyChild`, `ProfessionalAdult`, `CasualBrowser`
- [ ] **Phrase Pool 구조**: 한국어 + 영어 각 3개씩, polite tone 통일

```yaml
# personas/casual_browser.yaml
parent: generic
icebreak_phrases:
  ko:
    - "안녕하세요! 오늘 어떤 음료가 끌리세요?"
    - "더운데 시원한 거 한 잔 어떠세요?"
    - "잠깐 시간 되시면 게임 한 판 하실래요?"
  en:
    - "Hello! What kind of drink are you in the mood for today?"
approach_distance: 1.5
abort_threshold:
  customer_walks_away: 0.5
  customer_silence_sec: 8
```

### 3.4 Phase 1 산출물
- [ ] `dobi_npc_bt` 패키지 — 6개 BT 액션 노드 (C++)
- [ ] `cafe_funnel_v1.xml` — Groot2로 시각화 가능
- [ ] `personas/` — YAML 3종 + loader Python 모듈
- [ ] **데모 영상**: 빈 카페에서 Pinky가 가짜 고객(마네킹)에게 접근→인사→retreat
- [ ] `phase1_retrospective.md` — 회고 문서

### 3.5 Phase 1 검증 기준
| 항목 | 기준 |
|---|---|
| BT 실행 안정성 | 100회 tick 중 crash 0회 |
| Approach 안전 정지 | 1.0m 이내 인간 감지 시 5 tick 이내 정지 |
| 페르소나 전환 | rosparam으로 3종 페르소나 즉시 전환 |
| Groot2 디버깅 | 모든 노드 status 실시간 시각화 |

### 3.6 위험 요소와 대응
- **Risk**: BehaviorTree.CPP 4.x와 ROS2 Jazzy의 호환성 이슈
  - **대응**: 4.8.3 버전 고정 (Jazzy 공식 빌드 `ros-jazzy-behaviortree-cpp 4.8.3-1noble`). 4.9.0 업그레이드는 보류 (검증 시간 부족)
- **Risk**: Nav2 goal 보내고 도달 전에 BT가 다음 노드로 넘어감
  - **대응**: `Approach`를 `StatefulActionNode`로 구현 (`onRunning` 패턴)

---

## 4. Phase 2: 감정 인식 ROS2 노드 (Week 4-6)

**대응 학술 Layer**: Layer 2 (Russell 1980), Layer 3 (Salichs 2014)

### 4.1 목표
EyeCon v3.5의 13지표 + 7감정을 ROS2 노드로 포팅하고, **Russell 차원 모델 (V, A)**로 변환. Salichs **GEFA+GEVA Decision Rule** 구현.

### 4.2 노드 구조

```
┌─────────────────────────┐  ┌─────────────────────────┐
│ gefa_node               │  │ geva_node               │
│ (얼굴 분석)              │  │ (음성 분석)              │
│                         │  │                         │
│ - MediaPipe Face Mesh   │  │ - librosa pitch         │
│ - 7-emotion classifier  │  │ - speech rate           │
│ - confidence            │  │ - prosody features      │
└──────────┬──────────────┘  └──────────┬──────────────┘
           │ /emotion/face                │ /emotion/voice
           │ (EmotionState)               │ (EmotionState)
           ▼                              ▼
    ┌──────────────────────────────────────────┐
    │ valence_arousal_mapper_node              │
    │  - 7-emotion → (V, A) 좌표 변환          │
    │  - Russell 1980 표준 매핑                 │
    └──────────────────┬───────────────────────┘
                       │ /emotion/va_individual (양 채널 분리)
                       ▼
    ┌──────────────────────────────────────────┐
    │ decision_rule_node (Salichs 2014)        │
    │  - 두 채널 일치/불일치 판정              │
    │  - confidence 가중 평균                  │
    │  - 거짓 긍정 감지 (face=happy, voice=tense)│
    └──────────────────┬───────────────────────┘
                       │ /emotion/fused (V, A, conf, flags)
                       ▼
    ┌──────────────────────────────────────────┐
    │ rapport_tracker_node                     │
    │  - 시간적 trend 계산 (Russell 연속성)     │
    │  - rapport_event 발행                     │
    └──────────────────┬───────────────────────┘
                       │ /rapport/events
                       ▼
                BT의 `EmotionMonitor`
```

### 4.3 Week별 작업 분해

#### **Week 4**: GEFA 노드 (얼굴 분석)
- [ ] EyeCon v3.5의 facial expression 모듈을 ROS2 노드로 분리
- [ ] `/dev/video2` 입력 → `/emotion/face` 발행 (10Hz)
- [ ] 7-emotion 출력: happy, sad, angry, surprise, disgust, neutral, bored
- [ ] **AWB warmup 5프레임** (Pinky 카메라 경험에서 확립)
- [ ] **거리 적응**: 0.8m 이내에서만 신뢰도 > 0.6

#### **Week 5**: GEVA 노드 (음성 분석) + V-A 매퍼
- [ ] librosa로 pitch, intensity, speech rate 추출
- [ ] 카페 소음 대응: VAD(Voice Activity Detection) 우선 적용
- [ ] **Russell 매핑 테이블** 구현:

```python
# valence_arousal_mapper_node.py
EMOTION_TO_VA = {
    # (valence, arousal) — Russell 1980 표준 좌표
    'happy':    ( 0.8,  0.5),   # 우상단
    'excited':  ( 0.6,  0.9),   # 우상단 끝
    'relaxed':  ( 0.7, -0.4),   # 우하단
    'neutral':  ( 0.0,  0.0),   # 원점
    'bored':    (-0.3, -0.6),   # 좌하단
    'sad':      (-0.7, -0.5),   # 좌하단
    'angry':    (-0.8,  0.7),   # 좌상단 ← abort 트리거
    'disgust':  (-0.6,  0.4),   # 좌상단 ← abort 트리거
    'surprise': ( 0.2,  0.8),   # 상단 (양가성)
}

def to_va(emotion: str, confidence: float) -> tuple:
    v, a = EMOTION_TO_VA[emotion]
    # confidence가 낮으면 원점 쪽으로 끌어당김
    return (v * confidence, a * confidence)
```

#### **Week 6**: Decision Rule + Rapport Tracker
- [ ] **Salichs Decision Rule** 구현:

```python
# decision_rule_node.py
def fuse(face: EmotionState, voice: EmotionState) -> dict:
    """Salichs 2014 GEFA+GEVA 융합 규칙."""
    # 1. 한 채널 신뢰도가 매우 낮으면 → 다른 채널만 사용
    if face.confidence < 0.3:
        return {'va': voice.va, 'conf': voice.confidence * 0.7, 'flags': ['voice_only']}
    if voice.confidence < 0.3:
        return {'va': face.va, 'conf': face.confidence * 0.7, 'flags': ['face_only']}

    # 2. 일치 검사
    similarity = cosine_similarity(face.va, voice.va)
    if similarity > 0.7:
        # 두 채널 일치 → 신뢰도 부스트
        fused_va = weighted_avg(face, voice)
        return {'va': fused_va, 'conf': max(face.conf, voice.conf), 'flags': ['agree']}

    # 3. 불일치 (incongruence) → 거짓 긍정 의심
    if face.emotion == 'happy' and voice.emotion in ('tense', 'sad', 'angry'):
        return {'va': voice.va, 'conf': 0.5, 'flags': ['mask_smile', 'social_response']}

    # 4. 일반 충돌 → confidence 가중 평균, 신뢰도 ↓
    fused_va = weighted_avg(face, voice)
    return {'va': fused_va, 'conf': min(face.conf, voice.conf) * 0.6, 'flags': ['conflict']}
```

- [ ] `rapport_tracker_node`: 5초 슬라이딩 윈도우로 V-A trend 계산
- [ ] `EmotionMonitor` BT 노드 (Parallel) 구현 → Phase 1 BT에 통합
- [ ] **abort 트리거 규칙**:
  - V < -0.5 AND A > 0.4 (좌상단: 분노/혐오) → 즉시 abort
  - 'mask_smile' flag → rapport weight 0.5배

### 4.4 Phase 2 산출물
- [ ] `dobi_npc_emotion` 패키지 — 4개 노드
- [ ] `valence_arousal_mapper_node` 단위 테스트 (28개 감정 단어 좌표 검증)
- [ ] **데모**: 본인이 의도적으로 happy/angry/bored 표현 → 4-패널 시각화 (EyeCon 재사용)
- [ ] `phase2_retrospective.md`

### 4.5 Phase 2 검증 기준
| 항목 | 기준 |
|---|---|
| GEFA 정확도 | 본인 데이터 50샘플에서 70% 이상 (lab 환경) |
| GEVA 정확도 | 본인 데이터 50샘플에서 60% 이상 |
| 융합 후 정확도 | GEFA·GEVA 단독보다 5%p 이상 향상 ← Salichs 핵심 발견 검증 |
| abort 응답 시간 | 분노 표현 후 abort 트리거까지 1.5초 이내 |
| 거짓 긍정 감지 | 가짜 웃음(face=happy, voice=tense) 시나리오 80% 감지 |

### 4.6 위험 요소와 대응
- **Risk**: 카페 소음으로 GEVA 신뢰도 지속 낮음
  - **대응**: VAD 임계값을 환경별 자동 캘리브레이션 (시작 5초 ambient noise 측정)
- **Risk**: 7-emotion 분류기가 한국인 얼굴에 정확도 낮음
  - **대응**: 본인+동료(6명) 데이터 200샘플로 fine-tuning (이미 ST-GCN 경험 있음)

---

## 5. Phase 3: RPS 미니게임 + Polite Persona (Week 7-9)

**대응 학술 Layer**: Layer 4 (Castro-González 2016)

### 5.1 목표
가위바위보 미니게임을 Stage 4 BT 노드로 구현. **Polite phrase pool**로 호감도를 학술적으로 검증된 방식으로 설계.

### 5.2 RPS 모듈 구조

```
┌──────────────────────────┐
│ rps_vision_node          │
│  - MediaPipe Hands       │
│  - 가위/바위/보 분류      │
│  - confidence            │
└──────────┬───────────────┘
           │ /rps/customer_gesture
           ▼
┌──────────────────────────┐
│ rps_game_node            │
│  - 70% 고객 승리 비율 제어│
│  - 라운드 관리 (best of 3)│
│  - polite phrase 선택    │
└──────────┬───────────────┘
           │ /persona/say (TTS)
           │ /omx/gesture (로봇 손 모양)
           ▼
       OMX manipulator
       (가위/바위/보 포즈)
```

### 5.3 Week별 작업 분해

#### **Week 7**: RPS Vision (MediaPipe Hands)
- [ ] **Brock et al. 2020** 경량 RPS 프레임워크 참고
- [ ] MediaPipe Hands → 손가락 펴짐 개수 → 가위/바위/보 분류
- [ ] 0.8m 거리에서 95% 정확도 목표
- [ ] **타이머**: "하나, 둘, 셋" 신호 후 1.5초 이내 손동작 인식

#### **Week 8**: OpenMANIPULATOR-X 가위바위보 포즈
- [ ] OMX의 4DOF로 3가지 포즈 정의 (URDF 검증)
- [ ] **가위**: 손가락 부분 그리퍼 절반 닫힘
- [ ] **바위**: 그리퍼 완전 닫힘
- [ ] **보**: 그리퍼 완전 열림
- [ ] **준비 동작**: 흔드는 모션 3회 (참가자가 박자 맞추기 좋게)
- [ ] 안전 영역: OMX 작업공간이 사람 0.6m 밖에 있도록 배치

#### **Week 9**: Polite Phrase Pool + 70% 고객 승리 로직
- [ ] **승리 비율 제어**:

```python
# rps_game_node.py
class RPSGameLogic:
    def __init__(self):
        self.target_customer_win_rate = 0.7  # Castro-González 2016 정신
        self.history = []  # 라운드별 결과

    def select_robot_move(self, customer_predicted_move=None):
        """고객이 70%로 이기도록 robot의 다음 수를 선택."""
        current_win_rate = self._calc_customer_win_rate()
        if current_win_rate < self.target_customer_win_rate:
            # 고객이 이길 가능성 높은 수 선택 (의도적 패배)
            if customer_predicted_move:
                return self._losing_move_against(customer_predicted_move)
            return random.choice(['rock', 'paper', 'scissors'])
        else:
            # 가끔은 robot도 이김 (예측 가능성 회피)
            return random.choice(['rock', 'paper', 'scissors'])
```

- [ ] **Polite Phrase Pool** (Castro-González 검증 톤):

```yaml
# personas/polite_phrases.yaml
rps_intro:
  - "함께 가위바위보 한 판 어떠세요?"
  - "잠깐 게임 하시면 시원한 음료 추천드릴게요!"
rps_robot_wins:
  # 핵심: 절대 우쭐대지 않음
  - "어머, 제가 운이 좋았네요. 한 번 더 하실래요?"
  - "이번엔 제가 이겼지만, 다음 판은 어려울 것 같아요."
rps_customer_wins:
  # 핵심: 진심으로 축하 (Castro-González 입증)
  - "잘하시네요! 축하드려요."
  - "역시 빠르시네요. 한 잔 더 시원한 거 어떠세요?"
rps_tie:
  - "오, 같은 생각을 하셨네요!"
```

- [ ] BT의 `Minigame` 노드를 RPS 실제 구현으로 교체
- [ ] **Impolite 비교 시나리오**: A/B 테스트용 impolite phrase pool도 작성 (실험용)

### 5.4 Phase 3 산출물
- [ ] `dobi_npc_minigame` 패키지 — RPS 노드 2종
- [ ] OMX 가위바위보 launch 파일
- [ ] `personas/polite_phrases.yaml`, `impolite_phrases.yaml`
- [ ] **데모 영상**: 본인 + 동료 1명 vs Pinky+OMX, 5라운드 RPS 완주
- [ ] `phase3_retrospective.md`

### 5.5 Phase 3 검증 기준
| 항목 | 기준 |
|---|---|
| RPS 인식 정확도 | 100라운드 중 95% 이상 |
| 고객 승리 비율 | 50라운드 평균 65~75% (목표 70% ± 5%) |
| OMX 안전성 | 100라운드 중 충돌/오작동 0회 |
| 라운드 완주 시간 | 라운드당 평균 8초 이내 |
| Phrase 다양성 | 같은 phrase 연속 2회 출현 5% 이하 |

### 5.6 위험 요소와 대응
- **Risk**: MediaPipe Hands가 카페 조명에서 흔들림
  - **대응**: 천장 LED 추가 + 대조도 보정 전처리
- **Risk**: OMX 모션이 너무 느려 부자연스러움
  - **대응**: 모션 속도 70% 상향 + 사전 동작 prep 추가

---

## 6. Phase 4: 통합 + 5명 파일럿 테스트 (Week 10-12)

**대응 학술 Layer**: 6-Layer 통합 + Castro-González 표본 규모

### 6.1 목표
Phase 1-3을 통합한 **end-to-end 호객 시스템**을 5명 파일럿 테스트로 검증. 가설 검증과 회고를 통해 Phase 5 방향 결정.

### 6.2 통합 BT 최종 형태

```xml
<!-- cafe_funnel_v2.xml -->
<root BTCPP_format="4">
  <BehaviorTree ID="DobiBaristaFunnel">
    <Parallel success_count="1" failure_count="1">

      <!-- 메인 funnel -->
      <Fallback>
        <SafetyCheck/>
        <Sequence>
          <IdleScan output_customer="{customer}"/>
          <Approach customer="{customer}" distance="1.5"/>
          <IceBreak persona="{current_persona}"/>
          <RetainOrAbort condition="rapport > 0.3"/>  <!-- 중간 게이트 -->
          <Minigame type="rps" rounds="3"/>
          <Offer based_on="{customer_va}"/>
          <LeadIn destination="counter"/>
        </Sequence>
      </Fallback>

      <!-- 감정 모니터 (병렬) -->
      <EmotionMonitor abort_on="anger,disgust,walkaway"/>

    </Parallel>
  </BehaviorTree>
</root>
```

### 6.3 Week별 작업 분해

#### **Week 10**: 통합 + 디버깅
- [ ] 모든 노드 단일 launch 파일로 통합 (`dobi_npc_bringup`)
- [ ] Groot2로 실시간 BT 흐름 시각화
- [ ] **3가지 시나리오 핸드 테스트**:
  - (a) 정상 funnel 완주 (긍정적 고객)
  - (b) IceBreak에서 abort (분노 감지)
  - (c) Minigame에서 walk away (rapport 회수)
- [ ] 로깅: `rosbag` + `bt_log` (모든 tick history)

#### **Week 11**: 파일럿 실험 설계
- [ ] **N=5 참가자** (Castro-González N=12 스케일 다운)
- [ ] **2 조건 A/B**:
  - 조건 A: Polite phrase + V-A 기반 abort
  - 조건 B: Impolite phrase + abort 미사용
- [ ] **측정 지표**:
  - Likability (5점 척도, Castro-González 설문 한국어 번역)
  - Engagement (라운드 완주 여부)
  - 거절 시점 (어느 stage에서 walk away)
  - 재만남 의향 (1~5)
  - 정성 코멘트 (5분 인터뷰)
- [ ] IRB는 사내 파일럿이므로 동의서로 대체 (얼굴/음성 녹화 동의)

#### **Week 12**: 실험 실행 + 분석
- [ ] **Day 1-2**: 5명 × 2조건 = 10세션 (1인당 약 30분)
- [ ] **Day 3**: 데이터 분석
  - Likability A vs B (Mann-Whitney U test, N=5는 비모수)
  - 정성 코멘트 thematic coding
- [ ] **Day 4-5**: `phase4_pilot_report.md` 작성
  - 가설 1: Polite > Impolite (Castro-González 재현 여부)
  - 가설 2: V-A abort가 거절 시점 일치 (precision/recall)
  - 발견된 실패 모드 정리

### 6.4 Phase 4 산출물
- [ ] `cafe_funnel_v2.xml` — 통합 BT
- [ ] `dobi_npc_bringup/launch/full_system.launch.py`
- [ ] **파일럿 데이터셋**: 10세션 rosbag + 영상 + 설문 응답
- [ ] `phase4_pilot_report.md` — 정량 + 정성 분석
- [ ] **데모 영상**: 1인 정상 funnel 완주 (3분 풀버전)

### 6.5 Phase 4 검증 기준
| 항목 | 기준 |
|---|---|
| End-to-end 완주율 | 10세션 중 7회 이상 (70%) |
| 시스템 안정성 | 30분 연속 실행 시 crash 0회 |
| Polite 효과 가설 검증 | A 조건 likability 평균이 B보다 0.5점 이상 높음 |
| V-A abort 정밀도 | 실제 거절 직전 abort 트리거 정확도 70% 이상 |
| 학술 재현성 | Castro-González 발견(Polite > Impolite) 방향성 일치 |

### 6.6 파일럿 실험 윤리
- 동의서: 한국어 + 영어, 영상 사용 범위 명시 (논문/블로그 가능, SNS 비공개)
- 참가자 보상: 카페 음료 무료 + 5,000원 상품권
- 분노 시나리오 발생 시: 진행자가 즉시 중단하고 디브리핑

---

## 7. Phase 5: Layer 6 확장 — XAI / Learning (Week 13-16)

**대응 학술 Layer**: Layer 6 (Iovino 2022) — 4대 미해결 과제

### 7.1 목표
파일럿에서 발견한 한계를 Iovino 4대 과제(XAI, HRI, Safety, Learning) 중 **2개**(XAI, Learning) 시작점으로 확장.

### 7.2 Phase 5-A: XAI (Explainable AI) — Week 13-14

**목적**: "왜 이 고객을 골랐어요?" "왜 abort 했어요?" 자연어로 답변.

#### 작업
- [ ] BT tick log를 자연어로 변환하는 `bt_explainer_node`
- [ ] 템플릿 기반 (LLM 의존도 최소화):

```python
EXPLANATION_TEMPLATES = {
    'idle_scan_selected': "{customer_id}번 고객이 {distance}m에서 {dwell_time}초간 머물러서 우선 선택했어요.",
    'approach_aborted': "고객의 표정이 {dominant_emotion}으로 바뀌어서 (V={v:.1f}, A={a:.1f}) 접근을 멈췄어요.",
    'rps_won_intentional': "이번 판은 일부러 졌어요. 고객이 즐거워하시면 음료 추천이 더 잘 받아들여지거든요.",
}
```

- [ ] 옵션: Ollama EXAONE 7.8B로 더 자연스러운 phrase 생성 (피노키오 v3.5 재사용)
- [ ] **데모**: BT 실행 후 `ros2 topic echo /dobi/why` → 의사결정 설명 출력

### 7.3 Phase 5-B: Learning — Week 15-16

**목적**: phrase pool, 승리 비율, abort 임계값을 파일럿 데이터로 자동 튜닝.

#### 작업
- [ ] 파일럿 10세션 + 추가 수집 20세션 = 30세션 데이터
- [ ] **Learnable 파라미터**:
  - 페르소나별 abort 임계값 (현재 V<-0.5, A>0.4 고정)
  - 승리 비율 (현재 70% 고정)
  - phrase별 사용 빈도 (rapport 변화 가중)
- [ ] **간단한 Bandit 알고리즘** (Thompson Sampling):
  - 각 phrase 선택 = arm
  - rapport 증가량 = reward
  - 30세션이면 5~10개 phrase에 대해 의미있는 ranking 가능
- [ ] **LeRobot/ACT 경험 연결 (선택)**: Approach 궤적을 IL로 학습 (Phase 6 후보)

### 7.4 Phase 5 산출물
- [ ] `bt_explainer_node` — XAI 모듈
- [ ] `phrase_bandit_node` — Thompson Sampling 학습기
- [ ] `phase5_extension_report.md`
- [ ] **최종 데모 영상**: 풀 funnel + XAI 출력 + 학습된 phrase ranking

### 7.5 Phase 5 검증 기준
| 항목 | 기준 |
|---|---|
| XAI 설명 정확도 | 본인+동료 10세션 검수 시 80% 이상 합리적 |
| Phrase bandit 수렴 | 30세션 후 상위 3 phrase가 안정적으로 선택됨 |
| 시스템 안전성 | 학습 모듈 추가 후 abort 메커니즘 회귀 0건 |

---

## 8. 전체 일정과 마일스톤

### 8.1 16주 간트차트 (요약)

```
Week:  0    1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16
       │    │    │    │    │    │    │    │    │    │    │    │    │    │    │    │    │
[P0] ──┤
[P1] ──┴────┴────┴────┤
[P2]                  ├────┴────┴────┤
[P3]                                 ├────┴────┴────┤
[P4]                                                ├────┴────┴────┤
[P5]                                                              ├────┴────┴────┴────┤
                                                                   XAI       Learning
                       ▲                ▲                ▲                ▲
                       │                │                │                │
              M1: BT 골격         M2: 감정 통합     M3: RPS 데모      M4: 파일럿 완료
```

### 8.2 마일스톤 정의

| 마일스톤 | 주차 | 산출물 | 의미 |
|---|---|---|---|
| **M1** | Week 3 | BT 골격 + 페르소나 | Layer 1·5 검증 |
| **M2** | Week 6 | 감정 인식 통합 | Layer 2·3 검증, EyeCon 포팅 완료 |
| **M3** | Week 9 | RPS 미니게임 | Layer 4 검증, OMX 통합 |
| **M4** | Week 12 | 5명 파일럿 보고서 | 6-Layer 통합 + 학술 가설 검증 |
| **M5** | Week 16 | XAI + Learning 데모 | Layer 6 확장 시작 |

### 8.3 Dobi Barista 23주 데모와의 정합

기존 Dobi Barista 5-Phase 로드맵(29주)에서 본 호객 BT 시스템은:

- **Dobi Phase 1-2 (Week 1-12)**: Vic Pinky 베이스 + OMX 기본 동작 — 본 계획 Phase 0-3와 병행
- **Dobi Phase 3 (Week 13-18)**: 카페 시나리오 통합 — 본 계획 Phase 4(파일럿) 결과 입력
- **Dobi Phase 4 (Week 19-23)**: 데모 완성 — 본 계획 Phase 5 산출물이 핵심 차별점
- **취업 데모 어필 포인트**: "BT + HRI 융합으로 학술 frontier 영역에서 작동하는 호객 시스템" (Iovino 2022 미해결 과제 ②)

---

## 9. 리스크 매트릭스와 비상 계획

| 리스크 | 확률 | 영향 | 대응책 | Trigger Phase |
|---|---|---|---|---|
| BehaviorTree.CPP 4.x 호환 이슈 | 중 | 높음 | 4.8.3 버전 고정 (Jazzy 공식), 필요시 py_trees fallback | P1 Week 1 |
| EyeCon → ROS2 포팅 실패 | 낮음 | 중 | 7-emotion 분류기를 ONNX로 export 후 노드화 | P2 Week 4 |
| OMX RPS 모션 충돌 위험 | 중 | 높음 | 0.6m 안전 거리 + sw E-stop + 1차 마네킹 테스트 | P3 Week 8 |
| 파일럿 참가자 모집 실패 | 중 | 중 | PinkLAB 동료 6명 우선 활용 | P4 Week 11 |
| Polite > Impolite 가설 미입증 | 낮음 | 낮음 | 음의 결과도 학술적 가치 — 카페 환경 특수성 분석 | P4 Week 12 |
| 16주 일정 초과 | 높음 | 중 | Phase 5는 선택 사항, Phase 4 완료가 핵심 | 전 구간 |
| 카페 소음 GEVA 무력화 | 중 | 중 | GEFA 단독 모드 (Salichs Decision Rule이 이미 처리) | P2 Week 5 |

---

## 10. 일일/주간 작업 흐름

기존 선호도(`개발 소스 코드는 일관성을 유지하기 위해 하루 마지막 코드 작성 후 .md 파일을 만듭니다`)에 맞춘 작업 흐름:

### 10.1 일일 흐름
```
09:00 - 어제 .md 회고 읽기 + 오늘 계획 확정
09:30 - 코딩 (Vscode + Jupyter 병행)
12:00 - 점심
13:00 - 단위 테스트 실행 + 디버깅 (한 단계씩, 결과 확인 후 다음)
17:00 - 통합 테스트 + 영상 캡처
17:30 - 오늘 작성한 코드의 일일 .md 작성 (변경 사항 + 회고)
18:00 - git commit + push (`gjkong/dobi_npc_bt`)
```

### 10.2 주간 흐름
- **월**: 주간 계획 + 직전 주 retrospective 검토
- **화-목**: 핵심 구현
- **금**: 통합 테스트 + 주간 retrospective .md 작성
- **토**: 블로그 포스팅 1편 (10편 누적 → 본 프로젝트 16주 동안 추가 16편 가능)

### 10.3 매 Phase 종료 시
```
1. phaseN_retrospective.md 작성 (성공/실패/배움)
2. 데모 영상 5분 컷 → YouTube 업로드 (비공개 또는 공개)
3. 블로그 포스팅 (Layer N의 학술 배경 + 구현 경험)
4. 다음 Phase 계획 미세 조정
```

---

## 11. 산출물 체크리스트 (전체)

### 11.1 코드 산출물
- [ ] `dobi_npc_bt/` — BT 노드 7개 + cafe_funnel_v2.xml
- [ ] `dobi_npc_emotion/` — GEFA, GEVA, V-A mapper, Decision Rule, Rapport tracker
- [ ] `dobi_npc_dialog/` — 페르소나 loader, TTS 통합
- [ ] `dobi_npc_minigame/` — RPS vision + game logic + OMX 모션
- [ ] `dobi_npc_msgs/` — 4개 커스텀 메시지
- [ ] `dobi_npc_bringup/` — 통합 launch + rosparam YAML
- [ ] `dobi_npc_xai/` (Phase 5) — bt_explainer_node
- [ ] `dobi_npc_learning/` (Phase 5) — phrase_bandit_node

### 11.2 문서 산출물
- [ ] `CLAUDE.md` — 프로젝트 컨텍스트 (Phase 0)
- [ ] `README.md` — 6-Layer 학술 출처 + 빌드 가이드
- [ ] `phase{1,2,3,4,5}_retrospective.md` × 5
- [ ] `phase4_pilot_report.md` — 파일럿 실험 보고서
- [ ] `dobi_npc_paper_master.md` (이미 존재) — 학술 척추
- [ ] 일일 .md × 약 80일 (16주 × 5일)
- [ ] 주간 .md × 16주

### 11.3 데모 산출물
- [ ] Phase 1 영상: BT 골격 데모 (5분)
- [ ] Phase 2 영상: 감정 인식 4-패널 (5분)
- [ ] Phase 3 영상: RPS 풀버전 (3분)
- [ ] Phase 4 영상: 풀 funnel 완주 + 파일럿 하이라이트 (10분)
- [ ] Phase 5 영상: XAI 출력 + 학습된 phrase ranking (5분)
- [ ] 취업 어필용 종합 영상 (5분 컷)

### 11.4 학술/외부 산출물 (선택)
- [ ] 블로그 포스팅 16편 (주간 1편)
- [ ] HRI 또는 ICSR 워크숍 페이퍼 초안 (파일럿 결과 기반)
- [ ] GitHub `gjkong/dobi_npc_bt` 공개 저장소
- [ ] HuggingFace 데모 (선택, 감정 인식 모델만)

---

## 12. 결론

### 12.1 본 계획서의 실현 가능성 근거

1. **모든 핵심 컴포넌트가 이미 검증됨** — EyeCon, Vic Pinky, OMX, Nav2 튜닝, BehaviorTree.CPP는 이미 작동하는 자산
2. **학술 토대가 단단함** — 6-Layer 45년 누적, 모든 의사결정에 검증된 근거
3. **표본 규모 현실적** — N=5 파일럿은 Castro-González N=12와 유사한 신뢰성 가능
4. **점진적 통합** — 각 Phase가 독립 검증 가능, 실패 시 부분 회수 가능
5. **23주 Dobi Barista 데모와 정합** — 별도 트랙이 아닌 동일 프로젝트 내부 모듈

### 12.2 16주 후 Stephen이 보유하게 될 것

- **작동하는 호객 BT 시스템** — Vic Pinky + OMX + EyeCon 기반
- **검증된 학술 가설** — Polite > Impolite, V-A abort 효과
- **취업용 차별 포인트** — "Iovino 2022 미해결 과제 ②(BT + HRI)에서 frontier 작업 수행"
- **공개 가능한 자산** — GitHub 저장소, 데모 영상, 블로그 포스팅
- **다음 단계 명확** — Phase 5의 XAI/Learning이 Phase 6+로 확장됨

### 12.3 다음 즉시 실행 단계

1. 본 계획서 검토 + 일정 미세 조정
2. Phase 0 워크스페이스 생성 (`~/dev_ws/dobi_npc_ws`)
3. Phase 1 Week 1 작업 시작 — BT 노드 6개 골격 작성
4. CLAUDE.md 작성 (프로젝트 컨텍스트)

---

*이 계획서는 `cafe_npc_implementation_plan.md`로 저장됨. `cafe_npc_paper_master.md`(학술 척추)와 짝을 이루는 실행 계획. 6-Layer를 16주 ROS2 시스템으로 옮기는 구체적 청사진.*
