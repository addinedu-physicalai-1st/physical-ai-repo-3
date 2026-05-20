from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from style import BG, CYAN, ERROR, PURPLE, SUCCESS, TEXT2, TEXT3
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import ROBOT_LIST, ROBOT_STATUS_LIST

from gui.common import (
    card_frame,
    disabled_row,
    hdivider,
    mkbadge,
    mkbtn,
    mklbl,
    page_header,
    wrap_scroll,
)


class MonitoringPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('실시간 모니터링', '로봇 상태 실시간 확인 및 블랙박스 재생'))
        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(16)
        root.addWidget(body, 1)
        bl.addLayout(disabled_row(mkbtn('+ 로봇 추가'), mkbtn('로봇 제거', ERROR)))

        cards = QWidget()
        grid = QGridLayout(cards)
        for i, robot in enumerate(ROBOT_STATUS_LIST):
            grid.addWidget(self._robot_card(*robot), i // 3, i % 3)
        bl.addWidget(wrap_scroll(cards), 1)

        card, cl = card_frame('블랙박스 재생')
        row = disabled_row(mkbtn('블랙박스 재생', PURPLE))
        combo = QComboBox()
        combo.addItems(ROBOT_LIST)
        combo.setEnabled(True)
        row.insertWidget(0, mklbl('로봇 선택:', bold=True))
        row.insertWidget(1, combo)
        cl.addLayout(row)
        bl.addWidget(card)

    def _robot_card(self, rid, status, battery, signal, task, damage):
        card, lay = card_frame()
        card.setMinimumSize(240, 200)
        top = QHBoxLayout()
        top.addWidget(mklbl(rid, 15, True))
        top.addStretch()
        color = SUCCESS if status == '정상대기' else CYAN if status == '충전중' else TEXT3
        top.addWidget(mkbadge(status, color))
        lay.addLayout(top)
        lay.addWidget(hdivider())
        lay.addWidget(mklbl(f'배터리 {battery}%', bold=True))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(battery)
        bar.setTextVisible(False)
        lay.addWidget(bar)
        lay.addWidget(mklbl(f'통신: {signal}', color=TEXT2))
        lay.addWidget(mklbl(f'작업: {task}', color=TEXT2))
        lay.addWidget(mklbl(f'기물: {damage}', color=TEXT2))
        return card
