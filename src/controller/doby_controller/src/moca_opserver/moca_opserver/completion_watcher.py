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
          - config.auto_return_after_serve (bool)  ← 적재 후 자동 return 토글
          - get_logger(), publish_op_event(...)
          - send_arm_serve_goal(done_cb)  ← serving 완료 후 arm action 전송
          - publish_serving_goto_table(cmd)  ← return 명령 발행 (예 'T03:return')
          - _active_serving_route (str|None)  ← 현재 serving 대상 route id
          - _serving_state_json (dict)  ← /serving/state 캐시 (routes 목록 참조)
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
        # arm action 진행 중 플래그 (dwell 재진입 차단)
        self._arm_running: dict[str, bool] = {
            mode: False for mode in _DONE_SIGNALS
        }
        # 적재(Serve) 후 자동 return 2-phase 상태
        self._serving_return_pending: bool = False  # return 명령 발행됨, 복귀 대기
        self._serving_return_started: bool = False   # dispatcher 가 실제 return 주행 시작 확인
        self._serving_return_deadline: float = 0.0   # 빈/누락 return no-op 대비 fallback 시각
        self._return_fallback_sec: float = 8.0

    # ─────────── 외부 신호 수신 (opserver_node 의 콜백이 호출) ───────────

    def on_serving_state(self, state_value: str) -> None:
        """/serving/state 의 JSON 파싱된 state 필드 (예: 'idle', 'navigating')."""
        # return 명령 발행 후 dispatcher 가 idle 을 벗어나면(=실제 복귀 주행 시작) 표시.
        if (self._serving_return_pending
                and (state_value or '') not in _DONE_SIGNALS['serving']):
            self._serving_return_started = True
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
            if mode == 'serving':
                self._reset_return_state()
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
            # arm action 진행 중이면 tick 무시 (완료 콜백이 다음 단계 트리거)
            if self._arm_running[mode]:
                continue

            # phase 2: 적재 후 return 발행됨 — 복귀 완료(or no-op fallback) 시 idle 전환.
            if mode == 'serving' and self._serving_return_pending:
                if not (self._serving_return_started
                        or now >= self._serving_return_deadline):
                    # 복귀 주행이 아직 시작 안 됨 — 조기 idle 방지, 다음 tick 재확인
                    continue
                self._dwell_start[mode] = None
                self._last_trigger_at[mode] = now
                self._reset_return_state()
                self.node.get_logger().info(
                    'CompletionWatcher[serving]: return 복귀 완료 — idle 전환')
                self._trigger_idle('serving')
                continue

            # phase 1: 활동 종료 → (serving 이면) arm serve, 아니면 바로 idle
            self._dwell_start[mode] = None
            self._last_trigger_at[mode] = now
            self._arm_running[mode] = True
            self.node.get_logger().info(
                f'CompletionWatcher[{mode}]: dwell {dwell:.1f}s 만료 — '
                f'arm serve 요청')
            self._trigger_arm_then_idle(mode)

    def _trigger_arm_then_idle(self, completed_mode: str) -> None:
        """serving 완료 시 arm Serve action 전송 → (옵션) return 복귀 → idle 전환.
        serving 외 모드는 arm 없이 바로 idle 전환.
        """
        if completed_mode != 'serving':
            self._arm_running[completed_mode] = False
            self._trigger_idle(completed_mode)
            return

        def _after_arm(success: bool, msg: str) -> None:
            self._arm_running['serving'] = False
            self.node.get_logger().info(f'[arm] {"성공" if success else "실패"}: {msg}')
            # 적재 성공 + 토글 on + 대상이 return 경로 보유 → return 복귀 발행 후 idle 보류.
            if (success and not self._serving_return_pending
                    and getattr(self.node.config, 'auto_return_after_serve', True)
                    and self._target_has_route()):
                target = self.node._active_serving_route
                self.node.publish_serving_goto_table(f'{target}:return')
                self._serving_return_pending = True
                self._serving_return_started = False
                self._serving_return_deadline = time.time() + self._return_fallback_sec
                self.node.get_logger().info(
                    f'[arm] 적재 완료 → 자동 복귀 {target}:return 발행 — idle 보류')
                return
            self._trigger_idle('serving')

        try:
            self.node.send_arm_serve_goal(
                _after_arm,
                has_drink=self.node._current_serving_has_drink,
            )
        except Exception as e:
            self.node.get_logger().error(
                f'[arm] goal send 실패: {e} — idle 전환')
            self._arm_running['serving'] = False
            self._trigger_idle('serving')

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

    # ─────────── return 2-phase 헬퍼 ───────────

    def _reset_return_state(self) -> None:
        self._serving_return_pending = False
        self._serving_return_started = False
        self._serving_return_deadline = 0.0

    def _target_has_route(self) -> bool:
        """현재 serving 대상이 dispatcher 의 routes 목록에 있는 route 인지 (return 경로 후보)."""
        target = getattr(self.node, '_active_serving_route', None)
        if not target:
            return False
        sj = getattr(self.node, '_serving_state_json', None)
        routes = sj.get('routes', []) if isinstance(sj, dict) else []
        return target in (routes or [])

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
