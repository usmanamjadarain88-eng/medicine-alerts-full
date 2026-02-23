from theme.tokens import (
    PRIMARY,
    PRIMARY_HOVER,
    BORDER_LIGHT,
    TEXT_PRIMARY_LIGHT,
    TEXT_SECONDARY_LIGHT,
    BG_LIGHT,
    BG_CARD_LIGHT,
    BG_INPUT_LIGHT,
    ACCENT_LIGHT,
    RADIUS,
    RADIUS_SM,
    RADIUS_LG,
    LOW_STOCK_RED,
)

LIGHT_THEME = f"""
QMainWindow, QWidget, QDialog {{
    background-color: {BG_LIGHT};
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER_LIGHT};
    border-radius: {RADIUS_LG};
    top: -1px;
    background: {BG_CARD_LIGHT};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY_LIGHT};
    padding: 14px 24px;
    margin-right: 4px;
    border: none;
    border-radius: {RADIUS};
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    background-color: #CCFBF1;
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QLabel {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QGroupBox {{
    color: {ACCENT_LIGHT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: {RADIUS};
    margin-top: 18px;
    padding: 20px 16px 16px 16px;
    background-color: {BG_CARD_LIGHT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    background: transparent;
    color: {ACCENT_LIGHT};
    font-size: 15px;
    font-weight: 600;
}}
QPushButton {{
    background-color: {PRIMARY};
    color: #ffffff;
    border: none;
    padding: 12px 24px;
    border-radius: {RADIUS_SM};
    font-weight: 600;
    font-size: 14px;
}}
QPushButton:hover {{
    background-color: {PRIMARY_HOVER};
}}
QPushButton:pressed {{
    background-color: {PRIMARY_HOVER};
}}
QPushButton:disabled {{
    background-color: #CBD5E1;
    color: {TEXT_SECONDARY_LIGHT};
}}
QPushButton#danger {{
    background-color: #b91c1c;
    color: #fee2e2;
}}
QPushButton#danger:hover {{
    background-color: {LOW_STOCK_RED};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit, QTimeEdit {{
    background-color: {BG_INPUT_LIGHT};
    color: {TEXT_PRIMARY_LIGHT};
    border: 1px solid #CBD5E1;
    border-radius: {RADIUS_SM};
    padding: 12px 14px;
    selection-background-color: {PRIMARY};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
    border: 2px solid {PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: {BG_CARD_LIGHT};
    border: 1px solid {BORDER_LIGHT};
}}
QScrollBar:vertical {{
    background: {BG_CARD_LIGHT};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: #99D9CF;
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
    background: {BG_CARD_LIGHT};
    border: 1px solid #94a3b8;
    border-radius: {RADIUS};
}}
QTableWidget::item {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QHeaderView::section {{
    background: #F1F5F9;
    color: {ACCENT_LIGHT};
    padding: 10px;
}}
QListWidget {{
    background: {BG_CARD_LIGHT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: {RADIUS};
}}
QListWidget::item {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QCheckBox {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-radius: 4px;
}}
QSlider::groove:horizontal {{
    background: #E2E8F0;
    height: 8px;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: {PRIMARY};
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}}
QMenuBar {{
    background: {BG_CARD_LIGHT};
    color: {TEXT_PRIMARY_LIGHT};
}}
QMenuBar::item:selected {{
    background: {PRIMARY};
    color: #ffffff;
}}
QStatusBar {{
    background: {BG_CARD_LIGHT};
    color: {TEXT_SECONDARY_LIGHT};
    border-top: 1px solid {BORDER_LIGHT};
}}
QCalendarWidget {{
    background-color: {BG_CARD_LIGHT};
    color: {TEXT_PRIMARY_LIGHT};
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: #F1F5F9;
    color: {TEXT_PRIMARY_LIGHT};
    min-height: 36px;
}}
QCalendarWidget QToolButton {{
    background-color: #F1F5F9;
    color: {TEXT_PRIMARY_LIGHT};
    border: 1px solid {BORDER_LIGHT};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {BG_CARD_LIGHT};
    color: {TEXT_PRIMARY_LIGHT};
}}
QCalendarWidget QLabel {{
    color: {TEXT_PRIMARY_LIGHT};
}}
QCalendarWidget QComboBox {{
    background-color: {BG_INPUT_LIGHT};
    color: {TEXT_PRIMARY_LIGHT};
    min-height: 24px;
}}
"""

