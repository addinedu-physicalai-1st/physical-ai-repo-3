# 친밀감 빌드업 호객 BT 설계 v2 — 감정 인식 가중치 통합

**작성일**: 2026-05-01
**프로젝트**: Dobi Barista 호객 행위 시나리오 (engagement funnel + emotion-weighted rapport)
**상위 문서**: `cafe_npc_robot_research.md`
**핵심 컨셉**: 게임 미니이벤트로 친밀감 빌드업 → 카페 유도. 각 단계의 rapport 점수에 **고객의 실시간 감정 상태**를 가중치로 반영하여, "응답했다 / 안 했다"의 이분법을 넘어 "얼마나 즐거워했는가"를 측정한다.

---

## 1. 발상의 게임 디자인적 정합성

이 시나리오는 게임 디자인 관점에서 매우 정합적이다. 네 가지 검증된 패턴의 결합이다.

**패턴 1 — Quest Giver NPC**
RPG의 quest giver는 즉시 보상을 주지 않는다. 작은 상호작용으로 신뢰를 쌓고 본격적인 거래로 유도한다. 카페 호객 로봇이 "처음 만난 사람에게 메뉴부터 들이미는" 게 아니라 "가벼운 게임 → 친근감 → 카페 권유"로 가는 건 이 패턴 그대로다.

**패턴 2 — Affinity / Rapport System**
*Stardew Valley*, *Fire Emblem*, *Fallout 4*는 NPC와의 친밀도를 수치화(0~1000 같은 affinity score)하고, 임계값을 넘으면 새로운 dialogue branch가 열린다. 호객 로봇도 동일하게 **rapport_score**를 도입한다.

**패턴 3 — Gamification Marketing**
챗봇에 미니게임 도입 시 67%가 더 즐거워하고, 62%가 재방문 의향 증가 (2024 연구). 핵심 메커니즘: **points, badges, mini-game, reward**.

**패턴 4 — 감정 인식 기반 적응형 NPC** (NEW)
*The Sims 3*는 감정 상태(mood)에 따라 행동 utility 점수에 가중치를 곱해서 "기분 좋은 Sim은 사교적, 우울한 Sim은 회피적"으로 행동한다. 호객 로봇도 고객의 실시간 감정에 따라 rapport 점수를 차등 부여하면, "억지로 응답한 사람"과 "진짜 즐거워하는 사람"을 구분할 수 있다.

**HRI 학계 직접 증거**
- *Castro-González et al. (2016)*: 가위바위보 게임에서 친근한 톤의 로봇이 만족도를 크게 높임
- *Schulz & Utseth (HAI 2024)*: NAO 가위바위보 로봇의 목표는 "이기는 것이 아니라 engagement"
- *Salichs et al. (2014)*: GEVA(음성) + GEFA(얼굴) 다중모달 감정 인식이 단일 채널보다 정확도 향상, ROS 통합 검증됨

---

## 2. Engagement Funnel 5단계

```
[Stage 0] IDLE          ← 카페 내 순찰 중
    │ (perception trigger: 망설이는 고객 감지)
    ▼
[Stage 1] APPROACH      ← 사회적 거리 1.5m까지 접근, 가벼운 인사
    │ (response check + 감정 평가)
    ▼
[Stage 2] ICEBREAK      ← 짧은 멘트 + 미니게임 제안
    │ (consent check + 감정 평가)
    ▼
[Stage 3] MINI-GAME     ← 30초 이내 짧은 게임 (rapport 빌드업)
    │ (game outcome + 게임 내 감정 추이 평가)
    ▼
[Stage 4] OFFER         ← 친밀감 기반 메뉴 추천 + 게임 보상
    │ (acceptance + 감정 평가)
    ▼
[Stage 5] LEAD-IN       ← 카운터까지 동행 안내
    │
    ▼
[Stage 0] IDLE 복귀 + engagement_history 기록
```

각 단계에서 **drop-off**는 정상이며, BT의 fallback으로 자연스럽게 처리한다.

---

## 3. 미니게임 후보 선정

