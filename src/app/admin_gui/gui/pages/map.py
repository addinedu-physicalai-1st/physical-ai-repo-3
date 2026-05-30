from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from style import BG, ERROR, PRIMARY, TEXT2, WARNING
from gui.common import (
    card_frame,
    disabled_row,
    make_table,
    mkbtn,
    mklbl,
    mkobtn,
    page_header,
    set_table_rows,
)


class MapCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 360)
        self._map_name = ""
        self._origin = None
        self._resolution = None

    def set_map(self, map_data: dict | None) -> None:
        self._map_name = str((map_data or {}).get("name") or "")
        self._origin = (map_data or {}).get("origin")
        self._resolution = (map_data or {}).get("resolution")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#FAFBFE"))
        p.setPen(QPen(QColor("#E2E8F0"), 1))
        for x in range(0, self.width(), 30):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 30):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(QColor(PRIMARY), 2))
        p.drawRect(1, 1, self.width() - 2, self.height() - 2)

        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor("#334155"), 1))
        title = self._map_name or "선택된 지도 없음"
        p.drawText(0, self.height() // 2 - 18, self.width(), 24, Qt.AlignmentFlag.AlignCenter, title)

        font.setPointSize(9)
        font.setBold(False)
        p.setFont(font)
        detail = ""
        if self._resolution is not None:
            detail = f"resolution={self._resolution}"
            if self._origin is not None:
                detail += f" origin={self._origin}"
        p.drawText(0, self.height() // 2 + 8, self.width(), 20, Qt.AlignmentFlag.AlignCenter, detail)


class MapManagementPage(QWidget):
    def __init__(self, realtime=None):
        super().__init__()
        self.realtime = realtime
        self._maps: list[dict] = []
        self._state: dict = {}
        self._selected_map_id: int | None = None
        self._build()
        if self.realtime is not None:
            self.realtime.maps_updated.connect(self.update_maps)
            self.realtime.map_apply_result.connect(self._handle_apply_result)
            self.realtime.error.connect(self._show_error)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("서비스 지역 지도 관리", "지도 선택 및 도비 Nav2 맵 적용"))

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(20)
        root.addWidget(body, 1)

        left = QWidget()
        left.setMaximumWidth(360)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addWidget(mklbl("지도 목록", 14, True))
        self.apply_btn = mkbtn("이 맵 사용", small=True)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._request_apply)
        ll.addLayout(disabled_row(self.apply_btn))
        self.map_table = make_table(["ID", "지도", "상태"], [])
        self.map_table.itemSelectionChanged.connect(self._on_selection_changed)
        ll.addWidget(self.map_table, 1)
        bl.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(16)

        pcard, pl = card_frame("지도 속성")
        g = QGridLayout()
        self.e_name = QLineEdit()
        self.e_format = QLineEdit()
        self.e_resolution = QLineEdit()
        self.e_origin = QLineEdit()
        for widget in [self.e_name, self.e_format, self.e_resolution, self.e_origin]:
            widget.setReadOnly(True)
        g.addWidget(mklbl("이름", bold=True), 0, 0); g.addWidget(self.e_name, 0, 1)
        g.addWidget(mklbl("포맷", bold=True), 0, 2); g.addWidget(self.e_format, 0, 3)
        g.addWidget(mklbl("해상도", bold=True), 1, 0); g.addWidget(self.e_resolution, 1, 1)
        g.addWidget(mklbl("원점", bold=True), 1, 2); g.addWidget(self.e_origin, 1, 3)
        pl.addLayout(g)
        self.status_label = QLabel("선택된 지도 없음")
        self.status_label.setStyleSheet(f"font-size:13px; color:{TEXT2}; background:transparent;")
        pl.addWidget(self.status_label)
        rl.addWidget(pcard)

        ccard, cl = card_frame("지도 미리보기")
        toolbar = disabled_row(mkobtn("새로고침"), mkbtn("삭제", ERROR, True))
        toolbar.itemAt(0).widget().setEnabled(False)
        toolbar.itemAt(1).widget().setEnabled(False)
        cl.addLayout(toolbar)
        self.canvas = MapCanvas()
        cl.addWidget(self.canvas, 1)
        rl.addWidget(ccard, 1)
        bl.addWidget(right, 1)

    def update_maps(self, payload: dict) -> None:
        self._state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        maps = payload.get("maps")
        self._maps = maps if isinstance(maps, list) else []
        rows = []
        for item in self._maps:
            status = []
            if item.get("active"):
                status.append("선택")
            if item.get("applied"):
                status.append("적용")
            if not item.get("has_image"):
                status.append("이미지 없음")
            rows.append([item.get("map_id"), item.get("name"), ", ".join(status) or "-"])
        set_table_rows(self.map_table, rows)
        self._restore_selection()
        self._update_status()

    def _on_selection_changed(self) -> None:
        items = self.map_table.selectedItems()
        if not items:
            self._selected_map_id = None
            self.apply_btn.setEnabled(False)
            self._set_detail(None)
            return
        try:
            self._selected_map_id = int(self.map_table.item(items[0].row(), 0).text())
        except (AttributeError, ValueError):
            self._selected_map_id = None
        selected = self._selected_map()
        self.apply_btn.setEnabled(bool(selected and selected.get("has_image")))
        self._set_detail(selected)

    def _restore_selection(self) -> None:
        if self._selected_map_id is None:
            self._set_detail(None)
            return
        for row in range(self.map_table.rowCount()):
            item = self.map_table.item(row, 0)
            if item is not None and item.text() == str(self._selected_map_id):
                self.map_table.selectRow(row)
                self._set_detail(self._selected_map())
                return

    def _set_detail(self, selected: dict | None) -> None:
        self.e_name.setText(str((selected or {}).get("name") or ""))
        self.e_format.setText(str((selected or {}).get("image_format") or ""))
        self.e_resolution.setText(str((selected or {}).get("resolution") or ""))
        self.e_origin.setText(str((selected or {}).get("origin") or ""))
        self.canvas.set_map(selected)

    def _update_status(self) -> None:
        status = self._state.get("apply_status", "idle")
        active = self._state.get("active_map_id")
        applied = self._state.get("applied_map_id")
        error = self._state.get("last_error")
        if status == "failed":
            self.status_label.setText(f"적용 실패: {error or '-'}")
            self.status_label.setStyleSheet(f"font-size:13px; color:{ERROR}; background:transparent;")
            return
        if status == "applying":
            self.status_label.setText(f"지도 적용 중: map_id={active}")
            self.status_label.setStyleSheet(f"font-size:13px; color:{WARNING}; background:transparent;")
            return
        if status == "applied":
            self.status_label.setText(f"적용 완료: map_id={applied}")
            self.status_label.setStyleSheet(f"font-size:13px; color:{PRIMARY}; background:transparent;")
            return
        self.status_label.setText("선택된 지도 없음")
        self.status_label.setStyleSheet(f"font-size:13px; color:{TEXT2}; background:transparent;")

    def _request_apply(self) -> None:
        if self.realtime is None or self._selected_map_id is None:
            return
        self.apply_btn.setEnabled(False)
        self.realtime.request_map_apply(self._selected_map_id)

    def _handle_apply_result(self, result: dict) -> None:
        self.apply_btn.setEnabled(bool(self._selected_map() and self._selected_map().get("has_image")))
        if result.get("ok"):
            QMessageBox.information(self, "지도 적용", "지도 적용 요청이 완료되었습니다.")
        else:
            self._show_error(result.get("message") or result.get("reason") or "지도 적용 실패")

    def _show_error(self, message: str) -> None:
        if self.isVisible():
            QMessageBox.warning(self, "지도 관리", message)

    def _selected_map(self) -> dict | None:
        for item in self._maps:
            if item.get("map_id") == self._selected_map_id:
                return item
        return None
