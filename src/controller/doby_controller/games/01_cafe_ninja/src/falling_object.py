"""
falling_object.py — 떨어지는 메뉴 객체 (포물선 운동)
======================================================

화면 아래에서 위로 던져져 중력을 받아 다시 떨어지는 객체.
순수 데이터 클래스 + 매 프레임 step() 만 호출하면 위치 갱신.

vision/UI 의존성 없음 → 단위 테스트 친화적.

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 3)
"""

from dataclasses import dataclass, field


# ============================================================
# 1. 객체 종류 (점수표는 score_state.py에서 단일 소스로 관리)
# ============================================================
KIND_AMERICANO = "americano"
KIND_LATTE = "latte"
KIND_CAPPUCCINO = "cappuccino"
KIND_CAKE = "cake"
KIND_CROISSANT = "croissant"
KIND_KUNAI = "kunai"
KIND_BOMB = "bomb"

ALL_KINDS = (
    KIND_AMERICANO, KIND_LATTE, KIND_CAPPUCCINO,
    KIND_CAKE, KIND_CROISSANT, KIND_KUNAI, KIND_BOMB,
)
MENU_KINDS = ALL_KINDS[:6]  # 폭탄 제외 (kunai 포함)


# ============================================================
# 2. 물리 상수 (640x480 기준, 30fps 가정)
# ============================================================
DEFAULT_GRAVITY = 0.5         # px/frame²
DEFAULT_RADIUS = 36           # 충돌 반지름 (px)
CAKE_RADIUS = 44              # 케이크는 더 큼
DESPAWN_MARGIN = 80           # 화면 밖 이 정도 벗어나면 제거


# ============================================================
# 3. FallingObject 데이터 클래스
# ============================================================
@dataclass
class FallingObject:
    """포물선 운동하는 메뉴 객체

    좌표계는 화면 좌표 (y 아래로 증가).
    spawn 시 화면 하단(y = screen_h) 근처에서 vy < 0 (위로 솟구침),
    중력에 의해 vy가 양수로 변하며 다시 떨어진다.
    """
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    radius: int = DEFAULT_RADIUS
    angle: float = 0.0          # 회전 각도 (시각 효과)
    angular_vel: float = 0.0    # 회전 속도 (deg/frame)
    gravity: float = DEFAULT_GRAVITY
    sliced: bool = False        # 베인 적 있는가 (중복 점수 방지)
    age: int = 0                # 살아있는 프레임 수 (디버깅)

    def step(self):
        """1프레임 진행 — 위치 + 속도 + 회전 갱신"""
        self.vy += self.gravity
        self.x += self.vx
        self.y += self.vy
        self.angle = (self.angle + self.angular_vel) % 360.0
        self.age += 1

    def is_off_screen(self, screen_w: int, screen_h: int) -> bool:
        """화면 밖으로 충분히 벗어났는지 (제거 판단)

        - 위로 너무 솟구치는 경우는 거의 없으나 안전망으로 처리
        - 좌우/하단으로 벗어나면 제거
        """
        m = DESPAWN_MARGIN
        if self.x < -m or self.x > screen_w + m:
            return True
        if self.y > screen_h + m:
            return True
        if self.y < -m * 3:
            # 비정상적으로 위로 사라진 경우(중력 0이거나 초기 vy 너무 큼)
            return True
        return False

    def position(self) -> tuple:
        """현재 위치 (정수 픽셀)"""
        return (int(self.x), int(self.y))


# ============================================================
# 4. 헬퍼: 초기 속도 계산
# ============================================================
def initial_velocity_for_peak(target_peak_y: float,
                              current_y: float,
                              gravity: float = DEFAULT_GRAVITY) -> float:
    """객체가 target_peak_y 까지 솟구치게 하는 초기 vy

    화면 아래에서 발사 시 target_peak_y(화면 위쪽 = 작은 값)까지
    도달하려면 운동방정식: 0 = vy² + 2 * (-gravity) * (current_y - target_peak_y)
    → vy = -sqrt(2 * gravity * (current_y - target_peak_y))   (음수 = 위로)

    Args:
        target_peak_y: 도달 목표 y (화면 좌표, 작을수록 위)
        current_y: 발사 시점 y
        gravity: 중력 (px/frame²)
    Returns:
        초기 vy (음수)
    """
    height = current_y - target_peak_y
    if height <= 0:
        return 0.0
    import math
    return -math.sqrt(2.0 * gravity * height)
