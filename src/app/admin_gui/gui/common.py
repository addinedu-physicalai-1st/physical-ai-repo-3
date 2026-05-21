from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from style import (
    BG,
    BORDER,
    CARD,
    PRIMARY,
    TEXT,
    TEXT2,
    TEXT3,
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
    set_table_rows(t, rows or [])
    return t


def set_table_rows(table, rows):
    table.clearContents()
    table.clearSpans()
    if not rows:
        table.setRowCount(1)
        item = QTableWidgetItem('비어 있음')
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        table.setItem(0, 0, item)
        if table.columnCount() > 1:
            table.setSpan(0, 0, 1, table.columnCount())
        return

    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(value)))


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
        button.setEnabled(True)
        row.addWidget(button)
    row.addStretch()
    return row


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
        self.table = make_table(headers, rows)
        bl.addWidget(self.table, 1)

    def set_rows(self, rows):
        set_table_rows(self.table, rows)
