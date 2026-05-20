from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from style import BG, CYAN, ORANGE, PRIMARY, PURPLE, SUCCESS, TEXT2, TEXT3
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import DASHBOARD_STATS

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


DEVICE_ROBOT_LIST = ['Doby', 'DDooby']

DEVICE_ROBOT_STATUS_LIST = [
    ('Doby', '정상대기', 87, '양호(5G)', '대기 중', '정상'),
    ('DDooby', '충전중', 54, '보통(4G)', '충전 중', '정상'),
]


class DeviceManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('장치 관리', '로봇 모드 상태 모니터링'))
        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(20)
        root.addWidget(body, 1)

        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setSpacing(16)
        for i, robot in enumerate(DEVICE_ROBOT_STATUS_LIST):
            grid.addWidget(self._robot_card(*robot), i // 3, i % 3)
        bl.addWidget(wrap_scroll(cards), 1)

        top = QHBoxLayout()
        top.addWidget(mklbl('제어 대상 로봇:', bold=True))
        combo = QComboBox()
        combo.addItems(DEVICE_ROBOT_LIST)
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
