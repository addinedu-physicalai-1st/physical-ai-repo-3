"""
zombie.py — 떨어지는 좀비 도형 + 운동
==========================================

W3 falling_object 패턴 차용 — 화면 위에서 떨어지는 객체.
W7 적용 변형:
- 폭탄 X (좀비 한 종류만, 변형은 색/크기/속도만)
- 콤보 X (피하기 게임이라 한 마리씩 처리)
- 화면 통과 시점: 화면 하단 진입 → 회피 성공 카운트 (게임 게이지)

순수 dataclass — cv2/MediaPipe 의존성 X.

Author: Stephen (gjkong)
Date: 2026-05-12 (W7 Step 3)
"""

from dataclasses import dataclass, field


# ============================================================
# 1. 좀비 종류 (V1은 'normal'만, 추후 'fast'/'big' 등 확장)
# ============================================================
KIND_NORMAL = "normal"
KIND_FAST = "fast"
KIND_BIG = "big"

ALL_KINDS = (KIND_NORMAL, KIND_FAST, KIND_BIG)

# 종류별 속도 배수 (normal 기준)
KIND_SPEED_MULTIPLIER = {
    KIND_NORMAL: 1.0,
    KIND_FAST: 1.6,
    KIND_BIG: 0.8,
}

# 종류별 반지름 (픽셀)
KIND_RADIUS = {
    KIND_NORMAL: 32,
    KIND_FAST: 26,
    KIND_BIG: 48,
}


# ============================================================
# 2. Zombie dataclass
# ============================================================
@dataclass
class Zombie:
    """떨어지는 좀비 객체.

    Attributes:
        x, y: 현재 픽셀 위치 (float — 부드러운 운동)
        vy: 수직 속도 (픽셀/프레임). 음수면 위로 가지만 V1은 항상 양수
        kind: ALL_KINDS 중 하나
        radius: 충돌 반지름
        dodged: 한 번이라도 박스에 부딪힌 적 있나 (이중 카운트 방지)
        passed: 화면 하단 통과 (점수 가산용 캐시)
    """
    x: float
    y: float
    vy: float
    kind: str = KIND_NORMAL
    radius: int = field(default=32)
    dodged: bool = False
    passed: bool = False

    def step(self):
        """한 프레임 진행 — 단순 일정 속도 낙하."""
        self.y += self.vy

    def position(self) -> tuple:
        return (int(self.x), int(self.y))

    def is_off_screen(self, frame_w: int, frame_h: int) -> bool:
        """화면 밖으로 완전히 나갔는지 (좀비 상단이 frame 아래로 떨어짐)."""
        return self.y - self.radius > frame_h

    def has_passed_bottom(self, frame_h: int, dodge_y_threshold: int) -> bool:
        """좀비 중심이 회피 영역 아래로 내려갔는지.

        Args:
            frame_h: 프레임 높이
            dodge_y_threshold: 이 y 이상이면 회피 박스 아래쪽 — 통과로 침
        """
        return self.y > dodge_y_threshold


# ============================================================
# 3. 생성 헬퍼
# ============================================================
def make_zombie(x: float, y: float, vy: float,
                kind: str = KIND_NORMAL) -> Zombie:
    """기본 파라미터로 Zombie 생성."""
    if kind not in ALL_KINDS:
        raise ValueError(f"알 수 없는 좀비 종류: {kind}")
    radius = KIND_RADIUS[kind]
    return Zombie(x=x, y=y, vy=vy, kind=kind, radius=radius)
