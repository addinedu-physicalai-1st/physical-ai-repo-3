from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from style import (
    BG,
    BORDER,
    CARD,
    CYAN,
    ERROR,
    ORANGE,
    PRIMARY,
    PURPLE,
    SB_ACT,
    SB_HV,
    SIDEBAR,
    SUCCESS,
    TEXT,
    TEXT2,
    TEXT3,
    WARNING,
)


def mkbtn(text, color=None, small=False):
    b = QPushButton(text)
    c = color or PRIMARY
    pad = '6px 14px' if small else '9px 22px'
    fs = '12px' if small else '13px'
    b.setStyleSheet(f"""
        QPushButton {{
            background:{c}; color:#fff; border:none; border-radius:7px;
            font-size:{fs}; font-weight:700; padding:{pad};
        }}
        QPushButton:hover   {{ background:{c}dd; }}
        QPushButton:pressed  {{ background:{c}99; }}
        QPushButton:disabled {{ background:#E2E8F0; color:{TEXT3}; }}
    """)
    return b


def mkobtn(text, color=None):
    b = QPushButton(text)
    c = color or PRIMARY
    b.setStyleSheet(f"""
        QPushButton {{
            background:transparent; color:{c}; border:2px solid {c};
            border-radius:7px; font-size:13px; font-weight:700; padding:7px 18px;
        }}
        QPushButton:hover   {{ background:{c}18; }}
        QPushButton:pressed  {{ background:{c}33; }}
        QPushButton:disabled {{ color:{TEXT3}; border-color:{BORDER}; }}
    """)
    return b


def mklbl(text, size=13, bold=False, color=None):
    l = QLabel(text)
    c = color or TEXT
    w = 700 if bold else 400
    l.setStyleSheet(f"font-size:{size}px; font-weight:{w}; color:{c}; background:transparent;")
    return l


def mkbadge(text, color):
    l = QLabel(f" {text} ")
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setFixedHeight(22)
    l.setStyleSheet(f"""
        background:{color}22; color:{color}; border-radius:11px;
        font-size:11px; font-weight:700; padding:0px 8px; border:1px solid {color}44;
    """)
    return l


def hdivider():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER}; max-height:1px; background:{BORDER};")
    return f


def wrap_scroll(widget):
    s = QScrollArea()
    s.setWidget(widget)
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setStyleSheet("background:transparent;")
    return s


def card_frame(title=''):
    f = QFrame()
    f.setObjectName('cardFrame')
    f.setStyleSheet(f"""
        QFrame#cardFrame {{
            background:{CARD}; border-radius:12px; border:1px solid {BORDER};
        }}
    """)
    vl = QVBoxLayout(f)
    vl.setContentsMargins(20, 18, 20, 18)
    vl.setSpacing(12)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size:15px; font-weight:700; color:{TEXT}; background:transparent;")
        vl.addWidget(lbl)
    return f, vl


def make_table(headers, rows=None):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setShowGrid(True)
    t.setStyleSheet("alternate-background-color:#F8FAFC;")
    if rows:
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                t.setItem(r, c, QTableWidgetItem(str(value)))
    return t


def page_header(title, subtitle=''):
    w = QWidget()
    w.setObjectName('pageHeader')
    w.setStyleSheet(f"QWidget#pageHeader{{background:{CARD}; border-bottom:1px solid {BORDER};}}")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(28, 18, 28, 18)
    vl = QVBoxLayout()
    vl.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"font-size:22px; font-weight:800; color:{TEXT}; background:transparent;")
    vl.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size:13px; color:{TEXT2}; background:transparent;")
        vl.addWidget(s)
    hl.addLayout(vl)
    hl.addStretch()
    return w


def disabled_row(*buttons):
    row = QHBoxLayout()
    for button in buttons:
        button.setEnabled(False)
        row.addWidget(button)
    row.addStretch()
    return row