| 게임 | 입력 방식 | 실현 난이도 | 추천도 |
|---|---|---|---|
| **가위바위보** | MediaPipe 손 인식 (21 landmark) | 낮음 | ★★★★★ |
| 사이먼 세즈 | 음성 인식 + 동작 시연 | 중간 | ★★★ |
| **숫자 맞추기** | 음성 인식만 | 매우 낮음 | ★★★★ |
| 표정 따라하기 | 얼굴 표정 인식 | 중간 | ★★★ |
| **퀴즈 (커피 상식)** | 음성/터치 응답 | 낮음 | ★★★★ |
| 로봇 미러링 (춤) | OpenMANIPULATOR-X 동작 따라하기 | 중간 | ★★★ |

**가위바위보 1순위 이유**: HRI 학계 표준, MediaPipe로 즉시 구현 (Stephen 보유 vision 스택 재사용), 30초 이내, OpenMANIPULATOR-X 그리퍼로 동작 표현, 결과 의도적 조작 가능 (70% 고객 승리).

---

## 4. 감정 인식 시스템 설계 (NEW)

### 4.1 학계 표준: Russell의 Circumplex Model

감정을 두 축으로 표현하는 차원 모델이다. 분류 기반(7-emotion) 모델보다 **연속적이고, 시간에 따른 변화 추적이 쉬움**.

```
                    Arousal (high)
                         ▲
                         │
              긴장        │        흥분
              ┌──────────┼──────────┐
              │          │          │
              │  분노     │    기쁨   │
              │  공포     │    즐거움  │
              │          │          │
   Valence ◄──┼──────────┼──────────┼──► Valence
   (negative) │          │          │   (positive)
              │  슬픔     │   평온    │
              │  지루함   │   만족    │
              │          │          │
              └──────────┼──────────┘
              우울        │        편안
                         │
                         ▼
                    Arousal (low)
```

- **Valence**: -1.0 (불쾌) ~ +1.0 (유쾌)
- **Arousal**: -1.0 (차분) ~ +1.0 (활성)

호객에 가장 좋은 상태는 **(valence > 0, arousal > 0)** 우상단 사분면 = "기쁘고 활기찬" 상태.

### 4.2 EyeCon 자산 재사용

Stephen이 이미 EyeCon v3.5에서 보유한 자산:
- **13개 실시간 지표** (6 video + 7 audio): micro-expression, pupil dilation, gaze patterns 등
- **7가지 감정 분류 + radar chart**
- **Ollama EXAONE 7.8B** LLM 통합

이 자산을 다음과 같이 재사용한다:
1. EyeCon의 7-emotion 출력을 **valence/arousal 좌표로 매핑**
2. 13개 지표 중 호객 시나리오에 핵심인 것만 추출 (gaze, smile intensity, voice pitch)
3. Edge inference (현장 카페 환경) 위해 경량화 — 1.5초 latency 최적화 그대로

### 4.3 감정 → 점수 변환 매핑 테이블

7가지 감정을 (valence, arousal) 좌표로 매핑하는 표 (Russell 모델 기반):

| EyeCon 감정 분류 | Valence | Arousal | rapport 가중치 |
|---|---|---|---|
| 기쁨 (Happy)   | +0.9 | +0.6 | **×1.5** |
| 놀람 (Surprise)| +0.4 | +0.8 | **×1.3** |
| 평온 (Neutral) |  0.0 |  0.0 | ×1.0 (기준) |
| 슬픔 (Sad)     | -0.7 | -0.4 | ×0.6 |
| 지루함 (Bored) | -0.3 | -0.7 | ×0.4 |
| 분노 (Angry)   | -0.8 | +0.7 | ×0.2 |
| 혐오 (Disgust) | -0.9 | +0.2 | **×0.0** (즉시 중단) |

### 4.4 시간적 추이 (Temporal Dynamics)

단일 프레임 감정이 아니라 **engagement 동안의 평균/변화**가 더 중요하다 (2024 NCBI 연구).

