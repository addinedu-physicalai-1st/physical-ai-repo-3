from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from style import BG, BORDER, CARD, CYAN, ORANGE, PRIMARY, SUCCESS, TEXT, TEXT2, TEXT3, WARNING

from gui.common import card_frame, hdivider, mkbadge, mkbtn, mklbl, page_header, wrap_scroll


class DobyMonitoringPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('도비 모니터링', '서빙 로봇 Doby 운영 상태 대시보드'))

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

    def _status_bar(self):
        bar = QFrame()
        bar.setObjectName('dobyStatusBar')
        bar.setStyleSheet(f"""
            QFrame#dobyStatusBar {{
                background:{CARD}; border:1px solid {BORDER}; border-radius:12px;
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        lay.addWidget(mkbadge('IDLE', PRIMARY))
        lay.addWidget(self._battery_chip(87))
        lay.addWidget(mkbadge('정상', SUCCESS))
        lay.addWidget(self._robot_chip('Doby', True))
        lay.addStretch()
        lay.addWidget(mklbl('14:32:08', 13, True, TEXT2))
        return bar

    def _main_dashboard(self):
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._floorplan_card(), 3)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._mode_card())
        right.addWidget(self._quick_mode_card(), 1)
        row.addLayout(right, 1)
        return row

    def _mode_card(self):
        card, lay = card_frame('현재 모드')
        card.setMinimumHeight(150)
        lay.addWidget(mkbadge('대기 모드', PRIMARY))
        lay.addWidget(mklbl('진입: 14:25:12 (7분 경과)', 12, color=TEXT2))
        lay.addStretch()
        return card

    def _floorplan_card(self):
        card, lay = card_frame()
        header = QHBoxLayout()
        header.addWidget(mklbl('도비 위치', 15, True))
        header.addStretch()
        lay.addLayout(header)
        lay.addWidget(self._floorplan(), 1)
        return card

    def _quick_mode_card(self):
        card, lay = card_frame('빠른 모드')
        lay.setSpacing(10)
        for label, color in [
            ('대기', PRIMARY),
            ('호객', ORANGE),
            ('서빙', SUCCESS),
            ('순회', CYAN),
            ('긴급 정지', WARNING),
        ]:
            btn = mkbtn(label, color)
            btn.setMinimumHeight(42)
            lay.addWidget(btn)
        lay.addStretch()
        return card

    def _event_feed(self):
        card, lay = card_frame()
        header = QHBoxLayout()
        header.addWidget(mklbl('실시간 이벤트', 15, True))
        header.addStretch()
        header.addWidget(mklbl('더보기', 12, True, PRIMARY))
        lay.addLayout(header)

        feed = QListWidget()
        feed.setMinimumHeight(220)
        feed.setStyleSheet(f"""
            QListWidget {{
                background:{CARD}; border:1px solid {BORDER}; border-radius:8px;
                color:{TEXT}; font-size:13px;
            }}
            QListWidget::item {{
                padding:10px 12px; border-bottom:1px solid {BORDER};
            }}
        """)
        for event in [
            '14:32:08 · Doby Online',
            '14:31:46 · 배터리 87%',
            '14:30:12 · idle 모드 진입',
            '14:27:33 · 테이블 3 서빙 완료',
            '14:25:12 · 자동 patrol 대기 시작',
        ]:
            feed.addItem(QListWidgetItem(event))
        lay.addWidget(feed)
        return card

    def _battery_chip(self, percentage):
        chip = QFrame()
        chip.setObjectName('batteryChip')
        chip.setStyleSheet(f"""
            QFrame#batteryChip {{
                background:{SUCCESS}12; border:1px solid {SUCCESS}44; border-radius:11px;
            }}
        """)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(8)
        lay.addWidget(mklbl('BATT', 11, True, SUCCESS))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(percentage)
        bar.setTextVisible(False)
        bar.setFixedSize(64, 8)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background:#DCFCE7; border:none; border-radius:4px;
            }}
            QProgressBar::chunk {{
                background:{SUCCESS}; border-radius:4px;
            }}
        """)
        lay.addWidget(bar)
        lay.addWidget(mklbl(f'{percentage}%', 11, True, SUCCESS))
        return chip

    def _robot_chip(self, name, online):
        color = SUCCESS if online else TEXT3
        text = f'{name} Online' if online else f'{name} Offline'
        return mkbadge(text, color)

    def _floorplan(self):
        plan = QFrame()
        plan.setMinimumHeight(360)
        plan.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plan.setObjectName('floorplan')
        plan.setStyleSheet(f"""
            QFrame#floorplan {{
                background:#F8FAFC; border:1px solid {BORDER}; border-radius:10px;
            }}
        """)
        grid = QGridLayout(plan)
        grid.setContentsMargins(18, 18, 18, 18)
        grid.setSpacing(12)

        for row in range(5):
            grid.setRowStretch(row, 1)
        for col in range(6):
            grid.setColumnStretch(col, 1)

        grid.addWidget(self._zone('카운터', ORANGE), 0, 0, 1, 2)
        grid.addWidget(self._zone('픽업 존', PRIMARY), 0, 2, 1, 2)
        grid.addWidget(self._zone('충전 스테이션', SUCCESS), 0, 4, 1, 2)
        grid.addWidget(self._table('T1'), 2, 0)
        grid.addWidget(self._table('T2'), 2, 2)
        grid.addWidget(self._table('T3'), 2, 4)
        grid.addWidget(self._table('T4'), 4, 1)
        grid.addWidget(self._table('T5'), 4, 3)
        grid.addWidget(self._robot_marker(), 3, 5)
        return plan

    def _zone(self, text, color):
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"""
            background:{color}18; color:{color}; border:1px solid {color}55;
            border-radius:8px; font-size:13px; font-weight:700;
        """)
        return label

    def _table(self, text):
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(86, 58)
        label.setStyleSheet(f"""
            background:{CARD}; color:{TEXT2}; border:1px solid {BORDER};
            border-radius:8px; font-size:13px; font-weight:800;
        """)
        return label

    def _robot_marker(self):
        marker = QFrame()
        marker.setObjectName('robotMarker')
        marker.setStyleSheet(f"""
            QFrame#robotMarker {{
                background:{PRIMARY}; border-radius:18px; border:3px solid #DBEAFE;
            }}
        """)
        lay = QVBoxLayout(marker)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(mklbl('Doby', 14, True, '#FFFFFF'), alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hdivider())
        lay.addWidget(mklbl('x 12.4 · y 8.1', 11, True, '#DBEAFE'), alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(mklbl('heading 90°', 11, True, '#DBEAFE'), alignment=Qt.AlignmentFlag.AlignCenter)
        return marker
