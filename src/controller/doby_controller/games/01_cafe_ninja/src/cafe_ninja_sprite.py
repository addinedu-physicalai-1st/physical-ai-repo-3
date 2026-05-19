"""
cafe_ninja_sprite.py — 닌자 마스코트 스프라이트 + 알파 오버레이
================================================================

OpenGameArt "Ninja Adventure" (pzUH, CC0) 챠비 닌자 PNG 시퀀스를 로드해
idle/attack/throw 상태 머신으로 코너 마스코트를 렌더링한다.

설계:
- 프레임 로드 시 target_height 기준으로 한 번 리사이즈 → 캐시 (매 프레임 리사이즈 비용 0)
- 상태 만료 시간(set_state duration) 지나면 자동 idle 복귀
- BGRA → BGR 알파 블렌딩 헬퍼는 모듈 함수 overlay_bgra()

Author: Stephen (gjkong)
Date: 2026-05-18 (폴리싱 1차)
"""

import os
import time

import cv2
import numpy as np


# ============================================================
# 1. 상태 상수
# ============================================================
STATE_IDLE = "idle"
STATE_ATTACK = "attack"
STATE_THROW = "throw"

ALL_STATES = (STATE_IDLE, STATE_ATTACK, STATE_THROW)


# ============================================================
# 2. NinjaSprite — 프레임 로더 + 상태 머신
# ============================================================
class NinjaSprite:
    """닌자 마스코트 애니메이션 상태 머신

    Attributes:
        target_height: 리사이즈된 높이 (가로는 원본 비율 유지)
        frame_interval: 다음 프레임 진행 간격 (초)
        state: 현재 상태 (STATE_IDLE / ATTACK / THROW)

    사용:
        sprite = NinjaSprite(sprite_root, target_height=220, fps=12)
        sprite.set_state(STATE_ATTACK, duration=0.5)  # 일시 발동
        sprite.update()                               # 매 프레임 호출
        frame_bgra = sprite.current_frame()           # 그릴 BGRA np.ndarray
    """

    def __init__(self, sprite_root: str, target_height: int = 220, fps: int = 12):
        self.sprite_root = sprite_root
        self.target_height = target_height
        self.frame_interval = 1.0 / fps

        self._frames = {}
        for state in ALL_STATES:
            self._frames[state] = self._load_state(state)

        self.state = STATE_IDLE
        self.frame_idx = 0
        self.last_frame_time = time.time()
        self.state_end_time = 0.0  # 0 = 무한 루프 (idle 전용)

    def _load_state(self, state: str) -> list:
        d = os.path.join(self.sprite_root, state)
        if not os.path.isdir(d):
            raise FileNotFoundError(f"스프라이트 폴더 없음: {d}")

        files = sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))
        if not files:
            raise FileNotFoundError(f"{d}에 PNG 프레임 없음")

        frames = []
        for f in files:
            path = os.path.join(d, f)
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                raise IOError(f"이미지 로드 실패: {path}")
            if img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

            h, w = img.shape[:2]
            scale = self.target_height / h
            new_w = max(1, int(round(w * scale)))
            resized = cv2.resize(
                img, (new_w, self.target_height),
                interpolation=cv2.INTER_AREA,
            )
            frames.append(resized)
        return frames

    # ------------------------------------------------------------
    # 상태 전이
    # ------------------------------------------------------------
    def set_state(self, state: str, duration: float = 0.5):
        """비-idle 상태를 duration 초간 발동. 종료 후 자동 idle 복귀."""
        if state not in ALL_STATES:
            raise ValueError(f"알 수 없는 상태: {state}")

        # 동일 비-idle 상태 재진입은 무시 (튀는 리셋 방지)
        if state == self.state and state != STATE_IDLE:
            return

        self.state = state
        self.frame_idx = 0
        now = time.time()
        self.last_frame_time = now
        self.state_end_time = now + duration if state != STATE_IDLE else 0.0

    def update(self):
        """매 프레임 호출 — 상태 만료 체크 + 프레임 진행"""
        now = time.time()

        if self.state_end_time > 0 and now >= self.state_end_time:
            self.state = STATE_IDLE
            self.frame_idx = 0
            self.last_frame_time = now
            self.state_end_time = 0.0

        if now - self.last_frame_time >= self.frame_interval:
            frames = self._frames[self.state]
            self.frame_idx = (self.frame_idx + 1) % len(frames)
            self.last_frame_time = now

    def current_frame(self) -> np.ndarray:
        return self._frames[self.state][self.frame_idx]


# ============================================================
# 3. 알파 오버레이 헬퍼
# ============================================================
def overlay_bgra(bg: np.ndarray, fg_bgra: np.ndarray, x: int, y: int) -> np.ndarray:
    """BGR 배경에 BGRA 전경을 (x,y) 좌상단으로 알파 블렌딩 (in-place)

    화면 밖으로 일부 벗어나도 클립해서 안전. 잘못된 입력은 무시.
    """
    if fg_bgra is None or fg_bgra.size == 0:
        return bg
    if fg_bgra.shape[2] != 4:
        return bg

    bh, bw = bg.shape[:2]
    fh, fw = fg_bgra.shape[:2]

    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(bw, x + fw)
    y1 = min(bh, y + fh)
    if x0 >= x1 or y0 >= y1:
        return bg

    fg_x0 = x0 - x
    fg_y0 = y0 - y
    fg_x1 = fg_x0 + (x1 - x0)
    fg_y1 = fg_y0 + (y1 - y0)

    fg_rgb = fg_bgra[fg_y0:fg_y1, fg_x0:fg_x1, :3].astype(np.float32)
    alpha = fg_bgra[fg_y0:fg_y1, fg_x0:fg_x1, 3:4].astype(np.float32) / 255.0
    bg_roi = bg[y0:y1, x0:x1].astype(np.float32)

    blended = bg_roi * (1.0 - alpha) + fg_rgb * alpha
    bg[y0:y1, x0:x1] = blended.astype(np.uint8)
    return bg


def load_background(path: str, screen_w: int, screen_h: int,
                    brightness: float = 1.0, saturation: float = 1.0) -> np.ndarray:
    """배경 JPG를 화면 비율에 맞춰 센터 크롭 + 리사이즈 (BGR)

    Args:
        brightness: 픽셀값 곱 (1.0 = 원본, 0.5 = 절반 밝기). 단순 V 다운.
        saturation: HSV S 채널 곱 (1.0 = 원본, 1.5 = 채도 50% 상향).
    """
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise IOError(f"배경 로드 실패: {path}")

    h, w = img.shape[:2]
    target_ratio = screen_w / screen_h
    src_ratio = w / h

    if src_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        img = img[:, x0:x0 + new_w]
    else:
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        img = img[y0:y0 + new_h, :]

    img = cv2.resize(img, (screen_w, screen_h), interpolation=cv2.INTER_AREA)

    # 채도 조정 (HSV)
    if saturation != 1.0:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * saturation, 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # 밝기 곱
    if brightness != 1.0:
        img = np.clip(img.astype(np.float32) * brightness, 0, 255).astype(np.uint8)

    return img
