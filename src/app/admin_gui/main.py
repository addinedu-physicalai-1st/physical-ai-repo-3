#!/usr/bin/env python3
"""Robot Service Admin GUI entrypoint."""
import logging
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from gui.layout import MainWindow
from gui.realtime import AdminGuiRealtimeBridge
from style import APP_STYLE


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(APP_STYLE)

    realtime = AdminGuiRealtimeBridge()
    win = MainWindow(realtime)
    win.show()
    QTimer.singleShot(0, realtime.start)
    try:
        return app.exec()
    finally:
        realtime.stop()


if __name__ == '__main__':
    sys.exit(main())
