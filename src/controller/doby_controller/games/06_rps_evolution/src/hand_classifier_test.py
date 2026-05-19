"""
Step 3: 5가지 손 모양 분류기 테스트
=====================================

목표: 21개 랜드마크 → 가위/바위/보/총/불사조 분류
- MediaPipe Hands로 손 인식
- 손가락 5개의 펴짐/접힘 상태 분석
- 5비트 패턴 → 손 모양 매핑
- 안정화 (최근 10프레임 중 7프레임 이상 동일 시 확정)
- 실시간 화면에 결과 표시

실행 방법:
    cd PlayWait
    python -m games.06_rps_evolution.src.hand_classifier_test

종료 방법:
    'q' 키 또는 ESC 키

Author: Stephen (gjkong)
Date: 2026-04-30
Project: PlayWait W1 - RPS Evolution
"""

import cv2
import mediapipe as mp
import time
from collections import deque, Counter


# ============================================================
# 1. MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles


# ============================================================
# 2. 손 모양 정의
# ============================================================
# 손가락 인덱스 (TIP = 끝, PIP = 둘째 마디)
# 참고: https://developers.google.com/mediapipe/solutions/vision/hand_landmarker
THUMB_TIP, THUMB_IP, THUMB_MCP = 4, 3, 2
INDEX_TIP, INDEX_PIP = 8, 6
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18
WRIST = 0

# 손 모양 매핑: (엄지, 검지, 중지, 약지, 새끼) → 이름
HAND_SHAPES = {
    (0, 0, 0, 0, 0): "rock",       # ✊ 바위
    (0, 1, 1, 0, 0): "scissors",   # ✌️ 가위
    (1, 1, 1, 1, 1): "paper",      # 🖐️ 보
    (1, 1, 0, 0, 0): "gun",        # 👉 총
    (1, 1, 0, 0, 1): "phoenix",    # 🤟 불사조
}

# 한글 이름 (UI 표시용)
SHAPE_KOREAN = {
    "rock": "바위",
    "scissors": "가위",
    "paper": "보",
    "gun": "총",
    "phoenix": "불사조",
    "unknown": "??",
}

# 이모지 (콘솔 출력용)
SHAPE_EMOJI = {
    "rock": "✊",
    "scissors": "✌️",
    "paper": "🖐️",
    "gun": "👉",
    "phoenix": "🤟",
    "unknown": "❓",
}


# ============================================================
# 3. 손가락 펴짐 판정 함수
# ============================================================
def is_finger_open(landmarks, tip_id, pip_id):
    """검지/중지/약지/새끼 펴짐 판정 (수직 방향)
    
    손이 위로 향한 자세에서, TIP이 PIP보다 위(y가 작음)에 있으면 펴진 상태.
    """
    return landmarks[tip_id].y < landmarks[pip_id].y


def is_thumb_open(landmarks, hand_label):
    """엄지 펴짐 판정 (수평 방향)
    
    엄지는 다른 손가락과 수직 관계라 x좌표로 판정.
    
    - 오른손(Right): 엄지 펴면 화면 왼쪽으로 향함 → THUMB_TIP.x < THUMB_IP.x
    - 왼손(Left): 엄지 펴면 화면 오른쪽으로 향함 → THUMB_TIP.x > THUMB_IP.x
    
    주의: 거울 모드 적용 후의 hand_label 기준
    """
    tip_x = landmarks[THUMB_TIP].x
    ip_x = landmarks[THUMB_IP].x
    
    if hand_label == "Right":
        return tip_x < ip_x
    else:  # Left
        return tip_x > ip_x


def get_finger_states(landmarks, hand_label):
    """5개 손가락의 펴짐/접힘 상태를 튜플로 반환
    
    Returns:
        (thumb, index, middle, ring, pinky) - 각 0 or 1
    """
    thumb = int(is_thumb_open(landmarks, hand_label))
    index = int(is_finger_open(landmarks, INDEX_TIP, INDEX_PIP))
    middle = int(is_finger_open(landmarks, MIDDLE_TIP, MIDDLE_PIP))
    ring = int(is_finger_open(landmarks, RING_TIP, RING_PIP))
    pinky = int(is_finger_open(landmarks, PINKY_TIP, PINKY_PIP))
    
    return (thumb, index, middle, ring, pinky)


def classify_hand_shape(finger_states):
    """손가락 상태 튜플 → 손 모양 이름
    
    매칭되는 패턴이 없으면 'unknown' 반환
    """
    return HAND_SHAPES.get(finger_states, "unknown")


