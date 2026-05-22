import math
import time
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from style import BG, BORDER, CARD, CYAN, ERROR, ORANGE, PRIMARY, SUCCESS, TEXT, TEXT2, TEXT3, WARNING

from gui.common import card_frame, mkbtn, mklbl, page_header, wrap_scroll


MODE_LABELS = {
    "idle": "대기",
    "serving": "서빙",
    "patrol": "순회",
    "guiding": "안내",
    "engaging": "호객",
}

MODE_COLORS = {
    "idle": PRIMARY,
    "serving": SUCCESS,
    "patrol": CYAN,
    "guiding": ORANGE,
    "engaging": "#DB2777",
    "offline": ERROR,
}


class DobyFloorplanCanvas(QWidget):
    """PyQt floorplan renderer using moca_opserver's ROS-map affine transform."""

    TABLES = [
        {"id": "T01", "x": -37.120, "y": 0.543, "yaw": -1.570},
        {"id": "T02", "x": -40.303, "y": -0.591, "yaw": 1.571},
        {"id": "T03", "x": -40.287, "y": 0.276, "yaw": 1.571},
        {"id": "T04", "x": -45.653, "y": 0.276, "yaw": -1.571},
        {"id": "T05", "x": -45.670, "y": -0.557, "yaw": -1.571},
    ]
    GATES = [
        {"id": "gate1", "x": -38.153, "y": -1.757, "yaw": -1.570},
        {"id": "gate2", "x": -39.353, "y": -1.824, "yaw": 1.571},
        {"id": "gate3", "x": -45.803, "y": -2.024, "yaw": -1.570},
    ]
    HOME_PX = 965.0
    HOME_PY = 174.0
    HOME_DEG = 90.0
    BASE_W = 1251.0
    BASE_H = 788.0

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pose: dict[str, Any] | None = None
        self.tables: dict[str, dict[str, Any]] = {}
        self.online = False

    def update_state(
        self,
        pose: dict[str, Any] | None,
        tables: list[dict[str, Any]] | None,
        online: bool,
    ) -> None:
        self.pose = pose if isinstance(pose, dict) else None
        self.tables = {
            str(row.get("id", row.get("table_id", ""))): row
            for row in tables or []
            if isinstance(row, dict)
        }
        self.online = online
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F8FAFC"))

        scale = min(self.width() / self.BASE_W, self.height() / self.BASE_H)
        ox = (self.width() - self.BASE_W * scale) / 2.0
        oy = (self.height() - self.BASE_H * scale) / 2.0

        painter.save()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        self._draw_grid(painter)
        self._draw_static_areas(painter)
        self._draw_tables(painter)
        self._draw_gates(painter)
        self._draw_home(painter)
        self._draw_robot(painter)
        painter.restore()

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

    @classmethod
    def to_px(cls, x: float, y: float) -> float:
        return 82.2331 * x + 2.5426 * y + 4010.7028

    @classmethod
    def to_py(cls, x: float, y: float) -> float:
        return -0.8722 * x + -79.5863 * y + 374.5820

    @staticmethod
    def to_deg(yaw: float) -> float:
        return -yaw * 180.0 / math.pi

    def _draw_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        for x in range(0, int(self.BASE_W), 50):
            painter.drawLine(x, 0, x, int(self.BASE_H))
        for y in range(0, int(self.BASE_H), 50):
            painter.drawLine(0, y, int(self.BASE_W), y)
        painter.setPen(QPen(QColor("#CBD5E1"), 2))
        painter.drawRect(QRectF(20, 20, self.BASE_W - 40, self.BASE_H - 40))

    def _draw_static_areas(self, painter: QPainter) -> None:
        self._draw_zone(painter, QRectF(110, 80, 210, 85), "카운터", ORANGE)
        self._draw_zone(painter, QRectF(420, 80, 230, 85), "픽업 존", PRIMARY)
        self._draw_zone(painter, QRectF(820, 115, 230, 85), "충전/HOME", SUCCESS)

    def _draw_zone(self, painter: QPainter, rect: QRectF, text: str, color: str) -> None:
        painter.setBrush(QColor(f"{color}22"))
        painter.setPen(QPen(QColor(f"{color}88"), 2))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(color))
        painter.setFont(self._font(18, True))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_tables(self, painter: QPainter) -> None:
        for table in self.TABLES:
            px = self.to_px(table["x"], table["y"])
            py = self.to_py(table["x"], table["y"])
            deg = self.to_deg(table["yaw"])
            state = self.tables.get(table["id"], {}).get("occupancy", "unknown")
            color = {
                "empty": SUCCESS,
                "occupied": ORANGE,
                "finished": WARNING,
                "unknown": TEXT3,
            }.get(str(state), TEXT3)
            self._draw_rotated_box(painter, px, py, deg, 70, 48, table["id"], color, fill_alpha="22")

    def _draw_gates(self, painter: QPainter) -> None:
        for gate in self.GATES:
            self._draw_rotated_box(
                painter,
                self.to_px(gate["x"], gate["y"]),
                self.to_py(gate["x"], gate["y"]),
                self.to_deg(gate["yaw"]),
                22,
                92,
                gate["id"],
                TEXT3,
                fill_alpha="08",
            )

    def _draw_home(self, painter: QPainter) -> None:
        self._draw_rotated_box(
            painter,
            self.HOME_PX,
            self.HOME_PY,
            self.HOME_DEG,
            78,
            54,
            "HOME",
            SUCCESS,
            fill_alpha="10",
        )

    def _draw_robot(self, painter: QPainter) -> None:
        if self.pose:
            px = self.to_px(float(self.pose.get("x", 0.0)), float(self.pose.get("y", 0.0)))
            py = self.to_py(float(self.pose.get("x", 0.0)), float(self.pose.get("y", 0.0)))
            deg = self.to_deg(float(self.pose.get("yaw", 0.0)))
        else:
            px, py, deg = self.HOME_PX, self.HOME_PY, self.HOME_DEG
        color = PRIMARY if self.online else TEXT3

        painter.save()
        painter.translate(px, py)
        painter.rotate(deg)
        painter.setBrush(QColor(f"{color}DD"))
        painter.setPen(QPen(QColor("#DBEAFE" if self.online else "#E2E8F0"), 4))
        painter.drawRoundedRect(QRectF(-24, -18, 48, 36), 6, 6)
        painter.setBrush(QColor("#FFFFFF"))
        points = [QPointF(13, -10), QPointF(30, 0), QPointF(13, 10)]
        painter.drawPolygon(*points)
        painter.restore()

        painter.setPen(QColor(TEXT))
        painter.setFont(self._font(16, True))
        painter.drawText(QRectF(px - 48, py + 24, 96, 26), Qt.AlignmentFlag.AlignCenter, "Doby")

    def _draw_rotated_box(
        self,
        painter: QPainter,
        x: float,
        y: float,
        deg: float,
        w: float,
        h: float,
        label: str,
        color: str,
        *,
        fill_alpha: str,
    ) -> None:
        painter.save()
        painter.translate(x, y)
        painter.rotate(deg)
        painter.setBrush(QColor(f"{color}{fill_alpha}"))
        painter.setPen(QPen(QColor(f"{color}AA"), 2))
        painter.drawRoundedRect(QRectF(-w / 2, -h / 2, w, h), 6, 6)
        painter.setPen(QColor(color))
        painter.setFont(self._font(15, True))
        painter.drawText(QRectF(-w / 2, -h / 2, w, h), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    @staticmethod
    def _font(size: int, bold: bool = False) -> QFont:
        font = QFont()
        font.setPointSize(size)
        font.setBold(bold)
        return font


class DobyMonitoringPage(QWidget):
    def __init__(self, realtime=None):
        super().__init__()
        self.realtime = realtime
        self._last_snapshot: dict[str, Any] = {}
        self._build()
        if self.realtime is not None:
            self.realtime.doby_updated.connect(self.update_doby)
            self.realtime.doby_control_result.connect(self._handle_control_result)
            self.realtime.error.connect(self._append_error_event)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("도비 모니터링", "서빙 로봇 Doby 운영 상태 대시보드"))

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(18)
        root.addWidget(body, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        content_layout.addWidget(self._status_bar())
        content_layout.addLayout(self._main_dashboard())
        content_layout.addWidget(self._event_feed())
        bl.addWidget(wrap_scroll(content), 1)

    def _status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dobyStatusBar")
        bar.setStyleSheet(f"""
            QFrame#dobyStatusBar {{
                background:{CARD}; border:1px solid {BORDER}; border-radius:12px;
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        self.mode_badge = self._badge("CONNECTING", TEXT3)
        self.battery_chip, self.battery_bar, self.battery_label = self._battery_chip()
        self.safety_badge = self._badge("UNKNOWN", TEXT3)
        self.online_badge = self._badge("Doby Offline", TEXT3)
        self.last_seen_label = mklbl("--:--:--", 13, True, TEXT2)

        lay.addWidget(self.mode_badge)
        lay.addWidget(self.battery_chip)
        lay.addWidget(self.safety_badge)
        lay.addWidget(self.online_badge)
        lay.addStretch()
        lay.addWidget(self.last_seen_label)
        return bar

    def _main_dashboard(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._floorplan_card(), 3)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._mode_card())
        right.addWidget(self._progress_card())
        right.addWidget(self._quick_mode_card())
        row.addLayout(right, 1)
        return row

    def _mode_card(self) -> QFrame:
        card, lay = card_frame("현재 모드")
        card.setMinimumHeight(154)
        self.mode_detail_badge = self._badge("연결 대기", TEXT3)
        self.mode_entered_label = mklbl("진입: -", 12, color=TEXT2)
        self.mode_params_label = mklbl("params: {}", 12, color=TEXT2)
        self.mode_reject_label = mklbl("거부 사유: 없음", 12, color=TEXT2)
        for widget in [
            self.mode_detail_badge,
            self.mode_entered_label,
            self.mode_params_label,
            self.mode_reject_label,
        ]:
            lay.addWidget(widget)
        lay.addStretch()
        return card

    def _progress_card(self) -> QFrame:
        card, lay = card_frame("진행 상태")
        self.serving_label, self.serving_bar = self._progress_row(lay, "서빙")
        self.patrol_label, self.patrol_bar = self._progress_row(lay, "순회")
        self.guiding_label, self.guiding_bar = self._progress_row(lay, "안내")
        return card

    def _progress_row(self, layout: QVBoxLayout, title: str) -> tuple[QLabel, QProgressBar]:
        label = mklbl(f"{title}: -", 12, True, TEXT2)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(f"""
            QProgressBar {{ background:#E2E8F0; border:none; border-radius:4px; }}
            QProgressBar::chunk {{ background:{PRIMARY}; border-radius:4px; }}
        """)
        layout.addWidget(label)
        layout.addWidget(bar)
        return label, bar

    def _floorplan_card(self) -> QFrame:
        card, lay = card_frame()
        header = QHBoxLayout()
        header.addWidget(mklbl("도비 위치", 15, True))
        header.addStretch()
        self.pose_label = mklbl("pose: -", 12, True, TEXT2)
        header.addWidget(self.pose_label)
        lay.addLayout(header)
        self.floorplan = DobyFloorplanCanvas()
        lay.addWidget(self.floorplan, 1)
        return card

    def _quick_mode_card(self) -> QFrame:
        card, lay = card_frame("빠른 모드")
        lay.setSpacing(10)
        for label, mode, color in [
            ("대기", "idle", PRIMARY),
            ("호객", "engaging", ORANGE),
            ("서빙", "serving", SUCCESS),
            ("순회", "patrol", CYAN),
        ]:
            btn = mkbtn(label, color)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _checked=False, m=mode: self._request_mode(m))
            lay.addWidget(btn)

        stop_btn = mkbtn("긴급 정지", WARNING)
        stop_btn.setMinimumHeight(40)
        stop_btn.clicked.connect(self._request_emergency_stop)
        lay.addWidget(stop_btn)
        lay.addStretch()
        return card

    def _event_feed(self) -> QFrame:
        card, lay = card_frame()
        header = QHBoxLayout()
        header.addWidget(mklbl("실시간 이벤트", 15, True))
        header.addStretch()
        self.event_count_label = mklbl("0건", 12, True, PRIMARY)
        header.addWidget(self.event_count_label)
        lay.addLayout(header)

        self.feed = QListWidget()
        self.feed.setMinimumHeight(220)
        self.feed.setStyleSheet(f"""
            QListWidget {{
                background:{CARD}; border:1px solid {BORDER}; border-radius:8px;
                color:{TEXT}; font-size:13px;
            }}
            QListWidget::item {{
                padding:10px 12px; border-bottom:1px solid {BORDER};
            }}
        """)
        self.feed.addItem(QListWidgetItem("도비 상태 수신 대기 중"))
        lay.addWidget(self.feed)
        return card

    def update_doby(self, snapshot: dict[str, Any]) -> None:
        self._last_snapshot = snapshot
        mode = snapshot.get("mode") if isinstance(snapshot.get("mode"), dict) else {}
        battery = snapshot.get("battery") if isinstance(snapshot.get("battery"), dict) else {}
        pose = snapshot.get("pose") if isinstance(snapshot.get("pose"), dict) else None
        tables = snapshot.get("tables") if isinstance(snapshot.get("tables"), list) else []
        online = snapshot.get("robot_online") is True

        self._update_status(mode, battery, online)
        self._update_mode_card(mode)
        self._update_pose(pose, tables, online)
        self._update_progress(snapshot)
        self._update_events(snapshot.get("events") if isinstance(snapshot.get("events"), list) else [])

    def _update_status(self, mode: dict[str, Any], battery: dict[str, Any], online: bool) -> None:
        current = str(mode.get("current") or "offline")
        mode_color = MODE_COLORS.get(current if online else "offline", TEXT3)
        mode_text = current.upper() if online and current != "offline" else "OFFLINE"
        self._set_badge(self.mode_badge, mode_text, mode_color)

        pct = self._battery_percent(battery.get("percentage"))
        if pct is None:
            self.battery_bar.setValue(0)
            self.battery_label.setText("--%")
            battery_color = TEXT3
        else:
            self.battery_bar.setValue(max(0, min(100, pct)))
            self.battery_label.setText(f"{pct}%")
            battery_color = SUCCESS if mode.get("battery_ok", True) is not False else WARNING
        self._style_battery_chip(battery_color)

        safety_ok = mode.get("safety_ok")
        if safety_ok is False:
            self._set_badge(self.safety_badge, "ALARM", ERROR)
        elif mode.get("battery_ok") is False:
            self._set_badge(self.safety_badge, "BATT LOW", WARNING)
        else:
            self._set_badge(self.safety_badge, "정상", SUCCESS)

        self._set_badge(self.online_badge, "Doby Online" if online else "Doby Offline", SUCCESS if online else TEXT3)
        self.last_seen_label.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_mode_card(self, mode: dict[str, Any]) -> None:
        current = str(mode.get("current") or "-")
        label = MODE_LABELS.get(current, current)
        self._set_badge(self.mode_detail_badge, f"{label} 모드", MODE_COLORS.get(current, TEXT3))
        entered = mode.get("entered_at")
        self.mode_entered_label.setText(f"진입: {self._format_elapsed(entered)}")
        params = mode.get("params") if isinstance(mode.get("params"), dict) else {}
        self.mode_params_label.setText(f"params: {self._shorten(str(params), 56)}")
        reject = mode.get("last_reject_reason") or "없음"
        self.mode_reject_label.setText(f"거부 사유: {reject}")

    def _update_pose(self, pose: dict[str, Any] | None, tables: list[dict[str, Any]], online: bool) -> None:
        self.floorplan.update_state(pose, tables, online)
        if pose:
            yaw_deg = math.degrees(float(pose.get("yaw", 0.0)))
            self.pose_label.setText(
                f"{pose.get('frame', '-')} x {float(pose.get('x', 0.0)):.2f} · "
                f"y {float(pose.get('y', 0.0)):.2f} · {yaw_deg:.0f}°"
            )
        else:
            self.pose_label.setText("pose: -")

    def _update_progress(self, snapshot: dict[str, Any]) -> None:
        self._apply_progress(self.serving_label, self.serving_bar, "서빙", snapshot.get("serving_state"))
        self._apply_progress(self.patrol_label, self.patrol_bar, "순회", snapshot.get("patrol_state"))
        self._apply_progress(self.guiding_label, self.guiding_bar, "안내", snapshot.get("guiding_state"))

    def _apply_progress(self, label: QLabel, bar: QProgressBar, title: str, state: Any) -> None:
        if not isinstance(state, dict) or not state:
            label.setText(f"{title}: -")
            bar.setValue(0)
            return
        current = state.get("state", state.get("current_state", "-"))
        progress = state.get("progress", 0.0)
        try:
            value = int(float(progress) * 100 if float(progress) <= 1.0 else float(progress))
        except (TypeError, ValueError):
            value = 0
        label.setText(f"{title}: {current}")
        bar.setValue(max(0, min(100, value)))

    def _update_events(self, events: list[dict[str, Any]]) -> None:
        self.feed.clear()
        self.event_count_label.setText(f"{len(events)}건")
        if not events:
            self.feed.addItem(QListWidgetItem("수신된 이벤트 없음"))
            return
        for event in events[:80]:
            ts = self._format_ts(event.get("ts"))
            source = event.get("source", "-")
            message = event.get("message", event.get("msg", ""))
            self.feed.addItem(QListWidgetItem(f"{ts} · {source} · {message}"))

    def _request_mode(self, mode: str) -> None:
        if self.realtime is None:
            self._append_error_event("실시간 연결이 없습니다")
            return

        params: dict[str, Any] = {}
        if mode in {"serving", "guiding"}:
            table, ok = QInputDialog.getItem(
                self,
                "테이블 선택",
                f"{MODE_LABELS.get(mode, mode)} 대상 테이블",
                ["T01", "T02", "T03", "T04", "T05"],
                0,
                False,
            )
            if not ok:
                return
            if mode == "serving":
                params = {"waypoint": table, "via_pickup": True}
            else:
                params = {"target_table": table, "customer_id": f"C-{int(time.time())}"}
        elif mode == "engaging":
            persona, ok = QInputDialog.getItem(
                self,
                "페르소나 선택",
                "호객 페르소나",
                ["casual_browser", "friendly_child", "professional_adult"],
                0,
                False,
            )
            if not ok:
                return
            params = {"persona": persona}

        if QMessageBox.question(
            self,
            "모드 전환",
            f"Doby를 {MODE_LABELS.get(mode, mode)} 모드로 전환할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.realtime.request_doby_mode(mode, params)

    def _request_emergency_stop(self) -> None:
        if self.realtime is None:
            self._append_error_event("실시간 연결이 없습니다")
            return
        if QMessageBox.warning(
            self,
            "긴급 정지",
            "Doby 긴급 정지를 요청할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.realtime.request_doby_emergency_stop()

    def _handle_control_result(self, result: dict[str, Any]) -> None:
        status = "성공" if result.get("ok") else "실패"
        reason = result.get("reason") or result.get("message") or result.get("code") or ""
        self._prepend_event(f"{datetime.now().strftime('%H:%M:%S')} · control · {status} {reason}".strip())

    def _append_error_event(self, message: str) -> None:
        self._prepend_event(f"{datetime.now().strftime('%H:%M:%S')} · error · {message}")

    def _prepend_event(self, text: str) -> None:
        self.feed.insertItem(0, QListWidgetItem(text))
        self.event_count_label.setText(f"{self.feed.count()}건")

    def _battery_chip(self) -> tuple[QFrame, QProgressBar, QLabel]:
        chip = QFrame()
        chip.setObjectName("batteryChip")
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(8)
        lay.addWidget(mklbl("BATT", 11, True, SUCCESS))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedSize(64, 8)
        lay.addWidget(bar)
        value = mklbl("--%", 11, True, SUCCESS)
        lay.addWidget(value)
        self._style_battery_chip(SUCCESS, chip, bar)
        return chip, bar, value

    def _style_battery_chip(
        self,
        color: str,
        chip: QFrame | None = None,
        bar: QProgressBar | None = None,
    ) -> None:
        chip = chip or self.battery_chip
        bar = bar or self.battery_bar
        chip.setStyleSheet(f"""
            QFrame#batteryChip {{
                background:{color}12; border:1px solid {color}44; border-radius:11px;
            }}
        """)
        bar.setStyleSheet(f"""
            QProgressBar {{ background:#E2E8F0; border:none; border-radius:4px; }}
            QProgressBar::chunk {{ background:{color}; border-radius:4px; }}
        """)
        self.battery_label.setStyleSheet(
            f"font-size:11px; font-weight:700; color:{color}; background:transparent;"
        ) if hasattr(self, "battery_label") else None

    def _badge(self, text: str, color: str) -> QLabel:
        label = QLabel(f" {text} ")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedHeight(22)
        self._set_badge(label, text, color)
        return label

    @staticmethod
    def _set_badge(label: QLabel, text: str, color: str) -> None:
        label.setText(f" {text} ")
        label.setStyleSheet(f"""
            background:{color}22; color:{color}; border-radius:11px;
            font-size:11px; font-weight:700; padding:0px 8px; border:1px solid {color}44;
        """)

    @staticmethod
    def _battery_percent(value: Any) -> int | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric < 0:
            return None
        if numeric <= 1.0:
            numeric *= 100.0
        return int(round(numeric))

    @staticmethod
    def _format_elapsed(value: Any) -> str:
        if not isinstance(value, (int, float)) or value <= 0:
            return "-"
        elapsed = max(0, int(time.time() - value))
        mins, secs = divmod(elapsed, 60)
        entered = datetime.fromtimestamp(value).strftime("%H:%M:%S")
        return f"{entered} ({mins}분 {secs}초 경과)"

    @staticmethod
    def _format_ts(value: Any) -> str:
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value).strftime("%H:%M:%S")
        if value:
            return str(value)
        return "--:--:--"

    @staticmethod
    def _shorten(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: limit - 3] + "..."
