import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import (
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QTabWidget,
        QLabel,
        QPushButton,
        QFrame,
        QStackedWidget,
        QDialog,
        QDialogButtonBox,
        QComboBox,
        QGroupBox,
        QMessageBox,
        QStatusBar,
        QGraphicsDropShadowEffect,
    )
    from PyQt6.QtCore import Qt, QThread, QSize, pyqtSignal, QTimer, QRectF
    from PyQt6.QtGui import QFont, QPainter, QPainterPath, QLinearGradient, QColor, QPixmap, QMovie, QPen
except ImportError:
    from PyQt5.QtWidgets import (  # type: ignore[import-untyped]
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QTabWidget,
        QLabel,
        QPushButton,
        QFrame,
        QStackedWidget,
        QDialog,
        QDialogButtonBox,
        QComboBox,
        QGroupBox,
        QMessageBox,
        QStatusBar,
        QGraphicsDropShadowEffect,
    )
    from PyQt5.QtCore import Qt, QThread, QSize, pyqtSignal, QTimer, QRectF  # type: ignore[import-untyped]
    from PyQt5.QtGui import QFont, QPainter, QPainterPath, QLinearGradient, QColor, QPixmap, QMovie, QPen  # type: ignore[import-untyped]

from ui.styles import DARK_THEME, LIGHT_THEME, NEON_GREEN, PRIMARY, TEXT_SECONDARY, ACCENT_LIGHT, ACCENT_DARK, SECONDARY_LIGHT_DARK
from ui.widgets.theme_toggle import ThemeToggle
from ui.tabs.main_panel_tab import MainPanelTab
from ui.tabs.add_medicine_tab import AddMedicineTab
from ui.tabs.dose_tracking_tab import DoseTrackingTab
from ui.tabs.medical_reminders_tab import MedicalRemindersTab
from ui.tabs.alerts_tab import AlertsTab
from ui.tabs.temp_adjustment_tab import TempAdjustmentTab
from ui.tabs.settings_tab import SettingsTab
from auth.pin_dialog import PinDialog


class BluetoothConnectThread(QThread):
    """Run connect_bluetooth in background."""
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def run(self):
        ok = self.controller.connect_bluetooth()
        # you can hook a signal here if needed


class LockedScreen(QWidget):
    """Locked screen matching dashboard design: card-style panel, teal accent, no animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "light"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        # Card container (same visual language as dashboard stat cards)
        self._card = QFrame()
        self._card.setObjectName("lockedCard")
        self._card.setMinimumWidth(420)
        self._card.setMaximumWidth(520)
        card_layout = QVBoxLayout(self._card)
        card_layout.setSpacing(20)
        card_layout.setContentsMargins(40, 36, 40, 36)

        self.center_lock = QLabel("System Locked")
        self.center_lock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_lock.setObjectName("lockedTitle")
        card_layout.addWidget(self.center_lock, alignment=Qt.AlignmentFlag.AlignCenter)

        self._subtitle = QLabel("Connect your device, then tap Authenticate in the sidebar to unlock.")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setObjectName("lockedSubtitle")
        card_layout.addWidget(self._subtitle, alignment=Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("lockedStatus")
        card_layout.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.set_theme("light")

    def set_status(self, text: str, color_hex: str):
        self._status_label.setText(text or "")
        if color_hex:
            self._status_label.setStyleSheet(f"font-size: 13px; color: {color_hex}; background: transparent;")
        self._status_label.setVisible(bool(text))

    def set_theme(self, theme: str):
        self._theme = (theme or "light").lower()
        if self._theme == "dark":
            self.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0f172a, stop:1 #0b1220);")
            self._card.setStyleSheet(
                "QFrame#lockedCard {"
                "background-color: #1E293B;"
                "border-radius: 16px;"
                "border: 1px solid #334155;"
                "}"
            )
            self.center_lock.setStyleSheet(
                "font-size: 28px; font-weight: 700; letter-spacing: -0.5px; "
                "color: #2DD4BF; background: transparent;"
            )
            self._subtitle.setStyleSheet("font-size: 14px; color: #94A3B8; background: transparent;")
        else:
            self.setStyleSheet(
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f0f6fc, stop:0.5 #e8f0f8, stop:1 #e2eef8);"
            )
            self._card.setStyleSheet(
                "QFrame#lockedCard {"
                "background-color: #ffffff;"
                "border-radius: 16px;"
                "border: 1px solid #cbd5e1;"
                "}"
            )
            self.center_lock.setStyleSheet(
                "font-size: 28px; font-weight: 700; letter-spacing: -0.5px; "
                "color: #0D9488; background: transparent;"
            )
            self._subtitle.setStyleSheet("font-size: 14px; color: #64748B; background: transparent;")
        self._status_label.setStyleSheet("font-size: 13px; background: transparent;")


class GradientTitleLabel(QLabel):
    """Custom label that paints gradient text depending on theme."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._theme = "dark"
        self._anim_phase = 0.0

    def set_theme(self, theme: str):
        self._theme = (theme or "light").lower()
        self.update()

    def set_anim_phase(self, phase: float):
        self._anim_phase = float(phase)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # PyQt6 uses QPainter.RenderHint.Antialiasing, PyQt5 uses QPainter.Antialiasing
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)  # PyQt6
        except AttributeError:
            try:
                painter.setRenderHint(QPainter.Antialiasing)  # PyQt5
            except AttributeError:
                pass

        font = self.font()
        # Heavy weight (bold) for main title in both modes
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(font)

        text = self.text()
        if not text:
            return

        path = QPainterPath()
        fm = painter.fontMetrics()
        try:
            text_width = fm.horizontalAdvance(text)
        except AttributeError:
            text_width = fm.width(text)
        x = max(0, (self.width() - text_width) / 2)
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        path.addText(x, y, font, text)

        grad = QLinearGradient(0, 0, self.width(), 0)
        shift = 0.12 * math.sin(self._anim_phase * 0.9)
        c0 = max(0.0, min(1.0, 0.0 + shift))
        c1 = max(0.0, min(1.0, 0.5 + shift))
        c2 = max(0.0, min(1.0, 1.0 + shift))
        if self._theme == "light":
            grad.setColorAt(c0, QColor("#054733"))
            grad.setColorAt(c1, QColor("#0A6C50"))
            grad.setColorAt(c2, QColor("#066044"))
        else:
            grad.setColorAt(c0, QColor("#22D3EE"))
            grad.setColorAt(c1, QColor("#54E0CF"))
            grad.setColorAt(c2, QColor("#14B8A6"))

        painter.fillPath(path, grad)


def _make_hamburger_pixmap(color_hex, size=24):
    """Draw three parallel horizontal lines as QPixmap (no style tinting)."""
    try:
        render_hint = QPainter.RenderHint.Antialiasing
    except AttributeError:
        render_hint = QPainter.Antialiasing
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(render_hint)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color_hex))
    w, h = size * 3 // 4, max(2, size // 12)
    x0 = (size - w) // 2
    gap = size // 6
    y0 = (size - (2 * gap + 3 * h)) // 2
    for i in range(3):
        p.drawRect(x0, y0 + i * (h + gap), w, h)
    p.end()
    return pix


