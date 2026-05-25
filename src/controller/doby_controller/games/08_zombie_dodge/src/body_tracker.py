"""body_tracker.py — SelfieSegmentation 마스크 → 회피 영역 (PersonMask).

순수 함수 모듈. MediaPipe 의존성 없음 — np.ndarray만 다룸.

이전 버전(2026-05-12)의 DodgeBox/compute_dodge_box는 마스크 기반으로 교체.

Author: Stephen (gjkong)
Date: 2026-05-19 (W7 hitbox v2)
"""

from dataclasses import dataclass

import cv2
import numpy as np


# 사람으로 인정하는 최소 픽셀 비율 (전체 frame 대비)
DEFAULT_MIN_PIXEL_RATIO = 0.02
# 충돌 마스크 erode 커널 크기 (픽셀) — 시각화는 원본, 충돌은 살짝 깎아 게임 난이도 완화
DEFAULT_COLLISION_ERODE_PX = 18


@dataclass(frozen=True)
class PersonMask:
    """사람 픽셀 마스크 + 외곽 bbox.

    Attributes:
        mask: H×W uint8 0/1. 시각화용 원본 마스크.
        collision_mask: H×W uint8 0/1. 외곽을 erode한 충돌 판정용 마스크.
        bbox: (x1, y1, x2, y2) — 원본 마스크 외곽 사각형.
    """
    mask: np.ndarray
    collision_mask: np.ndarray
    bbox: tuple

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)


def compute_person_mask(
    raw_mask: np.ndarray,
    min_pixel_ratio: float = DEFAULT_MIN_PIXEL_RATIO,
    collision_erode_px: int = DEFAULT_COLLISION_ERODE_PX,
):
    """binary mask → PersonMask | None.

    Args:
        raw_mask: H×W uint8 0/1.
        min_pixel_ratio: 사람 픽셀 수 / 전체 픽셀 수 임계값.
        collision_erode_px: 충돌 마스크 erode 반지름 (0이면 erode 안 함).
    """
    if raw_mask is None or raw_mask.size == 0:
        return None

    h, w = raw_mask.shape[:2]
    person_pixels = int(raw_mask.sum())
    if person_pixels < int(h * w * min_pixel_ratio):
        return None

    ys, xs = np.where(raw_mask > 0)
    if ys.size == 0:
        return None
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())

    if collision_erode_px > 0:
        k = 2 * collision_erode_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        collision_mask = cv2.erode(raw_mask, kernel, iterations=1)
    else:
        collision_mask = raw_mask

    return PersonMask(mask=raw_mask, collision_mask=collision_mask, bbox=(x1, y1, x2, y2))
