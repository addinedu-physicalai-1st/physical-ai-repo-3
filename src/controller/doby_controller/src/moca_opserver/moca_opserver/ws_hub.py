"""ws_hub.py — WebSocket broadcast hub (다중 클라이언트 fan-out).

API 사양: docs/moca_opserver_api_spec.md §3.

연결 lifecycle:
  1. connect → welcome 메시지 (현 status snapshot)
  2. server → client broadcast (mode_state, battery, table_update, ...)
  3. client → server 메시지는 라우터(rest_api) 가 dispatch
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace(
        '+00:00', 'Z')


class WsHub:
    """모든 연결된 dashboard WS 클라이언트에 메시지 fan-out."""

    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info(f'ws connected (total={len(self._clients)})')

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info(f'ws disconnected (total={len(self._clients)})')

    async def send_to(self, ws: WebSocket, msg_type: str, data: dict[str, Any]) -> None:
        """단일 클라이언트에게 전송 (welcome 등)."""
        payload = {"type": msg_type, "ts": now_iso(), "data": data}
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # 끊긴 연결
            log.warning(f'ws send_to failed: {e}')
            await self.disconnect(ws)

    async def broadcast(self, msg_type: str, data: dict[str, Any]) -> None:
        """전 클라이언트 fan-out."""
        payload = {"type": msg_type, "ts": now_iso(), "data": data}
        text = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(text)
            except Exception as e:
                log.warning(f'ws broadcast send failed: {e}')
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    def broadcast_threadsafe(self, loop: asyncio.AbstractEventLoop,
                              msg_type: str, data: dict[str, Any]) -> None:
        """ROS 콜백(별 thread)에서 호출하는 동기 진입점.

        loop.call_soon_threadsafe 로 broadcast coroutine 을 스케줄.
        """
        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(msg_type, data), loop)
        except Exception as e:
            log.warning(f'broadcast_threadsafe failed: {e}')

    @property
    def client_count(self) -> int:
        return len(self._clients)
