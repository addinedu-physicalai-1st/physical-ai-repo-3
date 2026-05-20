# 카페 호객 로봇 BT의 학술 척추 — 6-Layer 통합본

**작성일**: 2026-05-01
**프로젝트**: Dobi Barista 호객 행위 시나리오
**관련 설계 문서**: `cafe_npc_robot_research.md`, `cafe_npc_engagement_funnel.md`
**대체 문서**: `cafe_npc_paper_summary.md`, `cafe_npc_paper_summary_supplement.md` (이 두 문서를 통합)
**목적**: 호객 BT 시스템을 떠받치는 6편의 핵심 논문을 6-Layer 청사진으로 한 문서에 통합. 인간 감성 인식과 기계 행동 의사결정의 양 축을 모두 포괄.

---

## 0. 통합본의 구성 의도

호객 BT 시스템의 학술 척추를 6개 레이어로 정리하면 다음과 같다.

```
┌──────────────────────────────────────────────────────────────┐
│  [Layer 6] 미해결 과제 / 미래 확장 — Iovino+ (2022)            │
│            BT 10년 종합, 4대 미해결 과제                        │
├──────────────────────────────────────────────────────────────┤
│  [Layer 5] 게임→로봇 BT 형식화 — Marzinotto+ (2014)           │
│            Sequence/Fallback/Parallel 표준                    │
├──────────────────────────────────────────────────────────────┤
│  [Layer 4] 게임 인터랙션 검증 — Castro-González+ (2016)        │
│            가위바위보 + Polite Persona                         │
├──────────────────────────────────────────────────────────────┤
│  [Layer 3] 다중모달 감정 인식 — Salichs+ (2014)                │
│            GEVA + GEFA → ROS Decision Rule                    │
├──────────────────────────────────────────────────────────────┤
│  [Layer 2] 감정 표현 모델 — Russell (1980)                     │
│            Circumplex Model (Valence × Arousal)                │
├──────────────────────────────────────────────────────────────┤
│  [Layer 1] 행동 트리 패러다임의 시작 — Isla (2005)             │
│            Halo 2 — 모듈성·상속·우선순위 트리                   │
└──────────────────────────────────────────────────────────────┘
```

레이어 1~3은 **시스템의 토대**(BT 패러다임 자체, 감정 모델, 다중모달 인식). 레이어 4~5는 **시스템의 적용**(검증된 게임 인터랙션, 형식 표준). 레이어 6은 **시스템의 확장 방향**(미해결 과제). 6개 레이어가 합쳐지면 호객 BT의 모든 의사결정에 학술적 근거가 생긴다.

---

## 1. 두 학술 계보의 교차점

호객 BT는 우연히 묶인 기술 더미가 아니라, **두 독립 학술 흐름이 자연스럽게 수렴하는 지점**이다.

```
[KTH 그룹 / 스웨덴] — BT 행동 측면
  Isla 2005 (Bungie/게임 산업)
       │
       ▼
  Ögren 2012 (UAV 제어)
       │
       ▼
  Marzinotto+ 2014 (BT 형식 통일)
       │
       ▼
  Iovino+ 2022 (10년 종합 서베이)
                                    \
                                     \
                                      ▶ ── 카페 호객 BT
                                     /     (Stephen의 통합 지점)
                                    /
[Madrid 그룹 / 스페인] — 감정 인식·HRI
  Russell 1980 (감정 차원 모델, JPSP)
       │
       ▼
  Salichs+ 2014 (GEVA + GEFA 다중모달)
       │
       ▼
  Castro-González+ 2016 (RPS Polite/Impolite)
```

**KTH 그룹**: Petter Ögren을 중심으로 게임 BT를 학계로 들여오고 형식화·표준화. 호객 BT의 **의사결정 엔진** 측면을 담당.

**Madrid 그룹**: Carlos III University of Madrid RoboticsLab의 Salichs를 중심으로 감정 인식과 HRI 연구. 호객 BT의 **감성 인식** 측면을 담당.

호객 BT는 두 그룹의 연구를 처음으로 한 시스템에서 통합한다는 점에서 학술적 의의가 있다.

---

## 2. Layer 1 — Damian Isla (2005): *Handling Complexity in the Halo 2 AI*

### 2.1 기본 정보
- **저자**: Damian Isla (당시 Bungie Studios)
- **출처**: Game Developers Conference (GDC) 2005, Gamasutra 게재
- **인용**: 게임 AI 분야 가장 영향력 있는 산업계 발표 중 하나, 학술 논문 수백 편이 root reference로 인용

### 2.2 한 줄 요약
**"Halo 2 적 AI가 너무 복잡해져서 FSM(유한상태기계)로 감당이 안 됐다. Bungie는 행동을 계층 트리로 정리하는 새 표현 구조를 고안 — Behavior Tree의 시작."**

### 2.3 학술 논문이 아닌데 왜 중요한가
정식 학술 논문이 아닌 GDC 산업 발표지만, **모든 BT 학술 논문이 이 발표를 root reference로 인용**한다.
- BT라는 패러다임이 **여기서 처음 명시적으로 제시**됨
- **Halo 2(2004)라는 대규모 상용 게임에서 검증**된 실전 기술
- Petter Ögren이 2012년 학계로 들여오면서 BT 로봇 연구의 출발점이 됨

