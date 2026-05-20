# 발화 요청 — multi-mode → dialog_router → tts_node
# 페르소나/모드별 voice 메타데이터를 함께 전달해 한 메시지로 모든 정보 캡슐.
# voice/rate/pitch는 엔진 중립적 string. v1은 edge-tts SSML 형식 사용:
#   voice: "ko-KR-SunHiNeural"   (edge-tts voice ID)
#   rate:  "+0%"  ~ "+100%"      (SSML rate)
#   pitch: "+0Hz" ~ "+50Hz"      (SSML pitch)
# 미래 엔진 교체 시 같은 토픽 그대로 두고 tts_node 구현만 변경.

std_msgs/Header header

string text                 # 발화할 텍스트
string voice                # 엔진별 voice ID
string rate                 # 속도 hint (엔진별 형식)
string pitch                # 피치 hint (엔진별 형식)

# face/utter 시작 동기화 — tts_node가 합성 후 mixer.play 직전에 이 값을
# /face_avatar/expression에 발행. 빈 문자열이면 face 변경 없음 (이전 표정 유지).
string face_expression      # 8 어휘: basic|hello|happy|fun|interest|bored|sad|angry

string persona_id           # 디버깅/추적
string stage_id             # 디버깅/추적 (icebreak/offer/leadin 등)

# === dialog_router 라우팅 메타데이터 (멀티 모드 단일 출력 채널) ===
# source: 발화 요청 모드 식별. priority가 동일할 때 큐잉 순서 + 디버깅 추적.
#   값: "npc" | "serving" | "follow" | "operator" | "safety" | ""(legacy)
string source

# priority: 낮을수록 우선. dialog_router 큐잉 + preempt 판단 입력.
#   0=safety alarm  10=operator  20=serving  30=npc  255=lowest
uint8 priority

# preempt: true면 현재 진행 중 발화/face 즉시 중단 후 본 요청 즉시 재생.
#   false면 큐잉. safety alarm/operator 강제 발화에 사용.
bool preempt
