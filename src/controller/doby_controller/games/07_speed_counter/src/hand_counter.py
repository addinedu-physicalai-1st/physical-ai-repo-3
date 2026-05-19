"""
hand_counter.py - 양손 손가락 합산기
======================================

W1 (가위바위보 진화) 의 손 모양 분류기를 응용하여 양손의 펴진 손가락
총 개수를 합산. 0~10 범위 출력.

W1 대비 핵심 변경:
- max_num_hands=2 (한 손 → 양손)
- 출력이 손 모양 이름 → 손가락 총 개수
- 안정화 윈도우 10/7 → 5/4 (반응 속도 향상)

단독 실행 테스트:
    cd ~/PlayWait
    python -m games.07_speed_counter.src.hand_counter

또는:
    cd ~/PlayWait/games/07_speed_counter/src
    python hand_counter.py

종료: 'q' 키 또는 ESC

Author: Stephen (gjkong)
Date: 2026-04-30 (W2 Step 2)
"""

import os
import sys
import cv2
import time
import mediapipe as mp
from collections import deque, Counter


# ============================================================
# 1. MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles


# ============================================================
# 2. 손가락 인덱스 (W1과 동일)
# ============================================================
THUMB_TIP, THUMB_IP = 4, 3
INDEX_TIP, INDEX_PIP = 8, 6
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18


# ============================================================
# 3. 손가락 펴짐 판정 함수 (W1 재활용)
# ============================================================
def is_finger_open(landmarks, tip_id, pip_id):
    """검지/중지/약지/새끼 펴짐 판정 (수직 비교)"""
    return landmarks[tip_id].y < landmarks[pip_id].y


def is_thumb_open(landmarks, hand_label: str) -> bool:
    """엄지 펴짐 판정 (수평 비교, 좌우 손 자동 처리)
    
    Args:
        hand_label: "Right" or "Left" (거울 모드 적용 후)
    """
    tip_x = landmarks[THUMB_TIP].x
    ip_x = landmarks[THUMB_IP].x
    if hand_label == "Right":
        return tip_x < ip_x
    else:
        return tip_x > ip_x


def count_fingers_one_hand(landmarks, hand_label: str) -> int:
    """한 손의 펴진 손가락 개수 (0~5)"""
    count = 0
    if is_thumb_open(landmarks, hand_label):
        count += 1
    if is_finger_open(landmarks, INDEX_TIP, INDEX_PIP):
        count += 1
    if is_finger_open(landmarks, MIDDLE_TIP, MIDDLE_PIP):
        count += 1
    if is_finger_open(landmarks, RING_TIP, RING_PIP):
        count += 1
    if is_finger_open(landmarks, PINKY_TIP, PINKY_PIP):
        count += 1
    return count


# ============================================================
# 4. 양손 합산 함수 (W2 신규)
# ============================================================
def count_fingers_total(results) -> dict:
    """MediaPipe 결과에서 양손 손가락 총 개수 계산
    
    Args:
        results: mp_hands.process() 의 결과
    
    Returns:
        {
            "total": int (0~10),  # 합산 (인식 실패 시 None)
            "left": int or None,  # 왼손 개수
            "right": int or None, # 오른손 개수
            "hands_count": int,   # 인식된 손 개수 (0/1/2)
        }
    """
    result = {
        "total": None,
        "left": None,
        "right": None,
        "hands_count": 0,
    }
    
    if not results.multi_hand_landmarks:
        return result
    
    result["hands_count"] = len(results.multi_hand_landmarks)
    total = 0
    
    for hand_landmarks, handedness in zip(
        results.multi_hand_landmarks,
        results.multi_handedness
    ):
        # 거울 모드 보정 (W1과 동일)
        raw_label = handedness.classification[0].label
        hand_label = "Right" if raw_label == "Left" else "Left"
        
        # 한 손 손가락 개수
        count = count_fingers_one_hand(hand_landmarks.landmark, hand_label)
        total += count
        
        # 좌/우 결과 저장
        if hand_label == "Left":
            result["left"] = count
        else:
            result["right"] = count
    
    result["total"] = total
    return result


