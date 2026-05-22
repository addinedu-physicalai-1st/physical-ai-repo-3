"""
dodge_judge.py — 좀비-사람마스크 충돌 + 회피 판정 (v2)
=========================================================

순수 함수. 사람 픽셀 마스크와 좀비 원의 교집합 픽셀 수가 임계 이상이면 충돌.
좀비 중심 y가 dodge_y_threshold 아래로 내려가면 통과.

이중 카운트 방지:
- 이미 dodged/passed 마킹된 좀비는 재산정 X

호출 측 (game.py):
- 매 프레임 evaluate_frame(zombies, person, dodge_y_threshold) → FrameJudgement
- collisions: 마스크와 새로 충돌한 좀비 → 생명 -1 · 즉시 제거
- passes: 통과한 새 좀비 → 점수 +10

Author: Stephen (gjkong)
Date: 2026-05-19 (W7 hitbox v2)
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FrameJudgement:
    collisions: list
    passes: list


def mask_circle_collide(
    mask: np.ndarray,
    cx: int, cy: int, radius: int,
    overlap_ratio: float = 0.30,
) -> bool:
    """좀비 원과 사람 마스크의 픽셀 교집합 ≥ π·r²·overlap_ratio 이면 True."""
    if mask is None or radius <= 0:
        return False
    h, w = mask.shape[:2]
    x1 = max(0, cx - radius)
    y1 = max(0, cy - radius)
    x2 = min(w, cx + radius + 1)
    y2 = min(h, cy + radius + 1)
    if x2 <= x1 or y2 <= y1:
        return False

    yy, xx = np.ogrid[y1:y2, x1:x2]
    disk = ((xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius).astype(np.uint8)
    overlap = int(np.count_nonzero(mask[y1:y2, x1:x2] & disk))
    threshold = int(np.pi * radius * radius * overlap_ratio)
    return overlap >= threshold


def evaluate_frame(zombies, person, dodge_y_threshold: int) -> FrameJudgement:
    """현재 살아있는 좀비들에 대해 충돌/통과 판정.

    Args:
        zombies: Zombie 리스트
        person: PersonMask 또는 None (None이면 충돌 판정 skip — 통과 판정은 진행)
        dodge_y_threshold: 이 y 아래면 통과
    """
    collisions = []
    passes = []

    for z in zombies:
        if z.dodged or z.passed:
            continue

        if person is not None and mask_circle_collide(
            person.collision_mask, int(z.x), int(z.y), z.radius,
        ):
            z.dodged = True
            collisions.append(z)
            continue

        if z.y > dodge_y_threshold:
            z.passed = True
            passes.append(z)

    return FrameJudgement(collisions=collisions, passes=passes)