```python
# 핵심 지표 3가지
emotion_baseline    = 호객 시작 시점의 valence/arousal
emotion_during      = 각 stage 동안의 평균 valence/arousal
emotion_trend       = (emotion_during - emotion_baseline)  # 양수 = 호전
```

**예시**:
- 처음엔 평온(neutral)했다가 게임 중 기쁨(happy)으로 변하면 → trend = (+0.9, +0.6) → 강한 긍정 → rapport 보너스
- 처음부터 기쁨이었다가 끝까지 기쁨이면 → 본인 성격이라 호객 영향 ≠ rapport 가중치 그대로 1.5x
- 처음엔 기쁨이었다가 지루함으로 변하면 → trend 음수 → 호객 실패 신호 → 즉시 후퇴

---

## 5. Emotion-Weighted Rapport Score (NEW)

### 5.1 데이터 구조

```python
# rapport_tracker_v2.py
from dataclasses import dataclass, field
from typing import List, Tuple
from collections import deque
import time

@dataclass
class EmotionSample:
    """단일 시점의 감정 측정값"""
    timestamp: float
    valence: float        # -1.0 ~ +1.0
    arousal: float        # -1.0 ~ +1.0
    category: str         # "happy", "neutral", ...
    confidence: float     # 0.0 ~ 1.0


@dataclass
class CustomerRapport:
    customer_id: str
    session_start: float
    rapport_score: float = 0.0          # 0~100
    interactions: list = field(default_factory=list)
    emotion_history: deque = field(default_factory=lambda: deque(maxlen=300))
    # 5분 (1Hz 샘플링) 분량의 감정 히스토리

    # 친밀도 임계값
    THRESHOLD_FRIENDLY = 30
    THRESHOLD_TRUSTED  = 60
    THRESHOLD_LEAD_OK  = 80

    # 감정 가중치 매핑
    EMOTION_WEIGHTS = {
        "happy":    1.5,
        "surprise": 1.3,
        "neutral":  1.0,
        "sad":      0.6,
        "bored":    0.4,
        "angry":    0.2,
        "disgust":  0.0,   # 가중치 0 → 즉시 호객 중단
    }

    def add_emotion_sample(self, sample: EmotionSample):
        self.emotion_history.append(sample)

    def get_recent_emotion(self, window_sec: float = 5.0) -> Tuple[float, float]:
        """최근 window_sec 동안의 평균 valence, arousal 반환"""
        now = time.time()
        recent = [s for s in self.emotion_history
                  if now - s.timestamp <= window_sec]
        if not recent:
            return (0.0, 0.0)
        avg_v = sum(s.valence * s.confidence for s in recent) / len(recent)
        avg_a = sum(s.arousal * s.confidence for s in recent) / len(recent)
        return (avg_v, avg_a)

    def get_emotion_trend(self, baseline_window: float = 3.0,
                          recent_window: float = 5.0) -> Tuple[float, float]:
        """초기 baseline 대비 최근 감정 변화량"""
        now = time.time()
        baseline_samples = [s for s in self.emotion_history
                            if (now - self.session_start) - (s.timestamp - self.session_start) >= baseline_window
                            and s.timestamp - self.session_start <= baseline_window]
        recent_samples = [s for s in self.emotion_history
                          if now - s.timestamp <= recent_window]

        if not baseline_samples or not recent_samples:
            return (0.0, 0.0)

        bv = sum(s.valence for s in baseline_samples) / len(baseline_samples)
        ba = sum(s.arousal for s in baseline_samples) / len(baseline_samples)
        rv = sum(s.valence for s in recent_samples) / len(recent_samples)
        ra = sum(s.arousal for s in recent_samples) / len(recent_samples)
        return (rv - bv, ra - ba)

    def compute_emotion_weight(self, window_sec: float = 5.0) -> float:
        """현재 감정 상태의 rapport 가중치 (0.0 ~ 1.5)"""
        # 카테고리 기반 가중치
        recent = list(self.emotion_history)[-3:]   # 최근 3샘플
        if not recent:
            return 1.0
        category_weight = sum(
            self.EMOTION_WEIGHTS.get(s.category, 1.0) * s.confidence
            for s in recent
        ) / len(recent)

        # 추이 기반 보정 (긍정적 변화면 추가 보너스)
        trend_v, trend_a = self.get_emotion_trend()
        trend_bonus = max(0.0, trend_v * 0.3)   # 최대 +0.3

        return min(1.5, category_weight + trend_bonus)

    def add_event(self, event_type: str, base_score: int):
        """이벤트 발생 시 감정 가중치 적용한 rapport 누적"""
        weight = self.compute_emotion_weight()
        weighted_delta = base_score * weight
        self.rapport_score = max(0, min(100, self.rapport_score + weighted_delta))
        self.interactions.append({
            "t": time.time(),
            "event": event_type,
            "base": base_score,
            "weight": weight,
            "delta": weighted_delta,
            "score_after": self.rapport_score,
        })

    @property
    def stage(self) -> str:
        if self.rapport_score >= self.THRESHOLD_LEAD_OK: return "LEAD_OK"
        if self.rapport_score >= self.THRESHOLD_TRUSTED: return "TRUSTED"
        if self.rapport_score >= self.THRESHOLD_FRIENDLY: return "FRIENDLY"
        return "STRANGER"

    def should_abort(self) -> bool:
        """즉시 호객 중단 조건"""
        if not self.emotion_history:
            return False
        latest = self.emotion_history[-1]
        # 분노/혐오가 confidence 0.7 이상으로 감지되면 중단
        if latest.category in ("angry", "disgust") and latest.confidence > 0.7:
            return True
        # 추이가 급격히 부정적으로 변하면 중단
        trend_v, _ = self.get_emotion_trend()
        if trend_v < -0.5:
            return True
        return False


# 이벤트별 base score (감정 가중치 적용 전 원점수)
RAPPORT_EVENTS = {
    "responded_to_greeting":   +10,
    "made_eye_contact":        +5,
    "smiled":                  +5,
    "accepted_minigame":       +20,
    "completed_minigame":      +25,
    "won_minigame":            +5,
    "lost_minigame_gracefully":+10,
    "ignored_robot":           -15,
    "explicit_refusal":        -30,
    "walked_away":             -50,
}
```