### 2.4 배경 — 왜 새로운 구조가 필요했나
Halo 1까지는 FSM으로 충분했다. Halo 2에서 적 종류와 행동이 정교해지자 세 가지 문제가 폭발:

**상태 폭발**: N개 상태에 행동 하나 추가 = N개 전이 추가
**모듈성 부재**: 한 적의 AI를 다른 적에 재사용하려면 처음부터 다시 작성 → 코드가 스파게티
**디버깅 지옥**: "왜 이렇게 행동하는가" 추적이 거대한 상태 그래프를 다 따라가야 가능

### 2.5 Isla의 4가지 핵심 아이디어

**아이디어 1: 행동을 트리로 계층화**

기존(Halo 1, 평면 FSM):
```
Idle ←→ Patrol ←→ Alert ←→ Combat ←→ Flee  (모두 서로 연결)
```

Halo 2(계층 트리):
```
Root
├── Self-preservation (생존)
│   ├── Flee
│   └── TakeCover
├── Combat (전투)
│   ├── ShootAtPlayer
│   └── ThrowGrenade
└── Idle (대기)
    └── Patrol
```
상위 → 하위로 우선순위 탐색. 새 행동 추가는 적절한 가지에 leaf만 끼워넣음.

**아이디어 2: 모듈성을 통한 재사용성**
각 행동(노드)이 자기 완결적. "TakeCover" 노드는 다른 캐릭터의 트리에도 그대로 끼워넣을 수 있음.

**아이디어 3: Character hierarchy (캐릭터 상속)**
Halo 2의 적(Grunt, Elite, Brute, Hunter, Flood Parasite)은 각자 BT가 있지만 상속 관계로 정의. 자식은 부모와 다른 부분만 명시. Generic 캐릭터가 root.

**아이디어 4: Order/Style 시스템**
상위 의도("이 위치를 방어하라" = order)와 표현 방식("공격적/신중하게" = style)을 분리. 같은 order라도 style이 다르면 다른 행동.

### 2.6 호객 BT 적용

**(1) v2 funnel 자체가 Isla 패턴**
v2의 5-stage funnel(IDLE → APPROACH → ICEBREAK → MINIGAME → OFFER → LEAD-IN)은 Fallback + Sequence 계층 구조의 직접 응용.

**(2) 페르소나 상속 구조**
```
DobiBaristaGenericPersona (root)
├── FriendlyChildPersona       ← 아이 대상 (게임 위주)
├── ProfessionalAdultPersona   ← 비즈니스 고객
└── CasualBrowserPersona       ← 평상시 default
```
각 페르소나는 phrase pool, 미니게임 선호, 접근 거리, abort 임계값 등을 다르게 정의. **부모와의 차이만 명시**.

**(3) 복잡도 폭발 방지의 동일한 동기**
호객 시나리오도 빠르게 복잡해진다(다양한 미니게임, 고객 유형, 다국어, 시간대). FSM으로 짰다면 곧 Halo 2와 같은 문제. **BT를 처음부터 채택하는 것이 정답**.

**(4) Groot2 디버깅 = Halo 2 철학 계승**
"왜 이 적이 이렇게 행동했는가"를 트리 추적으로 즉시 파악하는 Halo 2 방식이 현대 BehaviorTree.CPP의 Groot2 시각 디버거로 직접 계승됨.

---

## 3. Layer 2 — James A. Russell (1980): *A Circumplex Model of Affect*

### 3.1 기본 정보
- **저자**: James A. Russell (당시 University of British Columbia)
- **출처**: *Journal of Personality and Social Psychology*, 39(6), 1161–1178
- **DOI**: 10.1037/h0077714
- **인용**: 30,000회 이상 (감정 심리학에서 가장 영향력 있는 논문 중 하나)

### 3.2 한 줄 요약
**"감정은 별개 카테고리(기쁨/슬픔/분노...)가 아니라, 두 연속 축(쾌-불쾌, 활성-비활성)이 만드는 2차원 평면 위의 점이다."**

### 3.3 연구의 배경
이전까지 감정 연구는 두 흐름이었다:
- **기본 감정 이론(Ekman)**: 6~12개 독립 카테고리 — 그러나 "지루함"과 "슬픔"이 정말 다른가?
- **일차원 모델**: 긍정 vs 부정 한 축 — 그러면 "분노"와 "슬픔"이 같은 점

Russell은 두 한계를 극복하려 했다.

### 3.4 핵심 실험
28개 감정 단어(happy, sad, tense, calm, excited 등)를 골라 참가자에게 유사도 평가를 시켰다. 다차원 척도법으로 분석했더니 **딱 2개의 축**으로 깔끔하게 배치됐다.

```
                    Activation (high)
                         ▲
                         │
               긴장(tense) │  흥분(excited)
                         │
            Unpleasant ──┼── Pleasant
                         │
              우울(depressed) │  편안(relaxed)
                         │
                         ▼
                    Activation (low)
```

