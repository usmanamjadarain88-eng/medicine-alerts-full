# Neumorphic theme toggle: sun (light) / moon+star (dark), smooth animation. Small icon, app palette.
import math
try:
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QPointF, QRectF, pyqtProperty
    from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QPolygonF
except ImportError:
    from PyQt5.QtWidgets import QWidget
    from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QPointF, QRectF, pyqtProperty
    from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QPolygonF

from theme.tokens import NEON_GREEN, NEON_GREEN_DIM

# Icon color: app accent green (matches CuraX palette)
ICON_COLOR = NEON_GREEN
ICON_COLOR_DARK_BG = NEON_GREEN_DIM  # lighter green when app is dark, so icon visible
TRACK_LIGHT = "#e8e8e8"
TRACK_DARK = "#3d3d3d"
KNOB_LIGHT = "#f0f0f0"
KNOB_DARK_BG = "#e0e0e0"  # knob on dark app background
TRACK_DARK_BG = "#404040"  # track fill when app is dark
BORDER_DARK_BG = "#606060"  # track border when app is dark
BORDER_LIGHT_BG = "#b0b0b0"  # track border when app is light (seekbar groove)
SHADOW_DARK = "#00000025"
HIGHLIGHT = "#ffffff30"


class ThemeToggle(QWidget):
    """Neumorphic toggle: sun (left) = light theme, moon+star (right) = dark theme. Knob slides with animation."""

    theme_changed = pyqtSignal(str)  # "light" or "dark"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slider_pos = 0.0  # 0 = light (knob right), 1 = dark (knob left)
        self._app_theme = "light"  # app background: so we draw visible in both light/dark
        self._anim = QPropertyAnimation(self, b"sliderPosition")
        self._anim.setDuration(200)
        try:
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        except AttributeError:
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setFixedSize(72, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def get_slider_position(self):
        return self._slider_pos

    def set_slider_position(self, value):
        self._slider_pos = max(0.0, min(1.0, value))
        self.update()

    sliderPosition = pyqtProperty(float, get_slider_position, set_slider_position)

    def is_dark(self):
        return self._slider_pos >= 0.5

    def set_theme(self, theme: str):
        name = (theme or "light").lower()
        self._app_theme = "dark" if name == "dark" else "light"
        target = 1.0 if name == "dark" else 0.0
        if abs(self._slider_pos - target) < 0.01:
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._slider_pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def _toggle(self):
        target = 0.0 if self.is_dark() else 1.0
        self._anim.stop()
        self._anim.setStartValue(self._slider_pos)
        self._anim.setEndValue(target)
        self._anim.start()
        theme = "dark" if target >= 0.5 else "light"
        self.theme_changed.emit(theme)

    def mousePressEvent(self, event):
        try:
            btn = Qt.MouseButton.LeftButton
        except AttributeError:
            btn = Qt.LeftButton
        if event.button() == btn and self.rect().contains(event.pos()):
            self._toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        qp = QPainter(self)
        try:
            qp.setRenderHint(QPainter.RenderHint.Antialiasing)
            qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        except AttributeError:
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        track_h = min(22, max(18, h - 4))
        track_w = min(64, max(56, w - 4))
        x0 = (w - track_w) // 2
        y0 = (h - track_h) // 2
        radius = track_h // 2
        knob_r = max(2, radius - 2)

        # Track and knob colors: clear seekbar look, and visible in dark mode
        on_dark = self._app_theme == "dark"
        if on_dark:
            track_color = QColor(TRACK_DARK_BG)
            border_color = QColor(BORDER_DARK_BG)
            knob_fill = QColor(KNOB_DARK_BG)
            knob_border = QColor("#888888")
        else:
            dark_amt = self._slider_pos
            r = int(0.91 * 255 * (1 - dark_amt) + 0.24 * 255 * dark_amt)
            g = int(0.91 * 255 * (1 - dark_amt) + 0.24 * 255 * dark_amt)
            b = int(0.91 * 255 * (1 - dark_amt) + 0.24 * 255 * dark_amt)
            track_color = QColor(r, g, b)
            border_color = QColor(BORDER_LIGHT_BG)
            knob_fill = QColor(KNOB_LIGHT)
            knob_border = QColor("#999999")

        # Track (seekbar groove) with clear border so selection is obvious
        path = QPainterPath()
        path.addRoundedRect(QRectF(x0, y0, track_w, track_h), radius, radius)
        qp.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(SHADOW_DARK)
        qp.fillPath(path.translated(1, 1), shadow)
        qp.fillPath(path, QBrush(track_color))
        try:
            border_pen = QPen(border_color, 1.2)
        except TypeError:
            border_pen = QPen(border_color)
        qp.setPen(border_pen)
        try:
            qp.setBrush(Qt.BrushStyle.NoBrush)
        except AttributeError:
            qp.setBrush(Qt.NoBrush)
        qp.drawPath(path)

        # Knob position: right when pos=0 (light selected), left when pos=1 (dark selected) — seekbar thumb
        knob_cx = x0 + radius + (track_w - 2 * radius) * (1 - self._slider_pos)
        knob_cy = y0 + track_h / 2

        # Knob (thumb) — clearly visible so selected side is obvious
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QBrush(QColor(SHADOW_DARK)))
        qp.drawEllipse(QPointF(knob_cx + 1, knob_cy + 1), knob_r, knob_r)
        qp.setBrush(QBrush(knob_fill))
        qp.drawEllipse(QPointF(knob_cx, knob_cy), knob_r, knob_r)
        qp.setPen(QPen(knob_border, 1))
        try:
            qp.setBrush(Qt.BrushStyle.NoBrush)
        except AttributeError:
            qp.setBrush(Qt.NoBrush)
        qp.drawEllipse(QPointF(knob_cx, knob_cy), knob_r, knob_r)

        # Icons: sun (left), moon+star (right) — app green; lighter green on dark app for visibility
        icon_color = QColor(ICON_COLOR_DARK_BG if on_dark else ICON_COLOR)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QBrush(icon_color))
        icon_y = y0 + track_h / 2
        sun_cx = x0 + radius + 1
        moon_cx = x0 + track_w - radius - 1

        # Sun: circle + 8 rays (scaled down)
        sun_r = 2.5
        qp.drawEllipse(QPointF(sun_cx, icon_y), sun_r, sun_r)
        for i in range(8):
            ang = i * 45
            rad = math.radians(ang)
            dx = math.cos(rad)
            dy = math.sin(rad)
            ray_len = 3.5 if i % 2 == 0 else 2.5
            x1 = sun_cx + dx * (sun_r + 0.8)
            y1 = icon_y + dy * (sun_r + 0.8)
            x2 = sun_cx + dx * (sun_r + 0.8 + ray_len)
            y2 = icon_y + dy * (sun_r + 0.8 + ray_len)
            try:
                qp.setPen(QPen(icon_color, 1.2))
            except TypeError:
                qp.setPen(QPen(icon_color, 1))
            qp.drawLine(int(x1), int(y1), int(x2), int(y2))
            qp.setPen(Qt.PenStyle.NoPen)

        # Moon: crescent + small star (scaled down)
        moon_outer = 3.5
        moon_inner = 2.2
        moon_off = 1.2
        path_moon = QPainterPath()
        path_moon.addEllipse(QPointF(moon_cx, icon_y), moon_outer, moon_outer)
        path_inner = QPainterPath()
        path_inner.addEllipse(QPointF(moon_cx + moon_off, icon_y), moon_inner, moon_inner)
        path_moon = path_moon.subtracted(path_inner)
        qp.setBrush(QBrush(icon_color))
        qp.drawPath(path_moon)
        star_cx = moon_cx + 2.8
        star_cy = icon_y - 2.2
        star_r = 1.2
        points = []
        for i in range(5):
            a = math.radians(i * 72 - 90)
            points.append((star_cx + star_r * math.cos(a), star_cy + star_r * math.sin(a)))
        poly = QPolygonF([QPointF(points[i][0], points[i][1]) for i in range(5)])
        qp.drawPolygon(poly)