### 5.2 점수 계산 예시

**시나리오 A: 즐거운 고객**
- 인사 응답 → base +10 × emotion_weight 1.5 (happy) = **+15**
- 미니게임 수락 → base +20 × 1.5 = **+30**
- 게임 완료 (졌지만 웃음) → base +25 × 1.5 + base +10 × 1.5 = **+52.5**
- **누적 rapport ≈ 97.5 → LEAD_OK** ✅ 카운터 유도 OK

**시나리오 B: 마지못해 응대한 고객**
- 인사 응답 → base +10 × emotion_weight 0.6 (sad) = **+6**
- 미니게임 수락 → base +20 × 0.6 = **+12**
- 게임 진행 중 지루함 감지 → emotion_weight 0.4
- 게임 완료 → base +25 × 0.4 = **+10**
- **누적 rapport ≈ 28 → STRANGER 단계 머무름** → Stage 4 진입 차단, 정중히 후퇴

이렇게 하면 **억지 응대 고객을 자동으로 거른다.**

---

## 6. 통합 BT 설계 (XML, 감정 게이팅 포함)

```xml
<root BTCPP_format="4" main_tree_to_execute="DobiEngagementFunnel">

  <BehaviorTree ID="DobiEngagementFunnel">
    <Fallback name="root">

      <!-- ────────────────────────────────────────── -->
      <!-- 우선순위 1: 능동적 호객 funnel               -->
      <!-- ────────────────────────────────────────── -->
      <Sequence name="EngagementFunnel">

        <!-- 항상 백그라운드에서 감정 sampling 작동 (Parallel) -->
        <Parallel success_count="1" failure_count="1">

          <!-- 감정 모니터: should_abort 시 전체 funnel 중단 -->
          <KeepRunningUntilFailure>
            <SubTree ID="EmotionMonitor"/>
          </KeepRunningUntilFailure>

          <!-- 메인 funnel -->
          <Sequence>
            <SelectBestCustomer
                output_key="{target}"
                min_utility="0.5"
                cooldown_sec="180"/>

            <!-- baseline 감정 기록 (3초간) -->
            <RecordEmotionBaseline target="{target}" duration="3.0"/>

            <SubTree ID="ApproachStage"  target="{target}"/>
            <SubTree ID="IcebreakStage"  target="{target}"/>
            <SubTree ID="MinigameStage"  target="{target}"/>
            <SubTree ID="OfferStage"     target="{target}"/>
            <SubTree ID="LeadInStage"    target="{target}"/>

            <RecordEngagement target="{target}" outcome="converted"/>
          </Sequence>
        </Parallel>
      </Sequence>

      <!-- ────────────────────────────────────────── -->
      <!-- 우선순위 2: 호객 대상 없으면 순찰             -->
      <!-- ────────────────────────────────────────── -->
      <Sequence name="PatrolMode">
        <SelectNextWaypoint output_key="{wp}"/>
        <NavigateToPose goal="{wp}"/>
        <WaitAction wait_duration="3"/>
      </Sequence>

    </Fallback>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- 감정 모니터: 분노/혐오/급격한 부정 변화 시 즉시 abort   -->
  <!-- ====================================================== -->
  <BehaviorTree ID="EmotionMonitor">
    <Sequence>
      <SampleEmotion target="{target}"
                     output_key="{current_emotion}"/>
      <CheckShouldAbort target="{target}"/>
      <!-- abort 조건이면 FAILURE 반환 → KeepRunningUntilFailure가 종료 -->
      <Wait duration="1.0"/>   <!-- 1Hz 샘플링 -->
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 1: 사회적 접근                                    -->
  <!-- ====================================================== -->
  <BehaviorTree ID="ApproachStage">
    <Sequence>
      <ComputeSocialApproachPose
          target="{target}"
          stop_distance="1.5"
          approach_angle_deg="45"
          output_key="{approach_pose}"/>
      <NavigateToPose goal="{approach_pose}"/>
      <FaceTarget target="{target}"/>

      <ReactiveFallback>
        <CheckCustomerWalkedAway target="{target}"/>
        <Sequence>
          <SpeakRandom phrases_key="greetings"/>
          <WaitForResponse target="{target}" timeout="3.0"
                           response_key="{response_1}"/>
          <CheckResponseIsReceptive response="{response_1}"/>
          <!-- 감정 가중치 적용된 rapport 업데이트 -->
          <UpdateRapportWeighted
              target="{target}"
              event="responded_to_greeting"/>
        </Sequence>
      </ReactiveFallback>
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 2: Icebreak + 미니게임 제안                        -->
  <!-- ====================================================== -->
  <BehaviorTree ID="IcebreakStage">
    <Sequence>
      <CheckRapportStage target="{target}" min_stage="FRIENDLY"/>

      <!-- 현재 감정에 따라 icebreak 멘트 선택 -->
      <SelectIcebreakLine
          target="{target}"
          emotion_aware="true"
          output_key="{icebreak_phrase}"/>
      <Speak text="{icebreak_phrase}"/>

      <ProposeMinigame target="{target}"
                       game_options="rps,number_guess,quiz"
                       output_key="{chosen_game}"/>

      <ReactiveFallback>
        <CheckMinigameAccepted game="{chosen_game}"/>
        <Sequence>
          <SpeakRandom phrases_key="polite_decline_response"/>
          <OfferConsolationCoupon target="{target}"/>
          <RetreatFromCustomer target="{target}"/>
          <AlwaysFailure/>
        </Sequence>
      </ReactiveFallback>

      <UpdateRapportWeighted target="{target}" event="accepted_minigame"/>
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 3: 미니게임 진행                                  -->
  <!-- ====================================================== -->
  <BehaviorTree ID="MinigameStage">
    <Sequence>
      <Switch3 case="{chosen_game}"
               case_1="rps"
               case_2="number_guess"
               case_3="quiz">
        <SubTree ID="PlayRPS"         target="{target}"/>
        <SubTree ID="PlayNumberGuess" target="{target}"/>
        <SubTree ID="PlayQuiz"        target="{target}"/>
      </Switch3>

      <UpdateRapportWeighted target="{target}" event="completed_minigame"/>

      <!-- 게임 중 감정 추이 평가 → 보너스/페널티 -->
      <EvaluateGameEmotionTrend
          target="{target}"
          output_key="{emotion_trend_bonus}"/>
      <ApplyRapportBonus target="{target}"
                         delta="{emotion_trend_bonus}"/>

      <Switch2 case="{game_outcome}"
               case_1="lose_for_customer"
               case_2="win_for_customer">
        <UpdateRapportWeighted target="{target}" event="lost_minigame_gracefully"/>
        <UpdateRapportWeighted target="{target}" event="won_minigame"/>
      </Switch2>

      <PerformReactionAnimation result="{game_outcome}"/>
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 3a: 가위바위보 (감정 인식 통합)                    -->
  <!-- ====================================================== -->
  <BehaviorTree ID="PlayRPS">
    <Sequence>
      <SpeakStatic phrase="가위바위보! 손을 내밀어주세요"/>
      <RetractableTimer duration="3.0"/>

      <!-- 라운드별 게임 진행 (최대 3라운드, best of 3) -->
      <Repeat num_cycles="3">
        <Sequence>
          <Parallel success_count="2" failure_count="1">
            <DetectHandGesture target="{target}"
                               output_key="{customer_gesture}"
                               timeout="2.0"/>
            <ChooseRobotGesture
                customer_lose_probability="0.30"
                emotion_state="{target.recent_emotion}"
                previous_outcomes="{rps_history}"
                output_key="{robot_gesture}"/>
          </Parallel>

          <ExecuteManipulatorGesture gesture="{robot_gesture}"/>
          <ComputeRPSOutcome
              customer="{customer_gesture}"
              robot="{robot_gesture}"
              output_key="{round_outcome}"/>

          <!-- 감정 인식 기반 reaction 톤 조절 -->
          <SelectRPSReactionByEmotion
              outcome="{round_outcome}"
              emotion="{target.recent_emotion}"
              output_key="{reaction_phrase}"/>
          <Speak text="{reaction_phrase}"/>

          <!-- 라운드별 감정 변화 sampling -->
          <SampleEmotion target="{target}"/>
        </Sequence>
      </Repeat>
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 4: 메뉴 제안 (감정 기반 차등 추천)                 -->
  <!-- ====================================================== -->
  <BehaviorTree ID="OfferStage">
    <Sequence>
      <CheckRapportStage target="{target}" min_stage="TRUSTED"/>

      <!-- 감정 + 시간대 + rapport에 따라 톤과 메뉴 차등 -->
      <GenerateContextualMenuOffer
          target="{target}"
          rapport="{target.rapport_score}"
          emotion="{target.recent_emotion}"
          time_of_day="{current_time}"
          output_key="{offer_phrase}"/>
      <Speak text="{offer_phrase}"/>

      <!-- 게임 결과 + rapport에 따라 보상 차등 -->
      <ComputeRewardLevel
          game_outcome="{game_outcome}"
          rapport="{target.rapport_score}"
          output_key="{discount_pct}"/>
      <OfferDiscountCoupon target="{target}" discount="{discount_pct}"/>

      <WaitForResponse target="{target}" timeout="10"
                       response_key="{offer_response}"/>
      <CheckResponseAcceptsOffer response="{offer_response}"/>
    </Sequence>
  </BehaviorTree>


  <!-- ====================================================== -->
  <!-- Stage 5: 카운터 안내                                    -->
  <!-- ====================================================== -->
  <BehaviorTree ID="LeadInStage">
    <Sequence>
      <CheckRapportStage target="{target}" min_stage="LEAD_OK"/>
      <SpeakStatic phrase="제가 카운터까지 모셔다드릴게요!"/>
      <NavigateAheadOf target="{target}"
                       lead_distance="1.0"
                       destination_key="counter_pose"/>
      <WaitAtDestination target="{target}" max_wait="30"/>
      <SpeakStatic phrase="좋은 시간 되세요!"/>
    </Sequence>
  </BehaviorTree>

</root>
```

