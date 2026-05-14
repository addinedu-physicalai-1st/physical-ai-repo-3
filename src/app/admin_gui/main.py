#!/usr/bin/env python3
"""Robot Service Admin GUI entrypoint."""
import sys

from PyQt6.QtWidgets import QApplication

from gui import MainWindow
from style import APP_STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(APP_STYLE)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
