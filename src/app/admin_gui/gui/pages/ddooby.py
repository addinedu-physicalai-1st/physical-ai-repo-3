from PyQt6.QtWidgets import QVBoxLayout, QWidget

from style import BG

from gui.common import page_header


class DDoobyMonitoringPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('뚜비 모니터링'))

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        root.addWidget(body, 1)