---

## 7. ROS2 노드 추가 (감정 인식 통합)

기존 `cafe_npc_robot_research.md`의 노드 구성에 다음 추가:

| 노드 이름 | 역할 | 언어 | 비고 |
|---|---|---|---|
| `emotion_perception_node` | 얼굴/음성 다중모달 감정 인식 | Python | EyeCon v3.5 재사용 |
| `valence_arousal_mapper` | 7-emotion → (V, A) 좌표 변환 | Python | 신규 |
| `rapport_tracker_node` | emotion-weighted rapport 점수 관리 | Python | 신규 |
| `emotion_aware_dialog_node` | 감정에 맞는 대화 phrase 선택 | Python | EXAONE 7.8B 활용 |
| `emotion_abort_monitor` | 분노/혐오/급격한 부정 시 abort signal | Python | 신규 |

### 7.1 토픽/서비스 인터페이스 (제안)

```
# 감정 측정 결과 publish
/customer_emotion/{customer_id}     [EmotionSample]
  - valence: float32
  - arousal: float32
  - category: string
  - confidence: float32

# rapport 상태 publish
/customer_rapport/{customer_id}     [RapportState]
  - score: float32
  - stage: string  ("STRANGER", "FRIENDLY", "TRUSTED", "LEAD_OK")
  - last_emotion_weight: float32

# abort signal (BT가 구독)
/engagement_abort                    [String]
  - customer_id
  - reason  ("anger", "disgust", "trend_negative", "walked_away")

# 감정 가중치 적용된 rapport 업데이트 서비스
/update_rapport_weighted             [UpdateRapportWeighted.srv]
  request:
    customer_id: string
    event: string
  response:
    base_score: int32
    emotion_weight: float32
    final_delta: float32
    score_after: float32
```

