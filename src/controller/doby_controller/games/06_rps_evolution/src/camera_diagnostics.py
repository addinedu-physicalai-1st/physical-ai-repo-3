"""
camera_diagnostics.py - 카메라 진단 스크립트
============================================

게임 실행 전 카메라 상태를 정확히 확인.
실제 지원 해상도, 프레임 읽기 정상 여부, OpenCV 윈도우 표시 가능 여부 검증.

실행:
    cd ~/PlayWait/games/06_rps_evolution/src
    python camera_diagnostics.py
"""

import cv2
import sys
import os


def test_camera_indices():
    """사용 가능한 카메라 인덱스 탐색"""
    print("=" * 60)
    print("[Test 1] 사용 가능한 카메라 탐색")
    print("=" * 60)
    
    available = []
    for idx in range(4):  # 0~3 시도
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                print(f"  ✅ Camera {idx}: 사용 가능 ({w}x{h})")
                available.append((idx, w, h))
            else:
                print(f"  ⚠️  Camera {idx}: 열림, but 프레임 읽기 실패")
            cap.release()
        else:
            print(f"  ❌ Camera {idx}: 열기 실패")
    
    return available


def test_resolution(camera_idx):
    """해상도 변경 가능 여부 확인"""
    print(f"\n{'=' * 60}")
    print(f"[Test 2] 카메라 {camera_idx} 해상도 테스트")
    print(f"{'=' * 60}")
    
    cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        print(f"  ❌ 카메라 {camera_idx} 열기 실패")
        return None
    
    # 기본 해상도
    default_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    default_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    default_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"  기본 해상도: {default_w}x{default_h} @ {default_fps:.0f}fps")
    
    # 1280x720 시도
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    # 실제 적용된 해상도 확인
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  요청: 1280x720 → 실제: {actual_w}x{actual_h}")
    
    # 프레임 읽기 시도 (5번)
    success_count = 0
    for i in range(5):
        ret, frame = cap.read()
        if ret and frame is not None:
            success_count += 1
    print(f"  프레임 읽기 성공률: {success_count}/5")
    
    if success_count > 0:
        print(f"  실제 프레임 shape: {frame.shape}")
    
    cap.release()
    return (actual_w, actual_h, success_count)


def test_window_display(camera_idx):
    """OpenCV 윈도우 표시 테스트 (5초)"""
    print(f"\n{'=' * 60}")
    print(f"[Test 3] 카메라 {camera_idx} 윈도우 표시 테스트 (5초)")
    print(f"{'=' * 60}")
    print("  카메라 영상이 보이면 ✅, 검은 화면이면 ❌")
    print("  종료: 'q' 키 또는 5초 자동 종료")
    
    cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        print(f"  ❌ 카메라 {camera_idx} 열기 실패")
        return False
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    # 영문 제목 사용 (한글 깨짐 방지)
    window_name = "Camera Test - Press q to quit"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)
    
    import time
    start_time = time.time()
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("  ⚠️  프레임 읽기 실패")
            break
        
        frame_count += 1
        
        # 간단한 텍스트 오버레이 (영문)
        h, w = frame.shape[:2]
        cv2.putText(frame, f"Camera Test - Frame {frame_count}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"Resolution: {w}x{h}",
                    (20, 80), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 0), 2)
        cv2.putText(frame, "Press 'q' to quit",
                    (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (200, 200, 200), 1)
        
        cv2.imshow(window_name, frame)
        
        elapsed = time.time() - start_time
        if elapsed > 5.0:
            print(f"  ✅ 5초 경과, 프레임 수: {frame_count} (목표: 100+)")
            break
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    
    # 윈도우 종료 보장
    for _ in range(4):
        cv2.waitKey(1)
    
    return frame_count > 50


def main():
    print("\n" + "=" * 60)
    print("PlayWait 카메라 진단 스크립트")
    print("=" * 60)
    
    # OpenCV 환경 정보
    print(f"\nOpenCV 버전: {cv2.__version__}")
    print(f"DISPLAY: {os.environ.get('DISPLAY', '(없음)')}")
    print(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '(없음)')}")
    print(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE', '(없음)')}")
    print(f"QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', '(기본)')}")
    
    # Test 1: 카메라 인덱스
    available = test_camera_indices()
    if not available:
        print("\n❌ 사용 가능한 카메라가 없습니다!")
        print("\n해결 방법:")
        print("  1. 카메라가 다른 프로그램에 점유되어 있는지 확인")
        print("     $ sudo fuser -k /dev/video0")
        print("  2. 카메라 권한 확인")
        print("     $ ls -la /dev/video*")
        return
    
    # 가장 좋은 카메라 선택 (해상도 큰 것)
    best_camera = max(available, key=lambda x: x[1] * x[2])
    camera_idx = best_camera[0]
    print(f"\n→ 최선의 카메라: index {camera_idx}")
    
    # Test 2: 해상도
    res_result = test_resolution(camera_idx)
    
    # Test 3: 윈도우 표시 (대화식)
    print(f"\n5초간 카메라 영상이 표시됩니다. 화면 확인해주세요...")
    input("준비되면 Enter 눌러주세요...")
    
    display_ok = test_window_display(camera_idx)
    
    # 최종 진단
    print("\n" + "=" * 60)
    print("📋 진단 결과 요약")
    print("=" * 60)
    
    print(f"  사용 가능 카메라: {len(available)}개")
    print(f"  추천 카메라 인덱스: {camera_idx}")
    if res_result:
        actual_w, actual_h, success = res_result
        print(f"  실제 적용 해상도: {actual_w}x{actual_h}")
        print(f"  프레임 읽기 성공: {success}/5")
    print(f"  윈도우 표시 정상: {'✅ 예' if display_ok else '❌ 아니오'}")
    
    if display_ok and res_result and res_result[2] >= 4:
        print("\n✅ 카메라 정상! 게임 실행 가능")
        print(f"\n💡 game.py에서 카메라 인덱스가 {camera_idx} 인지 확인")
    else:
        print("\n⚠️  문제가 있습니다. 위 결과를 알려주세요.")


if __name__ == "__main__":
    main()