- **Valence(쾌-불쾌)**: 가로축, -1.0 ~ +1.0
- **Arousal(활성도)**: 세로축, -1.0 ~ +1.0

28개 감정이 이 평면에 **원형으로** 배열 → "circumplex" = 원형 모델.

### 3.5 호객 BT 적용

**(1) 감정의 카테고리 분류로는 부족**
EyeCon의 "기쁨/슬픔/분노/놀람/지루함/평온/혐오" 7-emotion을 그대로 rapport 가중치에 연결하면:
- "기쁨"과 "놀람"은 다른 카테고리지만 둘 다 호객에 긍정적
- "지루함"과 "슬픔"은 다른 카테고리지만 둘 다 부정적

(valence, arousal) 좌표로 변환 → **카테고리 경계의 모호함 제거 + 연속적 가중치**.

```python
emotion_weight = (valence + 1.0) / 2.0 * arousal_factor
```

**(2) 시간적 변화 추적**
카테고리 모델: "기쁨 → 슬픔" 점프(이산). 차원 모델: (0.9, 0.6) → (0.4, 0.3) → (-0.2, -0.1) **부드러운 궤적**. v2 문서의 `emotion_trend` 계산이 이 위에 성립.

**(3) 호객 스위트 스팟의 명확한 정의**
- **우상단**(V > 0, A > 0): 기쁘고 활기찬 → **호객 진입**
- 우하단(V > 0, A < 0): 너무 편안 → 자극 불필요, 후퇴
- 좌상단(V < 0, A > 0): 분노/긴장 → **즉시 abort**
- 좌하단(V < 0, A < 0): 우울/지루함 → 신중 접근, 거절 확률 높음

**(4) 1980년 논문이 지금도 표준인 이유**
현대 감정 인식 AI 거의 전부(2025 multimodal emotion estimator, 2024 UGotMe 등)가 이 모델을 출력 형식으로 채택. EyeCon → ROS2 노드로 포팅 시 출력을 (valence, arousal)로 통일하면 **모든 SOTA 모델과 호환**.

---

## 4. Layer 3 — Salichs et al. (2014): *A Multimodal Emotion Detection System during Human-Robot Interaction*

### 4.1 기본 정보
- **저자**: Miguel A. Salichs 그룹 (Carlos III University of Madrid RoboticsLab)
- **출처**: *International Journal of Advanced Robotic Systems*, PMC ID: PMC3871074
- **핵심 모듈**: GEVA(**Gender and Emotion Voice Analysis**, Chuck 언어로 작성) + GEFA(**Gender and Emotion Facial Analysis**, SHORE + CERT 통합)

> ⚠ **본 프로젝트는 모달리티 매핑을 재정의해 사용한다** — face=GEVA, body=GEFA.
> Salichs 원어 모달리티는 **GEVA=Voice / GEFA=Face**. 본 프로젝트에선 음성을 안 쓰고 얼굴(=우리의 GEVA) + 자세(=우리의 GEFA)로 매핑.
> 코드/회고 읽을 때 주의. 자세한 매핑은 `CLAUDE.md` §2 "약어 GEVA / GEFA — 본 프로젝트 정의" 참조. 본 문서(학술 척추)는 원어 풀이 그대로 유지.

### 4.2 한 줄 요약
**"음성과 얼굴 두 채널의 감정 인식을 통합하면 단일 채널보다 정확. 이 시스템은 ROS 위에서 작동하도록 설계되었다."**

### 4.3 왜 이 논문이 중요한가
호객 BT의 가장 큰 실무 도전: **"감정을 실시간으로 안정적으로 인식하기"**
- 카메라만 → 마스크/모자/조명에 약함
- 마이크만 → 카페 소음, 다중 화자 문제
- 둘을 합치려면 → 어떻게? 어디서? 어떤 형식으로?

이 논문은 **ROS 기반 다중모달 시스템**으로 해결. **Stephen의 ROS2 환경에 가장 직접적인 청사진**.

### 4.4 시스템 구조

```
┌──────────────┐                ┌──────────────┐
│   GEVA       │                │   GEFA       │
│ (음성 분석)   │                │ (얼굴 분석)   │
│              │                │              │
│ - pitch      │                │ - facial     │
│ - intensity  │                │   action     │
│ - speech rate│                │   units      │
│ - prosody    │                │ - eye state  │
└──────┬───────┘                └──────┬───────┘
       │                               │
       │ 단일 모달 감정 결과              │ 단일 모달 감정 결과
       ▼                               ▼
┌─────────────────────────────────────────────┐
│        Decision Rule (융합 규칙)              │
│   - 두 채널 결과 비교                          │
│   - 신뢰도 가중 결합                          │
│   - 충돌 시 우선순위 규칙                     │
└──────────────────┬──────────────────────────┘
                   │ 최종 감정 판정
                   ▼
┌─────────────────────────────────────────────┐
│   RDS (Robot Dialog System)                 │
│   - 감정에 맞춰 대화 전략 조정                 │
└─────────────────────────────────────────────┘
```

