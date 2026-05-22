from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from style import BG, ERROR, PRIMARY, WARNING
from gui.common import (
    card_frame,
    disabled_row,
    make_table,
    mkbtn,
    mklbl,
    mkobtn,
    page_header,
)
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import MAP_FACILITIES, MAP_LIST, MAP_PROPERTIES


class MapCanvas(QWidget):
    FACILITIES = MAP_FACILITIES

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 360)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#FAFBFE'))
        p.setPen(QPen(QColor('#E2E8F0'), 1))
        for x in range(0, self.width(), 30):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 30):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(QColor(PRIMARY), 2))
        p.drawRect(1, 1, self.width() - 2, self.height() - 2)

        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        for label, color, x, y in self.FACILITIES:
            p.setBrush(QColor(f'{color}22'))
            p.setPen(QPen(QColor(color), 2))
            p.drawEllipse(x - 20, y - 20, 40, 40)
            p.drawText(x - 48, y + 30, 96, 18, Qt.AlignmentFlag.AlignCenter, label)


class MapManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('서비스 지역 지도 관리', '지도 생성·수정·삭제 및 시설 배치'))

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(20)
        root.addWidget(body, 1)

        left = QWidget()
        left.setMaximumWidth(260)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addWidget(mklbl('지도 목록', 14, True))
        ll.addLayout(disabled_row(mkbtn('+ 추가', small=True), mkbtn('삭제', ERROR, small=True)))
        ll.addWidget(make_table(['지도'], MAP_LIST), 1)
        bl.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(16)
        pcard, pl = card_frame('지도 속성')
        g = QGridLayout()
        self.e_name = QLineEdit(MAP_PROPERTIES.get('name', ''))
        self.e_loc = QLineEdit(MAP_PROPERTIES.get('location', ''))
        self.e_w = QLineEdit(MAP_PROPERTIES.get('width', ''))
        self.e_h = QLineEdit(MAP_PROPERTIES.get('height', ''))
        for widget in [self.e_name, self.e_loc, self.e_w, self.e_h]:
            widget.setReadOnly(False)
        g.addWidget(mklbl('이름', bold=True), 0, 0); g.addWidget(self.e_name, 0, 1)
        g.addWidget(mklbl('위치', bold=True), 0, 2); g.addWidget(self.e_loc, 0, 3)
        g.addWidget(mklbl('너비', bold=True), 1, 0); g.addWidget(self.e_w, 1, 1)
        g.addWidget(mklbl('높이', bold=True), 1, 2); g.addWidget(self.e_h, 1, 3)
        pl.addLayout(g)
        rl.addWidget(pcard)

        ccard, cl = card_frame('시설 배치')
        toolbar = disabled_row(
            mkobtn('이동'),
            mkbtn('삭제', ERROR, True),
        )
        cl.addLayout(toolbar)
        cl.addWidget(MapCanvas(), 1)
        rl.addWidget(ccard, 1)
        bl.addWidget(right, 1)
