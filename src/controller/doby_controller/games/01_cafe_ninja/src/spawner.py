"""
spawner.py — 떨어지는 객체 출현 관리
=====================================

난이도별 출현 간격 + 메뉴/폭탄 비율 + 초기 위치/속도 결정.
다중 동시 spawn(콤보 유도)을 위해 매 호출마다 리스트 반환.

순수 로직 (random.Random 격리, vision/UI 의존성 없음).

Author: Stephen (gjkong)
Date: 2026-05-05 (W3 Step 3)
"""

import random

from falling_object import (
    ALL_KINDS,
    CAKE_RADIUS,
    DEFAULT_GRAVITY,
    DEFAULT_RADIUS,
    FallingObject,
    KIND_AMERICANO,
    KIND_BOMB,
    KIND_CAKE,
    KIND_CAPPUCCINO,
    KIND_CROISSANT,
    KIND_KUNAI,
    KIND_LATTE,
    MENU_KINDS,
    initial_velocity_for_peak,
)


# ============================================================
# 1. 난이도별 파라미터
# ============================================================
DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"
DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)

SPAWN_INTERVAL = {
    DIFFICULTY_EASY: 1.2,
    DIFFICULTY_NORMAL: 0.9,
    DIFFICULTY_HARD: 0.6,
}

BOMB_RATIO = {
    DIFFICULTY_EASY: 0.03,
    DIFFICULTY_NORMAL: 0.05,
    DIFFICULTY_HARD: 0.08,
}

# 동시 spawn 분포: [1개, 2개, 3개]의 확률
MULTI_SPAWN_DIST = {
    DIFFICULTY_EASY: (0.85, 0.15, 0.0),
    DIFFICULTY_NORMAL: (0.70, 0.25, 0.05),
    DIFFICULTY_HARD: (0.55, 0.30, 0.15),
}


# ============================================================
# 2. 메뉴 등장 가중치 (폭탄 제외)
# ============================================================
MENU_WEIGHTS = {
    KIND_AMERICANO: 30,
    KIND_LATTE: 22,
    KIND_CAPPUCCINO: 14,
    KIND_CAKE: 10,
    KIND_CROISSANT: 14,
    KIND_KUNAI: 10,   # B1 안: 7번째 종류 (희귀, 고득점)
}


# ============================================================
# 3. Spawner 클래스
# ============================================================
class Spawner:
    """난이도별 객체 출현 스케줄링

    매 프레임 update(dt)를 호출하면 누적 시간이 spawn_interval을
    넘을 때마다 1~3개의 객체를 한 번에 생성해 리스트로 반환.
    """

    def __init__(self,
                 difficulty: str = DIFFICULTY_NORMAL,
                 screen_w: int = 640,
                 screen_h: int = 480,
                 seed: int = None):
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"알 수 없는 난이도: {difficulty}")

        self.difficulty = difficulty
        self.screen_w = screen_w
        self.screen_h = screen_h
        self._rng = random.Random(seed)

        self.spawn_interval = SPAWN_INTERVAL[difficulty]
        self.bomb_ratio = BOMB_RATIO[difficulty]
        self.multi_dist = MULTI_SPAWN_DIST[difficulty]

        self._accumulator = 0.0
        self.spawn_count = 0

    def reset(self):
        self._accumulator = 0.0
        self.spawn_count = 0

    # ------------------------------------------------------------
    # 출현 결정
    # ------------------------------------------------------------
    def update(self, dt: float) -> list:
        """경과 시간 dt(초)를 누적하고 spawn 시점이면 객체 리스트 반환

        Returns:
            새로 생성된 FallingObject 리스트 (없으면 빈 리스트)
        """
        self._accumulator += dt
        spawned = []

        while self._accumulator >= self.spawn_interval:
            self._accumulator -= self.spawn_interval
            spawned.extend(self._spawn_batch())

        return spawned

    def force_spawn(self) -> list:
        """누적 시간 무시하고 즉시 1배치 생성 (디버그/테스트용)"""
        return self._spawn_batch()

    # ------------------------------------------------------------
    # 1배치 = 1~3개 동시
    # ------------------------------------------------------------
    def _spawn_batch(self) -> list:
        n = self._roll_batch_size()
        objects = []
        for i in range(n):
            objects.append(self._spawn_one(batch_index=i, batch_size=n))
        self.spawn_count += n
        return objects

    def _roll_batch_size(self) -> int:
        r = self._rng.random()
        cumulative = 0.0
        for size, prob in enumerate(self.multi_dist, start=1):
            cumulative += prob
            if r < cumulative:
                return size
        return 1  # 안전망

    # ------------------------------------------------------------
    # 1개 객체 생성
    # ------------------------------------------------------------
    def _spawn_one(self, batch_index: int = 0, batch_size: int = 1) -> FallingObject:
        kind = self._roll_kind()

        # x: 중앙 ±200 px 범위. 다중 spawn 시 좌우 분산
        if batch_size > 1:
            slot_w = 320 / batch_size
            x = (self.screen_w / 2 - 160 + slot_w * (batch_index + 0.5)
                 + self._rng.uniform(-20, 20))
        else:
            x = self.screen_w / 2 + self._rng.uniform(-200, 200)

        x = max(40, min(self.screen_w - 40, x))

        # y: 화면 하단 살짝 아래에서 시작
        y = self.screen_h + 40

        # 목표 peak: 화면 위쪽 ~30%~50% 영역에 도달
        peak_y = self._rng.uniform(self.screen_h * 0.10, self.screen_h * 0.40)
        vy = initial_velocity_for_peak(peak_y, y)

        # vx: 화면 중앙으로 약간 모이는 경향
        center_pull = (self.screen_w / 2 - x) * 0.005
        vx = self._rng.uniform(-2.0, 2.0) + center_pull

        # 회전
        angular_vel = self._rng.uniform(-6.0, 6.0)

        radius = CAKE_RADIUS if kind == KIND_CAKE else DEFAULT_RADIUS

        return FallingObject(
            kind=kind, x=x, y=y, vx=vx, vy=vy,
            radius=radius, angular_vel=angular_vel,
        )

    def _roll_kind(self) -> str:
        # 폭탄 비율 먼저 결정
        if self._rng.random() < self.bomb_ratio:
            return KIND_BOMB
        # 메뉴 가중 무작위
        kinds = list(MENU_WEIGHTS.keys())
        weights = list(MENU_WEIGHTS.values())
        return self._rng.choices(kinds, weights=weights, k=1)[0]
