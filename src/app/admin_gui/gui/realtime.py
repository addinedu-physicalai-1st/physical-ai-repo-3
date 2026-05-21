import json
import logging

from PyQt6.QtCore import QObject, pyqtSignal

from communication.admin_gui import create_admin_gui_communication_runtime
from communication.admin_gui.protocol import (
    ChunkAssembler,
    EVENT_SNAPSHOT,
    EVENT_START,
    EVENT_STOP,
    TOPIC_MONITOR,
    TOPIC_ORDERS,
    TOPIC_PRODUCTS,
    TOPIC_TABLES,
)
from config import AdminGuiConfig, load_config


class AdminGuiRealtimeBridge(QObject):
    products_updated = pyqtSignal(list)
    orders_updated = pyqtSignal(list)
    tables_updated = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, config: AdminGuiConfig | None = None, logger: logging.Logger | None = None):
        super().__init__()
        self.config = config or load_config()
        self.logger = logger or logging.getLogger("admin_gui.realtime")
        self._assembler = ChunkAssembler()
        self._runtime = create_admin_gui_communication_runtime(
            listen_host=self.config.host,
            listen_port=self.config.port,
            peer_host=self.config.moca_service_host,
            peer_port=self.config.moca_admin_gui_port,
            logger=self.logger,
            peer_name="MocaService",
            timeout=self.config.tcp_timeout_sec,
        )
        self._runtime.subscribe(TOPIC_PRODUCTS, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_ORDERS, EVENT_SNAPSHOT, self._handle_snapshot)
        self._runtime.subscribe(TOPIC_TABLES, EVENT_SNAPSHOT, self._handle_snapshot)

    def start(self) -> None:
        self._runtime.start()
        try:
            self._runtime.request(
                TOPIC_MONITOR,
                EVENT_START,
                b'{"client":"admin_gui"}',
                timeout=self.config.tcp_timeout_sec,
            )
        except Exception as exc:
            message = f"관제 시작 요청 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)

    def stop(self) -> None:
        try:
            self._runtime.request(
                TOPIC_MONITOR,
                EVENT_STOP,
                b'{"client":"admin_gui"}',
                timeout=self.config.tcp_timeout_sec,
            )
        except Exception as exc:
            self.logger.warning("관제 종료 요청 실패: %s", exc)
        finally:
            self._runtime.stop()

    def _handle_snapshot(self, frame, _peer) -> None:
        payload = self._assembler.add(frame)
        if payload is None:
            return
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            message = f"관제 데이터 디코딩 실패: {exc}"
            self.logger.warning(message)
            self.error.emit(message)
            return

        if not isinstance(decoded, list):
            message = "관제 snapshot payload must be a JSON array"
            self.logger.warning(message)
            self.error.emit(message)
            return

        if frame.topic == TOPIC_PRODUCTS:
            self.products_updated.emit(decoded)
        elif frame.topic == TOPIC_ORDERS:
            self.orders_updated.emit(decoded)
        elif frame.topic == TOPIC_TABLES:
            self.tables_updated.emit(decoded)
