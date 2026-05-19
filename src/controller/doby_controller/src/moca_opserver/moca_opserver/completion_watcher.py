"""completion_watcher.py — 4 활동 모드 자동 idle 복귀 watcher.

API 사양 SoT: docs/moca_opserver_api_spec.md §5.4
FSM 사양: docs/moca_5state_fsm_spec.md §5.2 — "e_complete 사건 감지는 OpServer 책임"

책임:
  각 활동 모드 (serving/patrol/guiding/engaging) 의 상태 토픽을 관찰해서
  "종료 시그널" 을 dwell 후 mode_manager 에 SetMode('idle') 로 외부 조율.

  활동 모드 dispatcher 자체는 self-terminate 하지 않음 (디자인 결정):
    - serving_dispatcher: 큐 소진 + home 복귀 → /serving/state JSON.state="idle"
    - patrol_scheduler: 5 테이블 + home → PatrolState.current_state="done"
    - patrol_scheduler abort: PatrolState.current_state="aborted"
    - guiding_controller: 도착 + 5s dwell → GuidingState.current_state="done"
    - guiding_controller abort: GuidingState.current_state="aborted"
    - engaging (cafe_funnel BT): /bt/result 또는 funnel 6단계 완주 (M2 보류)

  각 시그널에 dwell 시간 (config 가능):
    serving=3.0s  patrol=1.0s  guiding=5.0s  engaging=2.0s

  override_priority=True 로 호출 — 활동 모드 → idle 은 우선순위 무관 통과.
"""

import logging
import time
from typing import Optional


log = logging.getLogger(__name__)


# 종료 시그널로 간주할 state 값 (모드별)
_DONE_SIGNALS = {
    'serving':  {'idle'},                # /serving/state JSON.state
    'patrol':   {'done', 'aborted'},     # PatrolState.current_state
    'guiding':  {'done', 'aborted'},     # GuidingState.current_state
    'engaging': {'done', 'completed'},   # /bt/result (M2 placeholder)
}


class CompletionWatcher:
    """활동 모드 종료 시그널 + dwell → 자동 SetMode('idle')."""

    def __init__(self, node):
        """node 가 노출해야 할 속성/메서드:
          - current_mode (str)
          - orchestrator (ModeOrchestrator)
          - config.completion_dwell_<mode> (float)
          - get_logger(), publish_op_event(...)
        """
        self.node = node
        # mode → dwell 시작 시각 (None = dwell 비활성)
        self._dwell_start: dict[str, Optional[float]] = {
            'serving': None,
            'patrol': None,
            'guiding': None,
            'engaging': None,
        }
        # 마지막 트리거 시각 (idempotent — 짧은 시간 안 재트리거 차단)
        self._last_trigger_at: dict[str, float] = {
            mode: 0.0 for mode in _DONE_SIGNALS
        }
        self._retrigger_cooldown_sec = 2.0

    # ─────────── 외부 신호 수신 (opserver_node 의 콜백이 호출) ───────────

    def on_serving_state(self, state_value: str) -> None:
        """/serving/state 의 JSON 파싱된 state 필드 (예: 'idle', 'navigating')."""
        self._observe(mode='serving', state_value=state_value or '')

    def on_patrol_state(self, current_state: str) -> None:
        """PatrolState.current_state (init/next/moving/dwell/scan/report/returning/done/aborted)."""
        self._observe(mode='patrol', state_value=current_state or '')

    def on_guiding_state(self, current_state: str) -> None:
        """GuidingState.current_state (init/lock_on/moving/waiting/arrived/done/aborted)."""
        self._observe(mode='guiding', state_value=current_state or '')

    def on_engaging_done(self, result: str = '') -> None:
        """engaging 종료 시그널 — M2 placeholder.

        cafe_funnel BT 가 /bt/result 또는 별 토픽으로 완주/abort 신호 보내면 그것을
        opserver_node 가 받아 본 메서드 호출.
        """
        self._observe(mode='engaging', state_value=(result or 'done'))

    # ─────────── 핵심 dwell 로직 ───────────

    def _observe(self, mode: str, state_value: str) -> None:
        """state 시그널 수신 → dwell 시작/리셋 판단."""
        # 현재 모드가 본 모드가 아니면 신호 무시 (다른 모드 진행 중 stale 신호)
        if self.node.current_mode != mode:
            self._dwell_start[mode] = None
            return

        if state_value in _DONE_SIGNALS[mode]:
            if self._dwell_start[mode] is None:
                self._dwell_start[mode] = time.time()
                self.node.get_logger().info(
                    f'CompletionWatcher[{mode}]: done signal received '
                    f"(state='{state_value}') — dwell 시작")
        else:
            # 활동 재개 신호 — dwell 리셋
            if self._dwell_start[mode] is not None:
                self.node.get_logger().info(
                    f'CompletionWatcher[{mode}]: dwell 리셋 '
                    f"(state='{state_value}')")
                self._dwell_start[mode] = None

    # ─────────── 1Hz tick (opserver_node 가 호출) ───────────

    def tick(self) -> None:
        """1Hz 또는 더 빠른 timer 에서 호출. dwell 만료 시 SetMode('idle')."""
        now = time.time()
        for mode, started in list(self._dwell_start.items()):
            if started is None:
                continue
            # 트리거 후 짧은 cooldown
            if now - self._last_trigger_at[mode] < self._retrigger_cooldown_sec:
                continue
            dwell = self._dwell_for_mode(mode)
            if now - started < dwell:
                continue
            # 현재 모드가 본 모드 아니면 invalidate
            if self.node.current_mode != mode:
                self._dwell_start[mode] = None
                continue
            # 트리거
            self._dwell_start[mode] = None
            self._last_trigger_at[mode] = now
            self.node.get_logger().info(
                f'CompletionWatcher[{mode}]: dwell {dwell:.1f}s 만료 — '
                f'SetMode("idle") 호출')
            self._trigger_idle(mode)

    def _trigger_idle(self, completed_mode: str) -> None:
        """orchestrator 로 SetMode('idle', override=True)."""
        try:
            result = self.node.orchestrator.request_mode_change(
                target_mode='idle',
                params={},
                trigger_source=f'completion_watcher:{completed_mode}',
                override_priority=True,
            )
        except Exception as e:
            self.node.get_logger().error(
                f'CompletionWatcher SetMode("idle") 실패: {e}')
            return

        # OpEvent echo (디버깅 + KPI)
        try:
            self.node.publish_op_event(
                source='timer',
                event_type='completion_idle',
                payload={'completed_mode': completed_mode,
                         'result': result},
                outcome=('accepted' if result.get('ok') else
                         f'rejected:{result.get("code","")}'),
            )
        except Exception:
            pass

    # ─────────── 설정 ───────────

    def _dwell_for_mode(self, mode: str) -> float:
        """config 에서 dwell 시간 조회. completion_dwell_<mode> 속성 또는 default."""
        attr = f'completion_dwell_{mode}'
        cfg = getattr(self.node, 'config', None)
        if cfg is not None and hasattr(cfg, attr):
            return float(getattr(cfg, attr))
        # default fallback
        defaults = {'serving': 3.0, 'patrol': 1.0, 'guiding': 5.0, 'engaging': 2.0}
        return defaults.get(mode, 2.0)
