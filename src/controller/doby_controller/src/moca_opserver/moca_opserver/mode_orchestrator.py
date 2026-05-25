"""mode_orchestrator.py — priority gating + SetMode 클라이언트.

API 사양: docs/moca_opserver_api_spec.md §5.1.
FSM 사양: docs/moca_5state_fsm_spec.md §3, §5.

핵심 책임:
  1. 현재 모드 vs 목표 모드의 priority 비교 (FSM spec §3.3)
  2. 사전 가드 (battery, safety) — REST 응답을 빨리 거부
  3. SetMode 서비스 호출 (mode_manager 측)
  4. override_priority=True 시 priority 무시 (운영자 의도 우선)

priority 규칙 enforce 는 OpServer 책임 (FSM §5.2).
mode_manager 는 priority 무관 모든 전이 허용.
"""

import json
import threading
from typing import Any

from dobi_npc_msgs.srv import SetMode


# FSM spec §1.4, API spec §5.1 — 숫자가 작을수록 우선순위 높음.
PRIORITY = {
    'serving': 1,
    'guiding': 2,
    'patrol': 3,
    'engaging': 5,
    'idle': 99,
}

VALID_MODES = tuple(PRIORITY.keys())


class ModeOrchestrator:
    """OpServer 의 모드 전환 게이트."""

    SETMODE_TIMEOUT_SEC = 2.0

    def __init__(self, node):
        self.node = node
        self.cli_set_mode = node.create_client(SetMode, '/mode/request')
        self._call_lock = threading.Lock()   # SetMode 직렬화 (선점 race 회피)

    # ---------- 가드 ----------

    def _battery_ok(self) -> bool:
        b = self.node.battery_pct
        if b is None or b < 0.0:
            return True   # 미수신은 안전 측 OK
        return b >= self.node.config.battery_min

    def _safety_ok(self) -> bool:
        return bool(getattr(self.node, 'safety_ok', True))

    def _robot_online(self) -> bool:
        return bool(getattr(self.node, 'robot_online', False))

    # ---------- gating ----------

    def request_mode_change(
        self,
        target_mode: str,
        params: dict[str, Any] | None = None,
        trigger_source: str = 'unknown',
        override_priority: bool = False,
    ) -> dict[str, Any]:
        """target_mode 진입을 mode_manager 에 요청.

        반환 dict:
          ok       : bool
          code     : "OK" | "INVALID_MODE" | "BATTERY_LOW" | "SAFETY_ALARM" |
                     "BUSY" | "ROBOT_OFFLINE" | "INTERNAL_ERROR"
          message  : str (선택)
          reason   : SetMode 응답 reason (선택)
          current_mode_before / _after : str (선택)
          preempted : bool
        """
        params = params or {}

        # 1. 모드명 검증
        if target_mode not in VALID_MODES:
            return {
                "ok": False,
                "code": "INVALID_MODE",
                "message": f"unknown mode '{target_mode}'",
            }

        current = self.node.current_mode or 'idle'

        # 2. 로봇 온라인 (idle 외 진입 시 필수)
        if target_mode != 'idle' and not self._robot_online():
            return {
                "ok": False,
                "code": "ROBOT_OFFLINE",
                "message": "/mode/state stale or never received",
            }

        # 3. 사전 가드 (idle 외 진입 시)
        if target_mode != 'idle':
            if not self._battery_ok():
                return {
                    "ok": False,
                    "code": "BATTERY_LOW",
                    "message": f"battery {self.node.battery_pct:.2f} < "
                               f"min {self.node.config.battery_min:.2f}",
                }
            if not self._safety_ok():
                return {
                    "ok": False,
                    "code": "SAFETY_ALARM",
                    "message": "alarm dwell active",
                }

        # 4. priority gating
        if not override_priority:
            if current != 'idle' and target_mode != 'idle':
                if PRIORITY[target_mode] >= PRIORITY[current]:
                    return {
                        "ok": False,
                        "code": "BUSY",
                        "message": f"lower_priority_during_{current}",
                        "current_mode_before": current,
                    }

        # 5. SetMode 호출 — call_async 후 wait (FastAPI thread 에서 동기 호출)
        params_json = json.dumps(params, ensure_ascii=False) if params else ''
        req = SetMode.Request()
        req.requested_mode = target_mode
        req.params = params_json

        with self._call_lock:
            if not self.cli_set_mode.wait_for_service(timeout_sec=1.0):
                return {
                    "ok": False,
                    "code": "INTERNAL_ERROR",
                    "message": "/mode/request service unavailable",
                }
            future = self.cli_set_mode.call_async(req)
            done = future.done
            # spin_until_future_complete 는 별 thread 에서 호출 못 함 (executor 충돌)
            # rclpy 4.x : future 자체 wait — daemon executor 가 처리
            try:
                resp = self._await_future(future, timeout=self.SETMODE_TIMEOUT_SEC)
            except TimeoutError:
                return {
                    "ok": False,
                    "code": "INTERNAL_ERROR",
                    "message": "setmode timeout",
                    "current_mode_before": current,
                }

        if resp is None:
            return {
                "ok": False,
                "code": "INTERNAL_ERROR",
                "message": "setmode null response",
            }

        return {
            "ok": bool(resp.success),
            "reason": resp.reason,
            "current_mode_before": current,
            "current_mode_after": resp.current_mode,
            "preempted": (
                current != 'idle' and target_mode != 'idle'
                and current != target_mode and bool(resp.success)
            ),
        }

    def _await_future(self, future, timeout: float):
        """future.result() polling (FastAPI thread 안전).

        node 의 executor 가 별 thread 에서 spin 중이므로 future 가 자연히 done.
        """
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if future.done():
                return future.result()
            time.sleep(0.02)
        raise TimeoutError("future not done in time")
