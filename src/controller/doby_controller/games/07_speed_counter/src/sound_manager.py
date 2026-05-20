"""
sound_manager.py - 사운드 관리자
==================================

pygame.mixer 기반 사운드 재생.
파일이 없으면 콘솔 로그로 폴백 (게임은 정상 진행).

Author: Stephen (gjkong)
Date: 2026-04-30
"""

import os
import sys

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from . import theme
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import theme


# ============================================================
# 1. pygame 초기화 (선택적)
# ============================================================
try:
    import pygame
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.mixer.init()
    PYGAME_AVAILABLE = True
    print("✅ pygame 사운드 시스템 초기화 완료")
except Exception as e:
    PYGAME_AVAILABLE = False
    print(f"⚠️  pygame 초기화 실패: {e}")
    print("   → 사운드 없이 진행됩니다.")


# ============================================================
# 2. SoundManager 클래스
# ============================================================
class SoundManager:
    """사운드 로드 및 재생 관리
    
    사운드 파일이 없으면 콘솔 텍스트로 폴백.
    """
    
    def __init__(self, sounds_dir: str):
        """
        Args:
            sounds_dir: 사운드 파일 폴더 경로
        """
        self.sounds_dir = sounds_dir
        self.sounds = {}
        self.enabled = PYGAME_AVAILABLE
        
        if self.enabled:
            self._load_sounds()
    
    def _load_sounds(self):
        """theme.SOUND_FILES에 정의된 모든 사운드 로드"""
        loaded_count = 0
        missing = []
        
        for sound_name, filename in theme.SOUND_FILES.items():
            file_path = os.path.join(self.sounds_dir, filename)
            
            if os.path.exists(file_path):
                try:
                    sound = pygame.mixer.Sound(file_path)
                    self.sounds[sound_name] = sound
                    loaded_count += 1
                except pygame.error as e:
                    print(f"⚠️  '{filename}' 로드 실패: {e}")
                    missing.append(filename)
            else:
                missing.append(filename)
        
        # 로드 결과 출력
        total = len(theme.SOUND_FILES)
        print(f"🎵 사운드 로드: {loaded_count}/{total}")
        
        if missing:
            print(f"   누락된 파일 ({len(missing)}개):")
            for f in missing:
                print(f"      - {f}")
            print(f"   저장 위치: {self.sounds_dir}")
            print(f"   → 누락 사운드는 콘솔 텍스트로 대체됩니다.")
    
    def play(self, sound_name: str, volume: float = 1.0):
        """사운드 재생 (논블로킹)
        
        Args:
            sound_name: 사운드 키 이름 ("countdown", "win" 등)
            volume: 볼륨 (0.0 ~ 1.0)
        """
        # 폴백: 사운드 없으면 콘솔 출력
        if not self.enabled or sound_name not in self.sounds:
            print(f"  [♪ {sound_name}]")
            return
        
        try:
            sound = self.sounds[sound_name]
            sound.set_volume(max(0.0, min(1.0, volume)))
            sound.play()
        except Exception as e:
            print(f"⚠️  '{sound_name}' 재생 실패: {e}")
    
    def stop_all(self):
        """모든 사운드 즉시 정지"""
        if self.enabled:
            pygame.mixer.stop()
    
    def cleanup(self):
        """pygame 정리"""
        if self.enabled:
            pygame.mixer.stop()
            pygame.mixer.quit()


# ============================================================
# 3. 자체 테스트 (이 파일을 직접 실행 시)
# ============================================================
def _self_test():
    """6개 사운드를 차례로 재생"""
    import time
    
    # 사운드 폴더 자동 탐색
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sounds_dir = os.path.join(
        os.path.dirname(current_dir), "assets", "sounds"
    )
    
    print(f"\n사운드 폴더: {sounds_dir}\n")
    
    sm = SoundManager(sounds_dir)
    
    print("\n=== 사운드 테스트 시작 ===")
    test_sequence = [
        ("click", "메뉴 클릭"),
        ("countdown", "카운트다운"),
        ("reveal", "공개 효과"),
        ("win", "라운드 승리"),
        ("lose", "라운드 패배"),
        ("victory", "최종 우승!"),
    ]
    
    for sound_name, desc in test_sequence:
        print(f"\n▶️  {desc} ({sound_name})")
        sm.play(sound_name)
        time.sleep(1.5)  # 사운드 끝나기 대기
    
    print("\n✅ 테스트 완료")
    sm.cleanup()


if __name__ == "__main__":
    _self_test()
