"""
Step 2: MediaPipe 손 인식 단독 테스트
=====================================

목표: 카메라에서 손 21개 랜드마크를 추출해 화면에 표시
- 게임 로직 X
- 손 모양 분류 X
- 오직 MediaPipe 동작 확인용

실행 방법:
    cd PlayWait
    python -m games.06_rps_evolution.src.hand_detector_test

종료 방법:
    화면 클릭 후 'q' 키 또는 ESC 키

Author: Stephen (gjkong)
Date: 2026-04-30
Project: PlayWait W1 - RPS Evolution
"""

import cv2
import mediapipe as mp
import time


# ============================================================
# 1. MediaPipe 초기화
# ============================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles


def main():
    # ============================================================
    # 2. 카메라 초기화
    # ============================================================
    # 카메라 인덱스 0 (기본 웹캠). 외장 카메라면 1, 2 시도.
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("❌ 카메라를 열 수 없습니다.")
        print("   - 다른 앱에서 카메라를 사용 중인지 확인")
        print("   - 카메라 인덱스를 0 → 1 → 2로 변경 시도")
        return

    # 해상도 설정 (1280x720 권장)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("✅ 카메라 연결 성공")
    print(f"   해상도: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    print(f"   FPS: {cap.get(cv2.CAP_PROP_FPS):.1f}")
    print("\n📌 종료: 화면을 클릭한 후 'q' 또는 ESC 키")
    print("📌 손을 카메라에 보여주세요!\n")

    # ============================================================
    # 3. MediaPipe Hands 컨텍스트
    # ============================================================
    with mp_hands.Hands(
        model_complexity=1,         # 0=가벼움, 1=정확 (기본)
        min_detection_confidence=0.7,  # 손 감지 최소 신뢰도
        min_tracking_confidence=0.5,   # 추적 최소 신뢰도
        max_num_hands=1,            # 최대 1개 손 (게임은 1인용)
    ) as hands:

        # FPS 측정용
        prev_time = time.time()
        fps = 0.0

        while cap.isOpened():
            # ----------------------------------------
            # 4. 프레임 읽기
            # ----------------------------------------
            success, frame = cap.read()
            if not success:
                print("⚠️  프레임을 읽지 못했습니다.")
                continue

            # 거울 모드 (좌우 반전): 사용자가 자연스럽게 손을 움직이도록
            frame = cv2.flip(frame, 1)

            # ----------------------------------------
            # 5. MediaPipe 처리 (BGR → RGB 변환 필수)
            # ----------------------------------------
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # 성능 최적화: 이미지를 읽기 전용으로 마크
            rgb_frame.flags.writeable = False
            results = hands.process(rgb_frame)
            rgb_frame.flags.writeable = True

            # ----------------------------------------
            # 6. 결과 시각화
            # ----------------------------------------
            if results.multi_hand_landmarks:
                for hand_landmarks, handedness in zip(
                    results.multi_hand_landmarks,
                    results.multi_handedness
                ):
                    # 21개 랜드마크와 연결선 그리기
                    mp_drawing.draw_landmarks(
                        frame,
                        hand_landmarks,
                        mp_hands.HAND_CONNECTIONS,
                        mp_drawing_styles.get_default_hand_landmarks_style(),
                        mp_drawing_styles.get_default_hand_connections_style(),
                    )

                    # 어느 손인지 표시 (Left/Right)
                    # 거울 모드라서 MediaPipe의 결과가 반대로 나옴 → 뒤집어서 표시
                    raw_label = handedness.classification[0].label
                    display_label = "Right" if raw_label == "Left" else "Left"
                    confidence = handedness.classification[0].score

                    # 손목 좌표 (랜드마크 0번)에 라벨 표시
                    h, w, _ = frame.shape
                    wrist = hand_landmarks.landmark[0]
                    wrist_x, wrist_y = int(wrist.x * w), int(wrist.y * h)
                    cv2.putText(
                        frame,
                        f"{display_label} ({confidence:.2f})",
                        (wrist_x - 50, wrist_y + 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )

                    # 디버깅: 각 손가락 끝점 좌표 표시 (선택)
                    fingertip_ids = {
                        4: "Thumb",   # 엄지
                        8: "Index",   # 검지
                        12: "Middle", # 중지
                        16: "Ring",   # 약지
                        20: "Pinky",  # 새끼
                    }
                    for tip_id, name in fingertip_ids.items():
                        tip = hand_landmarks.landmark[tip_id]
                        tip_x, tip_y = int(tip.x * w), int(tip.y * h)
                        cv2.circle(frame, (tip_x, tip_y), 8, (0, 165, 255), 2)

            # ----------------------------------------
            # 7. FPS 계산 및 표시
            # ----------------------------------------
            curr_time = time.time()
            elapsed = curr_time - prev_time
            if elapsed > 0:
                fps = 1.0 / elapsed
            prev_time = curr_time

            # 화면 좌상단에 정보 표시
            info_text = f"FPS: {fps:.1f} | Hands: {len(results.multi_hand_landmarks) if results.multi_hand_landmarks else 0}"
            cv2.putText(
                frame,
                info_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

            # 종료 안내
            cv2.putText(
                frame,
                "Press 'q' or ESC to quit",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (200, 200, 200),
                1,
            )

            # ----------------------------------------
            # 8. 화면 표시
            # ----------------------------------------
            cv2.imshow("PlayWait - Step 2: MediaPipe Hand Detection", frame)

            # 종료 키 (q 또는 ESC)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # 27 = ESC
                break

    # ============================================================
    # 9. 정리
    # ============================================================
    cap.release()
    cv2.destroyAllWindows()
    print("\n✅ 종료되었습니다.")


if __name__ == "__main__":
    main()