def _make_close_pixmap(color_hex, size=24):
    """Draw an X (close) as QPixmap (no style tinting) - stays white in dark theme."""
    try:
        render_hint = QPainter.RenderHint.Antialiasing
    except AttributeError:
        render_hint = QPainter.Antialiasing
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(render_hint)
    pen = p.pen()
    pen.setColor(QColor(color_hex))
    pen.setWidth(max(3, size // 6))
    p.setPen(pen)
    m = size // 4
    p.drawLine(m, m, size - m, size - m)
    p.drawLine(size - m, m, m, size - m)
    p.end()
    return pix


class MenuIconLabel(QLabel):
    """Clickable label that shows menu/close pixmap so icon is never tinted by style."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def mousePressEvent(self, event):
        try:
            btn = Qt.MouseButton.LeftButton
        except AttributeError:
            btn = Qt.LeftButton
        if event.button() == btn:
            self.clicked.emit()
        super().mousePressEvent(event)


class SidebarGridAnimation(QWidget):
    """Grid animation in sidebar below ESP32 status (same primary-color grid as main locked screen)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "light"
        self._phase = 0.0
        self._phase2 = 0.0
        self.setMinimumHeight(96)
        self.setMaximumHeight(140)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_theme(self, theme: str):
        self._theme = (theme or "light").lower()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.05) % (2.0 * math.pi)
        self._phase2 = (self._phase2 + 0.08) % (2.0 * math.pi)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
        except AttributeError:
            p.setRenderHint(QPainter.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        if w < 4 or h < 4:
            return
        if self._theme == "light":
            grid_rgb = (6, 96, 68)
        else:
            grid_rgb = (34, 211, 238)
        grid_step = max(7.0, min(11.0, min(w, h) / 18.0))
        shift = (self._phase * grid_step * 0.24) % grid_step
        gx0 = -shift
        gy0 = 0.0
        # Heavy layer
        heavy_alpha = 96 if self._theme == "light" else 82
        shimmer_h = 0.55 + 0.45 * math.sin(self._phase * 0.45)
        heavy_a = int(heavy_alpha * shimmer_h)
        p.setPen(QPen(QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], heavy_a), 1))
        gx = gx0
        while gx < w + grid_step:
            p.drawLine(int(gx), 0, int(gx), int(h))
            gx += grid_step
        gy = gy0
        while gy < h + grid_step:
            p.drawLine(0, int(gy), int(w), int(gy))
            gy += grid_step
        # Soft layer
        mild_alpha = 40 if self._theme == "light" else 30
        mild_a = int(mild_alpha * (0.50 + 0.50 * math.sin(self._phase * 0.38 + 0.5)))
        p.setPen(QPen(QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], mild_a), 1))
        gx = gx0
        while gx < w + grid_step:
            p.drawLine(int(gx), 0, int(gx), int(h))
            gx += grid_step
        gy = gy0
        while gy < h + grid_step:
            p.drawLine(0, int(gy), int(w), int(gy))
            gy += grid_step
        # Dots
        cols = max(2, int(w / grid_step) + 2)
        rows = max(2, int(h / grid_step) + 2)
        drift_x = (self._phase * 1.8) % grid_step
        for cx in range(cols):
            for cy in range(rows):
                if (cx + cy) % 3 != 0:
                    continue
                x = cx * grid_step + ((cy % 2) * (grid_step * 0.18)) - drift_x
                y = cy * grid_step + ((cx % 2) * (grid_step * 0.12))
                if x < 4 or y < 4 or x > (w - 4) or y > (h - 4):
                    continue
                tw = 0.5 + 0.5 * math.sin(self._phase * 0.8 + cx * 0.45 + cy * 0.30)
                base_a = int(72 + 64 * tw)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], base_a))
                p.drawEllipse(int(x - 1.5), int(y - 1.5), 3, 3)

        # A subtle vertical scanner keeps the empty sidebar zone alive.
        scan_x = int((self._phase2 * 24.0) % max(1.0, w + 24.0) - 24.0)
        grad = QLinearGradient(scan_x, 0, scan_x + 24, 0)
        grad.setColorAt(0.0, QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], 0))
        grad.setColorAt(0.5, QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], 44))
        grad.setColorAt(1.0, QColor(grid_rgb[0], grid_rgb[1], grid_rgb[2], 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(scan_x, 0, 24, int(h))


class SidebarAmbientWidget(QWidget):
    """Subtle animated decorative panel for empty sidebar space."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "light"
        self._phase = 0.0
        self.setMinimumHeight(130)
        self.setMaximumHeight(170)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def set_theme(self, theme: str):
        self._theme = (theme or "light").lower()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.06) % (2.0 * math.pi)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
        except AttributeError:
            p.setRenderHint(QPainter.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        if self._theme == "dark":
            bg_a, bg_b = QColor(10, 27, 39, 196), QColor(7, 20, 32, 182)
            edge = QColor(62, 156, 194, 108)
            dot = QColor(90, 206, 235, 118)
            wave = QColor(64, 174, 208, 90)
        else:
            bg_a, bg_b = QColor(239, 248, 244, 220), QColor(229, 243, 236, 208)
            edge = QColor(104, 178, 155, 108)
            dot = QColor(70, 166, 190, 108)
            wave = QColor(76, 162, 145, 84)
        grad = QLinearGradient(0, 0, int(w), int(h))
        grad.setColorAt(0.0, bg_a)
        grad.setColorAt(1.0, bg_b)
        p.setPen(QPen(edge, 1))
        p.setBrush(grad)
        p.drawRoundedRect(0, 0, int(w) - 1, int(h) - 1, 12, 12)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(wave, 1))
        for i in range(2):
            y0 = h * (0.30 + i * 0.24)
            path = QPainterPath()
            path.moveTo(10, y0)
            x = 10.0
            while x < w - 10:
                y = y0 + math.sin((x / max(1.0, w)) * math.pi * 4.0 + self._phase + i) * (4.0 + i * 1.5)
                path.lineTo(x, y)
                x += 7.0
            p.drawPath(path)

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            x = 14 + (i * 19) % max(18, int(w - 24))
            y = 16 + ((i * 31 + int(self._phase * 22)) % max(18, int(h - 30)))
            a = int(42 + 42 * (0.5 + 0.5 * math.sin(self._phase + i * 0.8)))
            p.setBrush(QColor(dot.red(), dot.green(), dot.blue(), a))
            p.drawEllipse(int(x), int(y), 3, 3)


class MainWindow(QMainWindow):
    """CuraX main window."""

    def apply_theme(self, theme_name: str):
        """Apply UI theme ('dark' or 'light') using shared QSS styles."""
        name = (theme_name or "light").lower()
        self._current_theme = "light" if name == "light" else "dark"
        if self._current_theme == "light":
            self.setStyleSheet(LIGHT_THEME)
        else:
            self.setStyleSheet(DARK_THEME)

        # Update sidebar / local widgets if they already exist
        if hasattr(self, "sidebar"):
            self._apply_sidebar_theme()
        if hasattr(self, "locked_title"):
            self._apply_title_theme()
        if hasattr(self, "locked_screen_widget"):
            self.locked_screen_widget.set_theme(self._current_theme)
        if hasattr(self, "theme_toggle_global"):
            self.theme_toggle_global.set_theme(self._current_theme)
        if hasattr(self, "tabs"):
            # Propagate to tabs that support apply_theme so temporary switch applies everywhere
            try:
                for i in range(self.tabs.count()):
                    w = self.tabs.widget(i)
                    if hasattr(w, "apply_theme"):
                        w.apply_theme(self._current_theme)
                self.tabs.update()
                if hasattr(self.tabs, "currentWidget") and self.tabs.currentWidget():
                    self.tabs.currentWidget().update()
            except Exception:
                pass

    def _apply_sidebar_theme(self):
        """Adjust sidebar colors for current theme (dark / light)."""
        theme = getattr(self, "_current_theme", "light")
        status_text = (self.admin_status.text() or "").lower()
        if "admin:" in status_text:
            status_kind = "admin"
        elif "user view" in status_text:
            status_kind = "user"
        else:
            status_kind = "locked"

        if theme == "light":
            self.left_column.setStyleSheet(
                "QWidget#leftColumn {"
                "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #eef6f2, stop:1 #e5f0eb);"
                "border-right: 1px solid #c8ddd2;"
                "}"
            )
            self.sidebar.setStyleSheet(
                "QFrame#sidebarFrame {"
                "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f8fcfa, stop:1 #f2f8f5);"
                "border-right: 1px solid #cfe2d8;"
                "border-top-right-radius: 22px;"
                "border-bottom-right-radius: 22px;"
                "padding-top: 6px;"
                "}"
            )
            if status_kind == "admin":
                status_bg, status_border, status_fg = "#0f7b57", "#0b6648", "#ecfffa"
            elif status_kind == "user":
                status_bg, status_border, status_fg = "#0e5f79", "#0b4f65", "#e9f8ff"
            else:
                status_bg, status_border, status_fg = "#4b5563", "#3e4652", "#f1f5f9"
            nav_style = (
                f"QPushButton {{"
                "background-color: #f3f8f5;"
                "color: #10372b;"
                "text-align: left;"
                f"padding: 10px 12px; min-height: {getattr(self, '_sidebar_row_height', 40) - 4}px;"
                f"border-radius: {getattr(self, '_sidebar_radius', 10)}px;"
                "border: 1px solid #cfe1d7;"
                "font-size: 10pt; font-weight: 600;"
                "}"
                "QPushButton:hover { background-color: #e5f2ec; border: 1px solid #b5d3c4; }"
            )
            card_bg = "#ffffff"
            card_border = "#d3e3db"
            input_bg = "#f9fcfb"
            input_border = "#9fbcaf"
            input_fg = "#12382b"
            tool_text = "#1b2632"
            tool_hover = "#e6edf2"
            com_text = "#12362b"
            com_hover = "#e5f2ec"
            com_border = "#9ebcaf"
            com_bg = "#d1f0e0"
            admin_btn_bg = "#075d43"
            admin_btn_hover = "#0b6f50"
        else:
            self.left_column.setStyleSheet(
                "QWidget#leftColumn {"
                "background-color: #0f172a;"
                "border-right: 1px solid #334155;"
                "}"
            )
            self.sidebar.setStyleSheet(
                "QFrame#sidebarFrame {"
                "background-color: #1e293b;"
                "border-right: 1px solid #334155;"
                "border-top-right-radius: 12px;"
                "border-bottom-right-radius: 12px;"
                "padding-top: 8px;"
                "}"
            )
            if status_kind == "admin":
                status_bg, status_border, status_fg = "#0d9488", "#0f766e", "#f0fdfa"
            elif status_kind == "user":
                status_bg, status_border, status_fg = "#0e7490", "#0c5a6e", "#ecfeff"
            else:
                status_bg, status_border, status_fg = "#475569", "#334155", "#f1f5f9"
            nav_style = (
                f"QPushButton {{"
                "background-color: #334155;"
                "color: #f1f5f9;"
                "text-align: left;"
                f"padding: 10px 12px; min-height: {getattr(self, '_sidebar_row_height', 40) - 4}px;"
                f"border-radius: {getattr(self, '_sidebar_radius', 10)}px;"
                "border: 1px solid #475569;"
                "font-size: 11pt; font-weight: 600; min-width: 180px;"
                "}"
                "QPushButton:hover { background-color: #475569; border: 1px solid #64748b; color: #ffffff; }"
            )
            card_bg = "#0f172a"
            card_border = "#334155"
            input_bg = "#1e293b"
            input_border = "#475569"
            input_fg = "#f8fafc"
            tool_text = "#f1f5f9"
            tool_hover = "#334155"
            com_text = "#f1f5f9"
            com_hover = "#334155"
            com_border = "#475569"
            com_bg = "#1e293b"
            admin_btn_bg = "#0d9488"
            admin_btn_hover = "#0f766e"

        r = getattr(self, "_sidebar_radius", 10)
        h = getattr(self, "_sidebar_row_height", 40)
        self.admin_status.setStyleSheet(
            f"background: {status_bg}; color: {status_fg}; padding: 10px 14px; min-height: {h - 4}px; "
            f"border: 1px solid {status_border}; border-radius: {r}px; font-weight: 700; font-size: 10pt;"
        )

        try:
            self.user_view_btn.setStyleSheet(nav_style)
        except Exception:
            pass
        border_color = com_border
        text_color = com_text
        hover_bg = com_hover
        r = getattr(self, "_sidebar_radius", 10)
        com_btn_style = (
            "QPushButton {"
            f"background-color: {com_bg};"
            f"color: {text_color};"
            "text-align: left;"
            "padding: 8px 12px; min-height: 36px;"
            f"border-radius: {r}px;"
            "font-size: 10pt; font-weight: 700;"
            f"border: 1px solid {border_color};"
            "}"
            "QPushButton:hover {"
            f"background-color: {hover_bg};"
            "}"
        )
        self._esp32_btn_style = com_btn_style
        self.connect_btn.setStyleSheet(com_btn_style)
        self.auth_btn.setStyleSheet(com_btn_style)
        self.com_frame.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: {card_bg};
                border-radius: {r}px;
                border: 1px solid {card_border};
                margin-top: 8px;
                padding: 10px;
            }}
            QGroupBox::title {{ height: 0px; padding: 0; }}
            QGroupBox QComboBox#portCombo {{
                border: 1px solid {input_border};
                border-radius: {r}px;
                padding: 8px 10px;
                min-height: 36px;
                font-size: 10pt;
                background-color: {input_bg};
                color: {input_fg};
            }}
            """
        )
        self.tool_group.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: {card_bg};
                border-radius: {r}px;
                border: 1px solid {card_border};
                margin-top: 6px;
                padding: 10px 8px 8px 8px;
            }}
            QGroupBox::title {{ height: 0px; padding: 0; }}
            QGroupBox QPushButton {{
                background-color: transparent;
                color: {tool_text};
                text-align: left;
                padding: 8px 10px;
                border-radius: {r}px;
                font-size: 10pt;
                font-weight: 600;
            }}
            QGroupBox QPushButton:hover {{
                background-color: {tool_hover};
            }}
            """
        )
        self.admin_quick_btn.setStyleSheet(
            "QPushButton {"
            f"background-color: {admin_btn_bg};"
            "color: #f6fbff; font-weight: 700; font-size: 11pt; "
            "padding: 10px 12px; border-radius: 10px; text-align: center; min-width: 180px;"
            "border: none;"
            "}"
            "QPushButton:hover {"
            f"background-color: {admin_btn_hover};"
            "}"
        )
        if theme == "dark":
            section_style = "font-size: 11px; letter-spacing: 0.5px; color: #94a3b8; font-weight: bold; padding: 2px 0;"
            self.tools_section_title.setStyleSheet(section_style)
            self.admin_section_title.setStyleSheet(section_style)
        else:
            self.tools_section_title.setStyleSheet(
                "font-size: 11px; letter-spacing: 0.5px; color: #6B7280; font-weight: bold; padding: 2px 0;"
            )
            self.admin_section_title.setStyleSheet(
                "font-size: 11px; letter-spacing: 0.5px; color: #6B7280; font-weight: bold; padding: 2px 0;"
            )
        # ESP32 toggle button: distinct style with left accent.
        if theme == "light":
            self.esp32_btn.setStyleSheet(
                f"""
                QPushButton#esp32ToggleBtn {{
                    background-color: #eaf5ef;
                    color: #123327;
                    text-align: left;
                    padding: 10px 12px;
                    min-height: {h - 4}px;
                    border-radius: {r}px;
                    border: 1px solid #cbe0d5;
                    border-left: 4px solid {NEON_GREEN};
                    font-size: 10pt;
                    font-weight: 800;
                }}
                QPushButton#esp32ToggleBtn:hover {{
                    background-color: #dff0e8;
                    border-left: 4px solid {NEON_GREEN};
                }}
                """
            )
        else:
            self.esp32_btn.setStyleSheet(
                f"""
                QPushButton#esp32ToggleBtn {{
                    background-color: #334155;
                    color: #f1f5f9;
                    text-align: left;
                    padding: 10px 12px;
                    min-height: {h - 4}px;
                    border-radius: {r}px;
                    border: 1px solid #475569;
                    border-left: 4px solid {NEON_GREEN};
                    font-size: 10pt;
                    font-weight: 800;
                }}
                QPushButton#esp32ToggleBtn:hover {{
                    background-color: #475569;
                    border-left: 4px solid {NEON_GREEN};
                }}
                """
            )

        # Close mark: white in dark mode, dark in light mode (pixmap = drawn color, no tint)
        if theme == "light":
            icon_color = "#111827"
            self.menu_btn.setStyleSheet("background: transparent; border: none;")
        else:
            icon_color = "#ffffff"
            self.menu_btn.setStyleSheet(
                "background: transparent; border: none; color: #ffffff;"
            )
        self._menu_hamburger_pixmap = _make_hamburger_pixmap(icon_color)
        self._menu_close_pixmap = _make_close_pixmap(icon_color)
        self.menu_btn.setPixmap(
            self._menu_close_pixmap if getattr(self, "sidebar_visible", False) else self._menu_hamburger_pixmap
        )
        self.menu_btn.update()

    def _apply_title_theme(self):
        """Apply title/subtitle/status styling for current theme."""
        theme = getattr(self, "_current_theme", "light")
        self.locked_title.set_theme(theme)
        if theme == "light":
            subtitle_color = "#1f3e34"
            status_color = "#8a5b0e"
        else:
            subtitle_color = "#8fb7c7"
            status_color = "#d6a24c"
        self.locked_subtitle.setStyleSheet(
            f"color: {subtitle_color}; {self._header_glass_style(12, 700, 4, 14, with_border=False)}"
        )
        self.locked_status.setStyleSheet(
            f"color: {status_color}; {self._header_glass_style(11, 700, 3, 12)}"
        )
        self._update_status_text()

    def _header_glass_style(self, font_pt: int, weight: int, pad_v: int, pad_h: int, with_border: bool = True) -> str:
        theme = getattr(self, "_current_theme", "light")
        phase = getattr(self, "_header_overlay_phase", 0.0)
        glow = 0.5 + 0.5 * math.sin(phase * 1.2)
        if theme == "light":
            bg_a = int(148 + glow * 26)
            border_a = int(78 + glow * 24)
            edge = "rgba(132, 186, 210, {})".format(border_a)
            bg = "rgba(255, 255, 255, {})".format(bg_a)
        else:
            bg_a = int(90 + glow * 24)
            border_a = int(88 + glow * 26)
            edge = "rgba(72, 192, 216, {})".format(border_a)
            bg = "rgba(8, 26, 38, {})".format(bg_a)
        border_css = f"border: 1px solid {edge};" if with_border else "border: none;"
        return (
            f"font-size: {font_pt}pt; font-weight: {weight}; "
            f"padding: {pad_v}px {pad_h}px; border-radius: 10px; "
            f"{border_css} background-color: {bg};"
        )

    def _animate_header_overlay(self):
        self._header_overlay_phase = (getattr(self, "_header_overlay_phase", 0.0) + 0.06) % (2.0 * math.pi)
        try:
            self.locked_title.set_anim_phase(self._header_overlay_phase)
        except Exception:
            pass
        # Keep subtitle/status text visible with animated glass overlay.
        self._apply_title_theme()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.sidebar_visible = False
        self._sidebar_locked_mode = True

        self.setWindowTitle("CuraX - Intelligent Medicine System")
        self.setMinimumSize(720, 600)
        # Remember saved appearance theme (dark / light); applied after UI is built; default is light
        self._initial_theme = getattr(self.controller, "appearance_theme", "light") or "light"

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # LEFT COLUMN: Menu + sidebar
        # When open: sidebar takes full width it needs (_sidebar_expanded_width).
        # When closed: only icon strip reserved (_sidebar_collapsed_width) so main content gets maximum space.
        self.left_column = QWidget()
        self.left_column.setObjectName("leftColumn")
        self._sidebar_expanded_width = 250
        self._sidebar_collapsed_width = 44
        self.left_column.setFixedWidth(self._sidebar_collapsed_width)
        left_layout = QVBoxLayout(self.left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Burger/close: pixmap label so icon is never tinted (close stays white in dark theme)
        self.menu_btn = MenuIconLabel()
        self.menu_btn.setObjectName("menuButton")
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.setToolTip("Menu")
        self.menu_btn.clicked.connect(self._toggle_sidebar)
        left_layout.addSpacing(4)
        left_layout.addWidget(self.menu_btn)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebarFrame")
        self.sidebar.setMinimumWidth(240)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 10, 12, 10)
        sidebar_layout.setSpacing(8)

        # Section title style: 11px, letter-spacing, #6B7280, uppercase (compact but clear)
        def _section_title(text):
            lbl = QLabel(text.upper())
            lbl.setStyleSheet(
                "font-size: 11px; letter-spacing: 0.5px; color: #6B7280; "
                "font-weight: bold; padding: 2px 0;"
            )
            return lbl

        # Sidebar: one radius (10px), one border, same row height for all blocks
        SIDEBAR_RADIUS = 10
        SIDEBAR_ROW_HEIGHT = 40
        self._sidebar_radius = SIDEBAR_RADIUS
        self._sidebar_row_height = SIDEBAR_ROW_HEIGHT

        # Top: status (same shape as ESP32 and connection block)
        self.admin_status = QLabel("Features Locked")
        self.admin_status.setObjectName("sidebarStatusPill")
        self.admin_status.setStyleSheet(
            f"background: #4b5563; color: #f1f5f9; padding: 10px 14px; min-height: {SIDEBAR_ROW_HEIGHT - 4}px; "
            f"border: 1px solid #3e4652; border-radius: {SIDEBAR_RADIUS}px; font-weight: bold; font-size: 10pt;"
        )
        sidebar_layout.addWidget(self.admin_status)

        # ESP32 row (same radius and border as status)
        sidebar_nav_style = (
            f"QPushButton {{"
            "background-color: #f3f8f5;"
            "color: #10372b;"
            "text-align: left;"
            f"padding: 10px 12px; min-height: {SIDEBAR_ROW_HEIGHT - 4}px;"
            f"border-radius: {SIDEBAR_RADIUS}px;"
            "border: 1px solid #cfe1d7;"
            "font-size: 10pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background-color: #e5f2ec; border: 1px solid #b5d3c4; }"
        )

        # In Tkinter version, 'User View' is a status, not a separate button.
        # Here we create the button but keep it hidden to avoid duplicate labels.
        self.user_view_btn = QPushButton("User View")
        self.user_view_btn.setStyleSheet(sidebar_nav_style)
        self.user_view_btn.setVisible(False)
        sidebar_layout.addWidget(self.user_view_btn)

        # ESP32 toggle
        self.esp32_btn = QPushButton("ESP32")
        self.esp32_btn.setObjectName("esp32ToggleBtn")
        self.esp32_btn.clicked.connect(self._toggle_esp32_section)
        self.esp32_btn.setStyleSheet(sidebar_nav_style)
        sidebar_layout.addWidget(self.esp32_btn)

        # Port + Connect/Disconnect + Authenticate (no "Connection" or "COM Port" labels for space)
        self.com_frame = QGroupBox("")
        com_layout = QVBoxLayout(self.com_frame)
        self.port_combo = QComboBox()
        self.port_combo.setObjectName("portCombo")
        self.port_combo.setMinimumWidth(200)
        self.port_combo.setMinimumHeight(36)
        try:
            self.port_combo.setPlaceholderText("Port")
        except Exception:
            pass
        self.port_combo.addItems(self.controller.get_available_ports())
        com_layout.addWidget(self.port_combo)

        self.port_connected_label = QLabel("")
        self.port_connected_label.setStyleSheet(f"color: {NEON_GREEN}; font-size: 9pt; font-weight: bold;")
        self.port_connected_label.setVisible(False)
        com_layout.addWidget(self.port_connected_label)

        self.connect_btn = QPushButton("Connect ESP32")
        self.connect_btn.setMinimumWidth(200)
        self.connect_btn.setMinimumHeight(36)
        self.connect_btn.clicked.connect(self._connect_esp32)
        com_layout.addWidget(self.connect_btn)

        self.auth_btn = QPushButton("Authenticate")
        self.auth_btn.setMinimumWidth(200)
        self.auth_btn.setMinimumHeight(36)
        self.auth_btn.clicked.connect(self._show_pin_dialog)
        self.auth_btn.setEnabled(False)
        com_layout.addWidget(self.auth_btn)

        self.com_status = QLabel("Disconnected")
        self.com_status.setStyleSheet("color: #ef4444; font-size: 9pt;")
        self.com_status.setMinimumHeight(24)
        com_layout.addWidget(self.com_status)

        # Connection block: same radius and border as status + ESP32
        self.com_frame.setStyleSheet(
            """
            QGroupBox {
                background-color: #1e293b;
                border-radius: 10px;
                border: 1px solid #334155;
                margin-top: 6px;
                padding: 10px;
            }
            QGroupBox::title { height: 0px; padding: 0; }
            QGroupBox QComboBox#portCombo {
                border: 1px solid #475569;
                border-radius: 10px;
                padding: 8px 10px;
                min-height: 36px;
                font-size: 10pt;
                background-color: #0f172a;
                color: #f8fafc;
            }
            """
        )

        # Connect and Authenticate: same as tool buttons but with outer border like ESP32
        _com_btn_style = (
            "QPushButton {"
            "background-color: transparent;"
            "color: #f1f5f9;"
            "text-align: left;"
            "padding: 6px 8px;"
            "border-radius: 6px;"
            "font-size: 10pt;"
            "border: 1px solid #334155;"
            "}"
            "QPushButton:hover {"
            "background-color: #1f2937;"
            "}"
        )
        self._esp32_btn_style = _com_btn_style
        self.connect_btn.setStyleSheet(self._esp32_btn_style)
        self.auth_btn.setStyleSheet(self._esp32_btn_style)

        sidebar_layout.addWidget(self.com_frame)

        # --- Section: Tools (hidden when locked) ---
        self.tools_section_title = _section_title("Tools")
        self.tools_section_title.setVisible(False)
        sidebar_layout.addWidget(self.tools_section_title)
        # --- TOOL PANEL (hidden until authentication), like Tkinter version ---
        self.tool_group = QGroupBox("")
        self.tool_group.setVisible(False)
        tool_layout = QVBoxLayout(self.tool_group)

        # Match Tkinter tool buttons: full text visible (sidebar width 300px fits all)
        backup_btn = QPushButton("Backup Database")
        backup_btn.clicked.connect(self._backup_database)
        tool_layout.addWidget(backup_btn)

        check_meds_btn = QPushButton("Check Medicine Data")
        check_meds_btn.clicked.connect(self._check_medicine_data)
        tool_layout.addWidget(check_meds_btn)

        restore_btn = QPushButton("Restore from Backup")
        restore_btn.clicked.connect(self._restore_database)
        tool_layout.addWidget(restore_btn)

        alerts_btn = QPushButton("Alert System Status")
        alerts_btn.clicked.connect(self._check_alert_status)
        tool_layout.addWidget(alerts_btn)

        # Tools section card — design system
        self.tool_group.setStyleSheet(
            """
            QGroupBox {
                background-color: #1E293B;
                border-radius: 12px;
                border: 1px solid #334155;
                margin-top: 6px;
                padding: 10px 8px 8px 8px;
            }
            QGroupBox::title { height: 0px; padding: 0; }
            QGroupBox QPushButton {
                background-color: transparent;
                color: #F8FAFC;
                text-align: left;
                padding: 8px 10px;
                border-radius: 8px;
                font-size: 13px;
            }
            QGroupBox QPushButton:hover {
                background-color: #334155;
            }
            """
        )

        sidebar_layout.addWidget(self.tool_group)

        # --- Section: Admin (hidden when locked) ---
        self.admin_section_title = _section_title("Admin")
        self.admin_section_title.setVisible(False)
        sidebar_layout.addWidget(self.admin_section_title)
        # Highlighted Admin Login / Logout button placed below Tools, outside its card
        self.admin_quick_btn = QPushButton("Admin Login / Logout")
        self.admin_quick_btn.clicked.connect(self._admin_quick_action)
        self.admin_quick_btn.setStyleSheet(
            "background-color: #0D9488; color: #fff; font-weight: 600; font-size: 13px; "
            "padding: 10px 12px; border-radius: 10px; text-align: center;"
        )
        # Hidden until system is authenticated; shown in _on_authenticated_changed
        self.admin_quick_btn.setVisible(False)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(self.admin_quick_btn)

        sidebar_layout.addStretch()
        left_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.left_column)

        # RIGHT: content â€” full width when sidebar closed (no fixed width, no empty sides)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 10, 0, 12)
        content_layout.setSpacing(0)

        # Header row: title centered, theme toggle always visible (locked screen + all views)
        header_row = QHBoxLayout()
        # Keep title exactly centered by balancing right controls with an equal left spacer.
        self._header_left_spacer = QWidget()
        self._header_left_spacer.setFixedWidth(92)
        self._header_left_spacer.setStyleSheet("background: transparent; border: none;")
        header_row.addWidget(self._header_left_spacer, alignment=Qt.AlignmentFlag.AlignLeft)
        header_row.addStretch()
        self.locked_title = GradientTitleLabel("CuraX - Intelligent Medicine System")
        self.locked_title.setStyleSheet("font-size: 18pt; border: none; background: transparent;")
        self.locked_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.locked_title.setMinimumWidth(520)  # full title must fit so nothing clips the text
        header_row.addWidget(self.locked_title, alignment=Qt.AlignmentFlag.AlignCenter)
        header_row.addStretch()
        self.theme_toggle_global = ThemeToggle(self)
        self.theme_toggle_global.setFixedSize(56, 28)
        self.theme_toggle_global.setToolTip("Switch theme for this session (light/dark).")
        header_row.addWidget(self.theme_toggle_global, alignment=Qt.AlignmentFlag.AlignRight)
        # Clear icon on right of toggle: save current theme to DB so next time you open, this theme is used
        self.theme_save_icon_btn = QPushButton("ðŸ’¾")
        self.theme_save_icon_btn.setObjectName("themeSaveIconBtn")
        self.theme_save_icon_btn.setFixedSize(28, 28)
        self.theme_save_icon_btn.setToolTip("Save current theme for next time you open the app")
        self.theme_save_icon_btn.setStyleSheet(
            "QPushButton#themeSaveIconBtn { font-size: 12pt; border: none; background: transparent; border-radius: 4px; } "
            "QPushButton#themeSaveIconBtn:hover { background: rgba(128,128,128,0.2); }"
        )
        self.theme_save_icon_btn.clicked.connect(self._save_theme_for_next_time)
        header_row.addWidget(self.theme_save_icon_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.locked_subtitle = QLabel("Smart IoT-Based Medicine Management System")
        self.locked_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.locked_status = QLabel("Please connect ESP32 first")
        self.locked_status.setStyleSheet(
            "color: #b45309; font-size: 11pt; font-weight: bold; border: none; background: transparent;"
        )
        self.locked_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addLayout(header_row)
        content_layout.addWidget(self.locked_subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.locked_status, alignment=Qt.AlignmentFlag.AlignCenter)

        # Stack: locked (animation) | main (tabs) — below header only
        self.stacked = QStackedWidget()
        self.locked_screen_widget = LockedScreen()
        self.stacked.addWidget(self.locked_screen_widget)
        main_content = QWidget()
        main_inner = QVBoxLayout(main_content)

        self.tabs = QTabWidget()
        self.tabs.addTab(MainPanelTab(controller, self), "Main Panel")
        self.tabs.addTab(AddMedicineTab(controller, self), "Add Medicine")
        self.tabs.addTab(DoseTrackingTab(controller, self), "Dose Tracking")
        self.tabs.addTab(MedicalRemindersTab(controller, self), "Medical Reminders")
        self.tabs.addTab(AlertsTab(controller, self), "Alerts")
        self.tabs.addTab(TempAdjustmentTab(controller, self), "T Adjustment")
        self.tabs.addTab(SettingsTab(controller, self), "Settings")

        main_inner.addWidget(self.tabs)
        self.stacked.addWidget(main_content)
        content_layout.addWidget(self.stacked, 1)

        main_layout.addWidget(content, 1)  # stretch: content takes full remaining width

        # Status bar: shows alert messages (medicine + medical reminders) so user sees in-app alert
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        # Start with sidebar hidden (user can open from menu icon).
        self.sidebar_visible = False
        self.sidebar.setVisible(False)
        self.left_column.setFixedWidth(self._sidebar_collapsed_width)

        self._connect_signals()
        self._update_status_text()
        self._apply_locked_state()
        self._refresh_port_combo()
        self._update_admin_status_label()

        # Hide menubar: no File / Help
        self._add_menu()

        # Finally apply the chosen theme now that all widgets exist
        self.apply_theme(self._initial_theme)
        self._header_overlay_phase = 0.0
        self._header_anim_timer = QTimer(self)
        self._header_anim_timer.timeout.connect(self._animate_header_overlay)
        self._header_anim_timer.start(70)
        self._animate_header_overlay()

        # Alert saved mobile bot when system starts (alert only, no email)
        QTimer.singleShot(1500, self._send_startup_alert_to_bot)

    # ------------------------------------------------------------------ helpers

    def _send_startup_alert_to_bot(self):
        """Send start alert to admin only (if admin bot credentials are saved)."""
        try:
            self.controller.send_admin_alert("system_started", "CuraX started")
        except Exception:
            pass

    def _send_unlocked_alert_to_bot(self):
        """Send system unlocked alert to admin only (if admin bot credentials are saved)."""
        try:
            self.controller.send_admin_alert("system_unlocked", "CuraX system unlocked")
        except Exception:
            pass

    def _add_menu(self):
        mb = self.menuBar()
        if mb is not None:
            mb.hide()

    def _toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        self.sidebar.setVisible(self.sidebar_visible)
        # Show close pixmap when sidebar open, hamburger when collapsed (pixmap = no tint)
        if hasattr(self, "_menu_close_pixmap") and hasattr(self, "_menu_hamburger_pixmap"):
            self.menu_btn.setPixmap(self._menu_close_pixmap if self.sidebar_visible else self._menu_hamburger_pixmap)
        # Open: sidebar takes full width. Closed: only icon strip so main content gets maximum space.
        if self.sidebar_visible:
            self.left_column.setFixedWidth(getattr(self, "_sidebar_expanded_width", 240))
        else:
            self.left_column.setFixedWidth(getattr(self, "_sidebar_collapsed_width", 44))

    def _toggle_esp32_section(self):
        self.com_frame.setVisible(not self.com_frame.isVisible())

    def _on_global_theme_toggle(self, theme: str):
        """Global theme toggle: apply theme for this session only. Use save icon (ðŸ’¾) to keep for next time."""
        self.controller.appearance_theme = theme
        self.apply_theme(theme)

    def _save_theme_for_next_time(self):
        """Save current theme to DB so next time the app opens, this theme is used."""
        theme = getattr(self.controller, "appearance_theme", "light") or "light"
        self.controller.save_appearance_theme(theme)
        self._status_bar.showMessage("Theme saved. It will be used next time you open the app.", 3000)

    def _connect_signals(self):
        self.controller.connected_changed.connect(self._on_connected_changed)
        self.controller.authenticated_changed.connect(self._on_authenticated_changed)
        self.controller.admin_status_changed.connect(self._update_admin_status_label)
        self.controller.status_message.connect(self._on_status_message)
        if hasattr(self, "theme_toggle_global"):
            self.theme_toggle_global.theme_changed.connect(self._on_global_theme_toggle)

    def _on_status_message(self, msg: str):
        """Show alert in status bar only (no popup); email and mobile handle alerts."""
        if not msg or not hasattr(self, "_status_bar"):
            return
        self._status_bar.showMessage(msg, 15000)

    def _on_connected_changed(self, connected):
        self._update_status_text()
        self.auth_btn.setEnabled(connected)
        if connected:
            # Use actual connected port from controller (e.g. COM5), not combo or "ESP32"
            port = (self.controller.get_connected_port() or self.port_combo.currentText() or "").strip()
            if not port:
                port = "ESP32"  # fallback only if controller/combo have no port
            self.com_status.setText(f"Connected to {port}")
            self.com_status.setStyleSheet(f"color: {NEON_GREEN};")
            self.port_connected_label.setText(f"Port: {port}")
            self.port_connected_label.setVisible(True)
            self.connect_btn.setText("Disconnect ESP32")
            self.connect_btn.setStyleSheet(getattr(self, "_esp32_btn_style", ""))
            self._refresh_port_combo()
            # Ensure connected port is visible in combo and selected
            if port and self.port_combo.findText(port) < 0:
                self.port_combo.insertItem(0, port)
            if port:
                self.port_combo.setCurrentText(port)
        else:
            self.com_status.setText("Disconnected")
            self.com_status.setStyleSheet("color: #ef4444;")
            self.port_connected_label.setText("")
            self.port_connected_label.setVisible(False)
            self.connect_btn.setText("Connect ESP32")
            self.connect_btn.setStyleSheet(getattr(self, "_esp32_btn_style", ""))
            self._refresh_port_combo()

    def _on_authenticated_changed(self, authenticated):
        self._update_status_text()
        self._apply_locked_state()
        # When unlocked: send alert to saved mobile bot (alert only, no mail)
        if authenticated:
            self._send_unlocked_alert_to_bot()
        # When unlocked: collapse only the ESP32 section (not the whole sidebar); sidebar stays visible
        if authenticated and hasattr(self, "com_frame") and self.com_frame.isVisible():
            self.com_frame.setVisible(False)
        # When locked: hide Tools and Admin; when unlocked: show them
        self.tools_section_title.setVisible(authenticated)
        self.tool_group.setVisible(authenticated)
        self.admin_section_title.setVisible(authenticated)
        if hasattr(self, "admin_quick_btn"):
            self.admin_quick_btn.setVisible(authenticated)

    def _apply_locked_state(self):
        is_unlocked = bool(self.controller.authenticated)
        self.stacked.setCurrentIndex(1 if is_unlocked else 0)
        self.locked_title.setVisible(True)
        self.locked_subtitle.setVisible(True)
        self.locked_status.setVisible(True)
        self._sidebar_locked_mode = not is_unlocked
        if self._sidebar_locked_mode:
            # Locked: keep compact layout; sidebar starts collapsed.
            self.sidebar_visible = False
            self.sidebar.setVisible(False)
            self.left_column.setFixedWidth(self._sidebar_collapsed_width)
        else:
            self.sidebar.setVisible(self.sidebar_visible)
            if self.sidebar_visible:
                self.left_column.setFixedWidth(self._sidebar_expanded_width)
            else:
                self.left_column.setFixedWidth(self._sidebar_collapsed_width)
        # Keep menu icon correct: burger when sidebar closed, close (X) when sidebar expanded
        if hasattr(self, "menu_btn") and hasattr(self, "_menu_close_pixmap") and hasattr(self, "_menu_hamburger_pixmap"):
            self.menu_btn.setPixmap(
                self._menu_close_pixmap if getattr(self, "sidebar_visible", False) else self._menu_hamburger_pixmap
            )
            self.menu_btn.update()

    def _update_status_text(self):
        base_style = self._header_glass_style(11, 700, 3, 12)
        theme = getattr(self, "_current_theme", "light")
        ready_color = ACCENT_LIGHT if theme == "light" else NEON_GREEN
        if not self.controller.connected:
            msg = "Please connect ESP32 first"
            color = "#b45309"
        elif not self.controller.authenticated:
            msg = "ESP32 connected - Authentication required"
            color = "#b45309"
        else:
            msg = "System Ready"
            color = ready_color

        self.locked_status.setText(msg)
        self.locked_status.setStyleSheet(f"color: {color}; {base_style}")
        if hasattr(self, "locked_screen_widget") and hasattr(self.locked_screen_widget, "set_status"):
            self.locked_screen_widget.set_status(msg, color)

    def _update_admin_status_label(self):
        """Mirror Tkinter sidebar indicator: Features Locked / User View / Admin."""
        try:
            db = self.controller.get_db()
            has_admin = db.has_admin_credentials()
        except Exception:
            has_admin = False

        if getattr(self.controller, "admin_logged_in", False):
            name = getattr(self.controller, "logged_in_admin_name", None) or "Admin"
            self.admin_status.setText(f"Admin: {name}")
        elif has_admin:
            # Admin exists but not logged in - User View
            self.admin_status.setText("User View")
        else:
            # No admin configured yet - Features Locked
            self.admin_status.setText("Features Locked")
        # Re-apply theme-driven status badge style so colors remain consistent with sidebar theme.
        try:
            self._apply_sidebar_theme()
        except Exception:
            pass

    def _refresh_port_combo(self):
        ports = self.controller.get_available_ports()
        self.port_combo.clear()
        self.port_combo.addItems(ports)

    def _connect_esp32(self):
        """Connect / disconnect ESP32 with Wired vs Bluetooth choice (like Tkinter UI)."""
        if self.controller.connected:
            self.controller.disconnect_esp32()
            QMessageBox.information(self, "ESP32", "ESP32 disconnected.")
            return

        # Ask for connection mode - YES = Wired (USB), NO = Bluetooth
        mode = QMessageBox.question(
            self,
            "Connection Mode",
            "YES -> WIRED (USB)\nNO -> BLUETOOTH\n\nESP32 must be ON.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if mode == QMessageBox.StandardButton.Cancel:
            return

        if mode == QMessageBox.StandardButton.Yes:
            self._connect_wired()
        else:
            self._connect_bluetooth()

    def _connect_wired(self):
        """Wired connection using current COM port, with Bluetooth safety check."""
        ports = self.controller.get_available_ports()
        if not ports:
            QMessageBox.warning(self, "Connect", "No serial (COM) ports found.")
            return

        port = self.port_combo.currentText() or ports[0]
        if self.controller.connect_to_port(port):
            QMessageBox.information(self, "ESP32", f"Connected to {port}")
        else:
            QMessageBox.warning(self, "ESP32", f"Could not connect to {port}")

    def _connect_bluetooth(self):
        """Bluetooth auto-detect using controller.connect_bluetooth, in background thread."""
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")

        self._bt_thread = BluetoothConnectThread(self.controller)

        def on_finished():
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Disconnect ESP32" if self.controller.connected else "Connect ESP32")
            self.connect_btn.setStyleSheet(getattr(self, "_esp32_btn_style", ""))
            # If not connected, show a message; if connected, the status bar already updated
            if not self.controller.connected:
                QMessageBox.warning(self, "ESP32", "Could not connect to Bluetooth device.")

        self._bt_thread.finished.connect(on_finished)
        self._bt_thread.start()

    def _show_pin_dialog(self):
        if not self.controller.connected:
            QMessageBox.warning(self, "ESP32", "Please connect ESP32 first.")
            return
        d = PinDialog(self.controller, self)
        d.apply_theme(getattr(self, "_current_theme", "light"))
        d.exec()

    # ------------------------------------------------------------------
    # Admin flow (mirrors Tkinter admin login + guarding actions)
    # ------------------------------------------------------------------

    def _show_admin_verify_dialog(self, action_label: str) -> str | None:
        """Custom Admin Authorization Required dialog (one-time approval, no login)."""
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLineEdit, QPushButton
        except ImportError:
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLineEdit, QPushButton  # type: ignore[import-untyped]
        dlg = QDialog(self)
        dlg.setWindowTitle("Admin Verification Required")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        # Red header bar
        header = QFrame()
        header.setStyleSheet("background-color: #b91c1c;")
        h_layout = QVBoxLayout(header)
        title = QLabel("Admin Authorization Required")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: white;")
        h_layout.addWidget(title)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        info1 = QLabel("Admin approval is required for:")
        info1.setStyleSheet(f"color: {TEXT_SECONDARY};")
        body.addWidget(info1)
        info2 = QLabel(f"  {action_label}")
        info2.setStyleSheet(f"font-weight: bold; color: {NEON_GREEN};")
        body.addWidget(info2)
        body.addSpacing(8)
        body.addWidget(QLabel("Enter Admin Password:"))

        pwd_edit = QLineEdit()
        try:
            pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            pwd_edit.setEchoMode(QLineEdit.Password)
        body.addWidget(pwd_edit)

        status = QLabel("")
        status.setStyleSheet(f"color: {TEXT_SECONDARY};")
        body.addWidget(status)

        # Buttons
        btn_row = QHBoxLayout()
        verify_btn = QPushButton("Verify")
        verify_btn.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 6px 18px;"
        )
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #b91c1c; color: white; font-weight: bold; padding: 6px 18px;"
        )
        btn_row.addWidget(verify_btn)
        btn_row.addWidget(cancel_btn)
        body.addLayout(btn_row)

        layout.addLayout(body)

        result = {"password": None}

        def on_verify():
            pwd = pwd_edit.text().strip()
            if not pwd:
                status.setText("Please enter password.")
                status.setStyleSheet("color: #f97316;")
                return
            result["password"] = pwd
            dlg.accept()

        def on_cancel():
            dlg.reject()

        verify_btn.clicked.connect(on_verify)
        cancel_btn.clicked.connect(on_cancel)

        dlg.exec()
        return result["password"]

    def _show_admin_login_dialog(self) -> bool:
        """Full Admin Login dialog (persistent session, like Tkinter admin_login_dialog)."""
        db = self.controller.get_db()
        if not db.has_admin_credentials():
            QMessageBox.warning(self, "Admin", "No admin account configured. Set up admin in Settings -> Admin Panel.")
            return False
        info = db.get_admin_info() or {}
        name = info.get("name", "Admin")
        email = info.get("email", "")

        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLineEdit, QPushButton
        except ImportError:
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLineEdit, QPushButton  # type: ignore[import-untyped]

        dlg = QDialog(self)
        dlg.setWindowTitle("Admin Login")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        # Green header
        header = QFrame()
        header.setStyleSheet("background-color: #15803d;")
        h_layout = QVBoxLayout(header)
        title = QLabel("Admin Login")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; color: white;")
        h_layout.addWidget(title)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        msg = QLabel("Please enter your password to unlock all features.")
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {TEXT_SECONDARY};")
        body.addWidget(msg)

        # Admin info line
        info_label = QLabel(f"  {name} ({email})" if email else f"  {name}")
        info_label.setStyleSheet(
            "border: 1px solid #1e293b; border-radius: 6px; padding: 6px 10px;"
        )
        body.addWidget(info_label)

        body.addWidget(QLabel("Password:"))
        pwd_edit = QLineEdit()
        try:
            pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            pwd_edit.setEchoMode(QLineEdit.Password)
        body.addWidget(pwd_edit)

        status = QLabel("")
        status.setStyleSheet(f"color: {TEXT_SECONDARY};")
        body.addWidget(status)

        # Buttons
        btn_row = QHBoxLayout()
        login_btn = QPushButton("Login")
        login_btn.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 6px 24px;"
        )
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #4b5563; color: white; font-weight: bold; padding: 6px 24px;"
        )
        btn_row.addWidget(login_btn)
        btn_row.addWidget(cancel_btn)
        body.addLayout(btn_row)

        layout.addLayout(body)

        def attempt_login():
            pwd = pwd_edit.text().strip()
            if not pwd:
                status.setText("Please enter password.")
                status.setStyleSheet("color: #f97316;")
                return
            if self.controller.verify_admin_login(pwd):
                QMessageBox.information(self, "Admin", f"Welcome {name}! All features unlocked.")
                dlg.accept()
            else:
                status.setText("Incorrect password")
                status.setStyleSheet("color: #ef4444;")

        def on_cancel():
            dlg.reject()

        login_btn.clicked.connect(attempt_login)
        cancel_btn.clicked.connect(on_cancel)

        dlg.exec()
        return self.controller.admin_logged_in

    def open_admin_login_dialog(self):
        """Public helper used by Settings tab to trigger the login dialog."""
        return self._show_admin_login_dialog()

    def verify_admin_for_action(self, action_label: str) -> bool:
        """
        Ensure an admin is logged in before performing a protected action.

        - If no admin credentials exist in DB - show info and open Settings -> Admin Panel.
        - If admin already logged in - allow.
        - Otherwise - prompt for password and log in via controller.verify_admin_login.
        """
        db = self.controller.get_db()
        if not db.has_admin_credentials():
            QMessageBox.information(
                self,
                "Admin Required",
                "No admin account configured.\n\n"
                "Please open Settings -> Admin Panel and set up an admin first.",
            )
            self._open_settings_tab()
            return False

        # If an admin session is already active, allow all protected actions.
        if self.controller.admin_logged_in:
            return True

        # Distinguish between full admin login vs one-time approval.
        if action_label == "Admin Login":
            # Persistent session login (used by sidebar/Admin Panel buttons)
            return self._show_admin_login_dialog()

        # For all other actions, show custom verify dialog and perform one-time verification only
        pwd = self._show_admin_verify_dialog(action_label)
        if not pwd:
            return False

        if self.controller.verify_admin_password_for_action(action_label, pwd):
            QMessageBox.information(
                self,
                "Admin Approval",
                f"Admin approval granted for: {action_label}",
            )
            return True

        QMessageBox.warning(self, "Admin", "Incorrect admin password.")
        return False

    # ----- Sidebar tool actions (ported from Tkinter sidebar) -----

    def _backup_database(self):
        """Save backup in two places: inside the DB and in a separate backup file (so if DB is deleted, backup file still has it)."""
        try:
            if self.controller.save_backup_snapshot():
                backup_path = self.controller._backup_file_path()
                QMessageBox.information(
                    self,
                    "Backup Database",
                    "Backup saved in two places:\n\n"
                    "1. Inside the database (same file)\n"
                    "2. Separate backup file:\n" + backup_path + "\n\n"
                    "If anyone deletes the main database, you can still restore from the backup file.",
                )
            else:
                QMessageBox.warning(self, "Backup Database", "Backup failed.")
        except Exception as e:
            QMessageBox.critical(self, "Backup Database", f"Backup failed: {e}")

    def _check_medicine_data(self):
        """Popup with detailed medicine data, similar to Tkinter check_medicine."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("Medicine Data Check")
        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)

        # Build a simple textual summary based on controller.medicine_boxes
        lines = []
        empty = 0
        filled = 0
        low_stock = []
        for box_id, med in (self.controller.medicine_boxes or {}).items():
            if med:
                filled += 1
                qty = med.get("quantity", 0)
                if qty <= 5:
                    low_stock.append(f"{med.get('name', 'Unknown')} (Box {box_id})")
                lines.append(f"Box {box_id}: {med.get('name', 'Unknown')} - qty {qty}")
            else:
                empty += 1
                lines.append(f"Box {box_id}: EMPTY")

        summary = [f"Filled boxes: {filled}/6", f"Empty boxes: {empty}/6", ""]
        summary.extend(lines)
        if low_stock:
            summary.append("")
            summary.append("Low stock alerts:")
            for m in low_stock:
                summary.append(f"  - {m}")

        text.setPlainText("\n".join(summary))
        layout.addWidget(text)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    def _restore_database(self):
        """Restore from in-DB backup first; if missing (e.g. DB was deleted), restore from the separate backup file."""
        try:
            restored = self.controller.restore_from_backup_snapshot()
            if not restored:
                restored = self.controller.restore_from_backup_file()
            if restored:
                try:
                    self.controller.load_data()
                    self.controller.load_alert_settings()
                    self.controller.load_medical_reminders()
                    self.controller.load_mobile_bot_config()
                    self.controller.load_admin_bot_config()
                    self.controller.load_appearance_theme()
                    self.controller.reschedule_all_medicine_alerts()
                    self.controller.medicine_updated.emit()
                    self.apply_theme(getattr(self.controller, "appearance_theme", "light"))
                except Exception:
                    pass
                QMessageBox.information(
                    self,
                    "Restore Database",
                    "Data restored from backup.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Restore Database",
                    "No backup found. Save a backup first using Backup Database.\n\n"
                    "If the database was deleted, make sure the backup file (curax_alerts_backup.db) is in the same folder.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Restore Database", f"Restore failed: {e}")

    def _check_alert_status(self):
        """Show alert system status summary, similar to Tkinter check_alert_status popup."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("Alert System Status - Complete Details")
        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        lines = []

        # Scheduler info
        lines.append("SCHEDULER STATUS")
        lines.append("-----------------")
        sched = getattr(self.controller, "alert_scheduler", None)
        if sched is not None:
            lines.append("Alert Scheduler: RUNNING")
            if hasattr(sched, "scheduled_alerts"):
                count = len(getattr(sched, "scheduled_alerts", []))
                lines.append(f"  - Scheduled jobs: {count}")
        else:
            lines.append("Alert Scheduler: NOT RUNNING")
        lines.append("")

        # Gmail config
        lines.append("GMAIL CONFIGURATION")
        lines.append("-------------------")
        gc = getattr(self.controller, "gmail_config", {})
        sender = (gc.get("sender_email") or "").strip()
        if sender:
            lines.append(f"Configured for: {sender}")
            rec = (gc.get("recipients") or "").strip()
            if rec:
                lines.append(f"  - Recipients: {rec}")
            else:
                lines.append("  - Recipients: Not configured (will use sender email)")
        else:
            lines.append("Gmail: NOT CONFIGURED")
        lines.append("")

        text.setPlainText("\n".join(lines))
        layout.addWidget(text)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    def _admin_quick_action(self):
        """
        Quick admin login/logout similar to Tkinter quick_login_btn:
        - If admin is logged in, log out.
        - If admin exists but not logged in, direct user to Settings -> Admin Panel.
        """
        if self.controller.admin_logged_in:
            # Logout flow similar to Tkinter admin_logout
            confirm = QMessageBox.question(
                self,
                "Logout Admin",
                f"Logout {self.controller.logged_in_admin_name or 'Admin'}?\n\nAll admin-only features will be locked again.",
            )
            if confirm == QMessageBox.StandardButton.Yes:
                self.controller.admin_logout()
                QMessageBox.information(self, "Admin", "Admin logged out.")
            return

        # Not logged in yet - open full Admin Login dialog
        self._show_admin_login_dialog()

    def _open_settings_tab(self):
        """Switch to Settings tab."""
        for i in range(self.tabs.count()):
            if "Settings" in self.tabs.tabText(i):
                self.tabs.setCurrentIndex(i)
                break

    def closeEvent(self, event):
        self.controller.disconnect_esp32()
        event.accept()