---

## 8. 안전장치와 윤리적 설계

게임에서 NPC를 무시할 권리가 있듯, 카페 고객도 부담 없이 거절할 권리가 보장되어야 한다.

**8.1 강제성 제거**
- 모든 stage에서 `explicit_refusal` 시 즉시 funnel 중단 + 후퇴
- "한 번 더 권유" 패턴 금지
- 거절한 고객은 24시간 또는 세션 종료까지 재접근 금지

**8.2 시간 제약**
- 전체 funnel은 90초 이내
- 각 stage timeout: Approach 10s, Icebreak 5s, Minigame 30s, Offer 10s, Lead-in 30s

**8.3 감정 기반 자동 abort 트리거** (NEW)
- `EmotionMonitor` SubTree가 1Hz로 항상 작동
- 분노/혐오 감지 (confidence > 0.7) → 즉시 후퇴 + 사과 멘트
- valence trend < -0.5 → 즉시 후퇴
- abort 시 phrase: "방해해서 죄송해요. 편한 시간 보내세요" — 사과는 짧고 1회만

**8.4 어린이 보호**
- 미성년자 추정 시 미니게임은 OK, **결제 유도는 차단**
- 보호자 확인 없이 카운터 lead-in 금지
- utility scorer에서 가중치 자동 감소

