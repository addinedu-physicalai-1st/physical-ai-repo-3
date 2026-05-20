#!/usr/bin/env python3
"""Robot Service Admin GUI entrypoint."""
import logging
import sys

from PyQt6.QtWidgets import QApplication

from gui.layout import MainWindow
from style import APP_STYLE
from tcp_api import AdminGuiTcpHealthServer


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def main() -> int:
    tcp_health_server = AdminGuiTcpHealthServer()
    tcp_health_server.start()

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(APP_STYLE)

    win = MainWindow()
    win.show()
    try:
        return app.exec()
    finally:
        tcp_health_server.stop()


if __name__ == '__main__':
    sys.exit(main())