### 4.5 핵심 발견 3가지

**(1) 다중모달 융합이 항상 더 정확**
- GEVA 단독: X1%
- GEFA 단독: X2%
- GEVA + GEFA: 두 단독보다 모두 높음

이는 단순 평균이 아니라 **두 채널이 서로의 약점 보완**. 카페 소음으로 GEVA가 흔들려도 GEFA가 안정적이면 최종 판정 정확.

**(2) 가짜 감정도 더 잘 잡아낸다**
참가자에게 감정을 일부러 꾸며보라고 한 실험에서, 단일 모달은 속았지만 다중모달은 더 자주 정확히 분류. 이유: 사람이 얼굴은 웃지만 목소리에는 긴장 — **불일치(incongruence) 감지**.

호객 시나리오 응용: **고객이 예의상 웃으며 응답하지만 실제로는 부담스러워하는 경우**, 다중모달이 GEFA(웃음)와 GEVA(긴장한 목소리) 불일치를 감지 → **거짓 긍정 신호로 처리**, abort 트리거.

**(3) ROS 통합 검증**
시스템 전체가 ROS 위에서 작동, 실시간으로 RDS(대화 시스템)에 감정 결과 전달. **Stephen의 ROS2 환경에서 직접 재현 가능**.

### 4.6 호객 BT 적용

**(1) v2 ROS2 노드 구조의 학술적 청사진**

| Salichs (2014) | Stephen v2 ROS2 노드 |
|---|---|
| GEFA (얼굴 분석) | EyeCon facial expression 모듈 |
| GEVA (음성 분석) | EyeCon audio 7개 지표 모듈 |
| Decision Rule | `valence_arousal_mapper` + `rapport_tracker_node` |
| RDS | `emotion_aware_dialog_node` |

v2 노드 구조 = **이 논문 아키텍처의 ROS2 + 차원 모델 버전**.

**(2) Decision Rule 설계 가이드**
- 두 채널 일치 → 최종 감정 = 일치된 감정, 신뢰도 ↑
- 충돌 → confidence 가중 평균, 신뢰도 ↓로 표시
- 한 채널 신뢰도 매우 낮음 → 다른 채널만 사용

호객 BT의 `compute_emotion_weight()`에 그대로 적용 → 노이즈 환경에서 안정적 가중치.

**(3) 거짓 긍정 방어**
```python
if facial_emotion == "happy" and voice_emotion in ("tense", "neutral"):
    # 불일치 감지 → 사회적 응답일 가능성
    rapport_event_weight *= 0.5
    flag_for_abort_check = True
```

---

## 5. Layer 4 — Castro-González et al. (2016): *The Effects of an Impolite vs. a Polite Robot Playing Rock-Paper-Scissors*

### 5.1 기본 정보
- **저자**: Á. Castro-González, J.C. Castillo, F. Alonso-Martín 등 (Carlos III University of Madrid)
- **출처**: *Social Robotics: 8th International Conference (ICSR 2016)*, Kansas City, pp. 306–316
- **DOI**: 10.1007/978-3-319-47437-3_30

### 5.2 한 줄 요약
**"같은 가위바위보 게임이라도 로봇이 예의 바르게 말할 때(polite) 무례할 때(impolite)보다 더 호감을 얻고 engaging하다."**

### 5.3 왜 가위바위보인가
가위바위보를 단순 게임이 아닌 **HRI 효과 측정의 표준 실험 패러다임**으로 정립. 장점:
1. 모든 문화권이 알고 있음 (학습 비용 0)
2. 한 라운드가 짧음 (5~10초)
3. 결과가 명확 (승/패/무)
4. 결과 외 변인 통제 쉬움 (게임 진행 동일, 말투만 다르게)

### 5.4 실험 설계
12명 참가, 사회적 로봇 Mini와 가위바위보. 두 조건:

**조건 A — Polite Robot**
- 시작: "안녕하세요, 함께 게임해주셔서 감사합니다"
- 이겼을 때: "잘하셨네요! 좋은 게임이에요"
- 졌을 때: "축하드립니다, 다음에는 제가 노력해볼게요"

**조건 B — Impolite Robot**
- 시작: "그래, 시작하자"
- 이겼을 때: "역시 내가 이겼지"
- 졌을 때: "운이 좋았네"

**중요 통제**: 게임 결과 비율, 동작, 음색 동일. **오직 발화 내용**만 다르게.

### 5.5 결과
- **Likability(호감도)**: Polite 로봇 유의미하게 높음
- **Engagement(몰입도)**: Polite 로봇 더 높음
- **재만남 의향**: Polite 로봇 더 높음

핵심: 게임의 "내용"보다 **로봇의 페르소나(말투, 태도)**가 사용자 경험을 결정.

### 5.6 호객 BT 적용

**(1) 가위바위보를 1순위 미니게임으로 선정한 학술적 근거**
가위바위보가 **HRI 학계에서 신뢰성 있게 검증된 게임**임을 입증. 다른 미니게임(예: 비밀번호 풀기)은 비슷한 검증 데이터 없음.