# ============================================================
# 4. 안정화 (Stability Buffer)
# ============================================================
class StabilityBuffer:
    """최근 N프레임 중 K프레임 이상 동일하면 확정
    
    매 프레임 인식 결과가 흔들리는 것을 방지.
    """
    
    def __init__(self, window_size=10, threshold=7):
        self.window_size = window_size
        self.threshold = threshold
        self.buffer = deque(maxlen=window_size)
        self.confirmed_shape = "unknown"
    
    def update(self, shape):
        """새로운 인식 결과 추가, 확정된 손 모양 반환"""
        self.buffer.append(shape)
        
        if len(self.buffer) < self.window_size:
            return self.confirmed_shape
        
        # 가장 많이 나온 손 모양 찾기
        most_common, count = Counter(self.buffer).most_common(1)[0]
        
        # 임계값 이상이면 확정
        if count >= self.threshold and most_common != "unknown":
            self.confirmed_shape = most_common
        
        return self.confirmed_shape


# ============================================================
# 5. 메인 함수
# ============================================================
def main():
    # 카메라 초기화
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 카메라를 열 수 없습니다.")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    print("✅ 카메라 연결 성공")
    print("\n📌 5가지 손 모양을 만들어 보세요:")
    print("   ✊ 바위 (Rock)     - 모두 접기")
    print("   ✌️  가위 (Scissors) - 검지+중지")
    print("   🖐️ 보 (Paper)      - 모두 펴기")
    print("   👉 총 (Gun)        - 엄지+검지")
    print("   🤟 불사조 (Phoenix) - 엄지+검지+새끼")
    print("\n📌 종료: 'q' 또는 ESC\n")
    
    # 안정화 버퍼
    stability = StabilityBuffer(window_size=10, threshold=7)
    
    # FPS 측정
    prev_time = time.time()
    fps = 0.0
    
    # 마지막 콘솔 출력 손 모양 (변경시에만 출력)
    last_printed_shape = None
    
    with mp_hands.Hands(
        model_complexity=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
        max_num_hands=1,
    ) as hands:
        
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                continue
            
            # 거울 모드
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            
            # MediaPipe 처리
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False
            results = hands.process(rgb_frame)
            rgb_frame.flags.writeable = True
            
            # 결과 변수 초기화
            current_shape = "unknown"
            finger_states = (0, 0, 0, 0, 0)
            hand_label = "?"
            
            if results.multi_hand_landmarks:
                hand_landmarks = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0]
                
                # 거울 모드 보정: MediaPipe는 거울 적용 전 기준이라 뒤집어야 함
                raw_label = handedness.classification[0].label
                hand_label = "Right" if raw_label == "Left" else "Left"
                
                # 손 랜드마크 그리기
                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    mp_drawing_styles.get_default_hand_landmarks_style(),
                    mp_drawing_styles.get_default_hand_connections_style(),
                )
                
                # 손가락 상태 분석
                landmarks = hand_landmarks.landmark
                finger_states = get_finger_states(landmarks, hand_label)
                current_shape = classify_hand_shape(finger_states)
            
            # 안정화 적용
            confirmed_shape = stability.update(current_shape)
            
            # 콘솔 출력 (확정 모양이 바뀔 때만)
            if confirmed_shape != last_printed_shape and confirmed_shape != "unknown":
                emoji = SHAPE_EMOJI.get(confirmed_shape, "?")
                korean = SHAPE_KOREAN.get(confirmed_shape, "?")
                print(f"  {emoji} {korean} ({confirmed_shape}) - 손가락: {finger_states}")
                last_printed_shape = confirmed_shape
            
            # ----------------------------------------
            # UI 그리기 (영문, 한글은 PIL 필요)
            # ----------------------------------------
            # 좌상단: 정보 패널
            curr_time = time.time()
            elapsed = curr_time - prev_time
            if elapsed > 0:
                fps = 1.0 / elapsed
            prev_time = curr_time
            
            # 반투명 배경
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (450, 200), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            
            # 정보 텍스트
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(frame, f"Hand: {hand_label}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(frame, f"Fingers: {finger_states}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Raw: {current_shape}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            # 확정 손 모양 (큰 글씨, 색상 강조)
            color = (0, 255, 255) if confirmed_shape != "unknown" else (100, 100, 100)
            cv2.putText(frame, f"SHAPE: {confirmed_shape.upper()}", (10, 170),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
            
            # 우상단: 안정화 버퍼 시각화
            buffer_text = "Buffer: " + "".join([
                {"rock":"R", "scissors":"S", "paper":"P",
                 "gun":"G", "phoenix":"X", "unknown":"."}.get(s, "?")
                for s in stability.buffer
            ])
            cv2.putText(frame, buffer_text, (w - 280, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            
            # 하단: 종료 안내
            cv2.putText(frame, "Press 'q' or ESC to quit", (10, h - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            
            # 화면 표시
            cv2.imshow("PlayWait - Step 3: Hand Shape Classifier", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
    
    cap.release()
    cv2.destroyAllWindows()
    print("\n✅ 종료되었습니다.")


if __name__ == "__main__":
    main()
