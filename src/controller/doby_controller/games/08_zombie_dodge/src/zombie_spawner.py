"""
zombie_spawner.py — 난이도별 좀비 spawn
=============================================

W3 spawner 패턴 차용. RNG 인스턴스 격리 (W2 트러블 #10).

생성 규칙
---------
- spawn 간격은 난이도별 base ± jitter (인스턴스 RNG)
- x 좌표는 화면 좌우 안쪽 (margin) 사이 랜덤
- 종류 분포 (난이도별):
    easy:   normal 90%, big 10%
    normal: normal 70%, big 20%, fast 10%
    hard:   normal 50%, fast 35%, big 15%
- 속도: 난이도별 base × kind multiplier

Author: Stephen (gjkong)
Date: 2026-05-12 (W7 Step 3)
"""

import random

try:
    from .zombie import (
        ALL_KINDS,
        KIND_BIG,
        KIND_FAST,
        KIND_NORMAL,
        KIND_RADIUS,
        KIND_SPEED_MULTIPLIER,
        Zombie,
        make_zombie,
    )
except ImportError:
    from zombie import (
        ALL_KINDS,
        KIND_BIG,
        KIND_FAST,
        KIND_NORMAL,
        KIND_RADIUS,
        KIND_SPEED_MULTIPLIER,
        Zombie,
        make_zombie,
    )


# ============================================================
# 1. 난이도
# ============================================================
DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"
DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)


# spawn_interval: 평균 spawn 간격 (초)
# base_speed: normal 종류의 픽셀/프레임 속도
# kind_weights: 종류별 출현 가중치 (합 1.0 가정 X — random.choices)
DIFFICULTY_CONFIG = {
    DIFFICULTY_EASY: {
        "spawn_interval":   1.4,
        "interval_jitter":  0.4,
        "base_speed":       4.0,
        "kind_weights": {
            KIND_NORMAL: 9,
            KIND_BIG:    1,
            KIND_FAST:   0,
        },
    },
    DIFFICULTY_NORMAL: {
        "spawn_interval":   1.0,
        "interval_jitter":  0.3,
        "base_speed":       6.0,
        "kind_weights": {
            KIND_NORMAL: 7,
            KIND_BIG:    2,
            KIND_FAST:   1,
        },
    },
    DIFFICULTY_HARD: {
        "spawn_interval":   0.7,
        "interval_jitter":  0.2,
        "base_speed":       8.0,
        "kind_weights": {
            KIND_NORMAL: 5,
            KIND_FAST:   3.5,  # weight float 허용
            KIND_BIG:    1.5,
        },
    },
}


# spawn x 좌표 margin (frame 가장자리 제외 영역)
DEFAULT_X_MARGIN_RATIO = 0.10


# ============================================================
# 2. Spawner
# ============================================================
class Spawner:
    """난이도별 좀비 spawn 관리.

    Attributes:
        difficulty: 난이도 키
        config: 난이도별 설정 dict
        _rng: 인스턴스 random.Random (시드 격리)
        time_since_last: 누적 dt (초)
        next_interval: 다음 spawn까지 남은 시간 (초)
        spawned_total: 누적 생성 좀비 수 (통계용)
    """

    def __init__(self, difficulty: str = DIFFICULTY_NORMAL,
                 frame_width: int = 640, frame_height: int = 480,
                 seed=None):
        if difficulty not in DIFFICULTY_CONFIG:
            raise ValueError(f"알 수 없는 난이도: {difficulty}")
        self.difficulty = difficulty
        self.config = DIFFICULTY_CONFIG[difficulty]
        self.frame_width = frame_width
        self.frame_height = frame_height
        self._rng = random.Random(seed)
        self.reset()

    def reset(self):
        """카운터·타이머 초기화 (RNG 상태는 보존)."""
        self.time_since_last = 0.0
        # 첫 spawn은 약간 일찍 (게임 시작 직후 정적 시간 방지)
        self.next_interval = self.config["spawn_interval"] * 0.5
        self.spawned_total = 0

    def update(self, dt: float) -> list:
        """한 프레임 진행 — dt 초 후 spawn 가능 여부 확인.

        Args:
            dt: 이번 프레임 시간(초)

        Returns:
            이번 frame에 새로 생성된 좀비 리스트 (보통 0 또는 1마리)
        """
        new_zombies = []
        self.time_since_last += dt
        while self.time_since_last >= self.next_interval:
            self.time_since_last -= self.next_interval
            new_zombies.append(self._spawn_one())
            # 다음 간격 계산 (base ± jitter)
            jitter = self._rng.uniform(
                -self.config["interval_jitter"],
                self.config["interval_jitter"],
            )
            self.next_interval = max(
                0.1, self.config["spawn_interval"] + jitter,
            )
        return new_zombies

    def _spawn_one(self) -> Zombie:
        """좀비 한 마리 생성."""
        kind = self._random_kind()
        radius = KIND_RADIUS[kind]
        # x 위치: 좌우 margin 제외 영역에서 균등
        margin = int(self.frame_width * DEFAULT_X_MARGIN_RATIO)
        x = self._rng.randint(margin + radius,
                              self.frame_width - margin - radius)
        # y는 좀비 상단이 화면 위에 살짝 가려진 곳에서 시작
        y = -radius
        # 속도
        vy = self.config["base_speed"] * KIND_SPEED_MULTIPLIER[kind]
        zombie = make_zombie(x=x, y=y, vy=vy, kind=kind)
        self.spawned_total += 1
        return zombie

    def _random_kind(self) -> str:
        """난이도별 가중치로 종류 선택."""
        weights = self.config["kind_weights"]
        kinds = list(weights.keys())
        ws = [float(weights[k]) for k in kinds]
        return self._rng.choices(kinds, weights=ws, k=1)[0]