**(2) 페르소나 일관성의 중요성**
v2 문서 8.5절 "페르소나 일관성"의 *Symbolically Scaffolded Play* 원칙(quest giver는 엄격한 symbolic 규칙으로 stabilize)을 **HRI 실험으로 입증**한 셈. LLM 자유 생성보다 **사전 정의 phrase pool**이 안전.

**(3) "이기는 것"이 목표가 아니다**
저자들이 명시: *연구 목적은 로봇이 이기는 게 아니라 engagement와 enjoyment*.
이는 v2의 "70% 확률 고객 승리" 설계의 학술 근거. 패배 멘트("축하합니다, 다음엔 제가 노력해볼게요")가 승리 멘트("역시 내가 이겼지")보다 호감도를 높임이 검증됨.

**(4) 적은 표본도 의미있는 신호**
N=12 preliminary study. **Stephen의 카페에서 5~10명 파일럿 테스트로도 검증 가능**.

### 5.7 후속 연구 동향
이 2016 논문은 다음으로 확장:
- *Schulz & Utseth (HAI 2024)*: NAO RPS로 office/career fair visitor engagement
- *Brock et al. (IEEE Access 2020)*: 경량 RPS 프레임워크 (Leap motion + on-device ML)
- *Frontiers in Robotics and AI (2024)*: Politeness가 향후 상호작용 의향에까지 영향

→ **호객 로봇이 가위바위보를 ice-breaker로 쓰는 것이 학술 주류**.

---

## 6. Layer 5 — Marzinotto, Colledanchise, Smith, Ögren (2014): *Towards a Unified Behavior Trees Framework for Robot Control*

### 6.1 기본 정보
- **저자**: Alejandro Marzinotto, Michele Colledanchise, Christian Smith, Petter Ögren (KTH 왕립공과대학)
- **출처**: *2014 IEEE International Conference on Robotics and Automation (ICRA)*, pp. 5420–5427
- **DOI**: 10.1109/ICRA.2014.6907990
- **인용**: 1,000회 이상 (BT 로보틱스 토대 논문)

### 6.2 한 줄 요약
**"게임 BT를 로봇에 가져왔지만 사람마다 정의가 달라 호환이 안 됐다. 이 논문은 BT의 통일된 수학적 정의를 제시하고, 기존 로봇 제어 구조(FSM, Subsumption, Decision Tree, Sequential Composition)들이 모두 BT의 특수 사례임을 증명."**

### 6.3 배경 — 왜 통일이 필요했나
2012년 Ögren이 게임 BT를 UAV 제어에 적용한 이후 여러 연구실이 BT 도입했지만:
- A 연구실: "Sequence는 자식이 모두 success여야 success"
- B 연구실: "Sequence는 메모리를 가져 다음 tick에 이어서 실행"
- C 연구실: "Fallback과 Selector는 같은 말"
- D 연구실: "Parallel의 success 조건은..."

**같은 BT XML이 다른 라이브러리에서 다르게 작동** → 학술 비교 어렵고, 산업 채택 더디게 만듦.

### 6.4 핵심 기여 3가지

**(1) BT의 형식 수학적 정의**
- BT는 트리 구조, 노드는 함수 `Tick(): {Running, Success, Failure}` 반환
- 4가지 표준 노드: **Sequence(→), Fallback(?), Parallel, Decorator**
- 실행 의미론을 수학적 수식으로 명시

→ **어느 라이브러리에서 짜든 같은 BT는 같은 행동**.

**(2) 기존 제어 구조와의 통합 증명**
다음 4가지 구조가 모두 BT로 표현 가능함을 증명:
- **FSM** (유한상태기계)
- **Subsumption Architecture** (Brooks의 행동주의 로보틱스)
- **Decision Tree**
- **Sequential Behavior Composition**

→ **BT는 이전 패러다임들의 일반화(generalization)**. BT를 쓰면 이전 방식의 모든 표현이 가능하고, 더 많은 것도 할 수 있다.

**(3) 핵심 속성의 형식화**
- **Robustness**: BT의 reactive 특성 → 환경 변화에 강건
- **Safety**: 안전 조건을 priority Fallback으로 보장
- **Modularity**: 서브트리 단위 재사용/교체

### 6.5 후속 영향
- 2017: Colledanchise & Ögren의 IEEE Trans. on Robotics 확장
- 2018: BehaviorTree.CPP 라이브러리(Davide Faconti) — 이 논문 정의를 그대로 구현
- 2020+: Nav2가 BehaviorTree.CPP를 ROS2 네비게이션 표준으로 채택
- 2022+: PX4 Autopilot, Boston Dynamics Spot 등 산업 로봇이 BT 채택

**Stephen이 사용 중인 BehaviorTree.CPP 의미론 = 이 논문의 정의**. v2 BT XML이 이 표준에 따라 작성되어 다른 ROS2 시스템과 100% 호환.

### 6.6 호객 BT 적용

**(1) BT XML 표준 보장**
v2 호객 funnel BT XML이 BehaviorTree.CPP에서 정의된 대로 작동. 다른 사람이 받아도 동일 행동 재현 → **재현성·이전성 확보**.