class MapCanvas(QWidget):
    FACILITIES = [
        ('커피트럭', '#92400E', 150, 120),
        ('테이블 A', '#1D4ED8', 270, 180),
        ('테이블 B', '#1D4ED8', 360, 250),
        ('로봇 대기', '#059669', 210, 270),
    ]

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
        ll.addWidget(make_table(['지도', '위치'], [
            ['1층 로비', '서울 강남구 테헤란로 123'],
            ['2층 테라스', '서울 강남구 테헤란로 123'],
        ]), 1)
        bl.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(16)
        pcard, pl = card_frame('지도 속성')
        g = QGridLayout()
        self.e_name = QLineEdit('1층 로비')
        self.e_loc = QLineEdit('서울 강남구 테헤란로 123')
        self.e_w = QLineEdit('20.0 m')
        self.e_h = QLineEdit('15.0 m')
        for widget in [self.e_name, self.e_loc, self.e_w, self.e_h]:
            widget.setReadOnly(True)
        g.addWidget(mklbl('이름', bold=True), 0, 0); g.addWidget(self.e_name, 0, 1)
        g.addWidget(mklbl('위치', bold=True), 0, 2); g.addWidget(self.e_loc, 0, 3)
        g.addWidget(mklbl('너비', bold=True), 1, 0); g.addWidget(self.e_w, 1, 1)
        g.addWidget(mklbl('높이', bold=True), 1, 2); g.addWidget(self.e_h, 1, 3)
        pl.addLayout(g)
        rl.addWidget(pcard)

        ccard, cl = card_frame('시설 배치')
        toolbar = disabled_row(
            mkbtn('커피트럭', '#92400E', True),
            mkbtn('테이블', '#1D4ED8', True),
            mkbtn('로봇 대기', '#059669', True),
            mkobtn('이동/선택'),
            mkbtn('선택삭제', ERROR, True),
            mkbtn('전체삭제', WARNING, True),
        )
        cl.addLayout(toolbar)
        cl.addWidget(MapCanvas(), 1)
        rl.addWidget(ccard, 1)
        bl.addWidget(right, 1)


class SimpleTablePage(QWidget):
    def __init__(self, title, subtitle, toolbar_buttons, headers, rows):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header(title, subtitle))
        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(16)
        root.addWidget(body, 1)
        if toolbar_buttons:
            bl.addLayout(disabled_row(*toolbar_buttons))
        bl.addWidget(make_table(headers, rows), 1)


class MenuPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '상품 메뉴 관리',
            '음료 메뉴 등록·수정·삭제 및 대표 메뉴 지정',
            [mkbtn('+ 메뉴 추가'), mkbtn('수정', WARNING), mkbtn('삭제', ERROR), mkbadge('대표 메뉴: 아메리카노, 카라멜 마끼아또', PRIMARY)],
            ['상품번호', '상품명', '가격', '알러지', '옵션', '대표'],
            [
                ['M001', '아메리카노', '3,500원', '없음', '샷추가 / 기본 얼음', '대표'],
                ['M002', '카페라떼', '4,000원', '우유', '샷추가 / 저지방 / 기본 얼음', ''],
                ['M003', '카라멜 마끼아또', '4,500원', '우유, 대두', '샷추가 / 크러쉬드 아이스', '대표'],
            ],
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
        for i, robot in enumerate([
            ('ROB-01', '정상대기', 87, '양호(5G)', '대기 중', '정상'),
            ('ROB-02', '충전중', 54, '보통(4G)', '충전 중', '정상'),
            ('ROB-03', '오프라인', 100, '없음', '대기 중', '정상'),
        ]):
            grid.addWidget(self._robot_card(*robot), i // 3, i % 3)
        bl.addWidget(wrap_scroll(cards), 1)

        card, cl = card_frame('블랙박스 재생')
        row = disabled_row(mkbtn('블랙박스 재생', PURPLE))
        combo = QComboBox()
        combo.addItems(['ROB-01', 'ROB-02', 'ROB-03'])
        combo.setEnabled(False)
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
        combo.addItems(['ROB-01', 'ROB-02', 'ROB-03'])
        combo.setEnabled(False)
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
        for i, (label, value, color) in enumerate([
            ('현재 모드', '대기', PRIMARY),
            ('배터리', '87%', SUCCESS),
            ('안전 알람', '없음', SUCCESS),
            ('Reject 사유', '-', TEXT2),
        ]):
            stats.addWidget(mklbl(label, 11, color=TEXT3), 0, i)
            stats.addWidget(mklbl(value, 16, True, color), 1, i)
        sl.addLayout(stats)
        bl.addWidget(scard)

        fcard, fl = card_frame('강제 발화')
        text = QLineEdit()
        text.setPlaceholderText('발화 텍스트를 입력하세요...')
        text.setReadOnly(True)
        pri = QSpinBox()
        pri.setRange(1, 10)
        pri.setValue(10)
        pri.setEnabled(False)
        fl.addWidget(text)
        fl.addWidget(pri)
        fl.addLayout(disabled_row(mkbtn('전송', PURPLE)))
        bl.addWidget(fcard)
        bl.addStretch()


class SystemLogPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '시스템 로그',
            '로봇 및 시스템 이벤트 로그 조회',
            [mkobtn('로그 초기화', ERROR)],
            ['시각', '레벨', '로봇', '분류', '메시지'],
            [
                ['10:00:00', 'INFO', 'SYSTEM', 'task', '서빙 태스크 시작'],
                ['10:01:12', 'WARN', 'ROB-02', '하드웨어', '배터리 경고'],
                ['10:03:24', 'INFO', 'ROB-01', '주행', '목적지 도착'],
            ],
        )


class AnomalyPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '이상 상태 감지',
            '로봇 이상 알림 수신 및 확인 처리',
            [mkbtn('선택 확인 처리', SUCCESS), mkbtn('전체 확인', WARNING), mkbtn('확인된 항목 삭제', ERROR)],
            ['유형', '로봇', '발생시각', '상세', '상태'],
            [
                ['통신 이상', 'ROB-02', '05/20 10:12:00', '통신 지연 감지', '미확인'],
                ['로봇 파손', 'ROB-03', '05/20 10:15:00', '전면 파손 이벤트', '확인됨'],
            ],
        )


class Sidebar(QWidget):
    page_changed = pyqtSignal(int)

    NAV_ITEMS = [
        ('지도 관리'),
        ('메뉴 관리'),
        ('실시간 모니터링'),
        ('관제 대시보드'),
        ('시스템 로그'),
        ('이상 감지'),
    ]

    def __init__(self):
        super().__init__()
        self.setFixedWidth(220)
        self.setStyleSheet(f"background:{SIDEBAR};")
        self._btns = []
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        logo = QWidget()
        logo.setFixedHeight(70)
        logo.setStyleSheet(f"background:{SIDEBAR}; border-bottom:1px solid #2D3F5A;")
        ll = QVBoxLayout(logo)
        ll.setContentsMargins(20, 16, 20, 14)
        title = QLabel('Robot Admin')
        title.setStyleSheet("color:#fff; font-size:15px; font-weight:800; background:transparent;")
        ll.addWidget(title)
        vl.addWidget(logo)

        nav = QWidget()
        nav.setStyleSheet(f"background:{SIDEBAR};")
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 12, 10, 12)
        nl.setSpacing(4)
        for i, label in enumerate(self.NAV_ITEMS):
            b = QPushButton(f"  {label}")
            b.setFixedHeight(44)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setStyleSheet(self._btn_style(i == 0))
            b.clicked.connect(lambda checked, idx=i: self._nav(idx))
            self._btns.append(b)
            nl.addWidget(b)
        nl.addStretch()
        vl.addWidget(nav, 1)

        footer = QWidget()
        footer.setFixedHeight(56)
        footer.setStyleSheet("background:#111B2E; border-top:1px solid #2D3F5A;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 10, 16, 10)
        ver = QLabel('v2.0.0 - PyQt6')
        ver.setStyleSheet("color:#475569; font-size:11px; background:transparent;")
        fl.addWidget(ver)
        fl.addStretch()
        vl.addWidget(footer)

    def _btn_style(self, active):
        if active:
            return f"""
                QPushButton {{
                    background:{SB_ACT}; color:#fff; border:none; border-radius:8px;
                    font-size:13px; font-weight:700; text-align:left; padding-left:4px;
                }}
            """
        return f"""
            QPushButton {{
                background:transparent; color:#94A3B8; border:none; border-radius:8px;
                font-size:13px; font-weight:500; text-align:left; padding-left:4px;
            }}
            QPushButton:hover {{ background:{SB_HV}; color:#fff; }}
        """

    def _nav(self, idx):
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._btn_style(i == idx))
        self.page_changed.emit(idx)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Robot Service Admin GUI - PyQt6')
        self.setMinimumSize(1280, 780)
        self._build()

    def _build(self):
        central = QWidget()
        central.setObjectName('root')
        central.setStyleSheet(f"QWidget#root{{background:{BG};}}")
        self.setCentralWidget(central)

        hl = QHBoxLayout(central)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self._switch_page)
        hl.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{BG};")
        for page in [
            MapManagementPage(),
            MenuPage(),
            MonitoringPage(),
            DashboardPage(),
            SystemLogPage(),
            AnomalyPage(),
        ]:
            self.stack.addWidget(page)
        hl.addWidget(self.stack, 1)

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
