from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from style import BG, SB_ACT, SB_HV, SIDEBAR
from gui.pages import (
    AnomalyPage,
    DDoobyMonitoringPage,
    DobyMonitoringPage,
    DeviceManagementPage,
    MapManagementPage,
    MenuPage,
    ServiceManagementPage,
    SystemLogPage,
)


class Sidebar(QWidget):
    page_changed = pyqtSignal(int)

    NAV_ITEMS = [
        ('지도 관리'),
        ('상품 관리'),
        ('서비스 관리'),
        ('장치 관리'),
        ('도비 모니터링'),
        ('뚜비 모니터링'),
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
    def __init__(self, realtime=None):
        super().__init__()
        self.realtime = realtime
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
            MenuPage(self.realtime),
            ServiceManagementPage(self.realtime),
            DeviceManagementPage(),
            DobyMonitoringPage(),
            DDoobyMonitoringPage(),
            SystemLogPage(),
            AnomalyPage(),
        ]:
            self.stack.addWidget(page)
        hl.addWidget(self.stack, 1)

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
