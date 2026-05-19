"""
slice_judge.py — 슬라이스 충돌 판정 + 콤보 점수
================================================

W3 카페 닌자의 충돌 로직.
검지 끝의 직전→현재 이동 선분과 떨어지는 객체(원)의 충돌을 판정.
한 프레임에 여러 객체가 베이면 콤보 보너스 적용.

순수 함수 (vision/UI 의존성 없음).

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 4)
"""

from finger_tracker import point_to_segment_distance
from falling_object import KIND_BOMB


# ============================================================
# 1. 점수표 (단일 소스)
# ============================================================
KIND_SCORES = {
    "americano": 10,
    "latte": 15,
    "cappuccino": 20,
    "cake": 25,
    "croissant": 25,
    "kunai": 30,    # B1 안: 닌자 표창 — 최고 득점
    # bomb 은 점수 X (생명만 차감)
}


# ============================================================
# 2. 콤보 배수 (한 스와이프에 동시 베기 N개)
# ============================================================
def combo_multiplier(n: int) -> float:
    """동시 슬라이스 개수에 따른 점수 배수

    1개   → 1.0
    2개   → 1.5
    3개   → 2.0
    4개+ → 3.0
    """
    if n <= 1:
        return 1.0
    if n == 2:
        return 1.5
    if n == 3:
        return 2.0
    return 3.0


# ============================================================
# 3. 슬라이스 결과
# ============================================================
class SliceResult:
    """한 프레임의 슬라이스 결과

    Attributes:
        sliced_objects: 베인 FallingObject 리스트
        bomb_count: 베인 객체 중 폭탄 수
        base_score: 메뉴 객체 점수 합계 (콤보 미적용)
        multiplier: 콤보 배수
        score_gained: base_score * multiplier (정수 반올림)
    """
    __slots__ = (
        "sliced_objects", "bomb_count", "base_score",
        "multiplier", "score_gained",
    )

    def __init__(self, sliced_objects, bomb_count, base_score,
                 multiplier, score_gained):
        self.sliced_objects = sliced_objects
        self.bomb_count = bomb_count
        self.base_score = base_score
        self.multiplier = multiplier
        self.score_gained = score_gained

    def __repr__(self):
        return (f"SliceResult(n={len(self.sliced_objects)}, "
                f"bombs={self.bomb_count}, "
                f"score=+{self.score_gained} "
                f"[{self.base_score}×{self.multiplier}])")


# ============================================================
# 4. 메인 판정 함수
# ============================================================
def judge_slice(segment, objects) -> SliceResult:
    """검지 끝 선분과 모든 객체의 충돌 판정

    Args:
        segment: ((x1,y1), (x2,y2)) 또는 None — 손가락 직전→현재 이동
        objects: 살아있는 FallingObject 리스트
    Returns:
        SliceResult — 베인 객체들에 obj.sliced=True 마킹됨
    """
    sliced = []

    if segment is None:
        return SliceResult(
            sliced_objects=[], bomb_count=0,
            base_score=0, multiplier=1.0, score_gained=0,
        )

    seg_start, seg_end = segment

    for obj in objects:
        if obj.sliced:
            continue
        d = point_to_segment_distance(
            (obj.x, obj.y), seg_start, seg_end
        )
        if d <= obj.radius:
            obj.sliced = True
            sliced.append(obj)

    # 점수 계산
    bomb_count = sum(1 for o in sliced if o.kind == KIND_BOMB)
    base_score = sum(
        KIND_SCORES.get(o.kind, 0) for o in sliced
        if o.kind != KIND_BOMB
    )

    # 콤보 배수는 메뉴 객체 수에만 적용 (폭탄은 콤보 카운트 X)
    menu_count = len(sliced) - bomb_count
    multiplier = combo_multiplier(menu_count)

    score_gained = int(round(base_score * multiplier))

    return SliceResult(
        sliced_objects=sliced,
        bomb_count=bomb_count,
        base_score=base_score,
        multiplier=multiplier,
        score_gained=score_gained,
    )
