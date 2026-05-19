"""
finger_tracker.py — 검지 끝 추적 + 스와이프 detection
======================================================

W3 카페 닌자의 핵심 입력 모듈.
MediaPipe Hands에서 검지 끝(landmark 8)의 픽셀 좌표를 추적하여
최근 프레임 궤적, 이동 속도, 슬라이스 판정에 필요한 기하 함수를 제공.

설계 원칙:
- **순수 로직과 vision 래퍼 분리**
  - FingerTrail / point_to_segment_distance / segment_speed 는 좌표 튜플만 다룸 → 단위 테스트 가능
  - get_index_tip_pixel만 MediaPipe 의존
- W1·W2의 StabilityBuffer 같은 안정화 X (액션 게임은 즉시 반응이 중요)

단독 실행:
    cd ~/PlayWait
    python -m games.01_cafe_ninja.src.finger_tracker

종료: 'q' 또는 ESC

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 2)
"""

import math
import os
import sys
from collections import deque


# ============================================================
# 1. 상수
# ============================================================
INDEX_TIP = 8  # MediaPipe Hands landmark index

# 슬라이스 판정 기준 (640x480 @ 30fps 기준 픽셀/프레임)
DEFAULT_SLICE_SPEED_THRESHOLD = 25.0   # px/frame ≈ 750 px/s
DEFAULT_TRAIL_LENGTH = 10              # 화면에 그릴 트레일 길이


