import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from app.communication.admin_gui.protocol import (
    KIND_ERROR,
    KIND_PUBLISH,
    KIND_REQUEST,
    KIND_RESPONSE,
    AdminGuiFrame,
)
from app.communication.admin_gui.publisher import AdminGuiPublisher
from app.communication.admin_gui.subscriber import AdminGuiSubscriber

PublishHandler = Callable[[AdminGuiFrame, tuple[str, int]], None]
RequestHandler = Callable[[AdminGuiFrame, tuple[str, int]], bytes]


@dataclass
class _PendingRequest:
    event: threading.Event
    payload: bytes | None = None
    error: str | None = None


class AdminGuiCommunicationRuntime:
    def __init__(
        self,
        subscriber: AdminGuiSubscriber,
        publisher: AdminGuiPublisher,
        logger: logging.Logger,
    ) -> None:
        self.subscriber = subscriber
        self.publisher = publisher
        self.logger = logger
        self._lock = threading.Lock()
        self._sequence = 0
        self._correlation_id = 0
        self._publish_handlers: dict[tuple[int, int], PublishHandler] = {}
        self._request_handlers: dict[tuple[int, int], RequestHandler] = {}
        self._pending: dict[int, _PendingRequest] = {}

    def start(self) -> None:
        self.subscriber.start()

    def stop(self) -> None:
        self.subscriber.stop()

    def subscribe(self, topic: int, event: int, handler: PublishHandler) -> None:
        self._publish_handlers[(topic, event)] = handler

    def register_request_handler(self, topic: int, event: int, handler: RequestHandler) -> None:
        self._request_handlers[(topic, event)] = handler

    def publish(self, topic: int, event: int, payload: bytes = b"", *, flags: int = 0) -> bool:
        frame = AdminGuiFrame(
            kind=KIND_PUBLISH,
            topic=topic,
            event=event,
            flags=flags,
            sequence=self._next_sequence(),
            payload=payload,
        )
        return self.publisher.publish_frame(frame)

    def request(
        self,
        topic: int,
        event: int,
        payload: bytes = b"",
        *,
        flags: int = 0,
        timeout: float = 3.0,
    ) -> bytes:
        correlation_id = self._next_correlation_id()
        pending = _PendingRequest(threading.Event())
        with self._lock:
            self._pending[correlation_id] = pending

        frame = AdminGuiFrame(
            kind=KIND_REQUEST,
            topic=topic,
            event=event,
            flags=flags,
            sequence=self._next_sequence(),
            correlation_id=correlation_id,
            payload=payload,
        )
        if not self.publisher.publish_frame(frame):
            with self._lock:
                self._pending.pop(correlation_id, None)
            raise TimeoutError(f"failed to publish request correlation_id={correlation_id}")

        if not pending.event.wait(timeout):
            with self._lock:
                self._pending.pop(correlation_id, None)
            raise TimeoutError(f"admin_gui request timed out correlation_id={correlation_id}")
        if pending.error is not None:
            raise RuntimeError(pending.error)
        return pending.payload or b""

    def handle_frame(self, frame: AdminGuiFrame, peer: tuple[str, int]) -> None:
        if frame.kind == KIND_PUBLISH:
            self._handle_publish(frame, peer)
            return
        if frame.kind == KIND_REQUEST:
            self._handle_request(frame, peer)
            return
        if frame.kind in {KIND_RESPONSE, KIND_ERROR}:
            self._handle_reply(frame)
            return
        self.logger.warning("unsupported admin_gui frame kind=%s from %s", frame.kind, peer)

    def _handle_publish(self, frame: AdminGuiFrame, peer: tuple[str, int]) -> None:
        handler = self._publish_handlers.get((frame.topic, frame.event))
        if handler is None:
            self.logger.info("no admin_gui publish handler topic=%s event=%s", frame.topic, frame.event)
            return
        handler(frame, peer)

    def _handle_request(self, frame: AdminGuiFrame, peer: tuple[str, int]) -> None:
        handler = self._request_handlers.get((frame.topic, frame.event))
        if handler is None:
            self._publish_reply(frame, KIND_ERROR, b"request handler not found")
            return
        try:
            payload = handler(frame, peer)
        except Exception as exc:
            self.logger.warning("admin_gui request handler failed: %s", exc)
            self._publish_reply(frame, KIND_ERROR, str(exc).encode("utf-8"))
            return
        self._publish_reply(frame, KIND_RESPONSE, payload)

    def _handle_reply(self, frame: AdminGuiFrame) -> None:
        with self._lock:
            pending = self._pending.pop(frame.correlation_id, None)
        if pending is None:
            self.logger.info("no pending admin_gui request correlation_id=%s", frame.correlation_id)
            return
        if frame.kind == KIND_ERROR:
            pending.error = frame.payload.decode("utf-8", errors="replace") or "admin_gui request failed"
        else:
            pending.payload = frame.payload
        pending.event.set()

    def _publish_reply(self, request_frame: AdminGuiFrame, kind: int, payload: bytes) -> None:
        reply = AdminGuiFrame(
            kind=kind,
            topic=request_frame.topic,
            event=request_frame.event,
            flags=request_frame.flags,
            sequence=self._next_sequence(),
            correlation_id=request_frame.correlation_id,
            payload=payload,
        )
        self.publisher.publish_frame(reply)

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence = (self._sequence + 1) & 0xFFFF
            return self._sequence

    def _next_correlation_id(self) -> int:
        with self._lock:
            self._correlation_id = (self._correlation_id + 1) & 0xFFFF
            if self._correlation_id == 0:
                self._correlation_id = 1
            return self._correlation_id