**8.5 페르소나 일관성** (Symbolically Scaffolded Play 원칙)
- 멘트는 사전 정의 phrase pool에서 선택
- LLM은 reaction 생성에만 제한적 사용
- 고객 사적 정보를 묻는 자유 대화 금지

**8.6 Cooldown / 누적 호객 방지**
```python
# 호객 대상 선정 시 추가 필터
def is_eligible_for_engagement(customer, history):
    if customer.engaged_in_last(minutes=30):       return False
    if customer.refused_today:                     return False
    if customer.abort_triggered_in_last(hours=24): return False
    if customer.is_minor and not customer.has_guardian:
        return False    # 결제 유도 단계 차단
    return True
```

**8.7 프라이버시**
- 감정 데이터는 **세션 내 메모리에만 저장, 영구 저장 금지**
- 얼굴 임베딩은 tracking ID 부여용으로만 사용, 추출 후 즉시 폐기
- engagement_history는 익명화된 통계만 누적 (개인 식별자 ❌)

---

## 9. 구현 로드맵 (감정 통합 4주 계획 수정)

기존 4주 계획에 감정 인식을 통합하면 다음과 같이 조정.

**Week 1: Perception + Awareness + Emotion Baseline**
- YOLO 사람 탐지 + tracking ID
- Awareness buildup 모델
- EyeCon 감정 인식 모듈을 ROS2 노드로 포팅
- valence/arousal mapper 작성
- RViz에 awareness + 감정 좌표 dual visualization

