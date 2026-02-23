from theme.tokens import (
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    BG_CARD,
    BG_INPUT,
    RADIUS,
    RADIUS_SM,
    RADIUS_LG,
    LOW_STOCK_RED,
    ACCENT_DARK,
    ACCENT_DARK_DIM,
    BG_DARK,
)

DARK_THEME = f"""
QMainWindow, QWidget, QDialog {{
    background-color: {BG_DARK};
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_LG};
    top: -1px;
    background-color: {BG_DARK};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 14px 24px;
    margin-right: 4px;
    border: none;
    border-radius: {RADIUS};
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {ACCENT_DARK};
    background-color: rgba(45, 212, 191, 0.15);
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT_PRIMARY};
}}
QLabel {{
    color: {TEXT_PRIMARY};
}}
QGroupBox {{
    color: {ACCENT_DARK};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    background: transparent;
    color: {ACCENT_DARK};
    font-size: 16pt;
    font-weight: bold;
}}
QPushButton {{
    background-color: {ACCENT_DARK_DIM};
    color: #0a0e17;
    border: none;
    padding: 12px 24px;
    border-radius: {RADIUS_SM};
    font-weight: bold;
    font-size: 11pt;
}}
QPushButton:hover {{
    background-color: {ACCENT_DARK};
    border: 1px solid {ACCENT_DARK};
}}
QPushButton:pressed {{
    background-color: {ACCENT_DARK_DIM};
}}
QPushButton:disabled {{
    background-color: {BG_INPUT};
    color: {TEXT_SECONDARY};
}}
QPushButton#danger {{
    background-color: #7f1d1d;
    color: #fecaca;
}}
QPushButton#danger:hover {{
    background-color: {LOW_STOCK_RED};
    border: 1px solid {LOW_STOCK_RED};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit, QTimeEdit {{
    background-color: #000000;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM};
    padding: 10px 12px;
    selection-background-color: {ACCENT_DARK};
    selection-color: #0a0e17;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
    border: 1px solid {ACCENT_DARK};
}}
QComboBox::drop-down {{
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: #0a0e17;
    border: 1px solid {BORDER};
}}
QScrollBar:vertical {{
    background: {BG_CARD};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {ACCENT_DARK_DIM};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QTableWidget {{
    background: #000000;
    border: none;
    border-radius: {RADIUS};
}}
QTableWidget::item {{
    background-color: #000000;
    color: {TEXT_PRIMARY};
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}}
QTableWidget::item:hover {{
    background-color: #1e293b;
    color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background: #000000;
    color: {ACCENT_DARK};
    padding: 10px;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}}
QListWidget {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
}}
QListWidget::item {{
    color: {TEXT_PRIMARY};
}}
QCheckBox {{
    color: {TEXT_PRIMARY};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_DARK};
    border-radius: 4px;
}}
QSlider::groove:horizontal {{
    background: {BG_INPUT};
    height: 8px;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT_DARK};
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}}
QMenuBar {{
    background: {BG_CARD};
    color: {TEXT_PRIMARY};
}}
QMenuBar::item:selected {{
    background: {ACCENT_DARK};
    color: #0a0e17;
}}
QStatusBar {{
    background: {BG_CARD};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
}}
QCalendarWidget {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    min-height: 36px;
}}
QCalendarWidget QToolButton {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
}}
QCalendarWidget QLabel {{
    color: {TEXT_PRIMARY};
}}
QCalendarWidget QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    min-height: 24px;
}}
"""
