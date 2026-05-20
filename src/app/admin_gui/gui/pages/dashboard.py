from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from style import BG, ORANGE, PRIMARY, PURPLE, SUCCESS, TEXT2, TEXT3
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import ROBOT_LIST, DASHBOARD_STATS

from gui.common import (
    card_frame,
    disabled_row,
    mkbadge,
    mkbtn,
    mklbl,
    page_header,
)


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('관제 대시보드', '로봇 모드 전환 및 상태 모니터링'))
        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(20)
        root.addWidget(body, 1)

        top = QHBoxLayout()
        top.addWidget(mklbl('제어 대상 로봇:', bold=True))
        combo = QComboBox()
        combo.addItems(ROBOT_LIST)
        combo.setEnabled(True)
        top.addWidget(combo)
        top.addStretch()
        top.addWidget(mkbadge('연결됨', SUCCESS))
        bl.addLayout(top)

        card, lay = card_frame('모드 전환')
        row = disabled_row(
            mkbtn('대기', TEXT2),
            mkbtn('호객 NPC', ORANGE),
            mkbtn('서빙', PRIMARY),
            mkbtn('팔로우', PURPLE),
        )
        lay.addLayout(row)
        bl.addWidget(card)

        scard, sl = card_frame('상태 표시')
        stats = QGridLayout()
        for i, (label, value, color) in enumerate(DASHBOARD_STATS):
            stats.addWidget(mklbl(label, 11, color=TEXT3), 0, i)
            stats.addWidget(mklbl(value, 16, True, color), 1, i)
        sl.addLayout(stats)
        bl.addWidget(scard)

        fcard, fl = card_frame('강제 발화')
        text = QLineEdit()
        text.setPlaceholderText('발화 텍스트를 입력하세요...')
        text.setReadOnly(False)
        pri = QSpinBox()
        pri.setRange(1, 10)
        pri.setValue(10)
        pri.setEnabled(True)
        fl.addWidget(text)
        fl.addWidget(pri)
        fl.addLayout(disabled_row(mkbtn('전송', PURPLE)))
        bl.addWidget(fcard)
        bl.addStretch()