**(2) FSM 유혹을 거절할 학술 근거**
호객 시나리오에서 "FSM이 더 간단할 것 같은데?"라는 유혹이 들 때, 이 논문은 **BT가 FSM을 일반화한 상위 구조**임을 증명. **FSM에서 가능한 모든 것을 BT는 가능, 더 많은 것도** → BT 선택은 항상 안전.

**(3) Reactive + Robust 보장**
호객은 강한 reactivity 요구 — 고객 갑자기 walk away, 분노 감지, 우선순위 변화 등 즉시 반영. 이 논문은 BT의 reactive 특성을 형식적으로 보장. v2의 `EmotionMonitor` Parallel 패턴이 이 기반 위에 구축.

**(4) 안전성 형식 토대**
"Safety condition을 priority fallback의 가장 왼쪽 가지에 두면 항상 가장 먼저 체크" 패턴 형식화. 호객 BT의 EmotionMonitor + abort 트리거가 정확히 이 패턴.

```xml
<Fallback>
  <SafetyCheck/>          <!-- 가장 먼저 체크 (Marzinotto 형식 보장) -->
  <NormalEngagement/>
</Fallback>
```

---

## 7. Layer 6 — Iovino, Scukins, Styrud, Ögren, Smith (2022): *A Survey of Behavior Trees in Robotics and AI*

### 7.1 기본 정보
- **저자**: Matteo Iovino, Edvards Scukins, Jonathan Styrud, Petter Ögren, Christian Smith (KTH)
- **출처**: *Robotics and Autonomous Systems*, Volume 154, 104096
- **DOI**: 10.1016/j.robot.2022.104096
- **arXiv**: 2005.05842 (Open Access)
- **분량**: 160편 이상의 BT 관련 논문 종합 분석

### 7.2 한 줄 요약
**"2005년 Halo 2부터 2022년까지 게임에서 시작된 BT가 로봇에서 어떻게 발전했는지 160편 종합. BT는 이제 표준이지만 4대 미해결 과제(XAI, HRI, Safety, Learning)가 남아있다."**

### 7.3 왜 이 논문이 중요한가
호객 BT 설계자에게 **현재 위치를 알게 해주는 지도**:
- 내가 하려는 게 검증된 표준인가, 미개척 영역인가?
- 어떤 도구/라이브러리가 학술적으로 검증되었나?
- 남은 과제는?

### 7.4 핵심 발견 5가지

**(1) BT는 이미 로봇 표준 기술**
160편 분석 결과, BT는 다음에서 광범위 채택:
- Mobile robots / autonomous navigation (Nav2)
- Manipulation (산업용 매니퓰레이터)
- Multi-robot coordination
- Aerial robots (UAV)
- Search and rescue
- HRI (인간-로봇 상호작용)

**(2) 라이브러리 생태계 정착**
- **BehaviorTree.CPP**: ROS/ROS2 사실상 표준
- **py_trees / py_trees_ros**: Python 기반 프로토타이핑
- **Groot2**: 시각적 편집 + 디버깅
- **Nav2 BT XML**: 네비게이션 도메인 특화

**(3) BT vs 다른 의사결정 구조**
- **FSM**: scalability에서 BT 우월
- **HTN**: 추상화 단계 비슷하나 BT가 reactive에 강함
- **GOAP**: 동적 재계획 강하나 계산 비용 ↑, BT와 하이브리드 가능
- **PDDL Planner (PlanSys2)**: 상위 계획에 좋고, BT를 실행 엔진으로 결합 가능
- **Reinforcement Learning**: 학습 가능하나 안전 보장 어려움, BT는 명시적 안전성

→ v2가 GOAP를 보류하고 BT+Utility AI 하이브리드 선택한 결정의 학술 근거.

**(4) 4가지 미해결 과제 (Open Research Challenges)**

**①  Explainable AI (XAI)**: "왜 로봇이 이 행동을 했는가?" 자연어 설명. 호객 로봇이 "왜 저 고객을 골랐어요?"에 답할 수 있어야 신뢰 ↑.

**② Human-Robot Interaction (HRI)**: 사람의 의도와 감정을 반영하는 BT. **이게 정확히 v2 호객 BT가 다루는 영역**. 서베이가 active research임을 명시.

**③ Safe AI**: BT의 형식 검증 (Linear Temporal Logic, Event-B 등). 호객 BT의 abort 메커니즘 검증에 직결.

**④ Learning + BT**: 사람이 일일이 BT 작성하지 않고 학습으로 자동 생성. **Stephen의 LeRobot/ACT 경험과 결합 가능**.

**(5) 산업 적용 사례**
- SCANIA 트럭 (자율주행)
- iCub 휴머노이드 (인지 로봇 연구)
- 산업용 매니퓰레이터 (Universal Robots 등)
- 모바일 로봇 (배달, 청소 등 서비스 로봇)

→ **카페 호객 로봇은 "서비스 로봇 + HRI"의 교차점**, 서베이가 식별한 active research와 정확히 일치.

