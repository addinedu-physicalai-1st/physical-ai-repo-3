"""
opencv_render_test.py - OpenCV 렌더링 성능 테스트
=================================================

여러 조건으로 테스트하여 어떤 설정이 정상 작동하는지 확인.

조건 변경:
1. 해상도 (640x480 vs 1280x720)
2. 윈도우 플래그 (WINDOW_AUTOSIZE vs WINDOW_NORMAL)
3. waitKey 시간 (1ms vs 30ms)

목표: 60fps 이상 안정적 렌더링
"""

import cv2
import time
import numpy as np


def test_render_method(method_name, **config):
    """주어진 설정으로 렌더링 테스트"""
    print(f"\n{'=' * 60}")
    print(f"테스트: {method_name}")
    print(f"설정: {config}")
    print(f"{'=' * 60}")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("  ❌ 카메라 열기 실패")
        return
    
    # 해상도 설정
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.get('width', 640))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.get('height', 480))
    
    # 윈도우 생성
    win_name = f"Test - {method_name}"
    flag = config.get('window_flag', cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow(win_name, flag)
    
    if config.get('resize'):
        cv2.resizeWindow(win_name, config['width'], config['height'])
    
    # 워밍업
    for _ in range(5):
        cap.read()
    
    # 5초간 측정
    print("  5초간 측정 중...")
    start = time.time()
    frame_count = 0
    wait_ms = config.get('wait_ms', 1)
    
    while time.time() - start < 5.0:
        ret, frame = cap.read()
        if not ret:
            continue
        
        frame_count += 1
        
        # 간단한 텍스트만 추가
        cv2.putText(frame, f"FPS test - frame {frame_count}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 0), 2)
        
        cv2.imshow(win_name, frame)
        
        if cv2.waitKey(wait_ms) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    for _ in range(5):
        cv2.waitKey(1)
    
    fps = frame_count / 5.0
    print(f"  결과: {frame_count} 프레임 / 5초 = {fps:.1f} fps")
    if fps >= 25:
        print(f"  ✅ 정상 (25fps 이상)")
    elif fps >= 10:
        print(f"  ⚠️  느림")
    else:
        print(f"  ❌ 매우 느림")
    
    return fps


def main():
    print("OpenCV 렌더링 성능 테스트")
    print(f"OpenCV: {cv2.__version__}")
    
    test_configs = [
        ("기본 (640x480, AUTOSIZE)", 
         {'width': 640, 'height': 480, 'window_flag': cv2.WINDOW_AUTOSIZE, 'wait_ms': 1}),
        ("저해상도 (320x240)",
         {'width': 320, 'height': 240, 'window_flag': cv2.WINDOW_AUTOSIZE, 'wait_ms': 1}),
        ("HD (1280x720, NORMAL+resize)",
         {'width': 1280, 'height': 720, 'window_flag': cv2.WINDOW_NORMAL, 'resize': True, 'wait_ms': 1}),
        ("HD (1280x720, AUTOSIZE)",
         {'width': 1280, 'height': 720, 'window_flag': cv2.WINDOW_AUTOSIZE, 'wait_ms': 1}),
        ("waitKey 30ms (저주파)",
         {'width': 640, 'height': 480, 'window_flag': cv2.WINDOW_AUTOSIZE, 'wait_ms': 30}),
    ]
    
    results = []
    for name, config in test_configs:
        try:
            input(f"\n[Enter] '{name}' 시작 (창이 뜨고 5초 후 자동 종료)...")
            fps = test_render_method(name, **config)
            results.append((name, fps))
        except KeyboardInterrupt:
            print("\n중단됨")
            break
        except Exception as e:
            print(f"  ❌ 오류: {e}")
            results.append((name, 0))
    
    # 결과 요약
    print("\n" + "=" * 60)
    print("📋 최종 결과")
    print("=" * 60)
    for name, fps in results:
        marker = "✅" if fps >= 25 else "⚠️" if fps >= 10 else "❌"
        print(f"  {marker} {name}: {fps:.1f} fps")
    
    if results:
        best = max(results, key=lambda x: x[1])
        print(f"\n👉 최고: {best[0]} ({best[1]:.1f} fps)")
        if best[1] < 25:
            print("\n⚠️  모든 설정에서 25fps 미만 → 시스템 GPU/드라이버 문제")
            print("\n해결책:")
            print("  1. sudo apt install python3-opencv  (시스템 패키지)")
            print("  2. opencv-contrib-python 으로 변경")
            print("  3. AMD GPU 드라이버 업데이트")


if __name__ == "__main__":
    main()