# ============================================================
# 2. 순수 함수 (단위 테스트 대상)
# ============================================================
def segment_speed(p1, p2) -> float:
    """두 좌표 사이 유클리드 거리 (= 1프레임 당 이동 픽셀)

    Args:
        p1, p2: (x, y) 튜플
    Returns:
        픽셀 단위 거리 (음수 X)
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.hypot(dx, dy)


def point_to_segment_distance(point, seg_start, seg_end) -> float:
    """점에서 선분까지의 최단 거리

    Step 4 충돌 판정의 핵심 함수. 검지 끝의 직전→현재 이동 선분과
    객체 중심 사이의 거리를 계산해, 객체 반지름 이내면 슬라이스 성공.

    Args:
        point: (x, y) — 객체 중심
        seg_start, seg_end: (x, y) — 선분 양 끝점
    Returns:
        최단 거리 (px)
    """
    px, py = point
    x1, y1 = seg_start
    x2, y2 = seg_end

    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0.0:
        # 선분이 한 점 → 점-점 거리
        return math.hypot(px - x1, py - y1)

    # 점을 선분 위에 투영한 매개변수 t (0~1 범위 외이면 끝점에 클램프)
    t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    # 선분 위 가장 가까운 점
    cx = x1 + t * dx
    cy = y1 + t * dy
    return math.hypot(px - cx, py - cy)


# ============================================================
# 3. FingerTrail 클래스 (순수 로직)
# ============================================================
class FingerTrail:
    """최근 N프레임 검지 끝 좌표 버퍼 + 속도 + 슬라이스 상태

    프레임마다 update(pos)로 좌표를 push하고,
    is_slicing() / get_segment() / get_trail() 로 상태 조회.

    좌표가 None(인식 실패)이면 트레일을 끊는다(연속 슬라이스 방지).
    """

    def __init__(self,
                 max_length: int = DEFAULT_TRAIL_LENGTH,
                 slice_speed_threshold: float = DEFAULT_SLICE_SPEED_THRESHOLD):
        self.max_length = max_length
        self.threshold = slice_speed_threshold
        self.points = deque(maxlen=max_length)  # [(x, y), ...]

    def update(self, pos):
        """현재 프레임의 검지 끝 좌표 push

        Args:
            pos: (x, y) 또는 None
        """
        if pos is None:
            # 손 사라지면 트레일 단절 (이전과 새 위치를 잇지 않도록)
            self.points.clear()
        else:
            self.points.append((pos[0], pos[1]))

    def reset(self):
        self.points.clear()

    def get_trail(self) -> list:
        """전체 트레일 좌표 (오래된 순)"""
        return list(self.points)

    def get_segment(self):
        """가장 최근 두 좌표 (직전→현재) — 충돌 판정용 선분

        Returns:
            (p_prev, p_curr) 또는 None (점이 2개 미만)
        """
        if len(self.points) < 2:
            return None
        return (self.points[-2], self.points[-1])

    def get_current_speed(self) -> float:
        """가장 최근 프레임 이동 속도 (px/frame). 점 < 2면 0.0"""
        seg = self.get_segment()
        if seg is None:
            return 0.0
        return segment_speed(seg[0], seg[1])

    def is_slicing(self) -> bool:
        """현재 슬라이스 중인지 (최근 속도 >= threshold)"""
        return self.get_current_speed() >= self.threshold


# ============================================================
# 4. Vision 래퍼 (MediaPipe 의존)
# ============================================================
def get_index_tip_pixel(hand_landmarks, frame_w: int, frame_h: int):
    """MediaPipe HandLandmarks에서 검지 끝 픽셀 좌표 추출

    Args:
        hand_landmarks: mp_hands.process() 결과의 multi_hand_landmarks[i]
        frame_w, frame_h: 프레임 크기 (cv2 기준)
    Returns:
        (x_px, y_px) 정수 튜플
    """
    tip = hand_landmarks.landmark[INDEX_TIP]
    return (int(tip.x * frame_w), int(tip.y * frame_h))


def get_hand_bbox(hand_landmarks, frame_w: int, frame_h: int):
    """21개 landmark의 픽셀 bounding box

    Returns:
        (x_min, y_min, x_max, y_max) 정수 튜플. 손이 화면 밖이면 일부 클립 가능.
    """
    xs = [int(lm.x * frame_w) for lm in hand_landmarks.landmark]
    ys = [int(lm.y * frame_h) for lm in hand_landmarks.landmark]
    return (min(xs), min(ys), max(xs), max(ys))


# ============================================================
# 5. 단독 실행 테스트 (카메라 + 시각화)
# ============================================================
def _self_test():
    """카메라에서 검지 끝 트레일 + 슬라이스 상태 시각화"""
    import time
    import cv2
    import mediapipe as mp

    print("=" * 50)
    print("finger_tracker.py 단독 테스트")
    print("=" * 50)
    print("\n검지를 빠르게 휘저으면 핑크 트레일이 굵어집니다.")
    print(f"슬라이스 속도 임계: {DEFAULT_SLICE_SPEED_THRESHOLD:.0f} px/frame")
    print("\n종료: 'q' 또는 ESC\n")

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 카메라를 열 수 없습니다.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    trail = FingerTrail()
    fps = 0.0
    prev_t = time.time()

    with mp_hands.Hands(
        model_complexity=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
        max_num_hands=1,  # W3은 한 손 (검지 하나로 베기)
    ) as hands:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                continue

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            rgb.flags.writeable = True

            # 검지 끝 좌표 추출
            tip_px = None
            if results.multi_hand_landmarks:
                hl = results.multi_hand_landmarks[0]
                tip_px = get_index_tip_pixel(hl, w, h)
                mp_drawing.draw_landmarks(
                    frame, hl, mp_hands.HAND_CONNECTIONS
                )

            trail.update(tip_px)

            # 트레일 그리기 (오래된 점 → 최신 점, 굵기와 색 그라데이션)
            pts = trail.get_trail()
            if len(pts) >= 2:
                slicing = trail.is_slicing()
                base_color = (157, 107, 255) if slicing else (180, 180, 180)
                for i in range(1, len(pts)):
                    alpha = i / len(pts)
                    thickness = max(1, int(8 * alpha))
                    color = tuple(int(c * alpha) for c in base_color)
                    cv2.line(frame, pts[i - 1], pts[i],
                             color, thickness, cv2.LINE_AA)

            # 검지 끝 강조
            if tip_px is not None:
                color = (157, 107, 255) if trail.is_slicing() else (200, 200, 200)
                cv2.circle(frame, tip_px, 12, color, -1)
                cv2.circle(frame, tip_px, 12, (255, 255, 255), 2)

            # FPS
            now = time.time()
            dt = now - prev_t
            if dt > 0:
                fps = 1.0 / dt
            prev_t = now

            # HUD
            speed = trail.get_current_speed()
            hud = [
                f"FPS: {fps:.0f}",
                f"Speed: {speed:.1f} px/frame",
                f"Slicing: {'YES' if trail.is_slicing() else 'no'}",
            ]
            for i, line in enumerate(hud):
                cv2.putText(frame, line, (10, 25 + i * 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            (0, 255, 0), 2)

            cv2.imshow("PlayWait W3 - Finger Tracker Test", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break

    cap.release()
    cv2.destroyAllWindows()
    print("\n✅ 종료")


if __name__ == "__main__":
    _self_test()
