"""Shared style constants and QSS for the admin GUI."""

BG = '#F4F6F9'
SIDEBAR = '#1B2840'
SB_HV = '#263450'
SB_ACT = '#2563EB'
PRIMARY = '#2563EB'
SUCCESS = '#16A34A'
WARNING = '#D97706'
ERROR = '#DC2626'
PURPLE = '#7C3AED'
CYAN = '#0891B2'
ORANGE = '#EA580C'
CARD = '#FFFFFF'
BORDER = '#E2E8F0'
TEXT = '#0F172A'
TEXT2 = '#475569'
TEXT3 = '#94A3B8'

APP_STYLE = f"""
* {{
    font-family: 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
}}
QMainWindow {{ background: {BG}; }}
QDialog {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: #F1F5F9; width: 7px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1; border-radius: 3px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: #F1F5F9; height: 7px; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: #CBD5E1; border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {CARD}; border: 1.5px solid {BORDER};
    border-radius: 7px; padding: 8px 12px; font-size: 13px; color: {TEXT};
}}
QComboBox {{
    background: {CARD}; border: 1.5px solid {BORDER};
    border-radius: 7px; padding: 8px 12px; font-size: 13px; color: {TEXT};
}}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    selection-background-color: {PRIMARY}22;
}}
QTextEdit, QPlainTextEdit {{
    background: {CARD}; border: 1.5px solid {BORDER};
    border-radius: 7px; padding: 8px 12px; font-size: 13px; color: {TEXT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QTextEdit:focus {{ border-color: {PRIMARY}; }}
QTableWidget {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {BORDER}; font-size: 13px; outline: none; color: {TEXT};
}}
QTableWidget::item {{ padding: 6px 12px; border: none; }}
QTableWidget::item:selected {{ background: {PRIMARY}20; color: {TEXT}; }}
QHeaderView::section {{
    background: #F8FAFC; font-weight: 700; font-size: 12px; color: {TEXT2};
    padding: 10px 12px; border: none; border-bottom: 2px solid {BORDER};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER}; border-radius: 8px; background: {CARD}; top: -1px;
}}
QTabBar::tab {{
    background: #F1F5F9; border: none; padding: 10px 22px; font-size: 13px;
    color: {TEXT2}; margin-right: 2px; border-radius: 6px 6px 0 0;
}}
QTabBar::tab:selected {{ background: {CARD}; color: {PRIMARY}; font-weight: 700; }}
QTabBar::tab:hover:!selected {{ background: #E2E8F0; }}
QCheckBox {{ spacing: 8px; font-size: 13px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 4px;
    border: 2px solid #CBD5E1; background: white;
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY};
}}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px;
    margin-top: 16px; padding: 14px 12px 12px;
    font-weight: 700; font-size: 13px; color: {TEXT2};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px; padding: 0 6px;
}}
QListWidget {{
    background: {CARD}; border: 1px solid {BORDER};
    border-radius: 8px; font-size: 13px;
}}
QListWidget::item {{ padding: 10px 14px; border-bottom: 1px solid {BORDER}; }}
QListWidget::item:selected {{
    background: {PRIMARY}22; color: {TEXT};
    border-left: 3px solid {PRIMARY};
}}
"""