### 7.5 호객 BT 적용

**(1) Stephen의 프로젝트가 학술 frontier에 있음**
서베이가 BT + HRI를 4대 미해결 과제 중 하나로 명시. 호객 로봇이 정확히 frontier에 위치 → **단순 service robot 응용이 아닌 학술 기여 가능 영역**.

**(2) 도구 선택 정당화**
v2의 BehaviorTree.CPP + Nav2 + py_trees 채택이 서베이 표준 생태계와 100% 일치. **새 학습 비용 ↓, 커뮤니티 지원 ↑**.

**(3) 하이브리드 접근의 정당성**
v2가 BT(상위 의사결정) + Utility AI(우선순위) + Proxemic SFM(접근 궤적) + Emotion-Weighted Rapport(감정 가중치)를 결합한 것은 서베이 흐름("BT는 다른 기법과의 하이브리드로 강해진다")과 일치.

**(4) 단계별 확장 로드맵**
4대 미해결 과제 = 호객 BT의 **Phase 확장 방향**:
- Phase 1: 기본 BT funnel (현재 v2)
- Phase 2: HRI 강화 — 감정 가중치 (v2 진행 중)
- Phase 3: XAI — 호객 의사결정 설명 기능
- Phase 4: Learning — 실제 카페 데이터로 BT 자동 튜닝
- Phase 5: Formal verification — abort 메커니즘 안전성 증명

---

## 8. 6-Layer 통합 청사진 — 호객 BT 위에서의 종합

### 8.1 시스템 위에서의 6-Layer 매핑

```
┌────────────────────────────────────────────────────────────────┐
│                     호객 BT 시스템 (v2)                          │
├────────────────────────────────────────────────────────────────┤
│  [Layer 6] 미래 확장: XAI, Learning, Formal Verification         │
│           ↑ 누구의 자식: Iovino+ 2022 서베이                       │
├────────────────────────────────────────────────────────────────┤
│  [Layer 5] BT XML 표준: Sequence/Fallback/Parallel              │
│           ↑ 형식 보장: Marzinotto+ 2014                          │
├────────────────────────────────────────────────────────────────┤
│  [Layer 4] 가위바위보 미니게임 + Polite Persona                  │
│           ↑ 검증: Castro-González+ 2016                         │
├────────────────────────────────────────────────────────────────┤
│  [Layer 3] EyeCon → ROS2 노드: GEFA + GEVA + Decision Rule      │
│           ↑ 청사진: Salichs+ 2014                                │
├────────────────────────────────────────────────────────────────┤
│  [Layer 2] valence_arousal_mapper: 7-emotion → (V, A)           │
│           ↑ 모델: Russell 1980                                   │
├────────────────────────────────────────────────────────────────┤
│  [Layer 1] BT 패러다임: 5-stage funnel + 페르소나 상속           │
│           ↑ 시작: Isla 2005 (Halo 2)                             │
└────────────────────────────────────────────────────────────────┘
```

### 8.2 시간 축으로 본 통합

```
1980 ──────── 2005 ──── 2014 ──────── 2016 ──────── 2022 ──── 2026
 │              │         │  │           │              │       │
Russell      Isla    Salichs Marzinotto Castro-      Iovino    호객
감정 모델    BT 시작  다중모달  BT 형식화  González    서베이    BT v2
                              RPS 효과
```

45년에 걸친 6편이 호객 BT 위에서 자연스럽게 수렴.

### 8.3 두 흐름의 학술적 만남

```
[Madrid 그룹]                [KTH 그룹]
감정 인식·HRI 측면            BT 행동 측면

Russell 1980 (이론 토대)
       │
       ▼
Salichs 2014 (다중모달)         Isla 2005 (BT 시작)
       │                            │
       ▼                            ▼
Castro-González 2016          Marzinotto 2014 (형식화)
(RPS HRI 검증)                      │
       │                            ▼
       │                       Iovino 2022 (서베이)
       │                            │
       └──────────┬─────────────────┘
                  ▼
        [호객 BT 통합 지점]
        Stephen의 Dobi Barista
```

---

## 9. v2 시스템의 각 부분에 매핑된 학술 근거

호객 BT v2 문서의 주요 컴포넌트가 어느 논문에서 학술 근거를 얻는지 정리.