**Week 2: Utility AI Scorer + Emotion-Weighted Rapport**
- 6개 consideration 정의 + 응답 곡선 튜닝
- `rapport_tracker_v2.py` 구현
- 감정 가중치 검증 (시나리오 A/B 단위 테스트)

**Week 3: Mini-game + Emotion Trend Evaluation**
- 가위바위보 모듈 (MediaPipe)
- 게임 중 감정 추이 sampling 및 trend 계산
- 게임 결과 + 감정 추이 → 차등 reward 로직

**Week 4: Full BT 통합 + Demo + Safety Test**
- 5-stage funnel BT XML 작성
- EmotionMonitor parallel 통합
- abort 시나리오 5종 테스트 (분노/혐오/walk-away/timeout/refusal)
- 실측 카페 환경에서 시연

---

## 10. 결론

**감정 인식 통합의 핵심 가치 3가지**:

1. **품질(quality) 측정**: "응답했다 vs. 안 했다"의 이분법을 넘어, "얼마나 즐겁게 응답했는가"를 정량화. 마지못해 응대한 고객을 자동으로 거른다.

2. **윤리적 안전장치**: 감정 abort 트리거는 "고객이 불편해할 때 자동으로 물러나는" 기능. 이는 호객 로봇의 사회적 수용성에 결정적이다.

3. **자산 재사용**: EyeCon v3.5의 13개 지표 + 7-emotion 분류 + EXAONE 7.8B 통합 경험을 그대로 활용. **새 모델 학습 없이 즉시 적용 가능**.

**다음 단계 권장 순서**:
1. EyeCon 감정 모듈을 별도 ROS2 노드로 분리 (`emotion_perception_node`)
2. `rapport_tracker_v2.py` 단독 단위 테스트 (시나리오 A/B 시뮬레이션)
3. EmotionMonitor SubTree 단독 동작 검증 (분노/혐오 abort 5회 테스트)
4. 가위바위보 + 감정 sampling 통합 → 미니게임 stage 단독 데모
5. 전체 funnel 통합

**참고 문헌**
- Russell, J.A. (1980). *A Circumplex Model of Affect*. JPSP.
- Salichs et al. (2014). *A Multimodal Emotion Detection System during Human-Robot Interaction* (GEVA + GEFA, ROS 통합).
- Castro-González et al. (2016). *The Effects of an Impolite vs. a Polite Robot Playing Rock-Paper-Scissors*.
- Schulz & Utseth (HAI 2024). *A Rock, Paper, Scissors Robot for Engaging Interest in Research*.
- Brock et al. (2020). *Developing a Lightweight Rock-Paper-Scissors Framework for Human-Robot Collaborative Gaming*. IEEE Access.
- Li et al. (2024). *UGotMe: An Embodied System for Affective Human-Robot Interaction*. arXiv:2410.18373.
- Figueiredo & Elumeze (2025). *Symbolically Scaffolded Play* (quest giver NPC stability). arXiv:2510.25820.

---
*이 문서는 `cafe_npc_engagement_funnel.md` v2로 저장됨. EyeCon 프로젝트의 감정 인식 자산을 호객 로봇 시나리오로 확장한 첫 통합 설계 문서.*
