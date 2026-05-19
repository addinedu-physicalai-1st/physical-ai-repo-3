"""idle_patrol_timer.py — idle 5분 dwell + 영업시간 가드 → 자동 patrol 트리거.

API 사양 SoT: docs/moca_opserver_api_spec.md §5.2.

★ 명명 주의: 본 모듈은 dobi_npc_bringup 의 patrol_scheduler_node (모드 노드, 5
테이블 sweep 책임) 와 다른 컴포넌트. 본 모듈은 OpServer 내부 "5분 idle 타이머"
역할이며, 트리거 시 patrol_scheduler_node 를 spawn 시키는 mode_manager 의
SetMode('patrol') 을 호출한다.
  - moca_opserver.idle_patrol_timer.IdlePatrolTimer  ← 본 모듈
  - dobi_npc_bringup.patrol_scheduler_node           ← 모드 노드 (별개)

OpServer 에 둔 이유 (FSM spec §5.3):
  비즈니스 룰 (주기 변경, 영업시간, 야간 비활성) 은 OpServer 의 책임.
  mode_manager 는 priority 무관 FSM 코어만 유지. 점주가 자주 바꿔도 mode_manager
  재기동 불필요.
"""

import logging
import time
from datetime import datetime
from typing import Optional


log = logging.getLogger(__name__)


def _parse_business_hours(spec: str) -> tuple[Optional[tuple[int, int]], Optional[tuple[int, int]]]:
    """\"09:00-22:00\" → ((9,0), (22,0)). 잘못된 형식이면 (None, None).

    빈 문자열 또는 \"24h\" 면 (None, None) 반환 (= 24시간 활성).
    """
    if not spec or spec.strip() in ('', '24h', '24/7', 'always'):
        return (None, None)
    try:
        a, b = spec.split('-', 1)
        ah, am = a.strip().split(':', 1)
        bh, bm = b.strip().split(':', 1)
        return ((int(ah), int(am)), (int(bh), int(bm)))
    except (ValueError, AttributeError):
        return (None, None)


def _in_business_hours(spec: str, now: Optional[datetime] = None) -> bool:
    """현재 시각이 영업시간 안인지 확인."""
    start, end = _parse_business_hours(spec)
    if start is None:
        return True   # 24시간
    if now is None:
        now = datetime.now()
    cur = (now.hour, now.minute)
    # start <= cur <= end (overnight wrap 미지원 — M3)
    return start <= cur <= end


class IdlePatrolTimer:
    """/mode/state 가 idle 상태로 N분 누적되면 patrol 자동 트리거.

    트리거 가드:
      - config.patrol_enabled == True
      - 영업시간 내 (business_hours)
      - 배터리 >= battery_min (또는 미수신)
    """

    def __init__(self, node):
        """node 가 노출해야 할 속성/메서드:
          - current_mode (str)
          - battery_pct (float | None)
          - config: patrol_interval_minutes / patrol_enabled / business_hours / battery_min
          - orchestrator (ModeOrchestrator)
          - get_logger()
          - publish_op_event(...)
        """
        self.node = node
        # idle 진입 시각 (None = idle 아님). float (time.time()) 사용 — datetime 도 가능
        self._last_idle_entered_at: Optional[float] = None
        # 트리거 후 짧은 cooldown — 같은 idle 사이클에서 중복 트리거 차단
        self._last_trigger_at: float = 0.0
        self._retrigger_cooldown_sec = 30.0

    # ─────────── /mode/state 콜백 (opserver_node 가 호출) ───────────

    def on_mode_state(self, current_mode: str) -> None:
        """mode_state 토픽 수신 시. current_mode 가 idle 이면 dwell 시작 (or 유지),
        다른 모드면 dwell 리셋."""
        if current_mode == 'idle':
            if self._last_idle_entered_at is None:
                self._last_idle_entered_at = time.time()
                self.node.get_logger().debug(
                    'IdlePatrolTimer: idle 진입 — dwell 시작')
        else:
            if self._last_idle_entered_at is not None:
                self.node.get_logger().debug(
                    f'IdlePatrolTimer: {current_mode} 진입 — dwell 리셋')
                self._last_idle_entered_at = None

    # ─────────── 1Hz tick ───────────

    def tick(self) -> None:
        """1Hz 또는 더 빠른 timer 에서 호출. 모든 가드 통과 + dwell 만료 시 patrol 트리거."""
        if self._last_idle_entered_at is None:
            return

        cfg = self.node.config
        # 가드 1: 활성화
        if not getattr(cfg, 'patrol_enabled', True):
            return
        # 가드 2: 영업시간
        if not _in_business_hours(getattr(cfg, 'business_hours', '')):
            return
        # 가드 3: 배터리 (None 또는 -1 은 미수신 → 안전 측 OK)
        battery = getattr(self.node, 'battery_pct', None)
        battery_min = float(getattr(cfg, 'battery_min', 0.20))
        if battery is not None and battery >= 0.0 and battery < battery_min:
            return
        # 가드 4: 트리거 후 cooldown (같은 idle 사이클에서 중복 차단)
        # config.patrol_retrigger_cooldown_sec 로 override 가능 (테스트 0 가능)
        now = time.time()
        cooldown = float(getattr(
            cfg, 'patrol_retrigger_cooldown_sec',
            self._retrigger_cooldown_sec))
        if cooldown > 0 and now - self._last_trigger_at < cooldown:
            return

        # dwell 체크
        elapsed = now - self._last_idle_entered_at
        interval_sec = float(
            getattr(cfg, 'patrol_interval_minutes', 5.0)) * 60.0
        if elapsed < interval_sec:
            return

        # 트리거
        self._trigger_patrol(elapsed)

    def _trigger_patrol(self, elapsed: float) -> None:
        self.node.get_logger().info(
            f'IdlePatrolTimer: idle {elapsed:.1f}s 경과 — '
            f'patrol 자동 트리거')
        try:
            result = self.node.orchestrator.request_mode_change(
                target_mode='patrol',
                params={'sweep_mode': 'all', 'report_to_opserver': True},
                trigger_source='timer',
                override_priority=False,
            )
        except Exception as e:
            self.node.get_logger().error(
                f'IdlePatrolTimer SetMode("patrol") 실패: {e}')
            return

        # 트리거 후 리셋 — patrol 진입하면 다음 idle 시 다시 dwell 시작
        self._last_idle_entered_at = None
        self._last_trigger_at = time.time()

        try:
            self.node.publish_op_event(
                source='timer',
                event_type='patrol_timer',
                payload={'idle_elapsed_sec': round(elapsed, 1),
                         'result': result},
                outcome=('accepted' if result.get('ok') else
                         f'rejected:{result.get("code","")}'),
            )
        except Exception:
            pass

    # ─────────── 디버그 ───────────

    def idle_elapsed_sec(self) -> float:
        """현재 idle dwell 누적 시간 (sec). idle 아닐 때 -1."""
        if self._last_idle_entered_at is None:
            return -1.0
        return time.time() - self._last_idle_entered_at