# ============================================================
# 5. 안정화 버퍼 (W2 - 윈도우 5/4 로 빠른 확정)
# ============================================================
class StabilityBuffer:
    """최근 N프레임 중 K프레임 이상 동일하면 확정 (W2 빠른 반응 버전)"""
    
    def __init__(self, window_size: int = 5, threshold: int = 4):
        self.window_size = window_size
        self.threshold = threshold
        self.buffer = deque(maxlen=window_size)
        self.confirmed = None
    
    def update(self, value):
        """새 값 추가 후 확정값 반환"""
        self.buffer.append(value)
        if len(self.buffer) < self.window_size:
            return self.confirmed
        
        most_common, count = Counter(self.buffer).most_common(1)[0]
        if count >= self.threshold and most_common is not None:
            self.confirmed = most_common
        
        return self.confirmed
    
    def reset(self):
        self.buffer.clear()
        self.confirmed = None


# ============================================================
# 6. 단독 테스트 (이 파일 직접 실행 시)
# ============================================================
def _self_test():
    """카메라로 양손 손가락 합산 시각화"""
    print("=" * 50)
    print("hand_counter.py 단독 테스트")
    print("=" * 50)
    print("\n양손을 카메라에 보여주세요.")
    print("- 1~10 사이의 숫자를 손가락으로 만들어 보세요")
    print("- 화면에 합산된 숫자가 표시됩니다")
    print("\n종료: 'q' 또는 ESC")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("\n❌ 카메라를 열 수 없습니다.")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    stability = StabilityBuffer(window_size=5, threshold=4)
    last_printed = None
    
    prev_time = time.time()
    fps = 0.0
    
    with mp_hands.Hands(
        model_complexity=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
        max_num_hands=2,  # ★ W2 핵심: 두 손
    ) as hands:
        
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                continue
            
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            
            # MediaPipe 처리
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False
            results = hands.process(rgb_frame)
            rgb_frame.flags.writeable = True
            
            # 손가락 합산
            count_result = count_fingers_total(results)
            confirmed = stability.update(count_result["total"])
            
            # 변경 시 콘솔 출력
            if (confirmed is not None and confirmed != last_printed):
                print(f"  ✋ 합계: {confirmed}  "
                      f"(왼손 {count_result['left']}, 오른손 {count_result['right']})")
                last_printed = confirmed
            
            # 양손 랜드마크 그리기
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    mp_drawing.draw_landmarks(
                        frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                        mp_drawing_styles.get_default_hand_landmarks_style(),
                        mp_drawing_styles.get_default_hand_connections_style(),
                    )
            
            # FPS
            curr_time = time.time()
            elapsed = curr_time - prev_time
            if elapsed > 0:
                fps = 1.0 / elapsed
            prev_time = curr_time
            
            # ----------------------------------------
            # UI (영문, 단독 테스트라 간단하게)
            # ----------------------------------------
            # 좌상단 정보 패널
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (350, 130), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
            
            cv2.putText(frame, f"FPS: {fps:.0f}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, f"Hands: {count_result['hands_count']}",
                        (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            left_str = str(count_result['left']) if count_result['left'] is not None else "-"
            right_str = str(count_result['right']) if count_result['right'] is not None else "-"
            cv2.putText(frame, f"L: {left_str}  R: {right_str}",
                        (10, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # 합계 (큰 글씨)
            total_str = str(confirmed) if confirmed is not None else "-"
            cv2.putText(frame, f"TOTAL: {total_str}",
                        (10, 115),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                        (0, 255, 255) if confirmed is not None else (100, 100, 100),
                        2)
            
            # 화면 중앙에 큰 숫자
            if confirmed is not None:
                cx = w // 2
                cy = h // 2
                # 배경 원
                cv2.circle(frame, (cx, cy), 80, (0, 0, 0), -1)
                cv2.circle(frame, (cx, cy), 80, (0, 255, 255), 3)
                # 숫자 (영문 - cv2 native)
                text_str = str(confirmed)
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 4.0
                thickness = 8
                text_size = cv2.getTextSize(text_str, font, scale, thickness)[0]
                tx = cx - text_size[0] // 2
                ty = cy + text_size[1] // 2
                cv2.putText(frame, text_str, (tx, ty),
                            font, scale, (0, 255, 255), thickness)
            
            # 안정화 버퍼 시각화 (디버그)
            buffer_text = "Buffer: " + " ".join([
                str(v) if v is not None else "-" 
                for v in stability.buffer
            ])
            cv2.putText(frame, buffer_text, (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 200, 200), 1)
            
            # 종료 안내
            cv2.putText(frame, "Press 'q' or ESC to quit",
                        (w - 280, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 200, 200), 1)
            
            cv2.imshow("PlayWait W2 - Hand Counter Test", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
    
    cap.release()
    cv2.destroyAllWindows()
    print("\n✅ 종료")


if __name__ == "__main__":
    _self_test()