| v2 컴포넌트 | 학술 근거 | 매핑 내용 |
|---|---|---|
| 5-stage funnel 구조 | Isla 2005 | Fallback + Sequence 계층 |
| 페르소나 상속 (예정) | Isla 2005 | character hierarchy 패턴 |
| `valence_arousal_mapper` | Russell 1980 | 7-emotion → (V, A) |
| `emotion_trend` 계산 | Russell 1980 | 차원 모델의 연속성 |
| Abort 트리거 (분노/혐오) | Russell 1980 + Salichs 2014 | 좌상단 사분면 + 다중모달 신뢰도 |
| `emotion_perception_node` | Salichs 2014 | GEFA + GEVA |
| `compute_emotion_weight()` | Salichs 2014 | Decision Rule (충돌 시 confidence 가중) |
| 거짓 긍정 방어 | Salichs 2014 | facial-voice incongruence 감지 |
| 가위바위보 미니게임 | Castro-González 2016 | RPS 표준 패러다임 |
| Polite phrase pool | Castro-González 2016 | likability 입증 |
| 70% 고객 승리 비율 | Castro-González 2016 | "이기는 게 목적이 아닌 engagement" |
| BT XML 표준 | Marzinotto 2014 | BehaviorTree.CPP 의미론 |
| EmotionMonitor Parallel | Marzinotto 2014 | reactive + safety 형식 보장 |
| `<Fallback>` priority safety | Marzinotto 2014 | 가장 왼쪽 가지 우선 |
| Phase 3 XAI 확장 | Iovino 2022 | 미해결 과제 ① |
| Phase 2 HRI 강화 | Iovino 2022 | 미해결 과제 ② |
| Phase 5 abort 검증 | Iovino 2022 | 미해결 과제 ③ |
| Phase 4 Learning | Iovino 2022 | 미해결 과제 ④ |

---

## 10. 종합 결론과 다음 단계

### 10.1 6편의 큰 그림

호객 BT 시스템은 **45년 6편 핵심 논문이 수렴하는 지점**:
- **1980**: 감정을 어떻게 측정할지 (Russell)
- **2005**: 행동을 어떻게 구조화할지 (Isla)
- **2014a**: 다중모달로 어떻게 결합할지 (Salichs)
- **2014b**: 로봇 BT를 어떻게 형식화할지 (Marzinotto)
- **2016**: 어떤 게임 인터랙션이 효과적인지 (Castro-González)
- **2022**: 우리가 어디에 있고 어디로 갈지 (Iovino)

핵심 메시지: **호객 BT의 어느 부분이든 학술 근거가 있고, 검증된 도구로 구현 가능하며, frontier 영역까지 명확**.

### 10.2 즉시 활용 가이드

**구현 시 따를 표준**:
- BT XML: **Marzinotto 2014 의미론** (BehaviorTree.CPP가 그대로 구현)
- BT 디버깅: **Groot2** (Halo 2 디버깅 철학 계승)
- 페르소나 설계: **Isla 2005 character hierarchy** 패턴
- 감정 인식: **Salichs 2014 GEFA+GEVA Decision Rule**
- 감정 표현: **Russell 1980 (V, A) 좌표**
- 미니게임: **Castro-González 2016 RPS + Polite phrase pool**

### 10.3 중기 확장 방향 (Iovino 2022 미해결 과제 기반)

**Phase 2 (현재 v2)**: HRI 강화 — 감정 가중치 통합 ✅
**Phase 3**: XAI — 호객 의사결정의 자연어 설명 기능
**Phase 4**: Learning — 실제 카페 데이터로 BT 파라미터 자동 튜닝 (LeRobot/ACT 경험 활용)
**Phase 5**: Formal verification — abort 메커니즘 안전성 증명 (LTL 등)

### 10.4 권장 참고 자료 보관 위치

| 논문 | 접근 방법 |
|---|---|
| Russell 1980 | JPSP 학회 라이브러리 (대학 도서관 또는 ResearchGate) |
| Isla 2005 | gamedeveloper.com (구 Gamasutra) — 무료 공개 |
| Salichs 2014 | PMC PMC3871074 — 무료 공개 |
| Marzinotto 2014 | IEEE Xplore (ICRA 2014 proceedings) |
| Castro-González 2016 | Springer LNCS 9979 |
| Iovino 2022 | arXiv 2005.05842 — 무료 공개 |
| 보조: Colledanchise & Ögren 2018 *Behavior Trees in Robotics and AI: An Introduction* | arXiv 1709.00084 — 무료 공개 PDF |

---

## 11. 후속 보조 자료

핵심 6편 외에 호객 BT 구현 시 참고할 보조 자료:

1. **Symbolically Scaffolded Play (Figueiredo & Elumeze, 2025, arXiv:2510.25820)** — quest giver NPC가 LLM 자유 생성보다 symbolic phrase pool로 안정화되어야 함을 입증
2. **UGotMe (Li et al., 2024, arXiv:2410.18373)** — 다중인 환경에서 노이즈 제거하며 감정 인식하는 humanoid 시스템 (카페 다중 고객 환경에 직접 응용)
3. **Brock et al. (IEEE Access 2020)** — 경량 RPS 프레임워크. Leap motion 대신 MediaPipe로 Stephen 환경에 그대로 이식 가능
4. **NCBI 자기맥락 인식 감정 모델 (2024)** — 감정의 시간적 연속성과 context 통합
5. **Colledanchise & Natale 2021** — *On the Implementation of Behavior Trees in Robotics* — 실무 구현 가이드

---

*이 문서는 `cafe_npc_paper_master.md`로 저장됨. 호객 BT 시스템의 학술 척추를 한 문서에 통합한 마스터 reference. 이전 두 문서 (`cafe_npc_paper_summary.md`, `cafe_npc_paper_summary_supplement.md`)를 대체 가능.*
